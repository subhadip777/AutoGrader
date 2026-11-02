"""Host side of the sandbox: sends one JSON job to sandbox/runner.py and returns its result.

Backends (AUTOGRADER_SANDBOX):
  docker   (default) the runner inside the autograder-sandbox image: no network,
           read-only root filesystem, capped CPU/memory/pids, almost no capabilities.
  wsl      development on Windows without Docker: the runner under `wsl -u root`.
           Student code still runs as "nobody" with rlimits, but there is no network
           or filesystem isolation. Never use it for real submissions.
  process  development on Linux without Docker: the runner as a plain subprocess.
           Same caveat as wsl.

There is no silent fallback: if the chosen backend cannot run, SandboxUnavailable is raised.
"""
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("autograder.sandbox")

PROTOCOL = 2
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "sandbox" / "runner.py"
IMAGE = os.getenv("AUTOGRADER_SANDBOX_IMAGE", "autograder-sandbox:2")
BACKENDS = ("docker", "wsl", "process")
MAX_JOB_BYTES = 32 * 1024 * 1024
# Same pattern as sandbox/runner.py; checked here too so bad rules fail before a container starts.
FLAG_OK = re.compile(
    r"^(-W[A-Za-z0-9=+_-]*|-std=(c|gnu)(89|90|99|11|17|2x|23)|-O[0-3sg]?|-g|-pedantic(-errors)?"
    r"|-fsanitize=[a-z,-]+|-fno-sanitize-recover(=[a-z,-]+)?|-fno-omit-frame-pointer)$"
)

_slots = threading.Semaphore(int(os.getenv("AUTOGRADER_SANDBOX_SLOTS", "1")))  # 8 GB of RAM cannot take more
_status_cache: dict = {}


class SandboxError(RuntimeError):
    """The sandbox itself failed (not the student's program)."""


class SandboxUnavailable(SandboxError):
    """The configured backend cannot run at all (for example Docker is not installed)."""


def backend() -> str:
    name = os.getenv("AUTOGRADER_SANDBOX", "docker").strip().lower()
    if name not in BACKENDS:
        raise SandboxUnavailable(f"unknown AUTOGRADER_SANDBOX={name!r}; use one of {', '.join(BACKENDS)}")
    return name


def split_flags(flags) -> list[str]:
    """Rules give flags as a string ("-Wall -Wextra") or a list; return a validated list."""
    items = flags.split() if isinstance(flags, str) else list(flags or [])
    bad = [f for f in items if not isinstance(f, str) or not FLAG_OK.match(f)]
    if bad:
        raise ValueError(f"compiler flags not allowed: {bad}")
    return items


def _wsl_path(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    if not m:
        raise SandboxUnavailable(f"cannot map {s} into WSL")
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}"


def _docker_cmd(name: str) -> list[str]:
    return [
        "docker", "run", "--rm", "-i", "--init", "--name", name,
        "--network", "none",
        "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1", "--pids-limit", "128",
        "--ulimit", "nofile=256:256",
        "--read-only", "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=128m",
        "--cap-drop", "ALL", "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "KILL",
        "--cap-add", "DAC_OVERRIDE",   # root inside may clean up files that "nobody" created
        "--security-opt", "no-new-privileges",
        "--ipc", "none",
        IMAGE,
    ]


def _command(name: str, workdir: str) -> tuple[list[str], str]:
    b = backend()
    if b == "docker":
        if not shutil.which("docker"):
            raise SandboxUnavailable("Docker is not installed or not on PATH")
        return _docker_cmd(name), "/tmp"
    if b == "wsl":
        if platform.system() != "Windows" or not shutil.which("wsl.exe") and not shutil.which("wsl"):
            raise SandboxUnavailable("AUTOGRADER_SANDBOX=wsl needs Windows with WSL installed")
        return ["wsl.exe", "-u", "root", "-e", "python3", _wsl_path(RUNNER)], workdir
    if platform.system() == "Windows":
        raise SandboxUnavailable("AUTOGRADER_SANDBOX=process needs Linux; on Windows use docker or wsl")
    return ["python3", str(RUNNER)], workdir


def execute(job: dict, timeout_s: float | None = None) -> dict:
    """Run one protocol-2 job and return the runner's result. Raises SandboxError on failure."""
    name = "ag-" + uuid.uuid4().hex[:12]
    cmd, workdir = _command(name, f"/tmp/ag-{uuid.uuid4().hex[:16]}")
    job = dict(job, workdir=workdir)
    payload = json.dumps(job)
    if len(payload) > MAX_JOB_BYTES:
        raise SandboxError("the job is too large for the sandbox")
    if timeout_s is None:
        timeout_s = estimate_timeout(job)
    started = time.perf_counter()
    with _slots:
        try:
            p = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                               encoding="utf-8", timeout=timeout_s)
        except FileNotFoundError as e:
            raise SandboxUnavailable(f"{cmd[0]} could not be started: {e}")
        except subprocess.TimeoutExpired:
            if cmd[0] == "docker":
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            raise SandboxError("the sandbox run took too long and was stopped")
    log.debug("sandbox job %s finished in %.2fs", name, time.perf_counter() - started)
    if p.returncode != 0:
        err = (p.stderr or "")[-400:]
        if cmd[0] == "docker" and ("Unable to find image" in err or "No such image" in err):
            raise SandboxUnavailable(f"sandbox image {IMAGE} is missing; build it with: "
                                     f"docker build -t {IMAGE} sandbox")
        if cmd[0] == "docker" and ("Cannot connect" in err or "daemon" in err):
            raise SandboxUnavailable("the Docker daemon is not running")
        raise SandboxError(f"{backend()} sandbox failed: {err}")
    try:
        result = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise SandboxError("the sandbox returned invalid output")
    if "error" in result:
        raise SandboxError(result["error"])
    if result.get("protocol") != PROTOCOL:
        raise SandboxUnavailable(f"the sandbox runner is outdated (protocol {result.get('protocol')}); "
                                 f"rebuild the image: docker build -t {IMAGE} sandbox")
    result["backend"] = backend()
    return result


def estimate_timeout(job: dict) -> float:
    limit = float(job.get("time_limit_s", 1))
    total = 60.0 + 25.0 * len(job.get("builds") or [1])
    for r in job.get("runs") or job.get("tests") or []:
        per = (limit + 2) * max(1, int(r.get("repeat", 1)))
        if r.get("wrapper") == "valgrind":
            per *= 10
        total += per * 3
    return min(total, 1800.0)


def run_c(source: str, tests: list[dict], *, flags: list[str] | None = None,
          time_limit_s: float = 1.0, memory_limit_mb: int = 64) -> dict:
    """Compile `source` and run it on each test's input. Pass tests=[] to only compile.

    Only inputs enter the container. Expected outputs stay on the host, which does the comparison.
    """
    return execute({
        "source": source,
        "builds": [{"name": "main", "flags": flags or ["-O2", "-std=c11"]}],
        "runs": [{"id": t["id"], "build": "main", "input": t["input"]} for t in tests],
        "time_limit_s": time_limit_s,
        "memory_limit_mb": memory_limit_mb,
    })


def status(refresh: bool = False) -> dict:
    """Describe the configured backend and whether it can run right now (cached for 30 s)."""
    now = time.time()
    if not refresh and _status_cache.get("at", 0) > now - 30:
        return _status_cache["value"]
    try:
        b = backend()
        value = {"backend": b, "available": True, "detail": "", "isolated": b == "docker"}
        if b == "docker":
            if not shutil.which("docker"):
                raise SandboxUnavailable("Docker is not installed or not on PATH")
            p = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
                               capture_output=True, text=True, timeout=15)
            if p.returncode != 0:
                if "Cannot connect" in p.stderr or "daemon" in p.stderr:
                    raise SandboxUnavailable("the Docker daemon is not running")
                raise SandboxUnavailable(f"sandbox image {IMAGE} is missing; build it with: "
                                         f"docker build -t {IMAGE} sandbox")
        else:
            _command("probe", "/tmp/ag-00000000")
            value["detail"] = (f"development backend '{b}': student code runs as 'nobody' with rlimits "
                               "but without container isolation")
    except SandboxUnavailable as e:
        value = {"backend": os.getenv("AUTOGRADER_SANDBOX", "docker"), "available": False,
                 "detail": str(e), "isolated": False}
    except (OSError, subprocess.TimeoutExpired) as e:
        value = {"backend": os.getenv("AUTOGRADER_SANDBOX", "docker"), "available": False,
                 "detail": f"{type(e).__name__}: {e}", "isolated": False}
    _status_cache.update(at=now, value=value)
    return value
