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
"""
import gc


def pytest_configure(config):
    gc.disable()
