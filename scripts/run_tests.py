#!/usr/bin/env python3
"""Run the test suite with every test file isolated in its own process.

Why this exists
---------------
The GUI tests share a single ``QApplication`` and never dispose the top-level
widgets they build (``MainWindow``, dialogs, ...). In this PySide6 build the
widgets cannot be safely reclaimed mid-run: Python GC can't collect them (they
are pinned by app-level event filters and signal-connected bound methods), and
explicitly destroying the pyqtgraph-backed windows segfaults the interpreter.
So they accumulate across the whole session and ``apply_theme``'s app-wide
``setStyleSheet`` re-polish grows pathologically slow — minutes late in the run,
and an on-screen hang on Windows. See ``GUI_TEST_PERF_REPORT.md``.

Running each file in a fresh subprocess caps the live-widget count at a single
file's worth (each file in isolation is fast), so the suite stays quick on every
platform without deleting a single widget. Files run in a bounded parallel pool,
which typically makes the whole run faster than the old in-process suite too.

Usage
-----
    python scripts/run_tests.py                 # full suite, files isolated
    python scripts/run_tests.py -q -x           # extra args forwarded to pytest
    STARPOST_TEST_JOBS=4 python scripts/run_tests.py   # cap parallelism

Every argument is forwarded to each per-file ``pytest`` invocation. To run a
single file you can also just use pytest directly (already one process):

    python -m pytest tests/test_store.py

Set ``QT_QPA_PLATFORM=offscreen`` in the environment on a headless machine; it
is inherited by every subprocess.
"""
from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"

# pytest exit codes: 0 = all passed, 5 = no tests collected (fine for an
# all-skipped file). Everything else is a real failure.
_OK_CODES = frozenset({0, 5})


def _run_file(path: Path, pytest_args: list[str]) -> tuple[Path, int, str, float]:
    """Run one test file in its own pytest process; return (path, rc, output, secs)."""
    cmd = [sys.executable, "-m", "pytest", str(path), *pytest_args]
    start = time.monotonic()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return path, proc.returncode, proc.stdout + proc.stderr, time.monotonic() - start


def _summary_line(output: str) -> str:
    """pytest's 'N passed ...' summary line (Qt may print stderr noise after it)."""
    lines = [ln.strip().strip("=").strip() for ln in output.splitlines() if ln.strip()]
    for line in reversed(lines):
        if any(w in line for w in ("passed", "failed", "error", "skipped", "no tests")):
            return line
    return lines[-1] if lines else "(no output)"


def main(argv: list[str] | None = None) -> int:
    pytest_args = list(sys.argv[1:] if argv is None else argv)
    files = sorted(TESTS_DIR.glob("test_*.py"))
    if not files:
        print(f"no test files found under {TESTS_DIR}", file=sys.stderr)
        return 1

    jobs = int(os.environ.get("STARPOST_TEST_JOBS", os.cpu_count() or 4))
    jobs = max(1, min(jobs, len(files)))
    print(f"Running {len(files)} test files, each isolated, {jobs} at a time\n")

    failures: list[tuple[Path, int, str]] = []
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_run_file, f, pytest_args): f for f in files}
        for fut in concurrent.futures.as_completed(futures):
            path, rc, output, secs = fut.result()
            ok = rc in _OK_CODES
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {path.name:<28} {secs:5.1f}s  {_summary_line(output)}")
            if not ok:
                failures.append((path, rc, output))

    total = time.monotonic() - started
    print(f"\nTotal wall time: {total:.1f}s")
    if failures:
        for path, rc, output in failures:
            print(f"\n{'=' * 70}\nFAILED: {path.name} (exit {rc})\n{'=' * 70}")
            print(output)
        print(f"\n{len(failures)} file(s) failed.")
        return 1
    print("All files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
