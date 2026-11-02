"""Shared fixtures.

Execution tests need a sandbox backend. AUTOGRADER_SANDBOX is used when set; otherwise Docker
is used if its image is present, then WSL on Windows, then a plain process on Linux. Tests that
need to run C code are skipped (with the reason) when no backend works.
"""
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO = BACKEND_DIR.parent
SAMPLES = REPO / "samples"
sys.path.insert(0, str(BACKEND_DIR))


def _pick_backend() -> None:
    if os.getenv("AUTOGRADER_SANDBOX"):
        return
    from server import sandbox
    os.environ["AUTOGRADER_SANDBOX"] = "docker"
    if sandbox.status(refresh=True)["available"]:
        return
    if platform.system() == "Windows" and shutil.which("wsl.exe"):
        os.environ["AUTOGRADER_SANDBOX"] = "wsl"
    elif platform.system() == "Linux":
        os.environ["AUTOGRADER_SANDBOX"] = "process"


_pick_backend()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def sandbox_ok():
    from server import sandbox
    st = sandbox.status(refresh=True)
    if not st["available"]:
        pytest.skip(f"no sandbox backend available: {st['detail']}")
    return st


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A private data/Assignments folder for one test."""
    from server import storage
    root = tmp_path / "Assignments"
    root.mkdir()
    monkeypatch.setattr(storage, "ROOT", root)
    return root


def load_sample(name: str) -> dict:
    base = SAMPLES / name
    return {
        "rules": json.loads((base / "rules.json").read_text(encoding="utf-8")),
        "tests": json.loads((base / "testcases.json").read_text(encoding="utf-8")),
        "statement": (base / "problem.txt").read_text(encoding="utf-8"),
        "reference": (base / "reference.c").read_text(encoding="utf-8"),
        "submissions": {p.stem: p.read_text(encoding="utf-8") for p in sorted((base / "submissions").glob("*.c"))},
    }


@pytest.fixture(scope="session")
def add_sample():
    return load_sample("add_two_integers")


@pytest.fixture(scope="session")
def sort_sample():
    return load_sample("sort_numbers")


def wait_for(fn, timeout=300, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError("condition not met in time")
