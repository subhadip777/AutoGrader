from grading.types import Result


def result(metric: dict, **kw) -> Result:
    return Result(name=metric["name"], analyzer=metric["analyzer"], weight=float(metric["weight"]), **kw)


def params(metric: dict) -> dict:
    return metric.get("params") or {}


def clamp01(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 4)


def seed_for(ctx, salt: str) -> int:
    """A seed derived from the rules hash, so generated inputs are the same on every run."""
    base = ctx.sub.rules_sha256 or "0"
    return int(base[:12], 16) ^ (sum(map(ord, salt)) * 7919)
