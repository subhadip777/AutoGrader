"""llm_review: readability review by the local Ollama model.

Runs at temperature 0 with a fixed seed and asks for structured JSON. This is the one metric
that is not fully deterministic: a different model, Ollama version or hardware can change the
answer. If Ollama is not reachable the metric is "unavailable"; it is never guessed.
Params: model (used only if Ollama has it; otherwise OLLAMA_MODEL is used and the evidence says so),
temperature (0), seed (42).
"""
import json
import logging
import os
import urllib.error
import urllib.request

from pydantic import BaseModel, Field

from grading.analyzers.common import clamp01, params, result
from grading.types import OK, UNAVAILABLE

log = logging.getLogger("autograder.readability")

SYSTEM = """You review the readability of a student's C program. You do not judge correctness.
Score from 0 to 10 using these criteria: meaningful names for variables and functions, layout and
indentation, helpful comments (not excessive), sensible function organisation, and maintainability
(no magic numbers, no duplicated code). Base every reason on something visible in the code, quote
names or line content where useful, and keep each reason to one sentence."""


class Review(BaseModel):
    score: int = Field(ge=0, le=10, description="overall readability, 0 (unreadable) to 10 (excellent)")
    naming: str = Field(description="one sentence on variable and function names")
    layout: str = Field(description="one sentence on indentation, spacing and line length")
    comments: str = Field(description="one sentence on comments")
    organisation: str = Field(description="one sentence on how the code is split into functions")
    maintainability: str = Field(description="one sentence on magic numbers, duplication and clarity")
    suggestions: list[str] = Field(description="up to three concrete improvements")


def base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def local_models(timeout: float = 3.0) -> list[str] | None:
    """Model names Ollama has pulled, or None when Ollama is not reachable."""
    try:
        with urllib.request.urlopen(base_url() + "/api/tags", timeout=timeout) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def make_llm(model: str, temperature: float, seed: int):
    from langchain_ollama import ChatOllama
    return ChatOllama(model=model, base_url=base_url(), temperature=temperature, seed=seed,
                      num_predict=700, client_kwargs={"timeout": float(os.getenv("READABILITY_TIMEOUT_S", "180"))})


LLM_FACTORY = make_llm   # tests replace this with a stand-in model


def analyze(ctx, metric):
    from langchain_core.messages import HumanMessage, SystemMessage
    p = params(metric)
    temperature, seed = float(p.get("temperature", 0)), int(p.get("seed", 42))
    default = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    requested = p.get("model")
    models = local_models() if LLM_FACTORY is make_llm else [default]
    if models is None:
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback=f"Readability was not reviewed: Ollama is not reachable at {base_url()}.",
                      evidence={"reason": "ollama unreachable"})
    note = ""
    if requested and requested in models:
        model = requested
    else:
        model = default
        if requested:
            note = f"the rules ask for {requested!r}, which this Ollama does not have; {default!r} was used"
    if LLM_FACTORY is make_llm and model not in models and f"{model}:latest" not in models:
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback=f"Readability was not reviewed: the model {model!r} is not pulled in Ollama.",
                      evidence={"reason": f"run: ollama pull {model}", "available_models": models})
    numbered = "\n".join(f"{i:3d} | {line}" for i, line in enumerate(ctx.sub.source.splitlines(), 1))
    try:
        llm = LLM_FACTORY(model, temperature, seed)
        review = llm.with_structured_output(Review).invoke(
            [SystemMessage(SYSTEM), HumanMessage(f"C program (line numbers added):\n\n{numbered[:20000]}")])
    except Exception as e:
        log.warning("readability review failed: %s", e)
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback=f"Readability was not reviewed: the model call failed ({type(e).__name__}).",
                      evidence={"model": model, "error": str(e)[:300]})
    if review is None:
        return result(metric, status=UNAVAILABLE, deterministic=False,
                      feedback="Readability was not reviewed: the model returned no usable answer.",
                      evidence={"model": model})
    reasons = [review.naming, review.layout, review.comments, review.organisation, review.maintainability]
    ctx.tool_versions["readability_model"] = model
    return result(
        metric, status=OK, score=clamp01(review.score / 10), deterministic=False,
        feedback=f"Readability {review.score}/10. " + " ".join(r for r in reasons[:2] if r),
        suggestions=[s for s in review.suggestions[:3] if s],
        evidence={"model": model, "temperature": temperature, "seed": seed, "note": note,
                  "raw_response": review.model_dump(), "nondeterministic": True},
    )
