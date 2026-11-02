"""Compare a program's output with the expected output and explain any difference."""
import math
import re

SIGNAL_HELP = {
    "SIGSEGV": "segmentation fault (invalid memory access, e.g. a bad pointer or an array index out of range)",
    "SIGABRT": "the program aborted (often a failed assert or a corrupted heap)",
    "SIGFPE": "arithmetic error (for example division by zero)",
    "SIGKILL": "killed by the sandbox",
    "SIGXCPU": "CPU time limit exceeded",
    "SIGXFSZ": "output limit exceeded (the program printed more than 1 MiB)",
    "SIGBUS": "bus error (misaligned or invalid memory access)",
    "SIGILL": "illegal instruction",
}


def normalize(text: str) -> list[str]:
    """Lines with trailing whitespace removed; trailing blank lines dropped. Leading spaces are kept."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _tokens_equal(a: str, b: str, tol: float | None) -> bool:
    if a == b:
        return True
    if tol is None:
        return False
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    return math.isclose(x, y, rel_tol=tol, abs_tol=tol)


def outputs_match(expected: str, actual: str, mode: str = "trailing_ws", tol: float | None = None) -> bool:
    """mode: "exact", "trailing_ws" (default: ignore trailing spaces and final newlines) or "tokens"."""
    if mode == "exact":
        return (expected or "") == (actual or "")
    if mode == "tokens":
        e, a = (expected or "").split(), (actual or "").split()
        return len(e) == len(a) and all(_tokens_equal(x, y, tol) for x, y in zip(e, a))
    e, a = normalize(expected), normalize(actual)
    if tol is None:
        return e == a
    return len(e) == len(a) and all(
        len(x.split()) == len(y.split()) and all(_tokens_equal(p, q, tol) for p, q in zip(x.split(), y.split()))
        for x, y in zip(e, a))


def short(text: str, limit: int = 300) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more characters]"


def sanitizer_message(stderr: str) -> str | None:
    """First sanitizer diagnostic in stderr, without sandbox paths."""
    for pat in (r"runtime error: ([^\n]+)", r"ERROR: AddressSanitizer: ([\w-]+)", r"ERROR: LeakSanitizer: ([^\n]+)"):
        m = re.search(pat, stderr or "")
        if m:
            return m.group(1).strip()
    return None


def classify_run(run: dict, time_limit_s: float) -> tuple[str, str]:
    """Return (status, explanation) for a run that should have exited normally."""
    if run.get("unavailable"):
        return "unavailable", run["unavailable"]
    if run.get("skipped"):
        return "skipped", f"not run: {run.get('reason', 'skipped')}"
    if run.get("timed_out") or run.get("over_cpu_limit") or run.get("signal") == "SIGXCPU":
        return "timeout", f"did not finish within the {time_limit_s:g} s time limit (possible infinite loop or a too-slow algorithm)"
    if run.get("signal") == "SIGXFSZ":
        return "output_limit", SIGNAL_HELP["SIGXFSZ"]
    if run.get("signal"):
        sig = run["signal"]
        return "crash", f"crashed with {sig}: {SIGNAL_HELP.get(sig, 'terminated by a signal')}"
    if run.get("returncode", 0) != 0:
        san = sanitizer_message(run.get("stderr", ""))
        if san:
            return "runtime_error", f"runtime error: {san}"
        return "runtime_error", f"exited with code {run['returncode']} (a C program should return 0 from main on success)"
    return "ok", ""


def explain_mismatch(expected: str, actual: str) -> str:
    e, a = normalize(expected), normalize(actual)
    if not a:
        return "the program printed nothing"
    for i, (x, y) in enumerate(zip(e, a), 1):
        if x != y:
            hint = ""
            if x.strip() == y.strip():
                hint = " (only the leading spaces differ)"
            elif x.lower() == y.lower():
                hint = " (only upper/lower case differs)"
            elif " ".join(x.split()) == " ".join(y.split()):
                hint = " (only the spacing between values differs)"
            return f"line {i}: expected {short(x, 120)!r} but got {short(y, 120)!r}{hint}"
    if len(a) < len(e):
        return f"output stops after {len(a)} line(s); expected {len(e)} line(s), next expected line is {short(e[len(a)], 120)!r}"
    return f"{len(a) - len(e)} extra line(s) after the expected output, starting with {short(a[len(e)], 120)!r}"
