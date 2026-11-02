import json
import subprocess
import threading
import uuid

IMAGE = "autograder-sandbox:1"
_slots = threading.Semaphore(1)   # one container at a time; 8 GB of RAM cannot take more


class SandboxError(RuntimeError):
    """The sandbox itself failed (not the student's program)."""


def run_c(source: str, tests: list[dict], *, flags: list[str] | None = None,
          time_limit_s: float = 1.0, memory_limit_mb: int = 64) -> dict:
    """Compile `source` and run it on each test's input. Pass tests=[] to only compile.

    Only inputs enter the container. Expected outputs stay on the host, which does the comparison.
    """
    job = {
        "source": source,
        "flags": flags or ["-O2", "-std=c11"],
        "tests": [{"id": t["id"], "input": t["input"]} for t in tests],
        "time_limit_s": time_limit_s,
        "memory_limit_mb": memory_limit_mb,
    }
    name = "ag-" + uuid.uuid4().hex[:12]
    cmd = [
        "docker", "run", "--rm", "-i", "--init", "--name", name,
        "--network", "none",
        "--memory", "384m", "--memory-swap", "384m",
        "--cpus", "1", "--pids-limit", "128",
        "--read-only", "--tmpfs", "/tmp:rw,exec,nosuid,size=64m",
        "--cap-drop", "ALL", "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "KILL",
        "--security-opt", "no-new-privileges",
        IMAGE,
    ]
    total_timeout = 60 + len(tests) * (time_limit_s + 2)
    with _slots:
        try:
            p = subprocess.run(cmd, input=json.dumps(job), capture_output=True,
                               text=True, encoding="utf-8", timeout=total_timeout)
        except FileNotFoundError:
            raise SandboxError("Docker is not installed or not on PATH")
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            raise SandboxError("the sandbox run took too long and was stopped")
    if p.returncode != 0:
        raise SandboxError("docker failed: " + (p.stderr or "")[-400:])
    try:
        result = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise SandboxError("the sandbox returned invalid output")
    if "error" in result:
        raise SandboxError(result["error"])
    return result