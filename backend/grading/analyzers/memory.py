"""sanitizer_run: memory safety with AddressSanitizer, UBSan and valgrind.

The program is built with the rule's sanitizer flags and run on the accepted tests. A clean
program built with the same flags runs first as a self-test: if it fails, the sanitizer
runtime does not work in this sandbox and the metric is "unavailable" (never "clean").
Valgrind runs a -O0 -g build on a few tests when it is installed; when it is not, the
evidence says so. perf is not used: perf_event_open is blocked inside the sandbox, so the
profile reported is the CPU time and peak memory measured by the runner for each test.
Params: flags, max_tests (5), valgrind (true), valgrind_tests (2).
"""
import re

from grading import execution
from grading.analyzers.common import clamp01, params, result
from grading.types import OK, UNAVAILABLE
from server import sandbox

PENALTY = {"leak": 0.2, "undefined_behaviour": 0.3, "uninitialised": 0.3, "memory_error": 0.5}
ASAN_KINDS = {
    "heap-buffer-overflow": "buffer overflow on the heap", "stack-buffer-overflow": "buffer overflow on the stack",
    "global-buffer-overflow": "buffer overflow in a global array", "heap-use-after-free": "use after free",
    "stack-use-after-return": "use of a stack variable after its function returned",
    "double-free": "memory freed twice", "attempting double-free": "memory freed twice",
    "SEGV": "invalid memory access", "stack-overflow": "stack overflow (very deep recursion)",
    "alloc-dealloc-mismatch": "mismatched allocation/free",
}


def _loc(text: str) -> int | None:
    m = re.search(r"sol\.c:(\d+)", text or "")
    return int(m.group(1)) if m else None


def parse_sanitizers(stderr: str, test_id: str) -> list[dict]:
    text = execution.strip_paths(stderr)
    found = []
    for m in re.finditer(r"ERROR: AddressSanitizer: ([\w-]+)", text):
        kind = m.group(1)
        block = text[m.start():m.start() + 1500]
        found.append({"tool": "ASan", "category": "memory_error", "kind": kind,
                      "description": ASAN_KINDS.get(kind, kind), "line": _loc(block), "test": test_id,
                      "excerpt": "\n".join(block.splitlines()[:6])})
    if "ERROR: LeakSanitizer: detected memory leaks" in text:
        leaked = sum(int(x) for x in re.findall(r"(?:Direct|Indirect) leak of (\d+) byte", text))
        block = text[text.index("ERROR: LeakSanitizer"):][:1500]
        found.append({"tool": "LSan", "category": "leak", "kind": "memory-leak",
                      "description": f"memory leak ({leaked} bytes not freed)", "line": _loc(block), "test": test_id,
                      "excerpt": "\n".join(block.splitlines()[:6])})
    for m in re.finditer(r"sol\.c:(\d+):\d+: runtime error: ([^\n]+)", text):
        found.append({"tool": "UBSan", "category": "undefined_behaviour", "kind": "undefined-behaviour",
                      "description": m.group(2).strip(), "line": int(m.group(1)), "test": test_id,
                      "excerpt": m.group(0)})
    return found


def parse_valgrind(stderr: str, test_id: str) -> list[dict]:
    text = execution.strip_paths(stderr)
    found = []
    for pat, cat, desc in (
        (r"Invalid (read|write) of size (\d+)", "memory_error", "invalid {0} of {1} bytes"),
        (r"(Conditional jump or move depends on uninitialised value|Use of uninitialised value)", "uninitialised",
         "use of an uninitialised value"),
        (r"Invalid free\(\)", "memory_error", "invalid free"),
        (r"definitely lost: ([\d,]+) bytes", "leak", "{0} bytes definitely lost"),
    ):
        for m in re.finditer(pat, text):
            if cat == "leak" and m.group(1).replace(",", "") == "0":
                continue
            block = text[m.start():m.start() + 800]
            found.append({"tool": "valgrind", "category": cat, "kind": cat.replace("_", "-"),
                          "description": desc.format(*m.groups()), "line": _loc(block), "test": test_id,
                          "excerpt": "\n".join(block.splitlines()[:5])})
    return found


def analyze(ctx, metric):
    p = params(metric)
    flags = sandbox.split_flags(p.get("flags", "-fsanitize=address,undefined"))
    if not any(f.startswith("-fsanitize=") for f in flags):
        flags.append("-fsanitize=address,undefined")
    san_flags = execution.with_std(flags + ["-g", "-O1", "-fno-omit-frame-pointer"], ctx.rules)
    tests = ctx.sub.tests[: int(p.get("max_tests", 5))]
    use_vg = bool(p.get("valgrind", True))
    vg_tests = ctx.sub.tests[: int(p.get("valgrind_tests", 2))] if use_vg else []
    builds = [{"name": "selftest", "flags": san_flags, "source": execution.CLEAN_PROGRAM},
              {"name": "san", "flags": san_flags}]
    if vg_tests:
        builds.append({"name": "debug", "flags": execution.with_std(["-O0", "-g"], ctx.rules)})
    runs = [{"id": "SELFTEST", "build": "selftest", "input": ""}]
    runs += [{"id": t["id"], "build": "san", "input": t["input"]} for t in tests]
    runs += [{"id": "VG-" + t["id"], "build": "debug", "input": t["input"], "wrapper": "valgrind"} for t in vg_tests]
    res = execution.run_job(ctx, builds, runs)
    by_id = {r["id"]: r for r in res["runs"]}

    st = by_id["SELFTEST"]
    san_ok = res["builds"]["selftest"]["ok"] and st.get("returncode") == 0 and "ERROR:" not in st.get("stderr", "")
    tools = {"sanitizers": "ok" if san_ok else "unavailable"}
    findings: list[dict] = []
    profile = []
    if san_ok:
        if not res["builds"]["san"]["ok"]:
            return result(metric, status=UNAVAILABLE, feedback="The sanitizer build of the program failed.",
                          evidence={"compiler_output": execution.strip_paths(res["builds"]["san"]["stderr"])[:3000]})
        for t in tests:
            r = by_id[t["id"]]
            findings += parse_sanitizers(r.get("stderr", ""), t["id"])
            profile.append({"test": t["id"], "cpu_ms": r.get("cpu_ms"), "max_rss_kb": r.get("max_rss_kb")})
    vg_available = False
    for t in vg_tests:
        r = by_id["VG-" + t["id"]]
        if r.get("unavailable"):
            tools["valgrind"] = r["unavailable"]
            break
        vg_available = True
        findings += parse_valgrind(r.get("stderr", ""), t["id"])
    if vg_available:
        tools["valgrind"] = "ok"
    elif not use_vg:
        tools["valgrind"] = "disabled by the rules"
    tools["perf"] = "not available: perf_event_open is blocked in the sandbox; CPU time and peak memory are reported instead"

    if not san_ok and not vg_available:
        return result(metric, status=UNAVAILABLE,
                      feedback="Memory safety was not checked: neither the sanitizers nor valgrind work in this sandbox.",
                      evidence={"tools": tools, "selftest_stderr": execution.strip_paths(st.get("stderr", ""))[:2000]})

    unique: dict[tuple, dict] = {}
    for f in findings:
        unique.setdefault((f["tool"], f["kind"], f["line"], f["description"]), f)
    findings = list(unique.values())
    categories = sorted({f["category"] for f in findings})
    score = clamp01(1 - sum(PENALTY[c] for c in categories))
    if findings:
        first = findings[0]
        where = f" at line {first['line']}" if first["line"] else ""
        feedback = f"{len(findings)} memory/undefined-behaviour issue(s); first: {first['description']}{where} ({first['tool']}, test {first['test']})."
    else:
        feedback = "No memory errors, leaks or undefined behaviour detected on the tests run."
    if not san_ok:
        feedback += " Sanitizers were unavailable; only valgrind was used."
    suggestions = []
    if "leak" in categories:
        suggestions.append("Free every block you malloc before the program ends.")
    if "memory_error" in categories:
        suggestions.append("Check array indices and pointer arithmetic against the allocated size.")
    if "undefined_behaviour" in categories:
        suggestions.append("Avoid signed integer overflow and other undefined behaviour reported by UBSan.")
    if "uninitialised" in categories:
        suggestions.append("Initialise every variable before reading it.")
    return result(metric, status=OK, score=score, feedback=feedback, suggestions=suggestions,
                  evidence={"tools": tools, "flags": " ".join(san_flags), "tests_run": [t["id"] for t in tests],
                            "valgrind_tests": [t["id"] for t in vg_tests] if vg_available else [],
                            "findings": findings[:20], "categories": categories},
                  timings={"profile": profile})
