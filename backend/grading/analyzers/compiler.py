"""compiler_warnings: compile with the rule's gcc flags and score the diagnostics.

The build itself happens in the first pass. With -Werror gcc reports warnings as errors
("[-Werror=...]"); those still count as warnings here, because the program is executed from
a separate build without -Werror. Params: flags, penalty_per_warning (default 0.1).
"""
import re

from grading.analyzers.common import clamp01, params, result
from grading.first_pass import warning_flags
from grading.types import OK, SKIPPED

DIAG = re.compile(r"^sol\.c:(\d+):(\d+): (warning|error): (.*?)(?: \[(-W[^\]]+)\])?$", re.M)


def parse(stderr: str) -> list[dict]:
    out = []
    for line, col, kind, msg, flag in DIAG.findall(stderr or ""):
        flag = flag or ""
        promoted = flag.startswith("-Werror=")
        out.append({
            "line": int(line), "column": int(col),
            "kind": "warning" if kind == "warning" or promoted else "error",
            "flag": "-W" + flag[len("-Werror="):] if promoted else flag,
            "message": msg.strip(),
        })
    return out


def analyze(ctx, metric):
    p = params(metric)
    fp = ctx.first_pass
    flags = warning_flags(ctx.rules, metric)
    build = next((b for b in fp["builds"].values() if b["flags"] == flags), None)
    diags = parse(build["stderr"]) if build else []
    if not fp["compiled"]:
        errors = parse(fp["compiler_output"])
        first = next((d for d in errors if d["kind"] == "error"), None)
        msg = f"line {first['line']}: {first['message']}" if first else "see the compiler output"
        return result(metric, status=SKIPPED, score=0.0,
                      feedback=f"The program does not compile ({msg}).",
                      suggestions=["Fix the compilation errors first; nothing else can be tested until the program builds."],
                      evidence={"flags": " ".join(flags), "diagnostics": errors[:20],
                                "compiler_output": fp["compiler_output"][:4000]})
    warnings = [d for d in diags if d["kind"] == "warning"]
    by_flag: dict[str, int] = {}
    for d in warnings:
        by_flag[d["flag"] or "(no flag)"] = by_flag.get(d["flag"] or "(no flag)", 0) + 1
    penalty = float(p.get("penalty_per_warning", 0.1))
    score = clamp01(1 - penalty * len(warnings))
    if warnings:
        summary = ", ".join(f"{k} x{v}" for k, v in sorted(by_flag.items()))
        feedback = f"{len(warnings)} warning(s) with {' '.join(flags)}: {summary}."
        suggestions = [f"Line {d['line']}: {d['message']}" for d in warnings[:3]]
    else:
        feedback = f"No warnings with {' '.join(flags)}."
        suggestions = []
    return result(metric, status=OK, score=score, feedback=feedback, suggestions=suggestions,
                  evidence={"flags": " ".join(flags), "warnings": len(warnings), "by_flag": by_flag,
                            "diagnostics": diags[:30], "werror_build_ok": build["ok"] if build else None})
