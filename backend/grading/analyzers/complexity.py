"""complexity_estimator: time the program on growing inputs and fit a growth model.

The program runs `repeats` times at each input size; the first (cold) run is dropped and the
median CPU time of the rest is used. Models t(n) = a + b*f(n), b >= 0, are fitted by least
squares for f in 1, log n, n, n log n, n^2, n^3 and 2^n. If the total growth is within the
measurement noise the program is classed as O(1). Otherwise the best-fitting model wins, with
a simpler model preferred when it fits almost as well.

This is an empirical estimate over a few sizes, not a proof: constant factors, caches, I/O and
small n can make, for example, O(n) and O(n log n) indistinguishable. The evidence records the
fit quality and a confidence level so a teacher can judge it.
Params: required ("O(n log n)"), sizes, repeats, scale_fields, partial_credit.
"""
import math
import re
import statistics

from grading import compare, execution, inputspec
from grading.analyzers.common import params, result, seed_for
from grading.types import OK, UNAVAILABLE

CLASSES = ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3)", "O(2^n)"]
MODELS = {
    "O(log n)": lambda n: math.log2(max(n, 2)),
    "O(n)": lambda n: float(n),
    "O(n log n)": lambda n: n * math.log2(max(n, 2)),
    "O(n^2)": lambda n: float(n) ** 2,
    "O(n^3)": lambda n: float(n) ** 3,
    "O(2^n)": lambda n: 2.0 ** min(n, 1000),
}
DEFAULT_SIZES = [1000, 2000, 4000, 8000, 16000, 32000]
NOISE_FLOOR_MS = 0.4      # CPU-time differences below this are treated as measurement noise
RELATIVE_NOISE = 0.5      # ... and so are differences below half the time at the smallest size
MIN_RANK_CORRELATION = 0.8  # growth must be (almost) monotonic in n to count
SIMPLER_IF_WITHIN = 1.10  # prefer a simpler model if its error is within 10 % of the best


def parse_class(text: str) -> str | None:
    t = str(text or "").lower().replace(" ", "").replace("²", "^2").replace("³", "^3").replace("*", "")
    t = t.replace("lgn", "logn").replace("nlg", "nlog")
    table = {"o(1)": "O(1)", "o(logn)": "O(log n)", "o(n)": "O(n)", "o(nlogn)": "O(n log n)",
             "o(n^2)": "O(n^2)", "o(n2)": "O(n^2)", "o(n^3)": "O(n^3)", "o(n3)": "O(n^3)",
             "o(2^n)": "O(2^n)", "o(exp)": "O(2^n)"}
    return table.get(t)


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least squares y = a + b x with b >= 0. Returns (a, b, sse)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx > 0 else 0.0
    if b < 0:
        b = 0.0
    a = my - b * mx
    return a, b, sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))


def rank_correlation(xs: list[float], ys: list[float]) -> float:
    """Spearman's rho (no ties expected in sizes; ties in times get averaged ranks)."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def estimate(sizes: list[int], times_ms: list[float], noise_ms: float) -> dict:
    """Pick a complexity class for the measured (size, time) points."""
    sst = sum((t - statistics.fmean(times_ms)) ** 2 for t in times_ms)
    growth = max(times_ms[-1] - times_ms[0], 0.0)
    rho = rank_correlation([float(n) for n in sizes], times_ms)
    fits = {}
    for name, f in MODELS.items():
        if name == "O(2^n)" and max(sizes) > 60:
            continue
        top = f(max(sizes))
        xs = [f(n) / top for n in sizes]   # normalised for numerical stability
        a, b, sse = _fit(xs, times_ms)
        fits[name] = {"intercept_ms": round(a, 4), "slope_ms": round(b, 4), "sse": sse,
                      "r2": round(1 - sse / sst, 4) if sst > 0 else 0.0}
    threshold = max(NOISE_FLOOR_MS, 3 * noise_ms, RELATIVE_NOISE * times_ms[0])
    if growth <= threshold or rho < MIN_RANK_CORRELATION:
        why = (f"time grew by only {growth:.3f} ms over the sizes, within measurement noise" if growth <= threshold
               else f"time does not rise steadily with n (rank correlation {rho:.2f}), so the differences are noise")
        return {"class": "O(1)", "fits": fits, "growth_ms": round(growth, 4), "noise_threshold_ms": round(threshold, 4),
                "rank_correlation": round(rho, 3), "confidence": "medium" if len(sizes) >= 4 else "low",
                "reason": why}
    best = min(fits, key=lambda k: fits[k]["sse"])
    for name in CLASSES[1:]:   # simplest first
        if name in fits and fits[name]["sse"] <= fits[best]["sse"] * SIMPLER_IF_WITHIN + 1e-9:
            best = name
            break
    ranked = sorted(fits.values(), key=lambda v: v["sse"])
    r2 = fits[best]["r2"]
    separation = (ranked[1]["sse"] / ranked[0]["sse"]) if len(ranked) > 1 and ranked[0]["sse"] > 0 else float("inf")
    confidence = "high" if r2 >= 0.97 and separation >= 2 and len(sizes) >= 5 else "medium" if r2 >= 0.85 else "low"
    return {"class": best, "fits": fits, "growth_ms": round(growth, 4), "noise_threshold_ms": round(threshold, 4),
            "rank_correlation": round(rho, 3), "confidence": confidence, "reason": f"best fit {best} (R^2 = {r2:.3f})"}


def analyze(ctx, metric):
    p = params(metric)
    required = parse_class(p.get("required", ""))
    if not required:
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback=f"The rules give no recognised required bound ({p.get('required')!r}).")
    spec = ctx.rules.get("input_spec") or inputspec.infer(ctx.sub.tests)
    mode = inputspec.scaling_mode(spec, p) if spec else None
    if not mode:
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback="Complexity was not measured: no input that grows with a size can be built for this assignment.",
                      evidence={"reason": "add an input_spec with a size_field (or scale_fields) to rules.json"})
    lo, hi = inputspec.size_bounds(spec, mode)
    raw = p.get("sizes") or DEFAULT_SIZES
    sizes = sorted({min(max(int(s), lo), hi) for s in raw})
    if len(sizes) < 3:
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback="Complexity was not measured: fewer than three distinct input sizes are allowed.",
                      evidence={"sizes_requested": raw, "allowed_range": [lo, hi]})
    repeats = max(3, min(int(p.get("repeats", 5)), 15))
    seed = seed_for(ctx, "complexity")
    runs = [{"id": f"N{n}", "build": "main", "input": inputspec.scaled_input(spec, mode, n, seed), "repeat": repeats}
            for n in sizes]
    res = execution.run_job(ctx, [{"name": "main", "flags": execution.main_flags(ctx.rules)}], runs)

    points, failures = [], []
    for n, r in zip(sizes, res["runs"]):
        status, why = compare.classify_run(r, ctx.time_limit_s)
        if status != "ok":
            failures.append({"n": n, "status": status, "explanation": why})
            continue
        samples = r["cpu_times_ms"][1:] or r["cpu_times_ms"]
        # Noise only ever adds time, so the fastest repeat is the best estimate of the true cost.
        points.append({"n": n, "min_cpu_ms": round(min(samples), 4), "median_cpu_ms": round(statistics.median(samples), 4),
                       "cpu_ms": samples, "wall_ms": r["wall_times_ms"]})
    evidence = {"required": required, "scaling": {"mode": mode[0], "fields": mode[1]},
                "input_format": spec.get("note", "from rules.json"), "repeats": repeats,
                "measurements": points, "failures": failures,
                "method": "median CPU time per size (first run dropped), least-squares fit of a + b*f(n)",
                "limitations": "Empirical timing over a few sizes; constant factors, I/O and noise can hide or "
                               "imitate growth, so the class is an estimate, not a proof."}
    timeouts = [f for f in failures if f["status"] == "timeout"]
    est = None
    if len(points) >= 3:
        spreads = [statistics.median(pt["cpu_ms"]) - pt["min_cpu_ms"] for pt in points]
        est = estimate([pt["n"] for pt in points], [pt["min_cpu_ms"] for pt in points],
                       statistics.median(spreads) if spreads else 0.0)
        for v in est["fits"].values():
            v["sse"] = round(v["sse"], 6)
        evidence.update(estimated=est["class"], confidence=est["confidence"], fit=est)
    else:
        evidence.update(estimated=None, confidence=None)
    if timeouts:
        seen = f" Growth on the sizes that finished looks like {est['class']}." if est else ""
        return result(metric, status=OK, score=0.0, deterministic=False, evidence=evidence,
                      feedback=f"Timed out at n = {timeouts[0]['n']}: too slow for the required {required}.{seen}",
                      suggestions=[f"Use an algorithm that runs in {required} or better."])
    if est is None:
        return result(metric, status=OK, score=0.0, deterministic=False, evidence=evidence,
                      feedback=f"The program failed on {len(failures)} of the scaling inputs ({failures[0]['explanation']}), "
                               "so its growth could not be measured.")
    diff = CLASSES.index(est["class"]) - CLASSES.index(required)
    partial = float(p.get("partial_credit", 0.5))
    score = 1.0 if diff <= 0 else partial if diff == 1 else 0.0
    if diff <= 0:
        feedback = f"Measured growth is consistent with {est['class']}, within the required {required} ({est['confidence']} confidence)."
        suggestions = []
    else:
        feedback = f"Measured growth looks like {est['class']}, slower than the required {required} ({est['confidence']} confidence)."
        suggestions = [f"Look for nested loops or repeated work; the target is {required}."]
    return result(metric, status=OK, score=score, deterministic=False, feedback=feedback,
                  suggestions=suggestions, evidence=evidence)
