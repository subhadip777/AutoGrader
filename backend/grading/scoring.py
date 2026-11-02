"""Weighted grade from the analyzer results.

grade = 100 * sum(weight * score). A metric without a measured score (unavailable or error)
contributes 0 and is listed under "incomplete": weights are never redistributed and a missing
result is never treated as full marks. "coverage" is the share of the weight that was measured.
"""
import hashlib
import json

from grading.types import ERROR, OK, PARTIAL, SKIPPED, UNAVAILABLE, Result


def aggregate(results: list[Result]) -> dict:
    rows, total, measured_weight = [], 0.0, 0.0
    incomplete, partial = [], []
    for r in results:
        contribution = 0.0
        if r.status in (OK, PARTIAL, SKIPPED) and r.score is not None:
            contribution = r.weight * r.score * 100
            measured_weight += r.weight
        if r.status in (UNAVAILABLE, ERROR):
            incomplete.append(r.name)
        if r.status == PARTIAL:
            partial.append(r.name)
        total += contribution
        rows.append({"name": r.name, "status": r.status, "score": r.score, "weight": r.weight,
                     "contribution": round(contribution, 2)})
    return {
        "grade": round(total, 2),
        "max_grade": 100.0,
        "coverage": round(measured_weight, 4),
        "complete": not incomplete and not partial,
        "incomplete_metrics": incomplete,
        "partial_metrics": partial,
        "rows": rows,
    }


def fingerprint(results: list[Result], extra: dict) -> str:
    """Hash of everything that must be identical on a re-run: deterministic metrics only."""
    body = {
        "extra": extra,
        "metrics": [{"name": r.name, "status": r.status, "score": r.score}
                    for r in results if r.deterministic],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
