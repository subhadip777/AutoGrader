"""report.json (for machines) and report.txt (what the student reads).

Both are student-safe: they contain the failing inputs the assignment brief asks for, but never
the passing hidden tests, the rules file or anything about other students. Teacher-only details
(who a flagged submission resembles) go to review.json.
"""
import hashlib
import json
import textwrap

from grading.types import ERROR, OK, PARTIAL, SKIPPED, UNAVAILABLE

REPORT_VERSION = 1

USEFULNESS = [
    {"use_case": "First-pass grading of large classes",
     "example": "300 submissions for a sorting assignment are compiled, tested and scored overnight; the "
                "instructor only reads reports whose grade is incomplete or flagged.",
     "benefit": "The same rules are applied to every student, and every point lost is explained."},
    {"use_case": "Immediate feedback while students practise",
     "example": "A student whose sum overflows for INT_MAX + 1 gets that exact input, the expected output "
                "and the UBSan message within a minute, and can resubmit.",
     "benefit": "Concrete counter-examples teach more than a bare score."},
    {"use_case": "Plagiarism and LLM-copy triage",
     "example": "Two submissions with renamed variables reach similarity 0.93 against a 0.85 threshold and "
                "are flagged; the instructor checks only those pairs.",
     "benefit": "Review time goes to the suspicious cases only, and no one is penalised automatically."},
    {"use_case": "Coding-interview and hiring screens",
     "example": "Candidates are ranked by correctness, edge cases and memory safety, with a per-metric "
                "explanation for every rejection.",
     "benefit": "Fast, explainable first-round filtering."},
]
LIMITATIONS = [
    {"limitation": "Tests cannot prove correctness",
     "example": "A program that special-cases the exact hidden inputs passes every test and still gets full "
                "correctness marks.",
     "mitigation": "Upload a reference solution so random counter-tests are compared against it."},
    {"limitation": "LLM-written expected outputs can be wrong",
     "example": "The model claims the digit sum of -1234 is -10; a correct program printing 10 fails that test.",
     "mitigation": "The teacher review step before Accept; edit or regenerate doubtful tests."},
    {"limitation": "Timing-based complexity is an estimate",
     "example": "An O(n log n) sort and an O(n) loop can produce the same curve at n <= 32000 when input "
                "reading dominates, so both are reported as O(n).",
     "mitigation": "Use larger sizes in the rules; the report gives the fit quality and a confidence level."},
    {"limitation": "Similarity misses rewritten copies and over-flags tiny programs",
     "example": "An LLM answer rewritten with a different loop structure scores 0.4 and is not flagged, while "
                "two honest 6-line add-two-numbers programs look identical.",
     "mitigation": "Flags are only review requests; short programs are never flagged."},
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(sub, first_pass: dict, results: list, agg: dict, tool_versions: dict, flags: list[str],
          graded_at: str, fingerprint: str) -> tuple[dict, dict]:
    """Return (student report, teacher review)."""
    metrics = []
    rows = {r["name"]: r for r in agg["rows"]}
    suggestions: list[str] = []
    for r in results:
        d = r.to_dict()
        d["contribution"] = rows[r.name]["contribution"]
        metrics.append(d)
        for s in r.suggestions:
            if s not in suggestions:
                suggestions.append(s)
    failed_tests = next((m["evidence"].get("failing", []) for m in metrics if m["analyzer"] == "io_tests"), [])
    counter_tests = next((m["evidence"].get("failing", []) for m in metrics if m["analyzer"] == "edge_case_runner"), [])
    smoke = first_pass.get("smoke") or {}
    report = {
        "report_version": REPORT_VERSION,
        "assignment": {"id": sub.assignment_id, "title": sub.title},
        "student": {"name": sub.name, "roll_number": sub.roll_number},
        "submission": {"file": "solution.c", "attempt": sub.attempt, "submitted_at": sub.submitted_at,
                       "sha256": sub.source_sha256, "lines": len(sub.source.splitlines())},
        "graded_at": graded_at,
        "grade": agg["grade"],
        "max_grade": agg["max_grade"],
        "coverage": agg["coverage"],
        "complete": agg["complete"],
        "provisional": "originality_review" in flags or not agg["complete"],
        "incomplete_metrics": agg["incomplete_metrics"],
        "partial_metrics": agg["partial_metrics"],
        "flags": flags,
        "first_pass": {
            "compiled": first_pass.get("compiled"),
            "compile_flags": " ".join(first_pass.get("compile_flags", [])),
            "compiler_output": first_pass.get("compiler_output", "")[:4000] if not first_pass.get("compiled") else "",
            "smoke_ok": first_pass.get("smoke_ok"),
            "smoke": smoke,
            "suspected_infinite_loop": first_pass.get("suspected_infinite_loop"),
            "static_sanity": first_pass.get("sanity", {}),
        },
        "metrics": metrics,
        "failed_tests": failed_tests,
        "counter_tests": counter_tests,
        "runtime": {"smoke_cpu_ms": smoke.get("cpu_ms"), "smoke_wall_ms": smoke.get("wall_ms"),
                    "smoke_peak_rss_kb": smoke.get("max_rss_kb"),
                    "note": "peak RSS includes about 10 MB used by the sandbox runner itself"},
        "suggestions": suggestions[:10],
        "tool_versions": tool_versions,
        "rules_sha256": sub.rules_sha256,
        "tests_sha256": sha256_text(json.dumps(sub.tests, sort_keys=True)),
        "reproducibility": {
            "fingerprint": fingerprint,
            "deterministic_metrics": [r.name for r in results if r.deterministic],
            "nondeterministic_metrics": [r.name for r in results if not r.deterministic],
            "note": "Deterministic metrics give identical results for the same source, rules, tests and tool "
                    "versions. Readability (LLM) and complexity (timing) can vary slightly between runs.",
        },
        "usefulness_limitations": {"usefulness": USEFULNESS, "limitations": LIMITATIONS},
    }
    review = {
        "grade": agg["grade"], "flags": flags,
        "originality": [{"metric": r.name, **r.private} for r in results if r.private],
    }
    return report, review


STATUS_TEXT = {OK: "", PARTIAL: "partial", SKIPPED: "skipped", UNAVAILABLE: "unavailable", ERROR: "analyzer error"}


def _wrap(text: str, indent: str, width: int = 78) -> str:
    return "\n".join(textwrap.wrap(text, width=width, initial_indent=indent,
                                   subsequent_indent=" " * len(indent))) or indent


def _block(label: str, text: str, indent: str = "        ") -> list[str]:
    lines = (text or "").rstrip("\n").split("\n") or [""]
    if len(lines) > 12:
        lines = lines[:12] + [f"... ({len(lines) - 12} more lines)"]
    out = [f"{indent}{label:<9} {lines[0] if lines[0] else '(empty)'}"]
    out += [f"{indent}{'':<9} {ln}" for ln in lines[1:]]
    return out


def to_text(report: dict) -> str:
    a, s, sub = report["assignment"], report["student"], report["submission"]
    L = [
        f"===== Grading report: {a['title']} ({a['id']}) =====",
        f"Student      : {s['name']} ({s['roll_number']})",
        f"Attempt      : {sub['attempt']}, submitted {sub['submitted_at']}",
        f"Graded at    : {report['graded_at']}",
        f"Source       : solution.c, {sub['lines']} lines, sha256 {sub['sha256'][:16]}...",
        "",
        f"Overall grade: {report['grade']:.1f} / {report['max_grade']:.0f}"
        + ("   (PROVISIONAL, see notes)" if report["provisional"] else ""),
    ]
    if report["incomplete_metrics"] or report["partial_metrics"]:
        L.append(f"Measured     : {report['coverage'] * 100:.0f}% of the weight could be measured; "
                 "unmeasured parts count as 0 until regraded.")
    fp = report["first_pass"]
    L += ["", "--- First pass ---",
          f"Compiled     : {'yes' if fp['compiled'] else 'NO'} ({fp['compile_flags']})"]
    if fp["compiled"]:
        smoke = fp.get("smoke") or {}
        L.append(f"Smoke run    : {'ok' if fp['smoke_ok'] else smoke.get('status', '?')}"
                 + (f", {smoke.get('cpu_ms')} ms CPU" if smoke.get("cpu_ms") is not None else "")
                 + (f" - {smoke.get('explanation')}" if smoke.get("explanation") else ""))
    if fp["suspected_infinite_loop"]:
        L.append("FLAG         : suspected infinite loop - execution-based metrics were skipped")
    for note in fp.get("static_sanity", {}).get("notes", []):
        L.append(f"Sanity       : {note}")
    if not fp["compiled"] and fp.get("compiler_output"):
        L += ["Compiler output:"] + ["    " + ln for ln in fp["compiler_output"].splitlines()[:15]]

    L += ["", "--- Metrics ---", f"{'Metric':<15}{'Weight':>7}{'Score':>9}{'Points':>9}  Verdict"]
    for m in report["metrics"]:
        w = m["weight"] * 100
        score = f"{m['score'] * w:.1f}/{w:.0f}" if m["score"] is not None else "-"
        tag = STATUS_TEXT.get(m["status"], m["status"])
        verdict = (f"[{tag}] " if tag else "") + m["feedback"]
        L.append(f"{m['name'][:14]:<15}{w:>6.0f}%{score:>9}{m['contribution']:>9.1f}  {textwrap.shorten(verdict, 120)}")
    if report["failed_tests"]:
        L += ["", "--- Where you failed (accepted tests) ---"]
        for t in report["failed_tests"]:
            L.append(f"Test {t['id']} [{t['status']}]")
            L += _block("INPUT:", t["input"]) + _block("EXPECTED:", t["expected"]) + _block("GOT:", t["actual"])
            L.append(_wrap(f"WHY:      {t['explanation']}", "        "))
    if report["counter_tests"]:
        L += ["", "--- Counter-tests and edge cases that fail ---"]
        for t in report["counter_tests"]:
            L.append(f"{t['kind']} / {t['theme']}: {t['reason']}")
            L += _block("INPUT:", t["input"])
            if t.get("expected") is not None:
                L += _block("EXPECTED:", t["expected"])
            L += _block("GOT:", t["actual"])
            L.append(_wrap(f"WHY:      {t['explanation']}", "        "))
    details = []
    for m in report["metrics"]:
        ev = m["evidence"]
        if m["analyzer"] == "complexity_estimator" and ev.get("measurements"):
            pts = ", ".join(f"n={p['n']}: {p['min_cpu_ms']:.2f} ms" for p in ev["measurements"])
            est = (f"Estimated {ev['estimated']} ({ev.get('confidence')} confidence)" if ev.get("estimated")
                   else "No class estimated")
            timeouts = "".join(f" Timed out at n={f['n']}." for f in ev.get("failures", []) if f["status"] == "timeout")
            details.append(f"Complexity: {pts}.{timeouts} {est}, required {ev.get('required')}. {ev.get('limitations')}")
        if m["analyzer"] == "sanitizer_run":
            for f in ev.get("findings", [])[:5]:
                where = f" line {f['line']}" if f.get("line") else ""
                details.append(f"Memory: {f['tool']}{where}, test {f['test']}: {f['description']}")
            if ev.get("tools", {}).get("valgrind") not in (None, "ok"):
                details.append(f"Memory: valgrind not used ({ev['tools']['valgrind']})")
        if m["analyzer"] == "compiler_warnings":
            for d in ev.get("diagnostics", [])[:5]:
                details.append(f"Compiler: line {d['line']}: {d['kind']}: {d['message']} {d['flag']}".rstrip())
        if m["analyzer"] == "static_analysis":
            for f in ev.get("cppcheck_findings", [])[:5]:
                details.append(f"cppcheck: line {f['line']} {f['severity']}: {f['message']}")
        if m["analyzer"] == "llm_review" and m["status"] == OK:
            details.append("Readability is reviewed by an LLM and is the one metric that is not fully deterministic.")
    if details:
        L += ["", "--- Details ---"] + [_wrap(d, "- ") for d in details]
    if report["suggestions"]:
        L += ["", "--- Suggestions to raise the grade ---"] + [_wrap(s, "- ") for s in report["suggestions"]]
    notes = []
    if "originality_review" in report["flags"]:
        notes.append("Your program is very similar to another submission. This only asks the instructor to "
                     "take a look; it is not a finding of copying and did not change your score.")
    for name in report["incomplete_metrics"]:
        m = next(x for x in report["metrics"] if x["name"] == name)
        notes.append(f"{name} could not be measured ({m['feedback']}) and counts as 0 until the instructor regrades.")
    for name in report["partial_metrics"]:
        notes.append(f"{name} was only partly measured; see its verdict above.")
    if notes:
        L += ["", "--- Notes ---"] + [_wrap(n, "- ") for n in notes]
    ul = report["usefulness_limitations"]
    L += ["", "--- Usefulness & limitations of this evaluation ---", "Useful for:"]
    for i, u in enumerate(ul["usefulness"], 1):
        L += [f"  {i}. {u['use_case']}", _wrap(f"Example: {u['example']}", "     ")]
    L.append("Limits of this report:")
    for i, u in enumerate(ul["limitations"], 1):
        L += [f"  {i}. {u['limitation']}", _wrap(f"Example: {u['example']}", "     ")]
    tv = report["tool_versions"]
    L += ["", "--- Reproducibility ---",
          "Tools        : " + ", ".join(f"{k} {v}" for k, v in sorted(tv.items()) if v),
          f"Rules hash   : sha256:{report['rules_sha256']}",
          f"Tests hash   : sha256:{report['tests_sha256']}",
          f"Fingerprint  : {report['reproducibility']['fingerprint']}", ""]
    return "\n".join(L)
