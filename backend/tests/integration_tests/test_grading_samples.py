"""The ten required sample programs, graded end to end through the LangGraph grader."""
import hashlib

import pytest

from agents import grader
from grading import policy
from grading.types import Submission


def grade(sample, name, corpus=(), reference=True):
    src = sample["submissions"][name]
    sub = Submission(source=src, rules=sample["rules"], tests=[dict(t) for t in sample["tests"]],
                     assignment_id="ASG-TEST01", title="t", name=name, roll_number=name.upper()[:32],
                     source_sha256=hashlib.sha256(src.encode()).hexdigest(),
                     rules_sha256=policy.rules_hash(sample["rules"]),
                     reference_source=sample["reference"] if reference else None,
                     corpus=[{"label": c, "kind": "submission", "source": sample["submissions"][c]} for c in corpus])
    return grader.grade(sub)["report"]


def metric(rep, name):
    return next(m for m in rep["metrics"] if m["name"] == name)


@pytest.fixture(scope="module")
def add_reports(add_sample, sandbox_ok):
    return {n: grade(add_sample, n) for n in add_sample["submissions"]}


def test_correct_solution(add_reports):
    rep = add_reports["correct"]
    for name in ("correctness", "syntax", "modularity", "logical", "complexity", "memory_safety"):
        assert metric(rep, name)["score"] == 1.0, (name, metric(rep, name)["feedback"])
    assert rep["first_pass"]["compiled"] and rep["first_pass"]["smoke_ok"]
    assert not rep["failed_tests"] and not rep["counter_tests"]


def test_wrong_output(add_reports):
    rep = add_reports["wrong_output"]
    c = metric(rep, "correctness")
    assert c["score"] == 0.0
    f = rep["failed_tests"][0]
    assert f["expected"] == "12\n" and f["actual"].startswith("Sum = 12") and "expected '12'" in f["explanation"]


def test_compile_error(add_reports):
    rep = add_reports["compile_error"]
    assert "compile_failed" in rep["flags"] and not rep["first_pass"]["compiled"]
    for name in ("correctness", "logical", "complexity", "memory_safety"):
        assert metric(rep, name)["status"] == "skipped" and metric(rep, name)["score"] == 0.0
    assert metric(rep, "syntax")["score"] == 0.0
    assert metric(rep, "modularity")["status"] == "ok"        # source-only analyzers still run
    assert "expected ';'" in rep["first_pass"]["compiler_output"]


def test_infinite_loop(add_reports):
    rep = add_reports["infinite_loop"]
    assert rep["first_pass"]["suspected_infinite_loop"] and "suspected_infinite_loop" in rep["flags"]
    for name in ("correctness", "logical", "complexity", "memory_safety"):
        assert metric(rep, name)["status"] == "skipped"
    assert metric(rep, "syntax")["status"] == "ok"


def test_segfault(add_reports):
    rep = add_reports["segfault"]
    assert metric(rep, "correctness")["score"] == 0.0
    assert rep["failed_tests"][0]["status"] == "crash" and "SIGSEGV" in rep["failed_tests"][0]["explanation"]
    assert metric(rep, "memory_safety")["score"] < 1.0


def test_integer_overflow(add_reports):
    rep = add_reports["overflow"]
    assert metric(rep, "correctness")["score"] == 1.0          # fine inside the stated constraints
    edge = metric(rep, "logical")
    assert edge["score"] < 1.0
    ov = [c for c in rep["counter_tests"] if c["theme"] == "int_overflow"]
    assert ov and ov[0]["input"].startswith("2147483647")
    assert ov[0]["expected"].strip() == "2147483648"            # from the reference solution
    assert "signed integer overflow" in ov[0]["explanation"]


def test_compiler_warnings(add_reports):
    s = metric(add_reports["warnings"], "syntax")
    assert s["score"] < 1.0 and s["evidence"]["warnings"] >= 3
    flags = set(s["evidence"]["by_flag"])
    assert {"-Wunused-parameter", "-Wunused-variable", "-Wsign-compare"} <= flags
    assert metric(add_reports["warnings"], "correctness")["score"] == 1.0   # -Werror does not stop the tests


def test_memory_errors(add_reports):
    m = metric(add_reports["memory_error"], "memory_safety")
    assert m["status"] == "ok" and m["score"] < 1.0
    assert any(f["kind"] == "heap-buffer-overflow" for f in m["evidence"]["findings"])
    assert metric(add_reports["memory_error"], "correctness")["score"] == 1.0


def test_report_fields(add_reports):
    rep = add_reports["overflow"]
    for key in ("student", "assignment", "submission", "grade", "metrics", "tool_versions", "rules_sha256",
                "tests_sha256", "reproducibility", "first_pass", "suggestions", "usefulness_limitations"):
        assert key in rep
    assert sum(m["contribution"] for m in rep["metrics"]) == pytest.approx(rep["grade"], abs=0.05)
    assert metric(rep, "readability")["deterministic"] is False


def test_high_time_complexity(sort_sample, sandbox_ok):
    rep = grade(sort_sample, "slow_bubble")
    c = metric(rep, "complexity")
    assert c["score"] <= 0.5
    assert c["evidence"]["estimated"] in ("O(n^2)", "O(n^3)") or any(
        f["status"] == "timeout" for f in c["evidence"]["failures"])
    good = metric(grade(sort_sample, "correct"), "complexity")
    assert good["score"] == 1.0 and good["evidence"]["estimated"] in ("O(1)", "O(log n)", "O(n)", "O(n log n)")


def test_similar_submissions_flagged_for_review_only(sort_sample, sandbox_ok):
    rep = grade(sort_sample, "similar_b", corpus=["similar_a", "correct"])
    o = metric(rep, "originality")
    assert o["evidence"]["flagged"] and o["evidence"]["max_similarity"] >= 0.85
    assert o["score"] == 1.0 and "originality_review" in rep["flags"] and rep["provisional"]
    assert "similar_a" not in str(rep).lower()          # the student report never names the other student


def test_deterministic_metrics_are_reproducible(add_sample, sandbox_ok):
    a, b = grade(add_sample, "overflow"), grade(add_sample, "overflow")
    assert a["reproducibility"]["fingerprint"] == b["reproducibility"]["fingerprint"]
    for ma, mb in zip(a["metrics"], b["metrics"]):
        if ma["deterministic"]:
            assert (ma["status"], ma["score"], ma["feedback"]) == (mb["status"], mb["score"], mb["feedback"])
            assert ma["evidence"] == mb["evidence"], ma["name"]


def test_analyzer_crash_does_not_stop_grading(add_sample, sandbox_ok, monkeypatch):
    import dataclasses

    from grading import analyzers

    def boom(ctx, metric):
        raise RuntimeError("synthetic failure")
    monkeypatch.setitem(analyzers.REGISTRY, "function_split",
                        dataclasses.replace(analyzers.REGISTRY["function_split"], run=boom))
    rep = grade(add_sample, "correct")
    m = metric(rep, "modularity")
    assert m["status"] == "error" and m["score"] is None and "synthetic failure" in m["feedback"]
    assert "error:modularity" in rep["flags"] and metric(rep, "correctness")["score"] == 1.0


def test_invalid_rules_refuse_to_grade(add_sample):
    bad = dict(add_sample, rules=dict(add_sample["rules"], metrics=add_sample["rules"]["metrics"][:2]))
    with pytest.raises(grader.GradingError, match="weights must sum"):
        grade(bad, "correct")


def test_readability_with_a_model_stand_in(add_sample, sandbox_ok, monkeypatch):
    """The readability analyzer's parsing and scoring, with a stand-in for the Ollama model."""
    from grading.analyzers import readability

    class Fake:
        def __init__(self, *a):
            pass

        def with_structured_output(self, schema):
            outer = self

            class Runner:
                def invoke(self, messages):
                    assert "C program" in messages[1].content
                    return schema(score=6, naming="Single-letter names a, b.", layout="Cramped.", comments="None.",
                                  organisation="All in main.", maintainability="Fine.", suggestions=["Rename a, b."])
            return Runner()
    monkeypatch.setattr(readability, "LLM_FACTORY", Fake)
    rep = grade(add_sample, "overflow")
    r = metric(rep, "readability")
    assert r["status"] == "ok" and r["score"] == 0.6 and r["deterministic"] is False
    assert r["evidence"]["raw_response"]["score"] == 6 and "Rename a, b." in rep["suggestions"]
