"""Validation of the grading policy (rules.json). Used when an assignment is created and again
before every grading run, so a malformed policy can never produce a grade."""
import hashlib
import json
import math

from grading import inputspec
from grading.analyzers import REGISTRY
from grading.analyzers.complexity import parse_class
from server import sandbox

WEIGHT_TOLERANCE = 0.001


def rules_hash(rules: dict) -> str:
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def problems(rules: dict) -> list[str]:
    """Every problem found in the policy (empty list = valid)."""
    errs: list[str] = []
    metrics = rules.get("metrics") if isinstance(rules, dict) else None
    if not isinstance(metrics, list) or not metrics:
        return ["the policy needs a non-empty \"metrics\" list"]
    names = set()
    total = 0.0
    for i, m in enumerate(metrics, 1):
        if not isinstance(m, dict):
            errs.append(f"metric {i} is not an object")
            continue
        label = m.get("name") or f"metric {i}"
        if not isinstance(m.get("name"), str) or not m["name"].strip():
            errs.append(f"metric {i} needs a \"name\"")
        elif m["name"] in names:
            errs.append(f"metric name {m['name']!r} is used twice")
        names.add(m.get("name"))
        if m.get("analyzer") not in REGISTRY:
            errs.append(f"{label}: unknown analyzer {m.get('analyzer')!r} (known: {', '.join(sorted(REGISTRY))})")
        w = m.get("weight")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or not 0 <= w <= 1:
            errs.append(f"{label}: weight must be a number between 0 and 1")
        else:
            total += w
        p = m.get("params", {})
        if not isinstance(p, dict):
            errs.append(f"{label}: params must be an object")
            continue
        if "flags" in p:
            try:
                sandbox.split_flags(p["flags"])
            except ValueError as e:
                errs.append(f"{label}: {e}")
        if m.get("analyzer") == "complexity_estimator":
            if not parse_class(p.get("required", "")):
                errs.append(f"{label}: params.required must be a bound such as \"O(n log n)\"")
            sizes = p.get("sizes")
            if sizes is not None and (not isinstance(sizes, list) or not all(isinstance(s, int) and s >= 0 for s in sizes)):
                errs.append(f"{label}: params.sizes must be a list of non-negative integers")
        if m.get("analyzer") == "similarity_flag":
            t = p.get("flag_threshold", 0.85)
            if not isinstance(t, (int, float)) or not 0 < t <= 1:
                errs.append(f"{label}: params.flag_threshold must be between 0 and 1")
        if m.get("analyzer") == "edge_case_runner" and not isinstance(p.get("cases", []), list):
            errs.append(f"{label}: params.cases must be a list")
    if not errs and not math.isclose(total, 1.0, abs_tol=WEIGHT_TOLERANCE):
        errs.append(f"weights must sum to 1.00 (got {total:.3f})")
    t = rules.get("time_limit_s", 1)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 < t <= 10:
        errs.append("time_limit_s must be between 0 and 10 seconds")
    mem = rules.get("memory_limit_mb", 64)
    if isinstance(mem, bool) or not isinstance(mem, int) or not 8 <= mem <= 1024:
        errs.append("memory_limit_mb must be an integer between 8 and 1024")
    if "compile_flags" in rules:
        try:
            sandbox.split_flags(rules["compile_flags"])
        except ValueError as e:
            errs.append(f"compile_flags: {e}")
    if "input_spec" in rules:
        try:
            inputspec.validate(rules["input_spec"])
        except inputspec.SpecError as e:
            errs.append(f"input_spec: {e}")
    return errs


def validate(rules: dict) -> None:
    errs = problems(rules)
    if errs:
        raise ValueError("; ".join(errs))
