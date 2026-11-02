"""io_tests: run every accepted (frozen) test case and compare the output.

Expected outputs come only from testcases.json; nothing is generated here. The comparison
ignores trailing whitespace and trailing blank lines but keeps every other difference.
Params: compare ("trailing_ws" | "exact" | "tokens"), float_tolerance, show_failures.
"""
from grading import compare, execution
from grading.analyzers.common import clamp01, params, result
from grading.types import OK, UNAVAILABLE


def run_tests(ctx) -> dict:
    """Run the frozen tests once per grading and cache the runs by test id."""
    if "test_runs" not in ctx.cache:
        tests = ctx.sub.tests
        runs = [{"id": t["id"], "build": "main", "input": t["input"]} for t in tests]
        res = execution.run_job(ctx, [{"name": "main", "flags": execution.main_flags(ctx.rules)}], runs)
        ctx.cache["test_runs"] = {r["id"]: r for r in res["runs"]}
    return ctx.cache["test_runs"]


def check(test: dict, run: dict, ctx, mode: str, tol) -> dict:
    status, why = compare.classify_run(run, ctx.time_limit_s)
    actual = run.get("stdout", "")
    if status == "ok":
        if compare.outputs_match(test["expected_output"], actual, mode, tol):
            status = "pass"
        else:
            status, why = "wrong_answer", compare.explain_mismatch(test["expected_output"], actual)
    return {
        "id": test["id"],
        "category": test.get("category", ""),
        "status": status,
        "passed": status == "pass",
        "input": test["input"],
        "expected": test["expected_output"],
        "actual": compare.short(actual, 2000),
        "stderr": compare.short(execution.strip_paths(run.get("stderr", "")), 1000),
        "explanation": why,
        "test_reason": test.get("explanation", ""),
    }


def analyze(ctx, metric):
    p = params(metric)
    tests = ctx.sub.tests
    if not tests:
        return result(metric, status=UNAVAILABLE, feedback="No accepted test cases exist for this assignment.")
    mode, tol = p.get("compare", "trailing_ws"), p.get("float_tolerance")
    runs = run_tests(ctx)
    checks = [check(t, runs[t["id"]], ctx, mode, tol) for t in tests]
    passed = sum(c["passed"] for c in checks)
    failing = [c for c in checks if not c["passed"]]
    show = int(p.get("show_failures", 5))

    feedback = f"{passed} of {len(checks)} tests pass."
    if failing:
        f = failing[0]
        feedback += f" First failure ({f['id']}): {f['explanation']}."
    by_status: dict[str, int] = {}
    for c in checks:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    suggestions = []
    if by_status.get("timeout"):
        suggestions.append("Some tests time out: look for loops that never end or an algorithm that is too slow.")
    if by_status.get("crash") or by_status.get("runtime_error"):
        suggestions.append("Some tests crash: check array bounds, pointers and division by zero.")
    if by_status.get("wrong_answer"):
        suggestions.append("Compare your output format character by character with the examples in the statement.")
    timings = {t["id"]: {"cpu_ms": runs[t["id"]].get("cpu_ms"), "max_rss_kb": runs[t["id"]].get("max_rss_kb")}
               for t in tests}
    return result(
        metric, status=OK, score=clamp01(passed / len(checks)), feedback=feedback, suggestions=suggestions,
        timings=timings,
        evidence={
            "tests_passed": passed,
            "tests_total": len(checks),
            "by_status": by_status,
            "comparison": mode,
            "failing": failing[:show],
            "failing_total": len(failing),
            "results": [{"id": c["id"], "status": c["status"]} for c in checks],
        },
    )
