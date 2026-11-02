"""Grading graph (LangGraph): first pass, one stage per analyzer group, weighted grade, report.

    validate -> first_pass -+-> correctness -> edge_cases -+-> compiler -> structure -+-> memory -> complexity -+-> review
                            |                              |                          |                         |
                            '-> skip_execution ------------'                          '-------------------------'
    review -> aggregate -> report -> END

The first pass compiles the program and runs it once. If it does not compile, or the smoke run
times out (suspected infinite loop), the execution-based analyzers are recorded as skipped and
only the source-based ones run. An analyzer that crashes is recorded as "error" and the rest of
the graph continues. Which analyzer runs for which metric comes only from rules.json.
"""
import logging
import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from grading import first_pass, policy, report, scoring
from grading.analyzers import REGISTRY
from grading.types import ERROR, OK, SKIPPED, UNAVAILABLE, Context, Result, Submission

log = logging.getLogger("autograder.grader")


class GradingError(RuntimeError):
    """Grading cannot start (invalid rules, no tests, sandbox unavailable)."""


class State(TypedDict, total=False):
    ctx: Any
    on_stage: Any
    results: Annotated[list, operator.add]
    flags: list
    report: dict
    review: dict
    text: str


def _notify(state: State, stage: str, message: str) -> None:
    cb: Callable | None = state.get("on_stage")
    if cb:
        try:
            cb(stage, message)
        except Exception:
            log.exception("progress callback failed")


def _metrics_for(ctx: Context, stage: str) -> list[dict]:
    return [m for m in ctx.rules["metrics"] if REGISTRY[m["analyzer"]].stage == stage]


def _run_metric(ctx: Context, metric: dict) -> Result:
    spec = REGISTRY[metric["analyzer"]]
    try:
        r = spec.run(ctx, metric)
        r.deterministic = r.deterministic and spec.deterministic
        return r
    except Exception as e:
        log.exception("analyzer %s failed", metric["analyzer"])
        return Result(name=metric["name"], analyzer=metric["analyzer"], weight=float(metric["weight"]),
                      status=ERROR, feedback=f"The {metric['analyzer']} analyzer failed: {type(e).__name__}: {e}",
                      deterministic=spec.deterministic)


# ----------------------------------------------------------------------- nodes
def validate(state: State) -> dict:
    ctx: Context = state["ctx"]
    errs = policy.problems(ctx.rules)
    if errs:
        raise GradingError("the grading policy is invalid: " + "; ".join(errs))
    if not ctx.sub.source.strip():
        raise GradingError("the submission is empty")
    for i, t in enumerate(ctx.sub.tests, 1):
        t.setdefault("id", f"T{i:03d}")
    _notify(state, "running", "Compiling and running a smoke test")
    return {"results": [], "flags": []}


def run_first_pass(state: State) -> dict:
    ctx: Context = state["ctx"]
    try:
        ctx.first_pass = first_pass.run(ctx)
    except Exception as e:
        raise GradingError(f"the sandbox could not run the program: {e}") from e
    flags = list(state.get("flags", []))
    if not ctx.first_pass["compiled"]:
        flags.append("compile_failed")
    if ctx.first_pass["suspected_infinite_loop"]:
        flags.append("suspected_infinite_loop")
    return {"flags": flags}


def after_first_pass(state: State) -> str:
    return "execute" if state["ctx"].first_pass["run_execution_analyzers"] else "skip"


def skip_execution(state: State) -> dict:
    ctx: Context = state["ctx"]
    fp = ctx.first_pass
    why = ("the program does not compile" if not fp["compiled"] else
           "the smoke run timed out (suspected infinite loop)")
    out = []
    for m in ctx.rules["metrics"]:
        spec = REGISTRY[m["analyzer"]]
        if spec.execution:
            out.append(Result(name=m["name"], analyzer=m["analyzer"], weight=float(m["weight"]),
                              status=SKIPPED, score=0.0, deterministic=spec.deterministic,
                              feedback=f"Not run because {why}.",
                              evidence={"skipped_because": why}))
    _notify(state, "grading", "Execution skipped; running the source checks")
    return {"results": out}


def stage(name: str, message: str):
    def node(state: State) -> dict:
        ctx: Context = state["ctx"]
        metrics = _metrics_for(ctx, name)
        if metrics:
            _notify(state, "grading", message)
        return {"results": [_run_metric(ctx, m) for m in metrics]}
    node.__name__ = name
    return node


def after_structure(state: State) -> str:
    return after_first_pass(state)


def aggregate(state: State) -> dict:
    ctx: Context = state["ctx"]
    order = {m["name"]: i for i, m in enumerate(ctx.rules["metrics"])}
    results = sorted(state["results"], key=lambda r: order[r.name])
    flags = list(state.get("flags", []))
    for r in results:
        if r.status in (UNAVAILABLE, ERROR):
            flags.append(f"{r.status}:{r.name}")
        if r.analyzer == "similarity_flag" and r.evidence.get("flagged"):
            flags.append("originality_review")
    _notify(state, "reporting", "Calculating the grade and writing the report")
    return {"results": [], "flags": flags, "report": {"ordered": results}}


def make_report(state: State) -> dict:
    ctx: Context = state["ctx"]
    results = state["report"]["ordered"]
    agg = scoring.aggregate(results)
    tv = dict(sorted(ctx.tool_versions.items()))
    fp = scoring.fingerprint(results, {"source": ctx.sub.source_sha256, "rules": ctx.sub.rules_sha256,
                                       "tests": report.sha256_text(str(ctx.sub.tests)),
                                       "tools": {k: v for k, v in tv.items() if k != "readability_model"}})
    graded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rep, review = report.build(ctx.sub, ctx.first_pass, results, agg, tv, state["flags"], graded_at, fp)
    return {"report": rep, "review": review, "text": report.to_text(rep)}


def build_graph():
    g = StateGraph(State)
    g.add_node("validate", validate)
    g.add_node("first_pass", run_first_pass)
    g.add_node("skip_execution", skip_execution)
    g.add_node("correctness", stage("correctness", "Running the accepted test cases"))
    g.add_node("edge_cases", stage("edge_cases", "Running edge cases and counter-tests"))
    g.add_node("compiler", stage("compiler", "Checking compiler warnings"))
    g.add_node("structure", stage("structure", "Analysing structure and modularity"))
    g.add_node("memory", stage("memory", "Checking memory safety (ASan, UBSan, valgrind)"))
    g.add_node("complexity", stage("complexity", "Estimating time complexity"))
    g.add_node("review", stage("review", "Reviewing readability and originality"))
    g.add_node("aggregate", aggregate)
    g.add_node("report", make_report)

    g.add_edge(START, "validate")
    g.add_edge("validate", "first_pass")
    g.add_conditional_edges("first_pass", after_first_pass, {"execute": "correctness", "skip": "skip_execution"})
    g.add_edge("correctness", "edge_cases")
    g.add_edge("edge_cases", "compiler")
    g.add_edge("skip_execution", "compiler")
    g.add_edge("compiler", "structure")
    g.add_conditional_edges("structure", after_structure, {"execute": "memory", "skip": "review"})
    g.add_edge("memory", "complexity")
    g.add_edge("complexity", "review")
    g.add_edge("review", "aggregate")
    g.add_edge("aggregate", "report")
    g.add_edge("report", END)
    return g.compile()


graph = build_graph()


def grade(sub: Submission, on_stage: Callable[[str, str], None] | None = None) -> dict:
    """Grade one submission. Returns {"report", "text", "review"}; raises GradingError."""
    ctx = Context(sub=sub)
    final = graph.invoke({"ctx": ctx, "on_stage": on_stage, "results": [], "flags": []})
    return {"report": final["report"], "text": final["text"], "review": final["review"]}
