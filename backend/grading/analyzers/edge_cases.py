"""edge_case_runner: boundary cases named in the rules plus counter-tests that expose failures.

Four kinds of checks, every one with a written reason:
  1. category tests   accepted tests whose category matches a requested theme (negatives, zero, ...)
  2. format variants  an accepted test with a harmless input change (trailing newline removed,
                      extra spaces between values); the expected output must not change
  3. generated cases  inputs built from the assignment's input format for each theme. With a
                      reference solution the expected output is the reference's output; without
                      one the program must at least finish cleanly, print something and trigger
                      no undefined behaviour (it runs under UBSan, which catches int overflow)
  4. counter-tests    small random inputs biased to the boundaries, compared with the reference
                      solution (only when the teacher uploaded one)
Params: cases (themes), variants, random_tests, max_generated.
"""
import random

from grading import compare, execution, inputspec
from grading.analyzers import correctness
from grading.analyzers.common import clamp01, params, result, seed_for
from grading.types import OK, UNAVAILABLE

DEFAULT_VARIANTS = ["trailing_newline", "extra_spaces"]
REF_FLAGS = ["-O2"]


def variant(text: str, kind: str) -> str | None:
    if kind == "trailing_newline":
        return text.rstrip("\n") if text.endswith("\n") else text + "\n"
    if kind == "extra_spaces":
        lines = text.split("\n")
        if not any(len(ln.split()) > 1 for ln in lines):
            return None
        return "\n".join("   ".join(ln.split()) if ln.strip() else ln for ln in lines)
    return None


def _run_check(kind, theme, reason, inp, expected, run, ub_run, ctx, mode, need_output=True):
    status, why = compare.classify_run(run, ctx.time_limit_s)
    actual = run.get("stdout", "")
    if status == "ok" and ub_run is not None:
        san = compare.sanitizer_message(execution.strip_paths(ub_run.get("stderr", "")))
        if san:
            status, why = "undefined_behaviour", f"UndefinedBehaviorSanitizer: {san}"
    if status == "ok":
        if expected is not None:
            if not compare.outputs_match(expected, actual, mode):
                status, why = "wrong_answer", compare.explain_mismatch(expected, actual)
        elif need_output and not compare.normalize(actual):
            status, why = "no_output", "the program printed nothing"
    return {
        "kind": kind, "theme": theme, "reason": reason, "status": "pass" if status == "ok" else status,
        "passed": status == "ok", "input": inp, "expected": expected,
        "actual": compare.short(actual, 1000), "explanation": why,
    }


def analyze(ctx, metric):
    p = params(metric)
    themes = [inputspec.theme_name(t) for t in p.get("cases", [])]
    mode = p.get("compare", "trailing_ws")
    tests = ctx.sub.tests
    rng = random.Random(seed_for(ctx, "edge"))
    spec, spec_note = ctx.rules.get("input_spec"), "from rules.json"
    if not spec:
        spec = inputspec.infer(tests)
        spec_note = spec.get("note") if spec else "the input format could not be inferred from the accepted tests"
    reference = ctx.sub.reference_source
    notes: list[str] = []
    checks: list[dict] = []

    # 1. accepted tests in a requested category (reuses the correctness runs)
    cat_tests = [t for t in tests if inputspec.theme_name(t.get("category", "")) in themes]
    if cat_tests:
        runs = correctness.run_tests(ctx)
        for t in cat_tests:
            c = correctness.check(t, runs[t["id"]], ctx, mode, None)
            checks.append({"kind": "category_test", "theme": inputspec.theme_name(t["category"]),
                           "reason": f"accepted test {t['id']} ({t['category']}): {t.get('explanation', '')}".strip(),
                           "status": c["status"], "passed": c["passed"], "input": t["input"],
                           "expected": t["expected_output"], "actual": c["actual"], "explanation": c["explanation"]})

    # 2-4. inputs that need new runs, collected into one sandbox job
    pending: list[dict] = []
    for kind in p.get("variants", DEFAULT_VARIANTS):
        if kind == "extra_spaces" and not spec:
            notes.append("extra_spaces variants skipped: the input format is unknown")
            continue
        for t in tests[:4]:
            v = variant(t["input"], kind)
            if v is not None and v != t["input"]:
                pending.append({"kind": "format_variant", "theme": kind, "input": v, "expected": t["expected_output"],
                                "reason": f"{t['id']} with {'the final newline toggled' if kind == 'trailing_newline' else 'extra spaces between values'}; the answer must not change"})
                break
    if spec:
        max_generated = int(p.get("max_generated", 12))
        for theme in themes:
            inputs, note = inputspec.edge_inputs(spec, theme, rng, max_list=int(p.get("max_list", 100_000)))
            if note:
                notes.append(f"{theme}: {note}")
            for inp, why in inputs[:max_generated]:
                pending.append({"kind": "generated", "theme": theme, "input": inp, "expected": None, "reason": why})
        if reference:
            for inp in inputspec.random_inputs(spec, int(p.get("random_tests", 20)), rng):
                pending.append({"kind": "counter_test", "theme": "random", "input": inp, "expected": None,
                                "reason": "random input near the boundaries, compared with the reference solution"})
    elif themes:
        notes.append(f"generated cases skipped: {spec_note}")

    if pending:
        builds = [{"name": "main", "flags": execution.main_flags(ctx.rules)},
                  {"name": "ubsan", "flags": execution.with_std(list(execution.UBSAN_FLAGS), ctx.rules)}]
        runs = []
        for i, c in enumerate(pending):
            runs.append({"id": f"E{i}", "build": "main", "input": c["input"]})
            if c["kind"] in ("generated", "counter_test"):
                runs.append({"id": f"U{i}", "build": "ubsan", "input": c["input"]})
                if reference:
                    runs.append({"id": f"R{i}", "build": "reference", "input": c["input"]})
        if reference:
            builds.append({"name": "reference", "source": reference,
                           "flags": execution.with_std(list(REF_FLAGS), ctx.rules)})
        res = execution.run_job(ctx, builds, runs)
        by_id = {r["id"]: r for r in res["runs"]}
        if reference and not res["builds"]["reference"]["ok"]:
            notes.append("the reference solution did not compile; its checks were dropped")
        dropped = 0
        for i, c in enumerate(pending):
            expected = c["expected"]
            if reference and c["kind"] in ("generated", "counter_test"):
                ref = by_id.get(f"R{i}", {})
                if compare.classify_run(ref, ctx.time_limit_s)[0] != "ok":
                    dropped += 1
                    continue   # the reference rejects this input, so it is not a fair check
                expected = ref.get("stdout", "")
            elif c["kind"] == "counter_test":
                continue
            ub = by_id.get(f"U{i}") if c["kind"] in ("generated", "counter_test") else None
            checks.append(_run_check(c["kind"], c["theme"], c["reason"], c["input"], expected,
                                     by_id[f"E{i}"], ub, ctx, mode))
        if dropped:
            notes.append(f"{dropped} generated input(s) dropped because the reference solution rejected them")

    if not checks:
        return result(metric, status=UNAVAILABLE,
                      feedback="No edge-case checks could be built for this assignment.",
                      evidence={"notes": notes, "input_format": spec_note})

    passed = sum(c["passed"] for c in checks)
    failing = [c for c in checks if not c["passed"]]
    failing.sort(key=lambda c: (c["kind"] != "category_test", len(c["input"])))   # smallest counter-example first
    feedback = f"{passed} of {len(checks)} edge-case checks pass."
    if failing:
        f = failing[0]
        feedback += f" Fails on {f['theme']}: {f['explanation']}."
    suggestions = []
    themes_failed = {c["theme"] for c in failing}
    if "int_overflow" in themes_failed:
        suggestions.append("Values near INT_MAX overflow an int: use long long, or check the range before the arithmetic.")
    if themes_failed & {"trailing_newline", "extra_spaces"}:
        suggestions.append("Read input with scanf-style tokens so extra spaces and a missing final newline do not matter.")
    if themes_failed & {"empty", "single"}:
        suggestions.append("Handle the smallest inputs (0 or 1 element) explicitly.")
    if "negatives" in themes_failed or "zero" in themes_failed:
        suggestions.append("Test your program with negative numbers and zero.")
    return result(
        metric, status=OK, score=clamp01(passed / len(checks)), feedback=feedback, suggestions=suggestions,
        evidence={
            "checks_passed": passed,
            "checks_total": len(checks),
            "themes": themes,
            "input_format": spec_note,
            "reference_solution": bool(reference),
            "notes": notes,
            "failing": failing[: int(p.get("show_failures", 5))],
            "failing_total": len(failing),
            "checks": [{"kind": c["kind"], "theme": c["theme"], "status": c["status"], "reason": c["reason"]}
                       for c in checks],
        },
    )
