"""Shared data types: what an analyzer receives and what it returns."""
from dataclasses import asdict, dataclass, field
from typing import Any

# Result states. Only "ok" and "partial" carry a measured score.
OK = "ok"                  # the analyzer ran completely
PARTIAL = "partial"        # some of its tools were unavailable; the missing share scores 0
SKIPPED = "skipped"        # not run because of the student's program (compile failure, infinite loop): 0
UNAVAILABLE = "unavailable"  # a tool or service needed for it is missing: no score, counts as 0
ERROR = "error"            # the analyzer itself crashed: no score, counts as 0
STATES = (OK, PARTIAL, SKIPPED, UNAVAILABLE, ERROR)


@dataclass
class Submission:
    """Everything the grader needs about one submission, independent of how it is stored."""
    source: str
    rules: dict
    tests: list[dict]
    assignment_id: str = ""
    title: str = ""
    name: str = ""
    roll_number: str = ""
    attempt: int = 1
    submitted_at: str = ""
    source_sha256: str = ""
    rules_sha256: str = ""
    reference_source: str | None = None
    corpus: list[dict] = field(default_factory=list)   # [{"label", "source", "kind"}], other submissions etc.


@dataclass
class Result:
    name: str            # metric name from the rules
    analyzer: str
    weight: float
    status: str = OK
    score: float | None = None   # 0..1
    feedback: str = ""
    evidence: dict = field(default_factory=dict)
    deterministic: bool = True
    suggestions: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)   # measured times: vary between runs, kept out of evidence
    private: dict = field(default_factory=dict)   # teacher-only evidence (never in the student report)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("private")
        return d


@dataclass
class Context:
    """State shared by the analyzers of one grading run."""
    sub: Submission
    first_pass: dict = field(default_factory=dict)
    tool_versions: dict = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def rules(self) -> dict:
        return self.sub.rules

    @property
    def time_limit_s(self) -> float:
        return float(self.sub.rules.get("time_limit_s", 1))

    @property
    def memory_limit_mb(self) -> int:
        return int(self.sub.rules.get("memory_limit_mb", 64))
