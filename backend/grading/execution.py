"""Helpers that turn analyzer needs into sandbox jobs."""
import re

from server import sandbox

DEFAULT_MAIN_FLAGS = ["-O2", "-std=c11"]
# Arithmetic undefined behaviour only (overflow, shifts, division by zero): memory errors are
# the memory_safety metric's job, so they must not also fail every edge case.
UBSAN_FLAGS = ["-O1", "-g", "-fno-omit-frame-pointer",
               "-fsanitize=signed-integer-overflow,shift,integer-divide-by-zero,float-cast-overflow"]
CLEAN_PROGRAM = "#include <stdio.h>\nint main(void) { puts(\"ok\"); return 0; }\n"


def metrics(rules: dict, analyzer: str) -> list[dict]:
    return [m for m in rules.get("metrics", []) if m.get("analyzer") == analyzer]


def std_flag(flags: list[str]) -> str | None:
    return next((f for f in flags if f.startswith("-std=")), None)


def main_flags(rules: dict) -> list[str]:
    """Flags for the build that is executed. Never -Werror: a warning must not stop the tests."""
    if rules.get("compile_flags"):
        flags = sandbox.split_flags(rules["compile_flags"])
    else:
        flags = list(DEFAULT_MAIN_FLAGS)
        for m in metrics(rules, "compiler_warnings"):
            std = std_flag(sandbox.split_flags(m.get("params", {}).get("flags", "")))
            if std:
                flags = [f for f in flags if not f.startswith("-std=")] + [std]
                break
    return [f for f in flags if f != "-Werror" and not f.startswith("-Werror=")]


def with_std(flags: list[str], rules: dict) -> list[str]:
    std = std_flag(main_flags(rules))
    return flags + [std] if std and not std_flag(flags) else flags


def run_job(ctx, builds: list[dict], runs: list[dict], static: list[str] | None = None) -> dict:
    job = {
        "source": ctx.sub.source,
        "builds": builds,
        "runs": runs,
        "time_limit_s": ctx.time_limit_s,
        "memory_limit_mb": ctx.memory_limit_mb,
    }
    if static:
        job["static"] = static
    res = sandbox.execute(job)
    for k, v in (res.get("tool_versions") or {}).items():
        if v:
            ctx.tool_versions[k] = v
    ctx.tool_versions["sandbox_backend"] = res.get("backend")
    ctx.tool_versions["sandbox_isolation"] = res.get("isolation")
    return res


def strip_paths(text: str) -> str:
    """Remove sandbox-specific directories so evidence is identical between runs."""
    text = re.sub(r"/tmp(?:/ag-[0-9a-f]+)?/(?:build|job|static)/\w+/", "", text or "")
    text = re.sub(r"/tmp(?:/ag-[0-9a-f]+)?/(?:build|job|static)/", "", text)
    text = re.sub(r"==\d+==", "==PID==", text)
    text = re.sub(r"\(BuildId: [0-9a-f]+\)", "", text)
    return re.sub(r"0x[0-9a-f]{6,16}", "0x…", text)
