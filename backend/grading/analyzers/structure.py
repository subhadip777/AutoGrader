"""static_analysis (cppcheck + lizard) and function_split (lizard).

static_analysis: lizard measures every function's cyclomatic complexity and length, cppcheck
reports likely bugs and style problems. The score is 60 % lizard checks and 40 % cppcheck
(cppcheck_share). If cppcheck is unavailable its share scores 0 and the result is "partial":
a missing tool is never counted as a clean result.
Params: max_cyclomatic (8), max_function_length (40), cppcheck_share (0.4).

function_split: counts functions and helper functions against min_functions/expect_helpers.
Params: min_functions (2), expect_helpers (true), max_main_length (50).
"""
import lizard

from grading.analyzers.common import clamp01, params, result
from grading.types import OK, PARTIAL

CPPCHECK_PENALTY = {"error": 0.25, "warning": 0.15, "style": 0.05, "performance": 0.05,
                    "portability": 0.05, "information": 0.0}
LIZARD_VERSION = getattr(lizard, "version", None) or getattr(getattr(lizard, "lizard_ext", None), "version", "unknown")


def functions(ctx) -> list[dict]:
    if "functions" not in ctx.cache:
        info = lizard.analyze_file.analyze_source_code("sol.c", ctx.sub.source)
        ctx.cache["functions"] = [{
            "name": f.name, "start_line": f.start_line, "end_line": f.end_line,
            "length": f.end_line - f.start_line + 1, "nloc": f.nloc,
            "cyclomatic": f.cyclomatic_complexity, "parameters": len(f.parameters),
        } for f in info.function_list]
        ctx.tool_versions["lizard"] = str(LIZARD_VERSION)
    return ctx.cache["functions"]


def parse_cppcheck(output: str) -> list[dict]:
    items = []
    for line in (output or "").splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4 and parts[0].strip().isdigit():
            if parts[2] in ("missingIncludeSystem", "checkersReport", "normalCheckLevelMaxBranches"):
                continue
            items.append({"line": int(parts[0]), "severity": parts[1], "id": parts[2], "message": parts[3].strip()})
    return items


def analyze_structure(ctx, metric):
    p = params(metric)
    max_ccn = int(p.get("max_cyclomatic", 8))
    max_len = int(p.get("max_function_length", 40))
    share = float(p.get("cppcheck_share", 0.4))
    funcs = functions(ctx)
    too_complex = [f for f in funcs if f["cyclomatic"] > max_ccn]
    too_long = [f for f in funcs if f["length"] > max_len]
    lizard_score = clamp01(1 - 0.25 * len(too_complex) - 0.25 * len(too_long)) if funcs else 0.0

    cpp = (ctx.first_pass.get("static") or {}).get("cppcheck") or {"available": False, "reason": "cppcheck was not run"}
    findings = parse_cppcheck(cpp.get("output", "")) if cpp.get("available") else []
    if cpp.get("available"):
        cpp_score = clamp01(1 - min(0.8, sum(CPPCHECK_PENALTY.get(f["severity"], 0.05) for f in findings)))
        status, score = OK, clamp01((1 - share) * lizard_score + share * cpp_score)
    else:
        cpp_score, status = None, PARTIAL
        score = clamp01((1 - share) * lizard_score)

    parts = []
    if not funcs:
        parts.append("no functions were found")
    for f in too_complex:
        parts.append(f"{f['name']}() has cyclomatic complexity {f['cyclomatic']} (max {max_ccn})")
    for f in too_long:
        parts.append(f"{f['name']}() is {f['length']} lines long (max {max_len})")
    for f in findings[:3]:
        parts.append(f"cppcheck {f['severity']} at line {f['line']}: {f['message']}")
    if status == PARTIAL:
        parts.append(f"cppcheck unavailable ({cpp.get('reason')}), its {share:.0%} share scored 0")
    feedback = "; ".join(parts) + "." if parts else "Functions are short and simple; cppcheck found no issues."
    suggestions = [f"Split {f['name']}() into smaller functions." for f in (too_complex + too_long)[:2]]
    suggestions += [f"Line {f['line']}: {f['message']}" for f in findings[:2]]
    return result(metric, status=status, score=score, feedback=feedback[0].upper() + feedback[1:],
                  suggestions=suggestions,
                  evidence={"functions": funcs, "max_cyclomatic": max_ccn, "max_function_length": max_len,
                            "lizard_score": lizard_score, "cppcheck_score": cpp_score,
                            "cppcheck_available": bool(cpp.get("available")),
                            "cppcheck_unavailable_reason": None if cpp.get("available") else cpp.get("reason"),
                            "cppcheck_findings": findings[:30]})


def analyze_modularity(ctx, metric):
    p = params(metric)
    need = max(1, int(p.get("min_functions", 2)))
    expect_helpers = bool(p.get("expect_helpers", True))
    max_main = int(p.get("max_main_length", 50))
    funcs = functions(ctx)
    helpers = [f["name"] for f in funcs if f["name"] != "main"]
    main = next((f for f in funcs if f["name"] == "main"), None)
    if len(funcs) >= need and (helpers or not expect_helpers):
        score = 1.0
    elif expect_helpers and not helpers:
        score = 0.3 if main else 0.0
    else:
        score = len(funcs) / need
    notes = []
    if main and main["length"] > max_main:
        score -= 0.2
        notes.append(f"main() is {main['length']} lines long (max {max_main})")
    score = clamp01(score)
    if not helpers and expect_helpers:
        feedback = "Only main() is defined; move separate steps (reading, computing, printing) into helper functions."
    else:
        feedback = f"{len(funcs)} function(s) defined ({', '.join(f['name'] + '()' for f in funcs)}); {need} expected."
    if notes:
        feedback += " " + "; ".join(notes) + "."
    suggestions = ["Extract the computation into its own function and call it from main()."] if not helpers else []
    return result(metric, status=OK, score=score, feedback=feedback, suggestions=suggestions,
                  evidence={"functions_defined": len(funcs), "helpers": helpers, "expected_min": need,
                            "expect_helpers": expect_helpers, "main_length": main["length"] if main else None})
