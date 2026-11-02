import logging

import time

from server import storage

log = logging.getLogger("autograder")

# PLACEHOLDER pacing so each stage is visible in the UI.
# Remove the sleeps when the real sandbox and analyzers replace these stages.
STAGE_DELAY_S = 1.5


def _report_text(meta: dict, info: dict, source: bytes) -> str:
    lines = len(source.decode("utf-8").splitlines())
    return "\n".join([
        "===== AutoGrader submission receipt =====",
        f"Assignment : {meta['title']} ({meta['id']})",
        f"Student    : {info.get('name')}",
        f"Roll number: {info.get('roll_number')}",
        f"Attempt    : {info.get('attempt')}",
        f"Submitted  : {info.get('submitted_at')}",
        f"File       : solution.c, {info.get('bytes')} bytes, {lines} lines",
        f"SHA-256    : {info.get('sha256')}",
        f"Rules hash : {meta.get('rules_sha256')}",
        "",
        "STATUS: NOT GRADED",
        "This is a placeholder report. The sandbox and the analyzers are not",
        "connected yet, so your program was neither compiled nor run, and no",
        "grade was produced.",
        "",
    ])


def run_submission(aid: str, roll: str) -> None:
    try:
        storage.set_submission_status(aid, roll, "running", "Placeholder stage: the sandbox is not connected yet")
        time.sleep(STAGE_DELAY_S)
        storage.set_submission_status(aid, roll, "grading", "Placeholder stage: the analyzers are not connected yet")
        time.sleep(STAGE_DELAY_S)
        storage.set_submission_status(aid, roll, "reporting", "Writing the report")
        info, source = storage.read_submission(aid, roll)
        storage.write_report(aid, roll, _report_text(storage.get_meta(aid), info, source))
        storage.set_submission_status(aid, roll, "done", "Report ready (placeholder: not graded)")
    except Exception:
        log.exception("submission job failed for %s / %s", aid, roll)
        try:
            storage.set_submission_status(aid, roll, "failed", "Something went wrong while processing your submission.")
        except Exception:
            log.exception("could not record failure for %s / %s", aid, roll)