import copy

import pytest

from grading import policy, scoring
from grading.types import ERROR, OK, PARTIAL, SKIPPED, UNAVAILABLE, Result


def test_sample_rules_are_valid(add_sample, sort_sample):
    assert policy.problems(add_sample["rules"]) == []
    assert policy.problems(sort_sample["rules"]) == []


def test_existing_assignment_rules_still_valid():
    """Rules already stored in data/ (published, immutable) must keep validating."""
    import json
    from conftest import REPO
    for p in (REPO / "data" / "Assignments").glob("ASG-*/Problem/rules.json"):
        assert policy.problems(json.loads(p.read_text(encoding="utf-8"))) == [], p


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r["metrics"][0].update(weight=0.5), "sum to 1.00"),
    (lambda r: r["metrics"][0].update(weight=-0.1), "between 0 and 1"),
    (lambda r: r["metrics"][0].update(analyzer="magic"), "unknown analyzer"),
    (lambda r: r["metrics"][1]["params"].update(flags="-Wall; rm -rf /"), "not allowed"),
    (lambda r: r["metrics"][1]["params"].update(flags="-o /etc/passwd"), "not allowed"),
    (lambda r: r["metrics"][1]["params"].update(flags="-fplugin=evil.so"), "not allowed"),
    (lambda r: r["metrics"][5]["params"].update(required="fast"), "required"),
    (lambda r: r["metrics"].append(dict(r["metrics"][0])), "used twice"),
    (lambda r: r.update(time_limit_s=100), "time_limit_s"),
    (lambda r: r.update(memory_limit_mb=4), "memory_limit_mb"),
    (lambda r: r.update(input_spec={"lines": [[{"name": "x", "type": "string"}]]}), "input_spec"),
    (lambda r: r.update(metrics=[]), "non-empty"),
])
def test_invalid_rules_rejected(add_sample, mutate, message):
    rules = copy.deepcopy(add_sample["rules"])
    mutate(rules)
    errs = policy.problems(rules)
    assert errs and any(message in e for e in errs), errs
    with pytest.raises(ValueError):
        policy.validate(rules)


def _r(name, weight, status, score, deterministic=True):
    return Result(name=name, analyzer="io_tests", weight=weight, status=status, score=score, deterministic=deterministic)


def test_weighted_total_of_brief_example():
    # The brief's table: 18 + 9 + 6 + 3 + 8 + 10 + 10 + 5 + 10. The brief prints 89, but the sum is 79.
    rs = [_r("correctness", .2, OK, .9), _r("syntax", .1, OK, .9), _r("structure", .1, OK, .6),
          _r("modularity", .1, OK, .3), _r("logical", .1, OK, .8), _r("complexity", .1, OK, 1.0),
          _r("memory", .1, OK, 1.0), _r("readability", .1, OK, .5), _r("originality", .1, OK, 1.0)]
    agg = scoring.aggregate(rs)
    assert agg["grade"] == 79.0
    assert [r["contribution"] for r in agg["rows"]] == [18, 9, 6, 3, 8, 10, 10, 5, 10]
    assert agg["complete"] and agg["coverage"] == pytest.approx(1.0)


def test_unavailable_metrics_are_not_redistributed_or_assumed_perfect():
    rs = [_r("a", .5, OK, 1.0), _r("b", .3, UNAVAILABLE, None), _r("c", .2, ERROR, None)]
    agg = scoring.aggregate(rs)
    assert agg["grade"] == 50.0                     # not 100: missing weight is not redistributed
    assert agg["coverage"] == pytest.approx(0.5)
    assert agg["incomplete_metrics"] == ["b", "c"]
    assert not agg["complete"]


def test_skipped_counts_as_zero_and_partial_is_reported():
    agg = scoring.aggregate([_r("a", .6, SKIPPED, 0.0), _r("b", .4, PARTIAL, 0.5)])
    assert agg["grade"] == 20.0
    assert agg["partial_metrics"] == ["b"] and not agg["complete"]


def test_fingerprint_ignores_nondeterministic_metrics():
    base = [_r("a", .5, OK, 1.0), _r("llm", .5, OK, .4, deterministic=False)]
    other = [_r("a", .5, OK, 1.0), _r("llm", .5, OK, .9, deterministic=False)]
    changed = [_r("a", .5, OK, 0.9), _r("llm", .5, OK, .4, deterministic=False)]
    assert scoring.fingerprint(base, {}) == scoring.fingerprint(other, {})
    assert scoring.fingerprint(base, {}) != scoring.fingerprint(changed, {})


def test_rules_hash_matches_storage_convention(add_sample, data_root):
    from server import storage
    meta = storage.create_assignment("t", "s", add_sample["rules"], 5)
    assert meta["rules_sha256"] == policy.rules_hash(add_sample["rules"])
