"""Pure logic of the analyzers (no sandbox needed)."""
import math
import random

import pytest

from grading import compare, inputspec
from grading.analyzers import compiler, complexity, memory, originality, structure


# ------------------------------------------------------------------ comparison
def test_trailing_whitespace_ignored_but_real_differences_kept():
    assert compare.outputs_match("30\n", "30")
    assert compare.outputs_match("1 2\n3\n", "1 2   \n3\n\n\n")
    assert compare.outputs_match("a\r\nb\r\n", "a\nb")
    assert not compare.outputs_match("30\n", "31\n")
    assert not compare.outputs_match("1 2\n", " 1 2\n")          # leading space is meaningful
    assert not compare.outputs_match("1 2\n", "1  2\n")          # inner spacing is meaningful
    assert not compare.outputs_match("1\n2\n", "1\n\n2\n")       # blank line in the middle
    assert compare.outputs_match("1.0000\n", "1.00001\n", "tokens", 1e-3)


def test_mismatch_explanations():
    assert "expected '30' but got '31'" in compare.explain_mismatch("30\n", "31\n")
    assert "printed nothing" in compare.explain_mismatch("30\n", "")
    assert "extra line" in compare.explain_mismatch("1\n", "1\n2\n")
    assert "spacing" in compare.explain_mismatch("1 2\n", "1  2\n")


def test_classify_run():
    assert compare.classify_run({"returncode": 0}, 1)[0] == "ok"
    assert compare.classify_run({"timed_out": True, "returncode": -9}, 1)[0] == "timeout"
    st, why = compare.classify_run({"returncode": -11, "signal": "SIGSEGV"}, 1)
    assert st == "crash" and "segmentation fault" in why
    assert compare.classify_run({"returncode": -25, "signal": "SIGXFSZ"}, 1)[0] == "output_limit"
    assert compare.classify_run({"returncode": 3}, 1)[0] == "runtime_error"


# ------------------------------------------------------------------ input specs
TESTS_FIXED = [{"input": "1 2\n"}, {"input": "-5 7"}, {"input": "100 200\n"}, {"input": "1 2 3"}]
TESTS_COUNTED = [{"input": "3\n1 2 3\n"}, {"input": "1\n9\n"}, {"input": "5\n5 4 3 2 1\n"}]


def test_infer_fixed_layout_uses_majority_shape():
    spec = inputspec.infer(TESTS_FIXED)
    assert [f["name"] for f in inputspec.fields(spec)] == ["v1_1", "v1_2"]
    assert "1 test(s) with a different layout were ignored" in spec["note"]
    assert inputspec.allows_negative(spec)


def test_infer_count_then_list():
    spec = inputspec.infer(TESTS_COUNTED)
    assert spec["size_field"] == "n" and inputspec.fields(spec)[1]["type"] == "int_list"


def test_infer_gives_up_on_text():
    assert inputspec.infer([{"input": "hello world"}, {"input": "abc"}]) is None


def test_edge_themes(sort_sample, add_sample):
    rng = random.Random(1)
    add_spec, sort_spec = add_sample["rules"]["input_spec"], sort_sample["rules"]["input_spec"]
    ov, _ = inputspec.edge_inputs(add_spec, "int_overflow", rng)
    assert any("2147483647" in i for i, _ in ov) and any("-2147483648" in i for i, _ in ov)
    neg, _ = inputspec.edge_inputs(add_spec, "negatives", rng)
    assert neg and all("-" in i for i, _ in neg[:1])
    single, _ = inputspec.edge_inputs(sort_spec, "single", rng)
    assert single[0][0].startswith("1\n")
    dup, _ = inputspec.edge_inputs(sort_spec, "duplicates", rng)
    values = dup[0][0].split("\n")[1].split()
    assert len(set(values)) == 1
    empty, note = inputspec.edge_inputs(sort_spec, "empty", rng)     # n >= 1 in this spec
    assert empty == [] and "not applicable" in note
    positive = {"lines": [[{"name": "n", "type": "int", "min": 1, "max": 99}]]}
    none, note = inputspec.edge_inputs(positive, "negatives", rng)
    assert none == [] and "no negative" in note
    _, note = inputspec.edge_inputs(add_spec, "unicorns", rng)
    assert "not supported" in note


def test_generated_inputs_are_deterministic_and_valid(sort_spec_size=1000):
    spec = {"lines": [[{"name": "n", "type": "int", "min": 1, "max": 5000}],
                      [{"name": "v", "type": "int_list", "length": "n", "min": -9, "max": 9}]], "size_field": "n"}
    mode = inputspec.scaling_mode(spec, {})
    a = inputspec.scaled_input(spec, mode, sort_spec_size, 7)
    assert a == inputspec.scaled_input(spec, mode, sort_spec_size, 7)
    head, body = a.strip().split("\n")
    vals = list(map(int, body.split()))
    assert int(head) == len(vals) == sort_spec_size and all(-9 <= v <= 9 for v in vals)
    assert inputspec.size_bounds(spec, mode) == (1, 5000)


def test_spec_validation():
    inputspec.validate({"lines": [[{"name": "n", "type": "int"}], [{"name": "v", "type": "int_list", "length": "n"}]],
                        "size_field": "n"})
    for bad in ({"lines": []}, {"lines": [[{"name": "v", "type": "int_list", "length": "m"}]]},
                {"lines": [[{"name": "n", "type": "int", "min": 5, "max": 1}]]},
                {"lines": [[{"name": "n", "type": "int"}]], "size_field": "zz"}):
        with pytest.raises(inputspec.SpecError):
            inputspec.validate(bad)


# ------------------------------------------------------------------ complexity fitting
@pytest.mark.parametrize("cls, f", [
    ("O(n)", lambda n: 2 + n / 1000),
    ("O(n log n)", lambda n: 2 + n * math.log2(n) / 20000),
    ("O(n^2)", lambda n: 2 + (n / 1000) ** 2),
    ("O(n^3)", lambda n: 2 + (n / 1000) ** 3),
])
def test_estimator_recovers_growth_class(cls, f):
    sizes = [1000, 2000, 4000, 8000, 16000, 32000]
    assert complexity.estimate(sizes, [f(n) for n in sizes], 0.01)["class"] == cls


def test_estimator_treats_noise_as_constant():
    sizes = [1, 10, 100, 1000, 10000]
    # jitter smaller than half the baseline time
    assert complexity.estimate(sizes, [2.0, 2.4, 2.2, 2.6, 2.3], 0.1)["class"] == "O(1)"
    # large but non-monotonic jumps (a busy machine), rank correlation below 0.8
    assert complexity.estimate(sizes, [2.0, 6.5, 2.1, 7.0, 2.4], 0.1)["class"] == "O(1)"
    # a real, steady rise is not noise
    assert complexity.estimate(sizes, [2.0, 3.0, 4.0, 5.0, 6.0], 0.1)["class"] != "O(1)"


def test_parse_class():
    assert complexity.parse_class("O(n log n)") == "O(n log n)"
    assert complexity.parse_class("O(n²)") == "O(n^2)"
    assert complexity.parse_class("o(1)") == "O(1)"
    assert complexity.parse_class("fast") is None


# ------------------------------------------------------------------ parsers
def test_compiler_diagnostics_parser_counts_werror_as_warnings():
    out = ("sol.c: In function 'main':\n"
           "sol.c:5:9: error: unused variable 'x' [-Werror=unused-variable]\n"
           "sol.c:3:20: warning: unused parameter 'p' [-Wunused-parameter]\n"
           "sol.c:9:1: error: expected ';' before '}' token\n")
    d = compiler.parse(out)
    assert [(x["kind"], x["flag"]) for x in d] == [("warning", "-Wunused-variable"),
                                                    ("warning", "-Wunused-parameter"), ("error", "")]


def test_sanitizer_and_valgrind_parsers():
    asan = ("==123==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000018\n"
            "    #0 0x5555 in main /tmp/ag-abc12345/build/san/sol.c:15\n")
    f = memory.parse_sanitizers(asan, "T001")
    assert f[0]["kind"] == "heap-buffer-overflow" and f[0]["line"] == 15 and "0x502" not in f[0]["excerpt"]
    ub = memory.parse_sanitizers("sol.c:4:11: runtime error: signed integer overflow: 2147483647 + 1\n", "T2")
    assert ub[0]["category"] == "undefined_behaviour"
    lsan = memory.parse_sanitizers("ERROR: LeakSanitizer: detected memory leaks\nDirect leak of 8 byte(s)\n", "T3")
    assert lsan[0]["category"] == "leak" and "8 bytes" in lsan[0]["description"]
    vg = memory.parse_valgrind("==9== Invalid write of size 4\n==9==    at main (sol.c:7)\n"
                               "==9==    definitely lost: 0 bytes in 0 blocks\n", "T1")
    assert [x["category"] for x in vg] == ["memory_error"]


def test_cppcheck_parser():
    out = "5|error|arrayIndexOutOfBounds|Array 'a[2]' accessed at index 2\n0|information|missingIncludeSystem|x\n"
    assert structure.parse_cppcheck(out) == [{"line": 5, "severity": "error", "id": "arrayIndexOutOfBounds",
                                              "message": "Array 'a[2]' accessed at index 2"}]


# ------------------------------------------------------------------ originality
def test_similarity_ignores_renaming_and_layout(sort_sample):
    a, b = sort_sample["submissions"]["similar_a"], sort_sample["submissions"]["similar_b"]
    assert originality.similarity(a, b) >= 0.95
    assert originality.similarity(a, sort_sample["submissions"]["slow_bubble"]) < 0.6


def test_originality_flag_never_lowers_score_and_hides_other_students(sort_sample):
    from grading.types import Context, Submission
    sub = Submission(source=sort_sample["submissions"]["similar_a"], rules={}, tests=[],
                     corpus=[{"label": "ROLL42", "kind": "submission", "source": sort_sample["submissions"]["similar_b"]}])
    r = originality.analyze(Context(sub=sub), {"name": "originality", "analyzer": "similarity_flag", "weight": 0.1,
                                               "params": {"flag_threshold": 0.85}})
    assert r.evidence["flagged"] and r.score == 1.0
    assert "ROLL42" not in str(r.to_dict())            # student-facing output has no roll numbers
    assert r.private["matches"][0]["label"] == "ROLL42"


def test_short_programs_are_not_flagged(add_sample):
    from grading.types import Context, Submission
    src = add_sample["submissions"]["overflow"]
    sub = Submission(source=src, rules={}, tests=[], corpus=[{"label": "X", "source": src}])
    r = originality.analyze(Context(sub=sub), {"name": "o", "analyzer": "similarity_flag", "weight": 1, "params": {}})
    assert r.evidence["max_similarity"] == 1.0 and not r.evidence["flagged"]
