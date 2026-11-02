#!/usr/bin/env python3
"""AutoGrader sandbox runner. It runs INSIDE the container, as root.

It reads one JSON job on stdin and writes one JSON result on stdout.
Student code is compiled and run as the unprivileged user "nobody" with CPU,
memory, process-count and output-size limits. Expected outputs are never sent
here: the host compares the results.

Job (protocol 2):
    source              C source of the submission
    builds              [{"name", "flags", "source"?}]   each one is compiled separately
    runs                [{"id", "build", "input", "wrapper"?, "repeat"?}]
    static              ["cppcheck"]                     source-only tools to run
    time_limit_s, memory_limit_mb, max_consecutive_timeouts, workdir
The protocol-1 form ({"flags", "tests"}) is still accepted.
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
import threading
import time

PROTOCOL = 2
NOBODY = 65534
CAPTURE_BYTES = 64 * 1024        # stdout/stderr text returned per run
MAX_FILE_BYTES = 1024 * 1024     # a program may write at most 1 MiB to stdout or stderr
MAX_CONSECUTIVE_TIMEOUTS = 3     # after this many in a row, remaining runs of that build are skipped
FLAG_OK = re.compile(
    r"^(-W[A-Za-z0-9=+_-]*|-std=(c|gnu)(89|90|99|11|17|2x|23)|-O[0-3sg]?|-g|-pedantic(-errors)?"
    r"|-fsanitize=[a-z,-]+|-fno-sanitize-recover(=[a-z,-]+)?|-fno-omit-frame-pointer)$"
)
NAME_OK = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C"}
SAN_ENV = {
    "ASAN_OPTIONS": "detect_leaks=1:exitcode=86:abort_on_error=0:allocator_may_return_null=1",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=0",
    "LSAN_OPTIONS": "exitcode=86",
}
VALGRIND = ["valgrind", "--leak-check=full", "--show-leak-kinds=definite,indirect",
            "--errors-for-leak-kinds=definite", "--error-exitcode=99", "--log-fd=2"]
CPPCHECK = ["cppcheck", "--enable=warning,style,performance,portability", "--std=c11",
            "--quiet", "--inline-suppr", "--error-exitcode=0",
            "--template={line}|{severity}|{id}|{message}"]
IS_ROOT = os.geteuid() == 0


def limits(cpu_s, mem_mb, nproc):
    """Return a function that runs in the child just before exec."""
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        if mem_mb:
            cap = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if IS_ROOT:
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
            os.setgroups([])
            os.setgid(NOBODY)
            os.setuid(NOBODY)
    return apply


def kill_nobody():
    """Kill every process owned by 'nobody' (stray children of a student program)."""
    if not IS_ROOT:
        return
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


def run_limited(cmd, stdin_path, out_path, err_path, cwd, cpu_s, mem_mb, nproc, wall_s, env=None):
    """Run one process under limits and return its exit status and its own resource usage."""
    timed_out = threading.Event()
    with open(stdin_path, "rb") as fin, open(out_path, "wb") as fout, open(err_path, "wb") as ferr:
        start = time.perf_counter()
        proc = subprocess.Popen(
            cmd, stdin=fin, stdout=fout, stderr=ferr, cwd=cwd, env=env or ENV,
            start_new_session=True, preexec_fn=limits(cpu_s, mem_mb, nproc),
        )

    def stop():
        timed_out.set()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timer = threading.Timer(wall_s, stop)
    timer.start()
    try:
        _, status, ru = os.wait4(proc.pid, 0)
    finally:
        timer.cancel()
    wall = time.perf_counter() - start
    rc = os.waitstatus_to_exitcode(status)
    proc.returncode = rc  # already reaped; stops Popen from waiting again
    try:
        os.killpg(proc.pid, signal.SIGKILL)   # grandchildren left in the session
    except (ProcessLookupError, PermissionError):
        pass
    kill_nobody()
    try:
        sig = signal.Signals(-rc).name if rc < 0 else None
    except ValueError:
        sig = f"SIG{-rc}"
    return {
        "returncode": rc,
        "signal": sig,
        "timed_out": timed_out.is_set(),
        "cpu_ms": round((ru.ru_utime + ru.ru_stime) * 1000, 3),
        "wall_ms": round(wall * 1000, 3),
        "max_rss_kb": ru.ru_maxrss,
    }


def read_capped(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(CAPTURE_BYTES)
    return data.decode("utf-8", errors="replace"), size > CAPTURE_BYTES


def version(cmd, pattern=r"(\d+(?:\.\d+)+)"):
    if not shutil.which(cmd[0]):
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(pattern, out.stdout + out.stderr)
    return m.group(1) if m else (out.stdout or out.stderr).strip()[:40]


def normalise(job):
    """Accept the protocol-1 job shape and return (builds, runs)."""
    builds = job.get("builds")
    runs = job.get("runs")
    if builds is None:
        builds = [{"name": "main", "flags": job.get("flags") or ["-O2", "-std=c11"]}]
        runs = [{"id": t["id"], "build": "main", "input": t["input"]} for t in job.get("tests") or []]
    return builds, runs or []


def compile_build(b, workdir, default_source):
    flags = b.get("flags") or ["-O2", "-std=c11"]
    bad = [f for f in flags if not FLAG_OK.match(f)]
    if bad:
        raise ValueError(f"compiler flags not allowed: {bad}")
    bdir = f"{workdir}/build/{b['name']}"
    jdir = f"{workdir}/job/{b['name']}"
    io = f"{workdir}/io"
    os.makedirs(bdir, exist_ok=True)
    os.chmod(bdir, 0o777)
    with open(f"{bdir}/sol.c", "w", encoding="utf-8", newline="") as f:
        f.write(b.get("source", default_source))
    cc_out, cc_err = f"{io}/cc.out", f"{io}/cc.err"
    res = run_limited(["gcc", *flags, "sol.c", "-o", "prog", "-lm"],
                      "/dev/null", cc_out, cc_err, bdir, 20, 0, 64, 30)
    ok = res["returncode"] == 0 and not res["timed_out"] and os.path.exists(f"{bdir}/prog")
    if ok:
        os.makedirs(jdir, exist_ok=True)
        os.chmod(jdir, 0o755)
        shutil.copy(f"{bdir}/prog", f"{jdir}/prog")   # root-owned copy the student cannot modify
        os.chmod(f"{jdir}/prog", 0o755)
    shutil.rmtree(bdir, ignore_errors=True)
    return {
        "ok": ok,
        "flags": flags,
        "returncode": res["returncode"],
        "timed_out": res["timed_out"],
        "stdout": read_capped(cc_out)[0],
        "stderr": read_capped(cc_err)[0],
    }


def run_one(r, build, workdir, limit, mem_mb):
    jdir, io = f"{workdir}/job/{r['build']}", f"{workdir}/io"
    sanitized = any("sanitize" in f for f in build["flags"])
    wrapper = r.get("wrapper") or "none"
    cmd, env = [f"{jdir}/prog"], dict(ENV)
    cpu_s, wall_s = math.ceil(limit) + 1, limit + 1.0
    if sanitized:
        mem_mb = 0  # sanitizers reserve huge address ranges; the container cap still applies
        env.update(SAN_ENV)
        cpu_s, wall_s = cpu_s * 3, wall_s * 3
    if wrapper == "valgrind":
        if not shutil.which("valgrind"):
            return {"unavailable": "valgrind is not installed in the sandbox"}
        cmd = VALGRIND + cmd
        mem_mb = 0
        cpu_s, wall_s = cpu_s * 10, wall_s * 10
    elif wrapper != "none":
        raise ValueError(f"unknown wrapper {wrapper!r}")

    in_path, out_path, err_path = f"{io}/in.txt", f"{io}/out.txt", f"{io}/err.txt"
    with open(in_path, "w", encoding="utf-8", newline="") as f:
        f.write(r["input"])
    repeat = max(1, min(int(r.get("repeat", 1)), 25))
    first, cpu_times, wall_times = None, [], []
    for i in range(repeat):
        run = run_limited(cmd, in_path, out_path, err_path, jdir, cpu_s, mem_mb, 16, wall_s, env)
        cpu_times.append(run["cpu_ms"])
        wall_times.append(run["wall_ms"])
        if first is None:
            out, cut_out = read_capped(out_path)
            err, cut_err = read_capped(err_path)
            first = dict(run, stdout=out, stderr=err, truncated=cut_out or cut_err)
        if run["timed_out"] or run["returncode"] != 0:
            break   # no point timing a program that failed
    first.update(over_cpu_limit=first["cpu_ms"] > limit * 1000 and not sanitized and wrapper == "none",
                 cpu_times_ms=cpu_times, wall_times_ms=wall_times)
    return first


def run_static(tools, workdir, source):
    out = {}
    sdir, io = f"{workdir}/static", f"{workdir}/io"
    os.makedirs(sdir, exist_ok=True)
    os.chmod(sdir, 0o777)
    with open(f"{sdir}/sol.c", "w", encoding="utf-8", newline="") as f:
        f.write(source)
    for tool in tools:
        if tool != "cppcheck":
            raise ValueError(f"unknown static tool {tool!r}")
        if not shutil.which("cppcheck"):
            out[tool] = {"available": False, "reason": "cppcheck is not installed in the sandbox"}
            continue
        res = run_limited(CPPCHECK + ["sol.c"], "/dev/null", f"{io}/st.out", f"{io}/st.err",
                          sdir, 30, 0, 16, 60)
        out[tool] = {
            "available": res["returncode"] == 0 and not res["timed_out"],
            "returncode": res["returncode"],
            "output": read_capped(f"{io}/st.err")[0],
            "reason": "" if res["returncode"] == 0 else "cppcheck failed",
        }
    return out


def main():
    job = json.load(sys.stdin)
    workdir = job.get("workdir") or "/tmp"
    if not re.match(r"^/tmp(/ag-[a-f0-9]{8,32})?$", workdir):
        return {"error": "invalid workdir"}
    limit = float(job.get("time_limit_s", 1))
    mem_mb = int(job.get("memory_limit_mb", 64))
    max_to = int(job.get("max_consecutive_timeouts", MAX_CONSECUTIVE_TIMEOUTS))
    builds, runs = normalise(job)

    os.makedirs(workdir, exist_ok=True)
    os.chmod(workdir, 0o755)
    for sub, mode in (("build", 0o755), ("job", 0o755), ("io", 0o700)):
        os.makedirs(f"{workdir}/{sub}", exist_ok=True)
        os.chmod(f"{workdir}/{sub}", mode)

    result = {
        "protocol": PROTOCOL,
        "isolation": "nobody" if IS_ROOT else "current-user",
        "tool_versions": {
            "gcc": version(["gcc", "-dumpfullversion"], r"(\S+)"),
            "valgrind": version(["valgrind", "--version"]),
            "cppcheck": version(["cppcheck", "--version"]),
        },
        "builds": {},
        "runs": [],
    }
    try:
        for b in builds:
            if not NAME_OK.match(b.get("name", "")):
                return {"error": f"invalid build name {b.get('name')!r}"}
            result["builds"][b["name"]] = compile_build(b, workdir, job["source"])
        if builds:
            result["compile"] = result["builds"][builds[0]["name"]]
        if job.get("static"):
            result["static"] = run_static(job["static"], workdir, job["source"])

        timeouts = {}
        for r in runs:
            build = result["builds"].get(r.get("build", "main"))
            rec = {"id": str(r["id"])[:64], "build": r.get("build", "main"), "wrapper": r.get("wrapper") or "none"}
            if build is None:
                rec.update(skipped=True, reason="unknown build")
            elif not build["ok"]:
                rec.update(skipped=True, reason="build failed")
            elif timeouts.get(rec["build"], 0) >= max_to:
                rec.update(skipped=True, reason="too many consecutive timeouts")
            else:
                rec.update(run_one(r, build, workdir, limit, mem_mb))
                if rec.get("timed_out") or rec.get("over_cpu_limit"):
                    timeouts[rec["build"]] = timeouts.get(rec["build"], 0) + 1
                elif "returncode" in rec:
                    timeouts[rec["build"]] = 0
            result["runs"].append(rec)
    finally:
        if workdir != "/tmp":
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            for sub in ("build", "job", "io", "static"):
                shutil.rmtree(f"{workdir}/{sub}", ignore_errors=True)
    return result


if __name__ == "__main__":
    try:
        out = main()
    except Exception as e:  # report instead of crashing, so the host always gets JSON
        out = {"error": f"{type(e).__name__}: {e}"}
    json.dump(out, sys.stdout)
    sys.stdout.flush()
