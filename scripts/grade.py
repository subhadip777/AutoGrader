"""Grade C files from the command line, without the web server.

A problem folder holds rules.json, testcases.json and optionally problem.txt and reference.c.

    python scripts/grade.py samples/add_two_integers samples/add_two_integers/submissions/overflow.c
    python scripts/grade.py samples/sort_numbers --all          # every file in submissions/

With --all each file is compared for originality with the other files in the folder, and the
reports are written to <problem>/reports/<name>.json and .txt.
"""
import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agents import grader  # noqa: E402
from grading import policy  # noqa: E402
from grading.types import Submission  # noqa: E402


def load_problem(folder: Path) -> dict:
    rules = json.loads((folder / "rules.json").read_text(encoding="utf-8"))
    tests = json.loads((folder / "testcases.json").read_text(encoding="utf-8"))
    ref = folder / "reference.c"
    return {"rules": rules, "tests": tests, "title": rules.get("problem", folder.name),
            "reference": ref.read_text(encoding="utf-8") if ref.exists() else None}


def grade_file(problem: dict, path: Path, corpus: list[Path], use_reference: bool) -> dict:
    source = path.read_text(encoding="utf-8")
    sub = Submission(
        source=source, rules=problem["rules"], tests=problem["tests"], assignment_id="CLI",
        title=problem["title"], name=path.stem, roll_number=path.stem.upper()[:32],
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        rules_sha256=policy.rules_hash(problem["rules"]),
        reference_source=problem["reference"] if use_reference else None,
        corpus=[{"label": p.name, "kind": "submission", "source": p.read_text(encoding="utf-8")}
                for p in corpus if p.resolve() != path.resolve()],
    )
    return grader.grade(sub, on_stage=lambda stage, msg: print(f"  [{stage}] {msg}", file=sys.stderr))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem", type=Path, help="folder with rules.json and testcases.json")
    ap.add_argument("files", nargs="*", type=Path, help=".c files to grade")
    ap.add_argument("--all", action="store_true", help="grade every .c file in <problem>/submissions")
    ap.add_argument("--out", type=Path, help="folder for the reports (default <problem>/reports)")
    ap.add_argument("--no-reference", action="store_true", help="ignore reference.c")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    problem = load_problem(args.problem)
    files = sorted((args.problem / "submissions").glob("*.c")) if args.all else args.files
    if not files:
        ap.error("give .c files or --all")
    out_dir = args.out or args.problem / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus = sorted((args.problem / "submissions").glob("*.c")) if args.all else []
    summary = []
    for f in files:
        print(f"Grading {f} ...", file=sys.stderr)
        try:
            res = grade_file(problem, f, corpus, not args.no_reference)
        except grader.GradingError as e:
            print(f"  cannot grade: {e}", file=sys.stderr)
            return 2
        (out_dir / f"{f.stem}.json").write_text(json.dumps(res["report"], indent=2), encoding="utf-8")
        (out_dir / f"{f.stem}.txt").write_text(res["text"], encoding="utf-8")
        rep = res["report"]
        summary.append((f.name, rep["grade"], ",".join(rep["flags"])))
        print(f"  grade {rep['grade']:.1f}  flags: {', '.join(rep['flags']) or '-'}", file=sys.stderr)
    print(f"\n{'file':<22}{'grade':>8}  flags")
    for name, g, flags in summary:
        print(f"{name:<22}{g:>8.1f}  {flags or '-'}")
    print(f"\nReports written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
