# Implementation progress

Status of the work that turned the October 29 progress-report state into a complete grader.
Read this first when continuing the work.

## Audit of the starting point (commit 4ac06f1)

| Area | State found | Action |
|---|---|---|
| Assignment creation, policy validation (weights) | working | kept; validation extended (analyzers, flags, limits, input_spec) |
| LLM test generation graph (`agents/testgen.py`) | working | unchanged |
| Review / accept / publish, immutability | working | unchanged; Home link moved out of `<head>` |
| Student page, submission storage, history folder | working | kept; results view, downloads, history, "Check my results" added |
| `sandbox/runner.py`, `server/sandbox.py` | working prototype, never called | extended to protocol 2 (multiple builds, wrappers, repeats, cppcheck, per-run rusage) and pluggable backends |
| `server/jobs.py` | placeholder receipt "NOT GRADED" | replaced by a grading queue around the LangGraph grader |
| Grading graph, analyzers, scoring, reports | missing | built (`agents/grader.py`, `grading/`) |
| `requirements.txt` | UTF-16 `pip freeze`, editable path to `d:\autograder` | rewritten |
| `.env.example`, `docker-compose.yml` | empty | written |
| `tests/` | template tests importing functions that do not exist | removed, new suite written |
| `src/simple_agent/graph.py` | hard-coded `D:\Autograder\.env` | relative path |

## Files

New: `backend/agents/grader.py`, `backend/grading/{__init__,types,compare,inputspec,execution,first_pass,policy,scoring,report}.py`,
`backend/grading/analyzers/{__init__,common,correctness,edge_cases,complexity,compiler,structure,memory,readability,originality}.py`,
`frontend/submissions.{html,js}`, `samples/**`, `scripts/{grade,seed_demo}.py`,
`backend/tests/unit_tests/{test_policy_and_scoring,test_analyzer_logic,test_storage}.py`,
`backend/tests/integration_tests/{test_sandbox,test_grading_samples,test_api}.py`, `PROGRESS.md`.

Modified: `sandbox/runner.py`, `sandbox/Dockerfile`, `backend/server/{sandbox,storage,jobs,main}.py`, `backend/try_sandbox.py`,
`frontend/{student.html,student.js,teacher.html,app.js,review.html,style.css}`, `backend/tests/conftest.py`,
`backend/langgraph.json`, `backend/pyproject.toml`, `backend/src/simple_agent/graph.py`, `requirements.txt`,
`backend/requirements.txt`, `.env.example`, `.gitignore`, `docker-compose.yml`, `README.md`.

Removed from git: `backend/.langgraph_api/*.pckl`, `__pycache__/*.pyc`, the broken template tests.

## Verification environment

Windows 11, Python 3.14, no Docker, no Ollama. Execution was verified with the `wsl` backend
(Ubuntu 24.04 in WSL2, gcc 13.3, ASan/UBSan working, valgrind and cppcheck not installed). The Docker
command line is covered by a unit test, and the missing-Docker path is tested, but the Docker backend
itself has not been run on this machine.

## Test results (2026-11-03, `AUTOGRADER_SANDBOX=wsl`)

`python -m pytest -q` in `backend/`: **108 passed, 1 skipped** (the network-isolation test, which
needs the Docker backend), 4 min 8 s. The first run found one real defect (per-test CPU times were
part of the deterministic correctness evidence); it was fixed and the suite re-run.

Browser check (in-app browser, seeded demo data): student submits `add.c`, sees progress, grade
78.4 with the INT_MAX + 1 counter-test, downloads report.txt; teacher Submissions page shows the
report, flags, attempts and Regrade. No console errors.

Sample grades (`scripts/grade.py --all`, reports in `samples/*/reports/`):

| add_two_integers | grade | | sort_numbers | grade |
|---|---|---|---|---|
| correct.c | 86.0 | | correct.c | 91.0 |
| overflow.c (the brief's add.c) | 78.4 | | slow_bubble.c (O(n^2)) | 75.6 |
| warnings.c | 82.4 | | similar_a.c (flagged) | 91.0 |
| memory_error.c | 77.4 | | similar_b.c (flagged) | 91.0 |
| wrong_output.c | 56.0 | | | |
| segfault.c | 38.0 | | | |
| infinite_loop.c | 29.0 | | | |
| compile_error.c | 19.0 | | | |

Every grade here lacks the readability share (no Ollama) and 40 % of structure (no cppcheck in WSL);
both are listed as unmeasured/partial in the reports.

## Remaining / not verified here
- Build the image and run the suite with `AUTOGRADER_SANDBOX=docker` on a machine with Docker
  (also runs the network-isolation test, and exercises valgrind and cppcheck, which the image contains)
- Readability with a real Ollama model (the analyzer is tested with a stand-in model)
- PDF problem statements (item 13 of the progress report) are not supported; statements are text
- No authentication (documented limitation)
