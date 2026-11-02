"""Create and publish the two sample assignments in data/Assignments, for a demo without Ollama.

The test cases come from samples/*/testcases.json (written and checked by hand) instead of
the LLM; everything else goes through the same storage functions the web app uses.

    python scripts/seed_demo.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from grading import policy  # noqa: E402
from server import storage  # noqa: E402

SAMPLES = {"add_two_integers": "Add Two Integers (sample)", "sort_numbers": "Sort the Numbers (sample)"}


def main() -> None:
    existing = {m["title"]: m["id"] for m in storage.list_assignments()}
    for folder, title in SAMPLES.items():
        if title in existing:
            print(f"{title}: already exists as {existing[title]}")
            continue
        base = ROOT / "samples" / folder
        rules = json.loads((base / "rules.json").read_text(encoding="utf-8"))
        policy.validate(rules)
        tests = json.loads((base / "testcases.json").read_text(encoding="utf-8"))
        meta = storage.create_assignment(title, (base / "problem.txt").read_text(encoding="utf-8"), rules,
                                         len(tests), (base / "reference.c").read_text(encoding="utf-8"))
        storage.write_tests(meta["id"], tests)
        storage.set_generation(meta["id"], "done", f"{len(tests)} hand-written sample tests")
        storage.accept_tests(meta["id"])
        storage.publish(meta["id"])
        print(f"{title}: created and published as {meta['id']}")


if __name__ == "__main__":
    main()
