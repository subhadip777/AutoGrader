"""First pass: compile, smoke run and static sanity, before any analyzer runs.

One sandbox job compiles the program with the execution flags and with every set of
warning flags named in the rules, runs cppcheck when a structure metric needs it, and
feeds the first accepted test's input to the program once. A smoke run that times out
sets suspected_infinite_loop, and the execution-based analyzers are then skipped.
"""
import re

from grading import compare, execution
from server import sandbox

READERS = r"\b(scanf|fscanf|sscanf|getchar|fgets|getline|gets|fread|read|getc|fgetc)\s*\("
WRITERS = r"\b(printf|puts|putchar|fputs|fprintf|fwrite|write|putc|fputc)\s*\("


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def sanity(source: str) -> dict:
    code = strip_comments(source)
    m = re.search(r"\bint\s+main\s*\(", code) or re.search(r"\bmain\s*\(", code)
    body = code[m.end():] if m else ""
    checks = {
        "has_main": bool(m),
        "reads_input": bool(re.search(READERS, code)),
        "writes_output": bool(re.search(WRITERS, code)),
        "main_returns": bool(re.search(r"\breturn\b", body)),
    }
    notes = []
    if not checks["has_main"]:
        notes.append("no main() function found")
    if not checks["reads_input"]:
        notes.append("no input function (scanf, fgets, getchar, ...) is called")
    if not checks["writes_output"]:
        notes.append("no output function (printf, puts, ...) is called")
    if checks["has_main"] and not checks["main_returns"]:
        notes.append("main() has no return statement")
    return {"checks": checks, "notes": notes}


def warning_flags(rules: dict, metric: dict) -> list[str]:
    return execution.with_std(sandbox.split_flags(metric.get("params", {}).get("flags", "-Wall -Wextra")), rules)


def warning_builds(rules: dict) -> list[dict]:
    builds, seen = [], set()
    for i, m in enumerate(execution.metrics(rules, "compiler_warnings")):
        flags = warning_flags(rules, m)
        if tuple(flags) not in seen:
            seen.add(tuple(flags))
            builds.append({"name": f"warn{i}", "flags": flags})
    return builds


def run(ctx) -> dict:
    rules = ctx.rules
    tests = ctx.sub.tests
    builds = [{"name": "main", "flags": execution.main_flags(rules)}] + warning_builds(rules)
    static = ["cppcheck"] if execution.metrics(rules, "static_analysis") else None
    smoke_input = tests[0]["input"] if tests else ""
    res = execution.run_job(ctx, builds, [{"id": "SMOKE", "build": "main", "input": smoke_input}], static)

    main = res["builds"]["main"]
    fp = {
        "compiled": main["ok"],
        "compile_flags": main["flags"],
        "compiler_output": execution.strip_paths(main["stderr"])[:8000],
        "builds": {k: {"ok": v["ok"], "flags": v["flags"], "stderr": execution.strip_paths(v["stderr"])[:8000]}
                   for k, v in res["builds"].items()},
        "static": res.get("static") or {},
        "sanity": sanity(ctx.sub.source),
        "smoke_ok": False,
        "suspected_infinite_loop": False,
        "smoke": None,
    }
    if main["ok"]:
        run = res["runs"][0]
        status, why = compare.classify_run(run, ctx.time_limit_s)
        fp["smoke"] = {
            "status": status,
            "explanation": why,
            "test_id": tests[0].get("id") if tests else None,
            "returncode": run.get("returncode"),
            "signal": run.get("signal"),
            "cpu_ms": run.get("cpu_ms"),
            "wall_ms": run.get("wall_ms"),
            "max_rss_kb": run.get("max_rss_kb"),
        }
        fp["smoke_ok"] = status == "ok"
        fp["suspected_infinite_loop"] = status == "timeout"
    fp["run_execution_analyzers"] = fp["compiled"] and not fp["suspected_infinite_loop"]
    return fp
