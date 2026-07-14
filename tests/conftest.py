"""Suite-wide test configuration.

The GUI tests deliberately never dispose their top-level widgets (see
CLAUDE.md): in this PySide6 build, destroying a window mid-run segfaults.
Plain refcounting can't free them anyway (window ↔ event-filter ↔
bound-method cycles), but the *cyclic* collector can — and it fires at
allocation-driven, unpredictable moments, sometimes while Qt is inside
``QTimerInfoList::activateTimers`` processing another window's zero-delay
startup timers. Collecting a closed window right there tears its C++ widgets
(and their registered timers) out from under the running iteration —
an intermittent SIGSEGV that hits hardest late in ``test_main_window.py``,
once dozens of windows are collectable.

Disabling the cyclic collector pins every widget for the process lifetime,
which is exactly the suite's intended model: ``scripts/run_tests.py`` gives
each file a fresh, short-lived process, so nothing accumulates beyond one
file's worth of widgets.

``pytest_configure`` also gives every session a **private ``basetemp``**
instead of pytest's shared per-user temp root (``pytest-of-<user>``). The
shared root is a hazard here: ``run_tests.py`` runs many pytest sessions in
parallel, and they race each other in that directory's numbered-dir cleanup
and ``pytest-current`` symlink swap. On Windows the race (or a sandboxed
run with a different file owner) strands an undeletable ``pytest-current``
reparse point, after which *every* later session — parallel or not — dies
with ``PermissionError`` in its session-finish cleanup. A unique, throwaway
basetemp per session bypasses the numbered-dir/symlink machinery entirely.
The directory is removed when the session passes and kept for inspection
when it fails (mirroring pytest's own retention behaviour).
"""
import gc
import shutil
import tempfile
from pathlib import Path


def pytest_configure(config):
    gc.disable()
    if config.option.basetemp is None:
        config.option.basetemp = Path(tempfile.mkdtemp(prefix="starpost-pytest-"))
        config._starpost_basetemp = config.option.basetemp


def pytest_sessionfinish(session, exitstatus):
    if exitstatus == 0:
        tmp = getattr(session.config, "_starpost_basetemp", None)
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
