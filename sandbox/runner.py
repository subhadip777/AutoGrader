#!/usr/bin/env python3
"""AutoGrader sandbox runner. It runs INSIDE the container, as root.

It reads one JSON job on stdin and writes one JSON result on stdout.
Student code is compiled and run as the unprivileged user "nobody" with CPU,
memory, process-count and output-size limits. Expected outputs are never sent
here: the host compares the results.
"""
import json
import math
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

NOBODY = 65534
CAPTURE_BYTES = 64 * 1024        # stdout/stderr text returned per run
MAX_FILE_BYTES = 1024 * 1024     # a program may write at most 1 MiB to stdout or stderr
MAX_CONSECUTIVE_TIMEOUTS = 3     # after this many in a row, remaining tests are skipped
FLAG_OK = re.compile(
    r"^(-W[A-Za-z0-9=+_-]*|-std=c(89|99|11|17)|-O[0-3sg]|-g|-pedantic"
    r"|-fsanitize=[a-z,]+|-fno-omit-frame-pointer)$"
)
BUILD, JOB, IO = "/tmp/build", "/tmp/job", "/tmp/io"
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C"}


def limits(cpu_s, mem_mb, nproc):
    """Return a function that runs in the child just before exec."""
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        if mem_mb:
            cap = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setgroups([])
        os.setgid(NOBODY)
        os.setuid(NOBODY)
    return apply


def kill_nobody():
    """Kill every process owned by 'nobody' (stray children of a student program)."""
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/status") as f:
                uid_line = next(line for line in f if line.startswith("Uid:"))
            if int(uid_line.split()[1]) == NOBODY:
                os.kill(int(name), signal.SIGKILL)
        except (OSError, StopIteration, ValueError):
            pass


def run_limited(cmd, stdin_path, out_path, err_path, cwd, cpu_s, mem_mb, nproc, wall_s):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    timed_out = False
    with open(stdin_path, "rb") as fin, open(out_path, "wb") as fout, open(err_path, "wb") as ferr:
        proc = subprocess.Popen(
            cmd, stdin=fin, stdout=fout, stderr=ferr, cwd=cwd, env=ENV,
            start_new_session=True, preexec_fn=limits(cpu_s, mem_mb, nproc),
        )
        try:
            proc.wait(timeout=wall_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    kill_nobody()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
    rc = proc.returncode
    try:
        sig = signal.Signals(-rc).name if rc < 0 else None
    except ValueError:
        sig = f"SIG{-rc}"
    return {
        "returncode": rc,
        "signal": sig,
        "timed_out": timed_out,
        "cpu_ms": round(cpu * 1000),
        "wall_ms": round((time.perf_counter() - start) * 1000),
    }


def read_capped(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(CAPTURE_BYTES)
    return data.decode("utf-8", errors="replace"), size > CAPTURE_BYTES


def main():
    job = json.load(sys.stdin)
    flags = job.get("flags") or ["-O2", "-std=c11"]
    bad = [f for f in flags if not FLAG_OK.match(f)]
    if bad:
        return {"error": f"compiler flags not allowed: {bad}"}
    limit = float(job.get("time_limit_s", 1))
    mem_mb = int(job.get("memory_limit_mb", 64))
    if any("sanitize" in f for f in flags):
        mem_mb = 0  # sanitizers reserve huge address ranges; the container cap still applies

    for path, mode in ((BUILD, 0o777), (JOB, 0o755), (IO, 0o700)):
        os.makedirs(path, exist_ok=True)
        os.chmod(path, mode)
    with open(f"{BUILD}/sol.c", "w", encoding="utf-8", newline="") as f:
        f.write(job["source"])

    gcc = subprocess.run(["gcc", "-dumpfullversion"], capture_output=True, text=True).stdout.strip()
    cc_out, cc_err = f"{IO}/cc.out", f"{IO}/cc.err"
    res = run_limited(["gcc", *flags, "sol.c", "-o", "prog", "-lm"],
                      "/dev/null", cc_out, cc_err, BUILD, 20, 0, 64, 30)
    compiled = res["returncode"] == 0 and not res["timed_out"] and os.path.exists(f"{BUILD}/prog")
    result = {
        "tool_versions": {"gcc": gcc},
        "compile": {
            "ok": compiled,
            "returncode": res["returncode"],
            "timed_out": res["timed_out"],
            "stdout": read_capped(cc_out)[0],
            "stderr": read_capped(cc_err)[0],
        },
        "runs": [],
    }
    tests = job.get("tests") or []
    if not compiled or not tests:
        return result

    shutil.copy(f"{BUILD}/prog", f"{JOB}/prog")   # root-owned copy the student cannot modify
    os.chmod(f"{JOB}/prog", 0o755)
    shutil.rmtree(BUILD, ignore_errors=True)

    timeouts = 0
    for t in tests:
        if timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
            result["runs"].append({"id": t["id"], "skipped": True})
            continue
        in_path, out_path, err_path = f"{IO}/in.txt", f"{IO}/out.txt", f"{IO}/err.txt"
        with open(in_path, "w", encoding="utf-8", newline="") as f:
            f.write(t["input"])
        run = run_limited([f"{JOB}/prog"], in_path, out_path, err_path, JOB,
                          math.ceil(limit) + 1, mem_mb, 16, limit + 1.0)
        out, cut_out = read_capped(out_path)
        err, cut_err = read_capped(err_path)
        run.update(id=t["id"], stdout=out, stderr=err, truncated=cut_out or cut_err,
                   over_cpu_limit=run["cpu_ms"] > limit * 1000)
        timeouts = timeouts + 1 if (run["timed_out"] or run["over_cpu_limit"]) else 0
        result["runs"].append(run)
    return result


if __name__ == "__main__":
    try:
        out = main()
    except Exception as e:  # report instead of crashing, so the host always gets JSON
        out = {"error": f"{type(e).__name__}: {e}"}
    json.dump(out, sys.stdout)
    sys.stdout.flush()