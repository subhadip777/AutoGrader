import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
import threading
import shutil
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
# AUTOGRADER_DATA_DIR moves the data folder (for demos and tests); default is <repo>/data
ROOT = Path(os.getenv("AUTOGRADER_DATA_DIR") or REPO_ROOT / "data") / "Assignments"
ID_RE = re.compile(r"^ASG-[A-F0-9]{6}$")
_lock = threading.Lock()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _replace_with_retry(tmp: Path, path: Path) -> None:
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05)


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _replace_with_retry(tmp, path)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    _replace_with_retry(tmp, path)


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


def create_assignment(title: str, statement: str, policy: dict, num_tests: int,
                      reference_solution: str | None = None) -> dict:
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
        "has_reference": bool(reference_solution),
        "rules_sha256": hashlib.sha256(rules_canonical.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_atomic(base / "Problem" / "problem.txt", statement)
    _write_atomic(base / "Problem" / "rules.json", json.dumps(policy, indent=2))
    _write_atomic(base / "Problem" / "testcases.json", "[]")
    if reference_solution:
        _write_atomic(base / "Problem" / "reference.c", reference_solution)
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


def read_reference(aid: str) -> str | None:
    """The teacher's optional reference solution (never shown to students)."""
    p = _dir(aid) / "Problem" / "reference.c"
    return p.read_text(encoding="utf-8") if p.exists() else None


def read_corpus(aid: str, exclude_roll: str) -> list[dict]:
    """Programs to compare a submission with: the current submission of every other roll
    number, plus any known solutions the teacher dropped into Problem/corpus/*.c."""
    d = _dir(aid)
    out = []
    subs = d / "Submissions"
    if subs.is_dir():
        for s in sorted(subs.iterdir()):
            if s.is_dir() and s.name != exclude_roll and ROLL_RE.match(s.name) and (s / "solution.c").exists():
                out.append({"label": s.name, "kind": "submission",
                            "source": (s / "solution.c").read_text(encoding="utf-8", errors="replace")})
    corpus = d / "Problem" / "corpus"
    if corpus.is_dir():
        for f in sorted(corpus.glob("*.c"))[:200]:
            out.append({"label": f"corpus/{f.name}", "kind": "corpus",
                        "source": f.read_text(encoding="utf-8", errors="replace")})
    return out


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

# ---------------------------------------------------------------- submissions
ROLL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL",
                  *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}
MAX_SOURCE_BYTES = 100_000
ACTIVE_STATES = {"queued", "running", "grading", "reporting"}


class InvalidInput(ValueError):
    """User-supplied data failed validation (HTTP 422)."""


def _read_json(path: Path, default=None):
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
    return default


def _require_published(aid: str) -> dict:
    meta = get_meta(aid)
    if meta["status"] != "published":
        raise FileNotFoundError(aid)  # students must not learn that drafts exist
    return meta


def normalize_roll(raw: str) -> str:
    roll = (raw or "").strip().upper()  # Windows folders ignore case, so normalise it
    if not ROLL_RE.match(roll) or roll in RESERVED_NAMES:
        raise InvalidInput("Roll number may contain only letters, digits, '-' and '_' (max 32 characters).")
    return roll


def _sub_dir(aid: str, roll: str) -> Path:
    base = _dir(aid)
    d = base / "Submissions" / normalize_roll(roll)
    if not d.is_dir():
        raise FileNotFoundError(roll)
    return d


def list_published() -> list[dict]:
    return [
        {"id": m["id"], "title": m["title"], "published_at": m.get("published_at")}
        for m in list_assignments()
        if m["status"] == "published"
    ]


def get_public(aid: str) -> dict:
    meta = _require_published(aid)
    return {"id": aid, "title": meta["title"], "statement": read_statement(aid)}


def create_submission(aid: str, name: str, roll_raw: str, filename: str, source: bytes) -> dict:
    _require_published(aid)
    name = " ".join((name or "").split())
    if not name or len(name) > 80:
        raise InvalidInput("Name is required (max 80 characters).")
    roll = normalize_roll(roll_raw)
    if not (filename or "").lower().endswith(".c"):
        raise InvalidInput("Please upload a .c file.")
    if not source:
        raise InvalidInput("The file is empty.")
    if len(source) > MAX_SOURCE_BYTES:
        raise InvalidInput(f"The file is larger than {MAX_SOURCE_BYTES // 1000} KB.")
    if b"\x00" in source:
        raise InvalidInput("The file does not look like C source text.")
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidInput("The file must be UTF-8 text.")

    with _lock:
        sub_root = _dir(aid) / "Submissions"
        sub_root.mkdir(exist_ok=True)
        d = sub_root / roll
        hist = d / "history"
        n_hist = len(list(hist.iterdir())) if hist.exists() else 0
        attempt = n_hist + 1
        if (d / "solution.c").exists():
            current = _read_json(d / "status.json", {})
            if current.get("state") in ACTIVE_STATES:
                raise PermissionError("Your previous submission is still being processed. Please wait for it to finish.")
            dest = hist / f"attempt_{n_hist + 1}"
            dest.mkdir(parents=True)
            for item in list(d.iterdir()):
                if item.name != "history":
                    shutil.move(str(item), str(dest / item.name))
            attempt = n_hist + 2
        d.mkdir(exist_ok=True)

        info = {
            "assignment_id": aid,
            "name": name,
            "roll_number": roll,
            "attempt": attempt,
            "submitted_at": _now(),
            "bytes": len(source),
            "sha256": hashlib.sha256(source).hexdigest(),
        }
        _write_bytes_atomic(d / "solution.c", source)
        _write_atomic(d / "info.json", json.dumps(info, indent=2))
        _write_atomic(d / "status.json", json.dumps(
            {"state": "queued", "message": "Submission received", "updated_at": _now()}, indent=2))
        return info


def set_submission_status(aid: str, roll: str, state: str, message: str = "", **extra) -> None:
    d = _sub_dir(aid, roll)
    _write_atomic(d / "status.json", json.dumps(
        {"state": state, "message": message, "updated_at": _now(), **extra}, indent=2))


def _summary(report: dict | None) -> dict:
    if not report:
        return {}
    return {"grade": report.get("grade"), "max_grade": report.get("max_grade"),
            "complete": report.get("complete"), "provisional": report.get("provisional"),
            "flags": report.get("flags", [])}


def get_submission_status(aid: str, roll: str) -> dict:
    d = _sub_dir(aid, roll)
    st = _read_json(d / "status.json", {"state": "unknown", "message": ""})
    info = _read_json(d / "info.json", {})
    out = {"state": st.get("state"), "message": st.get("message", ""), "attempt": info.get("attempt"),
           "stage": st.get("stage"), "step": st.get("step"), "steps": st.get("steps"),
           "updated_at": st.get("updated_at")}
    if st.get("state") == "done":
        out.update(_summary(_read_json(d / "report.json", None)))
    return out


def read_submission(aid: str, roll: str) -> tuple[dict, bytes]:
    d = _sub_dir(aid, roll)
    return _read_json(d / "info.json", {}), (d / "solution.c").read_bytes()


def write_report(aid: str, roll: str, text: str, report: dict | None = None, review: dict | None = None) -> None:
    """Save report.txt, and report.json / review.json when given. JSON files are written first,
    so a reader who sees status "done" always finds all of them."""
    d = _sub_dir(aid, roll)
    if report is not None:
        _write_atomic(d / "report.json", json.dumps(report, indent=2))
    if review is not None:
        _write_atomic(d / "review.json", json.dumps(review, indent=2))
    _write_bytes_atomic(d / "report.txt", text.encode("utf-8"))


REPORT_FILES = {"txt": "report.txt", "json": "report.json"}


def report_path(aid: str, roll: str, kind: str = "txt") -> Path:
    if kind not in REPORT_FILES:
        raise ValueError("unknown report format")
    d = _sub_dir(aid, roll)
    st = _read_json(d / "status.json", {})
    p = d / REPORT_FILES[kind]
    if st.get("state") != "done" or not p.exists():
        raise FileNotFoundError("report not ready")
    return p


def read_report(aid: str, roll: str) -> dict:
    return json.loads(report_path(aid, roll, "json").read_text(encoding="utf-8"))


def read_review(aid: str, roll: str) -> dict:
    return _read_json(_sub_dir(aid, roll) / "review.json", {}) or {}


def history(aid: str, roll: str) -> list[dict]:
    """Every attempt of one student, oldest first; the current one is last."""
    d = _sub_dir(aid, roll)
    attempts = []
    hist = d / "history"
    folders = sorted(hist.iterdir(), key=lambda p: int(p.name.split("_")[-1])) if hist.is_dir() else []
    for folder in folders + [d]:
        info = _read_json(folder / "info.json", None)
        if not info:
            continue
        st = _read_json(folder / "status.json", {}) or {}
        attempts.append({"attempt": info.get("attempt"), "submitted_at": info.get("submitted_at"),
                         "sha256": info.get("sha256"), "state": st.get("state"),
                         "current": folder == d, **_summary(_read_json(folder / "report.json", None))})
    return attempts


def list_submissions(aid: str) -> list[dict]:
    """Teacher view: the current attempt of every student."""
    subs = _dir(aid) / "Submissions"
    out = []
    if not subs.is_dir():
        return out
    for d in sorted(subs.iterdir()):
        if not (d.is_dir() and ROLL_RE.match(d.name)):
            continue
        info = _read_json(d / "info.json", None)
        if not info:
            continue
        st = _read_json(d / "status.json", {}) or {}
        out.append({"roll_number": info.get("roll_number"), "name": info.get("name"),
                    "attempt": info.get("attempt"), "submitted_at": info.get("submitted_at"),
                    "state": st.get("state"), "message": st.get("message", ""),
                    **_summary(_read_json(d / "report.json", None) if st.get("state") == "done" else None)})
    return out


def read_source(aid: str, roll: str) -> str:
    return (_sub_dir(aid, roll) / "solution.c").read_text(encoding="utf-8", errors="replace")


def requeue(aid: str, roll: str, message: str = "Queued for regrading") -> None:
    with _lock:
        d = _sub_dir(aid, roll)
        st = _read_json(d / "status.json", {}) or {}
        if st.get("state") in ACTIVE_STATES:
            raise PermissionError("this submission is already being graded")
        _write_atomic(d / "status.json", json.dumps(
            {"state": "queued", "message": message, "updated_at": _now()}, indent=2))


def reset_stale_submissions() -> list[tuple[str, str]]:
    """A server restart kills background jobs. Grading is deterministic and the source is kept,
    so unfinished submissions are put back in the queue; returns them as (assignment id, roll)."""
    pending = []
    if not ROOT.exists():
        return pending
    for a in sorted(ROOT.iterdir()):
        subs = a / "Submissions"
        if not (ID_RE.match(a.name) and subs.is_dir()):
            continue
        for d in sorted(subs.iterdir()):
            st = _read_json(d / "status.json", None)
            if st and st.get("state") in ACTIVE_STATES and ROLL_RE.match(d.name) and (d / "solution.c").exists():
                _write_atomic(d / "status.json", json.dumps({
                    "state": "queued",
                    "message": "Interrupted by a server restart; grading again",
                    "updated_at": _now(),
                }, indent=2))
                pending.append((a.name, d.name))
    return pending
