"""Plain-file storage: validation, path safety, immutability and history."""
import json

import pytest

from server import storage


@pytest.fixture
def published(data_root, add_sample):
    meta = storage.create_assignment("Add", add_sample["statement"], add_sample["rules"], 10, add_sample["reference"])
    storage.write_tests(meta["id"], add_sample["tests"])
    storage.accept_tests(meta["id"])
    storage.publish(meta["id"])
    return meta["id"]


@pytest.mark.parametrize("aid", ["../etc", "ASG-12345", "asg-abcdef", "ASG-ABCDEF/../x", "ASG-ABCDE\\", ""])
def test_assignment_ids_are_validated(data_root, aid):
    with pytest.raises((ValueError, FileNotFoundError)):
        storage.get_meta(aid)


@pytest.mark.parametrize("roll", ["../x", "a/b", "a\\b", "CON", "nul", "", "x" * 33, "a b", "a.b"])
def test_roll_numbers_are_validated(roll):
    with pytest.raises(storage.InvalidInput):
        storage.normalize_roll(roll)


def test_roll_numbers_are_upper_cased():
    assert storage.normalize_roll(" 2611ai25 ") == "2611AI25"


@pytest.mark.parametrize("filename, data, msg", [
    ("a.txt", b"int main(){}", ".c file"),
    ("a.c", b"", "empty"),
    ("a.c", b"x" * (storage.MAX_SOURCE_BYTES + 1), "larger"),
    ("a.c", b"int main(){}\x00", "C source"),
    ("a.c", b"\xff\xfe\x00", "C source"),
    ("a.c", "int main(){}".encode("utf-16"), "C source"),
])
def test_uploads_are_validated(published, filename, data, msg):
    with pytest.raises(storage.InvalidInput, match=msg):
        storage.create_submission(published, "Ann", "R1", filename, data)


def test_drafts_are_invisible_to_students(data_root, add_sample):
    meta = storage.create_assignment("Draft", "s", add_sample["rules"], 5)
    assert storage.list_published() == []
    with pytest.raises(FileNotFoundError):
        storage.get_public(meta["id"])
    with pytest.raises(FileNotFoundError):
        storage.create_submission(meta["id"], "Ann", "R1", "a.c", b"int main(void){return 0;}")


def test_public_view_has_no_tests_rules_or_reference(published):
    pub = storage.get_public(published)
    assert set(pub) == {"id", "title", "statement"}
    assert all(set(a) == {"id", "title", "published_at"} for a in storage.list_published())


def test_published_assignments_are_immutable(published, add_sample):
    with pytest.raises(PermissionError):
        storage.write_tests(published, add_sample["tests"][:1])
    with pytest.raises(PermissionError):
        storage.begin_generation(published)
    with pytest.raises(PermissionError):
        storage.publish(published)


def test_resubmission_keeps_history(published):
    src1, src2 = b"int main(void){return 0;}\n", b"int main(void){return 1;}\n"
    storage.create_submission(published, "Ann", "r1", "a.c", src1)
    storage.set_submission_status(published, "R1", "done", "ok")
    storage.write_report(published, "R1", "first report", {"grade": 10.0, "max_grade": 100}, {})
    info = storage.create_submission(published, "Ann", "R1", "a.c", src2)
    assert info["attempt"] == 2
    d = storage.ROOT / published / "Submissions" / "R1"
    assert (d / "history" / "attempt_1" / "solution.c").read_bytes() == src1
    assert (d / "history" / "attempt_1" / "report.txt").read_text() == "first report"
    assert (d / "solution.c").read_bytes() == src2 and not (d / "report.txt").exists()
    h = storage.history(published, "R1")
    assert [a["attempt"] for a in h] == [1, 2] and h[0]["grade"] == 10.0 and h[1]["current"]


def test_cannot_resubmit_while_grading(published):
    storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")
    with pytest.raises(PermissionError, match="still being processed"):
        storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")


def test_reports_only_downloadable_when_done(published):
    storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")
    with pytest.raises(FileNotFoundError):
        storage.report_path(published, "R1")
    storage.write_report(published, "R1", "txt", {"grade": 1}, {"x": 1})
    storage.set_submission_status(published, "R1", "done")
    assert storage.report_path(published, "R1", "json").name == "report.json"
    with pytest.raises(ValueError):
        storage.report_path(published, "R1", "../../meta")


def test_restart_requeues_interrupted_submissions(published):
    storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")
    storage.set_submission_status(published, "R1", "grading", "half way")
    assert storage.reset_stale_submissions() == [(published, "R1")]
    assert storage.get_submission_status(published, "R1")["state"] == "queued"


def test_corpus_excludes_own_submission(published):
    storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")
    storage.create_submission(published, "Bob", "R2", "b.c", b"int main(void){return 2;}")
    labels = [c["label"] for c in storage.read_corpus(published, "R1")]
    assert labels == ["R2"]


def test_reference_solution_stored_privately(published, add_sample):
    assert storage.read_reference(published) == add_sample["reference"]
    assert storage.get_meta(published)["has_reference"] is True


def test_writes_are_atomic(published):
    storage.update_meta(published, note="x")
    leftovers = list((storage.ROOT / published).glob("*.tmp"))
    assert leftovers == [] and json.loads((storage.ROOT / published / "meta.json").read_text())["note"] == "x"


# ------------------------------------------------------------------ deletion
def test_delete_moves_assignment_to_trash(published):
    storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")
    storage.set_submission_status(published, "R1", "done")
    assert storage.assignment_summary(published)["submissions"] == 1
    out = storage.delete_assignment(published)
    assert not (storage.ROOT / published).exists()
    moved = storage.ROOT.parent / out["trash"]
    assert (moved / "Submissions" / "R1" / "solution.c").exists()      # nothing is erased
    assert moved.parent == storage.trash_dir() and storage.trash_dir().parent == storage.ROOT.parent
    assert storage.list_assignments() == [] and storage.list_published() == []
    with pytest.raises(FileNotFoundError):
        storage.get_meta(published)


def test_delete_refused_while_grading(published):
    storage.create_submission(published, "Ann", "R1", "a.c", b"int main(void){return 0;}")   # state: queued
    with pytest.raises(PermissionError, match="being graded"):
        storage.delete_assignment(published)
    assert (storage.ROOT / published).exists()


def test_delete_refused_while_generating(data_root, add_sample):
    meta = storage.create_assignment("D", "s", add_sample["rules"], 5)
    storage.begin_generation(meta["id"])
    with pytest.raises(PermissionError, match="generation"):
        storage.delete_assignment(meta["id"])


@pytest.mark.parametrize("aid", ["../Trash", "ASG-ZZZZZZ", "ASG-000000"])
def test_delete_validates_ids(data_root, aid):
    with pytest.raises((ValueError, FileNotFoundError)):
        storage.delete_assignment(aid)
