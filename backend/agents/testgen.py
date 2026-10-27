import json
import os
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BATCH_SIZE = 8       # tests requested per LLM call (small models need small batches)
MAX_ATTEMPTS = 8     # LLM calls before giving up
MAX_FIELD_CHARS = 10_000

SYSTEM = """You write test cases for a C programming assignment. The student's program reads standard input and writes standard output.

For each test case give:
- input: the exact text fed to stdin (use \\n for line breaks)
- expected_output: the exact text the correct program prints
- category: one or two words (typical, boundary, negative, zero, whitespace, large, ...)
- explanation: one sentence on why this case is useful and how the expected output follows

Rules:
- Every input must be valid according to the problem statement's input format and limits.
- The expected output must follow from the statement alone. Work it out carefully.
- Skip any case where the statement does not define the correct behaviour (for example overflow when no range is given).
- Vary the cases: typical values, smallest and largest allowed values, negatives, zero, and harmless whitespace variations when the format allows them."""


class GeneratedTest(BaseModel):
    input: str
    expected_output: str
    category: str
    explanation: str


class GeneratedBatch(BaseModel):
    tests: list[GeneratedTest]


class State(TypedDict):
    statement: str
    rules: dict
    num_tests: int
    tests: list[dict]
    candidates: list[dict]
    attempts: int
    notes: list[str]


def _llm(seed: int) -> ChatOllama:
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0.3,
        seed=seed,
    )


def _edge_hints(rules: dict) -> list[str]:
    hints: list[str] = []
    for m in rules.get("metrics", []):
        if m.get("analyzer") == "edge_case_runner":
            hints += [str(c) for c in m.get("params", {}).get("cases", [])]
    return hints


def generate(state: State) -> dict:
    count = min(state["num_tests"] - len(state["tests"]), BATCH_SIZE)
    existing = [t["input"] for t in state["tests"]][-40:]
    hints = _edge_hints(state["rules"])

    user = f"PROBLEM STATEMENT:\n{state['statement']}\n\nWrite {count} NEW test cases.\n"
    if hints:
        user += f"The instructor wants these edge-case themes covered: {', '.join(hints)}.\n"
    if existing:
        user += f"Do NOT repeat these existing inputs (JSON list): {json.dumps(existing)}\n"

    attempts = state["attempts"] + 1
    try:
        batch = (
            _llm(42 + attempts)
            .with_structured_output(GeneratedBatch)
            .invoke([SystemMessage(SYSTEM), HumanMessage(user)])
        )
        candidates = [t.model_dump() for t in batch.tests] if batch else []
    except Exception as e:
        note = f"attempt {attempts}: model call failed ({type(e).__name__})"
        return {"candidates": [], "attempts": attempts, "notes": state["notes"] + [note]}
    return {"candidates": candidates, "attempts": attempts}


def validate(state: State) -> dict:
    seen = {t["input"] for t in state["tests"]}
    tests = list(state["tests"])
    dropped = 0
    for c in state["candidates"]:
        inp = c["input"]
        out = c["expected_output"].rstrip()
        if not out or inp in seen or len(inp) > MAX_FIELD_CHARS or len(out) > MAX_FIELD_CHARS:
            dropped += 1
            continue
        seen.add(inp)
        tests.append({
            "input": inp,
            "expected_output": out + "\n",
            "category": c["category"].strip().lower()[:40] or "general",
            "explanation": c["explanation"].strip()[:500],
        })
        if len(tests) >= state["num_tests"]:
            break
    notes = state["notes"]
    if dropped:
        notes = notes + [f"attempt {state['attempts']}: dropped {dropped} duplicate/empty/oversized test(s)"]
    return {"tests": tests, "candidates": [], "notes": notes}


def more_needed(state: State) -> str:
    if len(state["tests"]) >= state["num_tests"] or state["attempts"] >= MAX_ATTEMPTS:
        return END
    return "generate"


def build_graph():
    g = StateGraph(State)
    g.add_node("generate", generate)
    g.add_node("validate", validate)
    g.add_edge(START, "generate")
    g.add_edge("generate", "validate")
    g.add_conditional_edges("validate", more_needed, {"generate": "generate", END: END})
    return g.compile()


graph = build_graph()


def run(statement: str, rules: dict, num_tests: int) -> dict:
    final = graph.invoke({
        "statement": statement, "rules": rules, "num_tests": num_tests,
        "tests": [], "candidates": [], "attempts": 0, "notes": [],
    })
    tests = [{"id": f"T{i:03d}", **t} for i, t in enumerate(final["tests"], 1)]
    notes = final["notes"]
    if len(tests) < num_tests:
        notes = notes + [f"only {len(tests)} of {num_tests} requested tests were produced"]
    return {"tests": tests, "notes": notes}