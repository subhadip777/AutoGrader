"""Grading jobs: a small in-process queue that runs the LangGraph grader for each submission."""
import hashlib
import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor

from agents import grader
from grading.types import Submission
from server import sandbox, storage

log = logging.getLogger("autograder")

# One worker by default: the sandbox already runs one container at a time.
_pool = ThreadPoolExecutor(max_workers=int(os.getenv("GRADER_WORKERS", "1")), thread_name_prefix="grader")
TOTAL_STEPS = 9   # first pass, seven analyzer stages, report


def build_submission(aid: str, roll: str) -> Submission:
    meta = storage.get_meta(aid)
    info, source = storage.read_submission(aid, roll)
    return Submission(
        source=source.decode("utf-8"),
        rules=storage.read_rules(aid),
        tests=storage.read_tests(aid),
        assignment_id=aid,
        title=meta["title"],
        name=info.get("name", ""),
        roll_number=info.get("roll_number", roll),
        attempt=info.get("attempt", 1),
        submitted_at=info.get("submitted_at", ""),
        source_sha256=info.get("sha256") or hashlib.sha256(source).hexdigest(),
        rules_sha256=meta.get("rules_sha256", ""),
        reference_source=storage.read_reference(aid),
        corpus=storage.read_corpus(aid, info.get("roll_number", roll)),
    )


def run_submission(aid: str, roll: str) -> None:
    """Grade one submission synchronously and store the reports. Never raises."""
    step = {"n": 0}

    def progress(state: str, message: str) -> None:
        step["n"] += 1
        storage.set_submission_status(aid, roll, state, message, step=min(step["n"], TOTAL_STEPS), steps=TOTAL_STEPS)

    try:
        st = sandbox.status()
        if not st["available"]:
            storage.set_submission_status(
                aid, roll, "failed",
                f"Grading is not available right now: {st['detail']}. Your file is saved; "
                "the instructor can regrade it once the sandbox works.")
            return
        sub = build_submission(aid, roll)
        out = grader.grade(sub, on_stage=progress)
        storage.write_report(aid, roll, out["text"], out["report"], out["review"])
        rep = out["report"]
        msg = f"Graded: {rep['grade']:.1f} / {rep['max_grade']:.0f}"
        if rep["provisional"]:
            msg += " (provisional)"
        storage.set_submission_status(aid, roll, "done", msg, grade=rep["grade"])
    except grader.GradingError as e:
        log.warning("grading refused for %s / %s: %s", aid, roll, e)
        storage.set_submission_status(aid, roll, "failed", f"Could not grade this submission: {e}")
    except Exception:
        log.exception("submission job failed for %s / %s", aid, roll)
        try:
            storage.set_submission_status(aid, roll, "failed", "Something went wrong while grading your submission.")
        except Exception:
            log.exception("could not record failure for %s / %s", aid, roll)


def enqueue(aid: str, roll: str) -> Future:
    return _pool.submit(run_submission, aid, roll)
