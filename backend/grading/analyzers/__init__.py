"""One analyzer per metric. Each takes (ctx, metric) and returns a grading.types.Result.

REGISTRY maps the analyzer name used in rules.json to its implementation, the grading-graph
stage that runs it, whether it needs to execute the program, and whether it is deterministic.
"""
from dataclasses import dataclass
from typing import Callable

from grading.analyzers import (compiler, complexity, correctness, edge_cases, memory, originality,
                               readability, structure)


@dataclass(frozen=True)
class Spec:
    run: Callable
    stage: str
    execution: bool
    deterministic: bool
    description: str


REGISTRY: dict[str, Spec] = {
    "io_tests": Spec(correctness.analyze, "correctness", True, True,
                     "runs the accepted test cases and compares the output"),
    "edge_case_runner": Spec(edge_cases.analyze, "edge_cases", True, True,
                             "boundary cases, input-format variations and counter-tests"),
    "compiler_warnings": Spec(compiler.analyze, "compiler", False, True,
                              "compiles with the rule's gcc flags and scores the diagnostics"),
    "static_analysis": Spec(structure.analyze_structure, "structure", False, True,
                            "cppcheck findings plus lizard cyclomatic complexity and function length"),
    "function_split": Spec(structure.analyze_modularity, "structure", False, True,
                           "number of functions and helper functions (lizard)"),
    "sanitizer_run": Spec(memory.analyze, "memory", True, True,
                          "AddressSanitizer, UndefinedBehaviorSanitizer and valgrind"),
    "complexity_estimator": Spec(complexity.analyze, "complexity", True, False,
                                 "times the program on growing inputs and fits a growth model"),
    "llm_review": Spec(readability.analyze, "review", False, False,
                       "LLM readability review (temperature 0, fixed seed)"),
    "similarity_flag": Spec(originality.analyze, "review", False, True,
                            "token similarity against other submissions; flags for human review only"),
}

STAGES = ["correctness", "edge_cases", "compiler", "structure", "memory", "complexity", "review"]
EXECUTION_STAGES = {s for s in STAGES if any(v.stage == s and v.execution for v in REGISTRY.values())}
