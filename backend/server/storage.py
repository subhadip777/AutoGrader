import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
import threading

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "data" / "Assignments"
ID_RE = re.compile(r"^ASG-[A-F0-9]{6}$")
_lock = threading.Lock()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _dir(aid: str) -> Path:
    if not ID_RE.match(aid):
        raise ValueError("invalid assignment id")
    d = ROOT / aid
    if not d.is_dir():
        raise FileNotFoundError(aid)
    return d


def _new_id() -> str:
    while True:
        aid = "ASG-" + secrets.token_hex(3).upper()
        if not (ROOT / aid).exists():
            return aid


def create_assignment(title: str, statement: str, policy: dict, num_tests: int) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    aid = _new_id()
    base = ROOT / aid
    (base / "Problem").mkdir(parents=True)
    (base / "Submissions").mkdir()

    rules_canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    meta = {
        "id": aid,
        "title": title,
        "status": "draft",
        "num_tests": num_tests,
        "tests_accepted": False,
        "rules_sha256": hashlib.sha256(rules_canonical.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_atomic(base / "Problem" / "problem.txt", statement)
    _write_atomic(base / "Problem" / "rules.json", json.dumps(policy, indent=2))
    _write_atomic(base / "Problem" / "testcases.json", "[]")
    _write_atomic(base / "meta.json", json.dumps(meta, indent=2))
    return meta


def get_meta(aid: str) -> dict:
    return json.loads((_dir(aid) / "meta.json").read_text(encoding="utf-8"))


def list_assignments() -> list[dict]:
    if not ROOT.exists():
        return []
    items = []
    for d in ROOT.iterdir():
        if d.is_dir() and ID_RE.match(d.name) and (d / "meta.json").exists():
            items.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
    return sorted(items, key=lambda m: m["created_at"], reverse=True)


def publish(aid: str) -> dict:
    with _lock:
        d = _dir(aid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta["status"] != "draft":
            raise PermissionError("assignment is already published")
        if meta.get("generation", {}).get("state") == "running":
            raise PermissionError("test generation is still running")
        if not meta.get("tests_accepted"):
            raise PermissionError("validate and accept the test cases before publishing")
        meta["status"] = "published"
        meta["published_at"] = _now()
        _write_atomic(d / "meta.json", json.dumps(meta, indent=2))
        return meta

def read_statement(aid: str) -> str:
    return (_dir(aid) / "Problem" / "problem.txt").read_text(encoding="utf-8")


def read_rules(aid: str) -> dict:
    return json.loads((_dir(aid) / "Problem" / "rules.json").read_text(encoding="utf-8"))


def read_tests(aid: str) -> list[dict]:
    return json.loads((_dir(aid) / "Problem" / "testcases.json").read_text(encoding="utf-8"))


def write_tests(aid: str, tests: list[dict]) -> None:
    d = _dir(aid)
    if get_meta(aid)["status"] != "draft":
        raise PermissionError("published assignments are locked")
    _write_atomic(d / "Problem" / "testcases.json", json.dumps(tests, indent=2))
    update_meta(aid, tests_accepted=False)


def update_meta(aid: str, **fields) -> dict:
    with _lock:
        d = _dir(aid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        meta.update(fields)
        _write_atomic(d / "meta.json", json.dumps(meta, indent=2))
        return meta


def begin_generation(aid: str) -> dict:
    with _lock:
        d = _dir(aid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta["status"] != "draft":
            raise PermissionError("published assignments are locked")
        if meta.get("generation", {}).get("state") == "running":
            raise PermissionError("test generation is already running")
        meta["generation"] = {"state": "running", "message": "", "updated_at": _now()}
        meta["tests_accepted"] = False
        _write_atomic(d / "meta.json", json.dumps(meta, indent=2))
        return meta


def set_generation(aid: str, state: str, message: str) -> None:
    update_meta(aid, generation={"state": state, "message": message, "updated_at": _now()})


def reset_stale_jobs() -> None:
    """A server restart kills background jobs, so mark leftovers as failed."""
    for m in list_assignments():
        if m.get("generation", {}).get("state") == "running":
            set_generation(m["id"], "failed", "interrupted by a server restart")


def accept_tests(aid: str) -> dict:
    with _lock:
        d = _dir(aid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta["status"] != "draft":
            raise PermissionError("published assignments are locked")
        if meta.get("generation", {}).get("state") == "running":
            raise PermissionError("test generation is still running")
        if not read_tests(aid):
            raise PermissionError("there are no test cases to accept")
        meta["tests_accepted"] = True
        meta["tests_accepted_at"] = _now()
        _write_atomic(d / "meta.json", json.dumps(meta, indent=2))
        return meta