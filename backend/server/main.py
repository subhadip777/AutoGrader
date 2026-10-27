import math

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from server import storage
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks
from agents import testgen

@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.reset_stale_jobs()
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
    def weights_sum_to_one(self):
        total = sum(m.weight for m in self.metrics)
        if not math.isclose(total, 1.0, abs_tol=0.001):
            raise ValueError(f"weights must sum to 1.00 (got {total:.2f})")
        return self


class NewAssignment(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=50_000)
    policy: Policy
    num_tests: int = Field(ge=5, le=100)

class CaseIn(BaseModel):
    input: str = Field(max_length=10_000)
    expected_output: str = Field(min_length=1, max_length=10_000)
    category: str = Field(default="general", max_length=40)
    explanation: str = Field(default="", max_length=500)


class TestsIn(BaseModel):
    tests: list[CaseIn] = Field(max_length=100)


@app.post("/api/assignments")
def create(body: NewAssignment):
    return storage.create_assignment(
        body.title, body.statement, body.policy.model_dump(), body.num_tests
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

# Serve the plain HTML/CSS/JS frontend. Must come after the API routes.
app.mount("/", StaticFiles(directory=storage.REPO_ROOT / "frontend", html=True), name="frontend")