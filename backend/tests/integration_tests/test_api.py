"""The HTTP API end to end: teacher flow, student submission, grading, reports, history."""
import json

import pytest
from fastapi.testclient import TestClient

from conftest import wait_for
from server import jobs, main, sandbox, storage


@pytest.fixture
def client(data_root):
    with TestClient(main.app) as c:
        yield c


def create_published(client, sample, title="Add"):
    r = client.post("/api/assignments", json={"title": title, "statement": sample["statement"],
                                              "policy": sample["rules"], "num_tests": 10,
                                              "reference_solution": sample["reference"]})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    assert client.post(f"/api/assignments/{aid}/publish").status_code == 409     # tests not accepted yet
    tests = [{k: t[k] for k in ("input", "expected_output", "category", "explanation")} for t in sample["tests"]]
    assert client.put(f"/api/assignments/{aid}/tests", json={"tests": tests}).status_code == 200
    assert client.post(f"/api/assignments/{aid}/accept-tests").json()["tests_accepted"]
    assert client.post(f"/api/assignments/{aid}/publish").json()["status"] == "published"
    return aid


def submit(client, aid, roll, source, name="Test Student", filename="solution.c"):
    return client.post(f"/api/student/assignments/{aid}/submissions",
                       data={"name": name, "roll_number": roll},
                       files={"file": (filename, source.encode() if isinstance(source, str) else source, "text/x-c")})


def wait_done(client, aid, roll):
    def check():
        st = client.get(f"/api/student/assignments/{aid}/submissions/{roll}/status").json()
        return st if st["state"] in ("done", "failed") else None
    return wait_for(check, timeout=600)


def test_policy_validation_on_create(client, add_sample):
    bad = json.loads(json.dumps(add_sample["rules"]))
    bad["metrics"][0]["weight"] = 0.9
    r = client.post("/api/assignments", json={"title": "x", "statement": "s", "policy": bad, "num_tests": 10})
    assert r.status_code == 422 and "sum to 1.00" in r.text
    bad = json.loads(json.dumps(add_sample["rules"]))
    bad["metrics"][0]["analyzer"] = "rm -rf"
    r = client.post("/api/assignments", json={"title": "x", "statement": "s", "policy": bad, "num_tests": 10})
    assert r.status_code == 422 and "unknown analyzer" in r.text


def test_student_endpoints_hide_drafts_tests_and_rules(client, add_sample):
    draft = client.post("/api/assignments", json={"title": "D", "statement": "s", "policy": add_sample["rules"],
                                                  "num_tests": 10}).json()["id"]
    aid = create_published(client, add_sample)
    listed = client.get("/api/student/assignments").json()
    assert [a["id"] for a in listed] == [aid]
    assert client.get(f"/api/student/assignments/{draft}").status_code == 404
    body = client.get(f"/api/student/assignments/{aid}").text
    assert "expected_output" not in body and "metrics" not in body and "long long a, b" not in body
    assert submit(client, draft, "R1", "int main(void){return 0;}").status_code == 404


def test_upload_validation(client, add_sample):
    aid = create_published(client, add_sample)
    assert submit(client, aid, "R1", "int main(){}", filename="a.txt").status_code == 422
    assert submit(client, aid, "../R1", "int main(){}").status_code == 422
    assert submit(client, aid, "R1", b"").status_code == 422
    assert submit(client, aid, "R1", b"\x00\x01").status_code == 422
    assert submit(client, aid, "R1", b"x" * 100_001).status_code == 422
    assert submit(client, "ASG-000000", "R1", "int main(){}").status_code == 404


def test_full_flow_submit_grade_download_resubmit(client, add_sample, sandbox_ok):
    aid = create_published(client, add_sample)
    r = submit(client, aid, "2611ai25", add_sample["submissions"]["overflow"], name="Aradhya Ranjan")
    assert r.status_code == 202 and r.json() == {"assignment_id": aid, "roll_number": "2611AI25", "attempt": 1}
    st = wait_done(client, aid, "2611AI25")
    assert st["state"] == "done", st
    assert isinstance(st["grade"], float)

    rep = client.get(f"/api/student/assignments/{aid}/submissions/2611AI25/result").json()
    assert rep["student"] == {"name": "Aradhya Ranjan", "roll_number": "2611AI25"}
    assert rep["assignment"]["id"] == aid and rep["grade"] == st["grade"]
    assert any(c["theme"] == "int_overflow" for c in rep["counter_tests"])

    txt = client.get(f"/api/student/assignments/{aid}/submissions/2611AI25/report")
    assert txt.status_code == 200 and "Overall grade" in txt.text and "Aradhya Ranjan" in txt.text
    assert "attachment" in txt.headers["content-disposition"] and "NOT GRADED" not in txt.text
    js = client.get(f"/api/student/assignments/{aid}/submissions/2611AI25/report?format=json")
    assert js.status_code == 200 and js.json()["grade"] == rep["grade"]
    assert client.get(f"/api/student/assignments/{aid}/submissions/2611AI25/report?format=meta").status_code == 422

    # resubmit a better version: the first attempt is kept
    assert submit(client, aid, "2611AI25", add_sample["submissions"]["correct"]).json()["attempt"] == 2
    st2 = wait_done(client, aid, "2611AI25")
    assert st2["state"] == "done" and st2["grade"] > st["grade"]
    hist = client.get(f"/api/student/assignments/{aid}/submissions/2611AI25/history").json()
    assert [h["attempt"] for h in hist] == [1, 2] and hist[0]["grade"] == st["grade"]

    # teacher view
    subs = client.get(f"/api/assignments/{aid}/submissions").json()
    assert subs[0]["roll_number"] == "2611AI25" and subs[0]["grade"] == st2["grade"]
    detail = client.get(f"/api/assignments/{aid}/submissions/2611AI25").json()
    assert detail["report"]["grade"] == st2["grade"] and "add_values" in detail["source"]
    assert client.post(f"/api/assignments/{aid}/submissions/2611AI25/regrade").status_code == 202
    st3 = wait_done(client, aid, "2611AI25")
    assert st3["state"] == "done"


def test_originality_flag_visible_to_teacher_only(client, sort_sample, sandbox_ok):
    aid = create_published(client, sort_sample, title="Sort")
    assert submit(client, aid, "A1", sort_sample["submissions"]["similar_a"]).status_code == 202
    wait_done(client, aid, "A1")
    assert submit(client, aid, "B2", sort_sample["submissions"]["similar_b"]).status_code == 202
    st = wait_done(client, aid, "B2")
    assert "originality_review" in st["flags"]
    student = client.get(f"/api/student/assignments/{aid}/submissions/B2/result").text
    assert "A1" not in json.loads(student)["metrics"][-1]["evidence"].values()
    assert '"A1"' not in student
    teacher = client.get(f"/api/assignments/{aid}/submissions/B2").json()
    assert teacher["review"]["originality"][0]["matches"][0]["label"] == "A1"


def test_grading_fails_safely_without_docker(client, add_sample, monkeypatch):
    aid = create_published(client, add_sample)
    monkeypatch.setenv("AUTOGRADER_SANDBOX", "docker")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    sandbox._status_cache.clear()
    called = []
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: called.append(a))
    assert submit(client, aid, "R9", add_sample["submissions"]["correct"]).status_code == 202
    st = wait_done(client, aid, "R9")
    assert st["state"] == "failed" and "Docker is not installed" in st["message"]
    assert called == []                       # nothing was executed on the host
    assert (storage.ROOT / aid / "Submissions" / "R9" / "solution.c").exists()   # the file is kept
    sandbox._status_cache.clear()


def test_frontend_pages_are_served(client):
    for page, marker in (("/", "Submit assignment"), ("/student.html", "result-section"),
                         ("/teacher.html", "reference-file"), ("/submissions.html", "Originality matches"),
                         ("/review.html", "Validate test cases")):
        r = client.get(page)
        assert r.status_code == 200 and marker in r.text, page
    js = client.get("/student.js").text
    for endpoint in ("/result", "/history", "/report?format="):
        assert endpoint in js
    assert client.get("/api/health").json()["analyzers"]


def test_jobs_never_raise(data_root):
    jobs.run_submission("ASG-FFFFFF", "NOPE")      # unknown submission: logged, no exception
