import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents import testgen
from grading import policy as grading_policy
from server import jobs, sandbox, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("autograder")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.reset_stale_jobs()
    for aid, roll in storage.reset_stale_submissions():
        jobs.enqueue(aid, roll)
    st = sandbox.status(refresh=True)
    if not st["available"]:
        log.error("sandbox unavailable (%s): submissions will be stored but not graded", st["detail"])
    elif not st["isolated"]:
        log.warning("%s", st["detail"])
    yield


app = FastAPI(title="AutoGrader", lifespan=lifespan)


class Metric(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    analyzer: str
    weight: float = Field(ge=0, le=1)
    params: dict = {}


class Policy(BaseModel):
    model_config = ConfigDict(extra="allow")
    metrics: list[Metric] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_policy(self):
        # weights sum to 1.00, known analyzers, valid flags, limits and input_spec
        grading_policy.validate(self.model_dump())
        return self


class NewAssignment(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=50_000)
    policy: Policy
    num_tests: int = Field(ge=5, le=100)
    reference_solution: str | None = Field(default=None, max_length=storage.MAX_SOURCE_BYTES)

class CaseIn(BaseModel):
    input: str = Field(max_length=10_000)
    expected_output: str = Field(min_length=1, max_length=10_000)
    category: str = Field(default="general", max_length=40)
    explanation: str = Field(default="", max_length=500)


class TestsIn(BaseModel):
    tests: list[CaseIn] = Field(max_length=100)


@app.get("/api/health")
def health():
    return {"sandbox": sandbox.status(), "analyzers": sorted(grading_policy.REGISTRY)}


@app.post("/api/assignments")
def create(body: NewAssignment):
    return storage.create_assignment(
        body.title, body.statement, body.policy.model_dump(), body.num_tests,
        (body.reference_solution or "").strip() and body.reference_solution,
    )


@app.get("/api/assignments")
def list_all():
    return storage.list_assignments()


@app.get("/api/assignments/{aid}")
def get_one(aid: str):
    try:
        return storage.get_meta(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")


@app.post("/api/assignments/{aid}/publish")
def publish(aid: str):
    try:
        return storage.publish(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))

def _generation_job(aid: str) -> None:
    try:
        meta = storage.get_meta(aid)
        out = testgen.run(storage.read_statement(aid), storage.read_rules(aid), meta["num_tests"])
        if not out["tests"]:
            msg = "; ".join(out["notes"]) or "the model produced no usable tests"
            storage.set_generation(aid, "failed", msg)
            return
        storage.write_tests(aid, out["tests"])
        msg = "; ".join(out["notes"]) or f"{len(out['tests'])} tests generated"
        storage.set_generation(aid, "done", msg)
    except Exception as e:
        storage.set_generation(aid, "failed", f"{type(e).__name__}: {e}")


@app.post("/api/assignments/{aid}/generate-tests", status_code=202)
def generate_tests(aid: str, background: BackgroundTasks):
    try:
        meta = storage.begin_generation(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))
    background.add_task(_generation_job, aid)
    return meta


@app.get("/api/assignments/{aid}/tests")
def get_tests(aid: str):
    try:
        return storage.read_tests(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")


@app.put("/api/assignments/{aid}/tests")
def put_tests(aid: str, body: TestsIn):
    try:
        if storage.get_meta(aid).get("generation", {}).get("state") == "running":
            raise PermissionError("test generation is running")
        tests = [{"id": f"T{i:03d}", **c.model_dump()} for i, c in enumerate(body.tests, 1)]
        storage.write_tests(aid, tests)
        return tests
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))

@app.post("/api/assignments/{aid}/accept-tests")
def accept_tests(aid: str):
    try:
        return storage.accept_tests(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))
# ------------------------------------------------------------ student endpoints
@app.get("/api/student/assignments")
def student_list():
    return storage.list_published()


@app.get("/api/student/assignments/{aid}")
def student_get(aid: str):
    try:
        return storage.get_public(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")


@app.post("/api/student/assignments/{aid}/submissions", status_code=202)
def student_submit(
    aid: str,
    name: str = Form(..., max_length=200),
    roll_number: str = Form(..., max_length=64),
    file: UploadFile = File(...),
):
    source = file.file.read(storage.MAX_SOURCE_BYTES + 1)
    try:
        info = storage.create_submission(aid, name, roll_number, file.filename or "", source)
    except storage.InvalidInput as e:
        raise HTTPException(422, str(e))
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))
    jobs.enqueue(aid, info["roll_number"])
    return {"assignment_id": aid, "roll_number": info["roll_number"], "attempt": info["attempt"]}


def _published_submission(aid: str, roll: str) -> None:
    """Student endpoints only ever see published assignments."""
    storage.get_public(aid)
    storage.normalize_roll(roll)


@app.get("/api/student/assignments/{aid}/submissions/{roll}/status")
def student_status(aid: str, roll: str):
    try:
        _published_submission(aid, roll)
        return storage.get_submission_status(aid, roll)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "submission not found")


@app.get("/api/student/assignments/{aid}/submissions/{roll}/report")
def student_report(aid: str, roll: str, format: Literal["txt", "json"] = Query("txt")):
    try:
        _published_submission(aid, roll)
        path = storage.report_path(aid, roll, format)
        roll_id = storage.normalize_roll(roll)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "report not ready")
    media = "application/json" if format == "json" else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media, filename=f"report_{aid}_{roll_id}.{format}")


@app.get("/api/student/assignments/{aid}/submissions/{roll}/result")
def student_result(aid: str, roll: str):
    """The graded report as JSON, for the results view on the student page."""
    try:
        _published_submission(aid, roll)
        return storage.read_report(aid, roll)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "report not ready")


@app.get("/api/student/assignments/{aid}/submissions/{roll}/history")
def student_history(aid: str, roll: str):
    try:
        _published_submission(aid, roll)
        return storage.history(aid, roll)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "submission not found")


# ------------------------------------------------------------ teacher: submissions
@app.get("/api/assignments/{aid}/submissions")
def teacher_submissions(aid: str):
    try:
        return storage.list_submissions(aid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "assignment not found")


@app.get("/api/assignments/{aid}/submissions/{roll}")
def teacher_submission(aid: str, roll: str):
    try:
        status = storage.get_submission_status(aid, roll)
        out = {"status": status, "history": storage.history(aid, roll),
               "source": storage.read_source(aid, roll), "report": None, "review": None}
        if status["state"] == "done":
            out["report"] = storage.read_report(aid, roll)
            out["review"] = storage.read_review(aid, roll)
        return out
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "submission not found")


@app.get("/api/assignments/{aid}/submissions/{roll}/report")
def teacher_report(aid: str, roll: str, format: Literal["txt", "json"] = Query("txt")):
    try:
        path = storage.report_path(aid, roll, format)
        roll_id = storage.normalize_roll(roll)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "report not ready")
    media = "application/json" if format == "json" else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media, filename=f"report_{aid}_{roll_id}.{format}")


@app.post("/api/assignments/{aid}/submissions/{roll}/regrade", status_code=202)
def teacher_regrade(aid: str, roll: str):
    try:
        storage.requeue(aid, roll)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "submission not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))
    jobs.enqueue(aid, storage.normalize_roll(roll))
    return {"assignment_id": aid, "roll_number": storage.normalize_roll(roll), "state": "queued"}
# Serve the plain HTML/CSS/JS frontend. Must come after the API routes.
app.mount("/", StaticFiles(directory=storage.REPO_ROOT / "frontend", html=True), name="frontend")