# Express batch dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the toolbar's single **Run batch** button into a hover dropdown offering **Full Batch** (the existing wizard) and **Express batch** (a lean new dialog that runs a saved batch profile quickly).

**Architecture:** Extend `BatchProfile` to store the three report-output settings. Extract the full dialog's Source tab into a reusable `SourcePanel(QWidget)` and its run-execution tail into a module-level `execute_batch(...)`. Build a new `ExpressBatchDialog` on those shared units. Replace the toolbar action with a hover-menu `QToolButton`.

**Tech Stack:** Python 3.11, PySide6 (Qt Widgets), pytest.

## Global Constraints

- ruff line-length 100, target py311. Run `.venv/bin/ruff check <files>` before each commit; introduce no new errors. (Two pre-existing F401s in `tests/test_main_window.py` at lines ~197 and ~1695 predate this work — leave them.)
- GUI tests instantiate a real `QApplication`; run headless with `QT_QPA_PLATFORM=offscreen`. Use `.venv/bin/python -m pytest`.
- Tests that touch config/cache must isolate per-user state — reuse each test file's existing `autouse` fixture that monkeypatches `paths.platformdirs.user_config_dir`/`user_cache_dir` to a `tmp_path`. Batch profiles live under the config dir, so this isolates them.
- Brand is **StarPost** in prose; `starpost` only for package/path identifiers.
- Keep heavy imports off the module top level where the codebase already does (e.g. `from starpost.batch.run import ...` is imported lazily inside methods).
- Commit after every task. Log the user-facing change in `CHANGELOG.md`, newest first.

## File Structure

- `src/starpost/core/settings.py` — `BatchProfile` gains `report_format` / `include_units` / `combined_report`.
- `src/starpost/gui/views/batch_run_dialog.py` — add `SourcePanel(QWidget)` and module-level `execute_batch(...)`; the full dialog embeds the panel and delegates its run tail; `_build_profile`/`_apply_profile` handle the three new fields.
- `src/starpost/gui/widgets.py` — add `HoverMenuToolButton(QToolButton)`.
- `src/starpost/gui/views/express_batch_dialog.py` — **new**: `ExpressBatchDialog(QDialog)`.
- `src/starpost/gui/main_window.py` — toolbar hover dropdown + `_run_express_batch`.
- `tests/test_settings.py`, `tests/test_main_window.py` — tests.
- `README.md`, `CHANGELOG.md`, `src/starpost/__init__.py` — docs + version.

---

### Task 1: BatchProfile stores the three report-output settings

**Files:**
- Modify: `src/starpost/core/settings.py` (`BatchProfile` dataclass ~394-430)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `BatchProfile(name, selected_reports, saved_plots, saved_scenes, report_format="CSV", include_units=True, combined_report=True)` — three new fields, round-tripped through `save()`/`load()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py` (it already has an `autouse` fixture isolating config to `tmp_path`):

```python
def test_batch_profile_round_trips_report_settings():
    import starpost.core.settings as cfg

    cfg.BatchProfile(
        name="Nightly", selected_reports=["Drag"],
        report_format="XLSX", include_units=False, combined_report=False,
    ).save()
    loaded = cfg.BatchProfile.load("Nightly")
    assert loaded.report_format == "XLSX"
    assert loaded.include_units is False
    assert loaded.combined_report is False


def test_batch_profile_defaults_when_keys_absent():
    import starpost.core.settings as cfg
    from starpost.utils.paths import batch_profiles_dir

    d = batch_profiles_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "Old.yaml").write_text("name: Old\nselected_reports:\n- A\n", encoding="utf-8")
    loaded = cfg.BatchProfile.load("Old")
    assert loaded.report_format == "CSV"
    assert loaded.include_units is True
    assert loaded.combined_report is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_settings.py -k batch_profile -v`
Expected: FAIL — `TypeError` on the unexpected `report_format` keyword.

- [ ] **Step 3: Add the fields**

In `src/starpost/core/settings.py`, in the `BatchProfile` dataclass, after the `saved_scenes` field (line 402) add:

```python
    report_format: str = "CSV"       # CSV | TSV | XLSX | ODS
    include_units: bool = True
    combined_report: bool = True
```

- [ ] **Step 4: Persist them in `save()`**

In `BatchProfile.save()`, extend the `data` dict (after the `"saved_scenes"` entry, line 412) with:

```python
            "report_format": self.report_format,
            "include_units": self.include_units,
            "combined_report": self.combined_report,
```

- [ ] **Step 5: Read them in `load()`**

In `BatchProfile.load()`, extend the `cls(...)` call (after `saved_scenes=...`, line 429) with:

```python
            report_format=str(data.get("report_format", "CSV")),
            include_units=bool(data.get("include_units", True)),
            combined_report=bool(data.get("combined_report", True)),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_settings.py -k batch_profile -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check src/starpost/core/settings.py tests/test_settings.py
git add src/starpost/core/settings.py tests/test_settings.py
git commit -m "Store report format/units/combined in BatchProfile"
```

---

### Task 2: Full dialog captures and applies the three settings

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (`_build_profile` ~663-675, `_apply_profile` ~688-699)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `BatchProfile.report_format/include_units/combined_report` (Task 1); existing widgets `self._report_format` (QComboBox, items CSV/TSV/XLSX/ODS), `self._report_include_units` (QCheckBox), `self._report_combined` (QCheckBox).
- Produces: profiles saved from the full dialog now carry the three settings; loading a profile restores them.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py` (near the other `test_batch_run_dialog_*` tests; the module already has the `isolated_paths` and `app` fixtures):

```python
def test_batch_run_dialog_profile_captures_report_settings(app):
    import starpost.gui.views.batch_run_dialog as brd
    from starpost.core.settings import BatchProfile

    dlg = brd.BatchRunDialog(None, report_names=["Drag"])
    dlg._report_format.setCurrentText("ODS")
    dlg._report_include_units.setChecked(False)
    dlg._report_combined.setChecked(False)

    prof = dlg._build_profile("P")
    assert prof.report_format == "ODS"
    assert prof.include_units is False
    assert prof.combined_report is False

    dlg._apply_profile(
        BatchProfile(name="Q", report_format="XLSX",
                     include_units=True, combined_report=True)
    )
    assert dlg._report_format.currentText() == "XLSX"
    assert dlg._report_include_units.isChecked() is True
    assert dlg._report_combined.isChecked() is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py::test_batch_run_dialog_profile_captures_report_settings -v`
Expected: FAIL — `prof.report_format` is the default `"CSV"`, not `"ODS"`.

- [ ] **Step 3: Capture the settings in `_build_profile`**

In `_build_profile` (the `return BatchProfile(...)` at line 666), add three arguments after `saved_scenes=self._saved_entries(self._saved_scenes),`:

```python
            report_format=self._report_format.currentText(),
            include_units=self._report_include_units.isChecked(),
            combined_report=self._report_combined.isChecked(),
```

- [ ] **Step 4: Apply the settings in `_apply_profile`**

In `_apply_profile`, after the `self._restore_saved(self._saved_scenes, profile.saved_scenes)` line (699) add:

```python
        idx = self._report_format.findText(profile.report_format)
        if idx >= 0:
            self._report_format.setCurrentIndex(idx)
        self._report_include_units.setChecked(profile.include_units)
        self._report_combined.setChecked(profile.combined_report)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py::test_batch_run_dialog_profile_captures_report_settings -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check src/starpost/gui/views/batch_run_dialog.py tests/test_main_window.py
git add src/starpost/gui/views/batch_run_dialog.py tests/test_main_window.py
git commit -m "Capture/apply report settings in full batch profiles"
```

---

### Task 3: Extract `SourcePanel` from the full dialog

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (Source tab: `_build_source_tab` 718-776, `_refresh_source_window` 778-800, `_set_all_source` 802-805, `_has_checked_source` 807-812, `_checked_sim_files` 814-821, `_load_files` 952-962, `_load_data_sets` 964-974, `_batch_sources` 1782-1808; wiring in `__init__` 548-576, `_advance` 1760-1779, `_extract_setup_sim` 832; `_run_batch` 1817)
- Test: `tests/test_main_window.py` (new panel test + update existing source tests)

**Interfaces:**
- Consumes: module classes `_CheckableList` (line 110) and `BatchSource` (`from starpost.batch.run import BatchSource`).
- Produces: `SourcePanel(QWidget)` with:
  - `__init__(self, parent=None, *, data_sets=None, results=None, show_similar_format=True)`
  - attributes `self._source_input` (QComboBox: data `"sim"`/`"data"`), `self._source_window` (`_CheckableList`), `self._has_similar_format` (QCheckBox), `self._sim_files: list[Path]`, `self._data_sets: list[str]`, `self._results: list`
  - `sources() -> list[BatchSource]` (checked, resolved — was `_batch_sources`)
  - `has_checked() -> bool` (was `_has_checked_source`)
  - `checked_sim_files() -> list[Path]`
  - `current_mode() -> str` (returns `self._source_input.currentData()`)

This is a **verbatim move** of the listed methods into the new class, changing their `self._…` source-state references (`_sim_files`, `_data_sets`, `_results`, `_source_input`, `_source_window`, `_has_similar_format`, `_load_file_btn`, `_load_dataset_btn`) to the panel's own attributes, plus renames (`_has_checked_source`→`has_checked`, `_batch_sources`→`sources`). Do not change their logic.

- [ ] **Step 1: Write the failing test for the panel**

Add to `tests/test_main_window.py`:

```python
def test_source_panel_resolves_checked_sources(app):
    import starpost.gui.views.batch_run_dialog as brd

    result = _sim_result_with_data()  # sim_name "caseA", existing test helper
    panel = brd.SourcePanel(
        None, data_sets=["caseA"], results=[result], show_similar_format=False
    )
    panel._source_input.setCurrentIndex(panel._source_input.findData("data"))
    assert panel._source_window.count() == 1
    panel._source_window.item(0).setCheckState(Qt.CheckState.Checked)

    srcs = panel.sources()
    assert [s.name for s in srcs] == ["caseA"]
    assert srcs[0].result is result
    assert panel.has_checked() is True


def test_source_panel_hides_similar_format_when_disabled(app):
    import starpost.gui.views.batch_run_dialog as brd

    panel = brd.SourcePanel(None, show_similar_format=False)
    assert panel._has_similar_format.isVisible() is False
```

(`Qt` is already imported at the top of `tests/test_main_window.py`; if not, add `from PySide6.QtCore import Qt`.)

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -k source_panel -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'SourcePanel'`.

- [ ] **Step 3: Create the `SourcePanel` class**

Add a new `class SourcePanel(QWidget):` to `batch_run_dialog.py` (place it just before `class BatchRunDialog` at line 540). Move the bodies of `_build_source_tab`, `_refresh_source_window`, `_set_all_source`, `_has_checked_source`(→`has_checked`), `_checked_sim_files`, `_load_files`, `_load_data_sets`, and `_batch_sources`(→`sources`) into it. Key points:
- `__init__` stores `self._data_sets = list(data_sets or [])`, `self._results = list(results or [])`, `self._sim_files: list[Path] = []`, `self._show_similar_format = show_similar_format`, then builds the same two-column layout `_build_source_tab` built and sets it as the panel's own layout (`QHBoxLayout(self)`). Only add `self._has_similar_format` to the layout when `show_similar_format` is true; when false, still create the checkbox widget but keep it hidden (so `_has_similar_format.isVisible()` is False and `_refresh_source_window`'s `setEnabled` call is harmless).
- `current_mode()` returns `self._source_input.currentData()`.
- `sources()` is the former `_batch_sources` body unchanged (it already does `from starpost.batch.run import BatchSource` and reads `self._results`).
- Add `from PySide6.QtWidgets import QWidget` to the file's imports if not present (check the existing import block).

- [ ] **Step 4: Make `BatchRunDialog` embed the panel**

In `BatchRunDialog.__init__`:
- Remove `self._sim_files`, and pass source state to the panel. Replace the `self._tabs.addTab(self._build_source_tab(), "Source")` line (569) with:

```python
        self._source_panel = SourcePanel(
            data_sets=self._data_sets, results=self._results,
            show_similar_format=True,
        )
        self._tabs.addTab(self._source_panel, "Source")
```

- Delete the now-moved methods (`_build_source_tab`, `_refresh_source_window`, `_set_all_source`, `_has_checked_source`, `_checked_sim_files`, `_load_files`, `_load_data_sets`, `_batch_sources`) from `BatchRunDialog`.
- In `_advance` (1765-1773) change `self._has_checked_source()` → `self._source_panel.has_checked()`, `self._source_input.currentData()` → `self._source_panel.current_mode()`, `self._has_similar_format.isChecked()` → `self._source_panel._has_similar_format.isChecked()`.
- In `_extract_setup_sim` (832) change `self._checked_sim_files()` → `self._source_panel.checked_sim_files()`.
- In `_run_batch` (1817) change `self._batch_sources()` → `self._source_panel.sources()`.

- [ ] **Step 5: Update the existing source tests to reach through the panel**

In `tests/test_main_window.py`, in the source-related tests, replace attribute paths on the dialog instance `dlg`:
- `dlg._source_input` → `dlg._source_panel._source_input`
- `dlg._source_window` → `dlg._source_panel._source_window`
- `dlg._has_similar_format` → `dlg._source_panel._has_similar_format`
- `dlg._load_file_btn` / `dlg._load_dataset_btn` → `dlg._source_panel._load_file_btn` / `dlg._source_panel._load_dataset_btn`

Affected tests (by name): `test_batch_run_dialog_sequential_navigation`, `test_batch_run_dialog_source_window`, `test_batch_run_dialog_source_buttons`, `test_batch_run_dialog_no_source_warns`, `test_batch_run_dialog_similar_format_disabled_in_data_mode`, `test_batch_run_dialog_similar_format_extracts_first`, `test_batch_run_dialog_source_row_click_toggles`. Search these for the four attribute prefixes above and update each occurrence.

- [ ] **Step 6: Run the panel test and the full source suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -k "source or similar or sequential_navigation" -v`
Expected: PASS (new panel tests + all updated source tests).

- [ ] **Step 7: Run the whole dialog test file (guard against a missed reference)**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: all pass.

- [ ] **Step 8: Lint and commit**

```bash
.venv/bin/ruff check src/starpost/gui/views/batch_run_dialog.py tests/test_main_window.py
git add src/starpost/gui/views/batch_run_dialog.py tests/test_main_window.py
git commit -m "Extract SourcePanel from the run-batch dialog"
```

---

### Task 4: Extract `execute_batch` and delegate the full dialog's run

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (`_run_batch` tail 1864-1902, `_on_batch_progress` 1904-1909, `_render_plot_for_worker` 1911-1922, and `__init__` state 562-563)

**Interfaces:**
- Consumes: module class `_BatchRunWorker` (line 490); `from starpost.batch.run import render_saved_plot`.
- Produces: module-level `execute_batch(parent, config, settings, runner, dest) -> str | None` — runs `config` behind a modal progress dialog on a worker thread, rendering saved plots on the GUI thread; returns the worker's error string, or `None` on success.

> Note: the design sketched `execute_batch(parent, config, settings, runner, plot_render_cb) -> Path | None`. This drops the unused `plot_render_cb` (both callers render identically via `render_saved_plot`, so the function calls it directly — DRY/YAGNI) and returns the error string instead of `Path` (the caller already holds `dest`). Behaviour is unchanged.

- [ ] **Step 1: Add the `execute_batch` function**

Add this module-level function to `batch_run_dialog.py` (place it just after the `_BatchRunWorker` class, ~line 538):

```python
def execute_batch(parent, config, settings, runner, dest) -> str | None:
    """Run ``config`` behind a modal progress dialog on a worker thread, rendering
    saved plots back on the GUI thread (Qt widgets can't be built off it). Returns
    the worker's error string, or None on success. Blocks (a local event loop)
    while the modal progress dialog stays painted."""
    from starpost.batch.run import render_saved_plot

    busy = QProgressDialog("Preparing…", "", 0, 100, parent)
    busy.setWindowTitle("Run batch")
    busy.setCancelButton(None)
    busy.setWindowModality(Qt.WindowModality.WindowModal)
    busy.setMinimumDuration(0)
    busy.setAutoClose(False)
    busy.setAutoReset(False)
    busy.setValue(0)

    thread = QThread(parent)
    worker = _BatchRunWorker(config, settings, runner, dest)
    worker.moveToThread(thread)

    def on_progress(fraction: float, message: str) -> None:
        busy.setValue(round(fraction * 100))
        busy.setLabelText(message)

    def on_render(result, plot_data, path) -> None:
        rendered = False
        try:
            rendered = render_saved_plot(result, plot_data, settings, path)
        finally:
            worker.finish_render(rendered)

    worker.progress.connect(on_progress)             # queued → GUI
    worker.render_request.connect(on_render)         # queued → GUI
    loop = QEventLoop()
    worker.done.connect(loop.quit)                   # queued → GUI
    thread.started.connect(worker.run)
    thread.start()
    busy.show()
    loop.exec()
    thread.quit()
    thread.wait()
    busy.close()
    return worker.error
```

- [ ] **Step 2: Delegate `_run_batch` to it**

In `BatchRunDialog._run_batch`, replace everything from `runner = StarRunner(...)` (1864) through `self.accept()` (1902) with:

```python
        runner = StarRunner(self._settings) if self._settings else None
        error = execute_batch(self, config, self._settings, runner, dest)
        if error is not None:
            QMessageBox.critical(self, "Run batch failed", error)
            return
        QMessageBox.information(self, "Run batch", f"Batch written to:\n{dest}")
        self.accept()
```

- [ ] **Step 3: Remove the now-dead handlers and state**

Delete `BatchRunDialog._on_batch_progress` (1904-1909) and `BatchRunDialog._render_plot_for_worker` (1911-1922). In `__init__`, delete the two lines `self._batch_worker: _BatchRunWorker | None = None` (562) and `self._busy: QProgressDialog | None = None` (563).

- [ ] **Step 4: Confirm no stale references remain**

Run: `grep -n "_batch_worker\|self._busy\|_on_batch_progress\|_render_plot_for_worker" src/starpost/gui/views/batch_run_dialog.py`
Expected: no output (all references removed).

- [ ] **Step 5: Run the full dialog test file**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: all pass (behaviour unchanged; the run tail is now shared).

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check src/starpost/gui/views/batch_run_dialog.py
git add src/starpost/gui/views/batch_run_dialog.py
git commit -m "Extract execute_batch helper shared by batch dialogs"
```

---

### Task 5: New `ExpressBatchDialog`

**Files:**
- Create: `src/starpost/gui/views/express_batch_dialog.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `SourcePanel`, `execute_batch` (Tasks 3-4); `BatchProfile`, `list_batch_profiles` (`starpost.core.settings`); `BatchConfig` (`starpost.batch.run`); `StarRunner` (`starpost.core.starccm_runner`).
- Produces: `ExpressBatchDialog(parent=None, *, data_sets=None, results=None, settings=None)` with attributes `self._profile_box` (QComboBox), `self._source_panel` (SourcePanel), `self._export_format` (QComboBox, data `"zip"`/`"7z"`), `self._include_dataset_csv` (QCheckBox), `self._run_btn` (QPushButton), and method `self._run()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_window.py`:

```python
def test_express_dialog_run_disabled_without_profile(app):
    import starpost.gui.views.express_batch_dialog as ebd

    dlg = ebd.ExpressBatchDialog(None, data_sets=[], results=[], settings=None)
    assert dlg._run_btn.isEnabled() is False


def test_express_dialog_builds_config_from_profile(app, monkeypatch, tmp_path):
    import starpost.gui.views.express_batch_dialog as ebd
    from starpost.core.settings import BatchProfile

    BatchProfile(
        name="Nightly", selected_reports=["Drag"],
        report_format="XLSX", include_units=False, combined_report=False,
    ).save()

    result = _sim_result_with_data()  # sim_name "caseA"
    dlg = ebd.ExpressBatchDialog(
        None, data_sets=["caseA"], results=[result], settings=None
    )
    dlg._profile_box.setCurrentText("Nightly")
    assert dlg._run_btn.isEnabled() is True

    # Check a source.
    panel = dlg._source_panel
    panel._source_input.setCurrentIndex(panel._source_input.findData("data"))
    panel._source_window.item(0).setCheckState(Qt.CheckState.Checked)
    dlg._export_format.setCurrentIndex(dlg._export_format.findData("7z"))
    dlg._include_dataset_csv.setChecked(True)

    captured = {}
    monkeypatch.setattr(ebd, "execute_batch",
                        lambda *a, **k: captured.setdefault("cfg", a[1]) and None)
    monkeypatch.setattr(ebd.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    monkeypatch.setattr(ebd.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    dlg._run()

    cfg = captured["cfg"]
    assert cfg.reports == {"Drag"}
    assert cfg.report_format == "xlsx"
    assert cfg.include_units is False
    assert cfg.combined_report is False
    assert cfg.archive_format == "7z"
    assert cfg.include_dataset_csv is True
    assert [s.name for s in cfg.sources] == ["caseA"]
```

(`monkeypatch.setattr(ebd, "execute_batch", ...)` requires `execute_batch` to be imported by name into the express module — Step 2 imports it as `from starpost.gui.views.batch_run_dialog import SourcePanel, execute_batch`. The lambda captures the 2nd positional arg, which is `config`.)

- [ ] **Step 2: Create the dialog**

Create `src/starpost/gui/views/express_batch_dialog.py`:

```python
"""Express batch: run a saved batch profile with minimal clicks.

For users who already have a batch profile. The profile supplies the reports,
plots, scenes and report-output settings; the user only picks the sources and the
archive options, then runs. Reuses the full dialog's SourcePanel and the shared
execute_batch runner."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from starpost.core.settings import BatchProfile, list_batch_profiles
from starpost.core.starccm_runner import StarRunner
from starpost.gui.views.batch_run_dialog import SourcePanel, execute_batch


class ExpressBatchDialog(QDialog):
    def __init__(self, parent=None, *, data_sets=None, results=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Express batch")
        self.resize(620, 420)
        self._settings = settings

        # Batch profile selector (front and centre).
        self._profile_box = QComboBox()
        self._profile_box.addItems(list_batch_profiles())
        self._profile_box.setCurrentIndex(-1)  # force an explicit choice
        self._profile_box.currentIndexChanged.connect(self._sync_run_enabled)
        empty_note = QLabel(
            "No batch profiles yet — create one in Full Batch first."
        )
        empty_note.setVisible(self._profile_box.count() == 0)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Batch profile"))
        profile_row.addWidget(self._profile_box, 1)

        # Sources (no "Has similar format" — the profile already defines outputs).
        self._source_panel = SourcePanel(
            data_sets=data_sets, results=results, show_similar_format=False
        )

        # Export options (mirrors the full Summary tab).
        self._export_format = QComboBox()
        self._export_format.addItem("ZIP", "zip")
        self._export_format.addItem("7Z", "7z")
        self._include_dataset_csv = QCheckBox("Include dataset .csv")
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("Archive format"))
        export_row.addWidget(self._export_format)
        export_row.addWidget(self._include_dataset_csv)
        export_row.addStretch(1)

        self._run_btn = QPushButton("Batch run")
        self._run_btn.clicked.connect(self._run)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._run_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(profile_row)
        layout.addWidget(empty_note)
        layout.addWidget(self._source_panel, 1)
        layout.addLayout(export_row)
        layout.addLayout(button_row)

        self._sync_run_enabled()

    def _sync_run_enabled(self, *_args) -> None:
        """The run button is live only once a profile is chosen."""
        self._run_btn.setEnabled(bool(self._profile_box.currentText()))

    def _run(self) -> None:
        from starpost.batch.run import BatchConfig

        name = self._profile_box.currentText()
        if not name:
            return
        profile = BatchProfile.load(name)

        sources = self._source_panel.sources()
        if not sources:
            QMessageBox.warning(self, "Express batch", "No data selected.")
            return

        reports = set(profile.selected_reports)
        saved_plots = list(profile.saved_plots)
        saved_scenes = list(profile.saved_scenes)
        include_dataset_csv = self._include_dataset_csv.isChecked()
        if not reports and not saved_plots and not saved_scenes and not include_dataset_csv:
            QMessageBox.warning(
                self, "Express batch",
                "Nothing to output — the selected profile is empty.",
            )
            return

        needs_exe = any(s.result is None for s in sources) or (
            bool(saved_scenes) and any(s.sim_file for s in sources)
        )
        if needs_exe and (self._settings is None or not self._settings.starccm_path):
            QMessageBox.warning(
                self, "Express batch",
                "Set the STAR-CCM+ executable path in Settings first.",
            )
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not out_dir:
            return
        fmt = self._export_format.currentData()
        dest = Path(out_dir) / f"starpost_batch_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
        config = BatchConfig(
            sources=sources,
            reports=reports,
            report_format=profile.report_format.lower(),
            include_units=profile.include_units,
            saved_plots=saved_plots,
            saved_scenes=saved_scenes,
            include_dataset_csv=include_dataset_csv,
            combined_report=profile.combined_report,
            archive_format=fmt,
        )
        runner = StarRunner(self._settings) if self._settings else None
        error = execute_batch(self, config, self._settings, runner, dest)
        if error is not None:
            QMessageBox.critical(self, "Express batch failed", error)
            return
        QMessageBox.information(self, "Express batch", f"Batch written to:\n{dest}")
        self.accept()
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -k express -v`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
.venv/bin/ruff check src/starpost/gui/views/express_batch_dialog.py tests/test_main_window.py
git add src/starpost/gui/views/express_batch_dialog.py tests/test_main_window.py
git commit -m "Add ExpressBatchDialog: run a saved batch profile fast"
```

---

### Task 6: Toolbar hover dropdown

**Files:**
- Modify: `src/starpost/gui/widgets.py` (add `HoverMenuToolButton`)
- Modify: `src/starpost/gui/main_window.py` (`_build_toolbar` 314-326, disable/enable 494 & 502, add `_run_express_batch`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `HoverMenuToolButton`; `ExpressBatchDialog` (Task 5).
- Produces: toolbar exposes a `QToolButton` (`self._run_button`) whose menu has actions **Full Batch** → `_run_batch` and **Express batch** → `_run_express_batch`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py`:

```python
def test_toolbar_run_batch_menu_has_full_and_express(app, monkeypatch):
    import starpost.gui.main_window as mw

    win = mw.MainWindow(Settings())
    labels = [a.text() for a in win._run_button.menu().actions()]
    assert labels == ["Full Batch", "Express batch"]

    opened = {}
    import starpost.gui.views.express_batch_dialog as ebd

    class _Fake:
        def __init__(self, *a, **k): opened["express"] = True
        def exec(self): return 0

    monkeypatch.setattr(ebd, "ExpressBatchDialog", _Fake)
    win._run_express_batch()
    assert opened.get("express") is True
```

(`Settings` is already imported in `tests/test_main_window.py`.)

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py::test_toolbar_run_batch_menu_has_full_and_express -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_run_button'`.

- [ ] **Step 3: Add `HoverMenuToolButton`**

In `src/starpost/gui/widgets.py`, add (put `QToolButton` on its import from `PySide6.QtWidgets` if not already there):

```python
class HoverMenuToolButton(QToolButton):
    """A toolbar button whose attached menu drops on hover (mouse-enter) as well
    as on click. Qt has no native hover-popup mode, so we pop the menu from
    ``enterEvent``; the guard stops it re-opening while it is already showing."""

    def enterEvent(self, event):
        super().enterEvent(event)
        menu = self.menu()
        if menu is not None and not menu.isVisible():
            self.showMenu()
```

- [ ] **Step 4: Wire the toolbar**

In `src/starpost/gui/main_window.py`:
- Add to the `PySide6.QtWidgets` import block: `QMenu`, `QToolButton`.
- Add to the widgets import: `from starpost.gui.widgets import HoverMenuToolButton, UniformTabBar`.
- Replace lines 318-321 (the `self._run_action = tb.addAction("Run batch", ...)` and its `setToolTip`) with:

```python
        self._run_button = HoverMenuToolButton()
        self._run_button.setText("Run batch")
        self._run_button.setAutoRaise(True)
        self._run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._run_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._run_button.setToolTip(
            "Run a batch export: Full Batch (full wizard) or Express batch "
            "(run a saved profile)"
        )
        run_menu = QMenu(self._run_button)
        run_menu.addAction("Full Batch", self._run_batch)
        run_menu.addAction("Express batch", self._run_express_batch)
        self._run_button.setMenu(run_menu)
        tb.addWidget(self._run_button)
```

(`Qt` is already imported in `main_window.py`.)

- [ ] **Step 5: Update the disable/enable calls**

In `main_window.py`, change `self._run_action.setEnabled(False)` (494) to `self._run_button.setEnabled(False)` and `self._run_action.setEnabled(True)` (502) to `self._run_button.setEnabled(True)`.

- [ ] **Step 6: Add `_run_express_batch`**

In `main_window.py`, add this method right after `_run_batch` (after line 388):

```python
    def _run_express_batch(self) -> None:
        """Open the Express batch dialog — run a saved batch profile quickly."""
        from starpost.gui.views.express_batch_dialog import ExpressBatchDialog

        results = [r for r in self.store.all() if r.error is None]
        data_sets = [r.sim_name for r in results]
        ExpressBatchDialog(
            self, data_sets=data_sets, results=results, settings=self.settings,
        ).exec()
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py::test_toolbar_run_batch_menu_has_full_and_express -v`
Expected: PASS.

- [ ] **Step 8: Lint and commit**

```bash
.venv/bin/ruff check src/starpost/gui/widgets.py src/starpost/gui/main_window.py tests/test_main_window.py
git add src/starpost/gui/widgets.py src/starpost/gui/main_window.py tests/test_main_window.py
git commit -m "Add hover dropdown: Full Batch / Express batch"
```

---

### Task 7: Documentation and version bump

**Files:**
- Modify: `README.md` (Run batch bullet, ~103-108)
- Modify: `CHANGELOG.md` (new top entry)
- Modify: `src/starpost/__init__.py` (`__version__`)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README Run batch bullet**

In `README.md`, at the end of the existing **Run batch** bullet (after "…reloaded as **batch profiles**." around line 107-108), add a sentence:

```
  The toolbar **Run batch** button is a hover dropdown: **Full Batch** opens this
  wizard, while **Express batch** runs an existing batch profile quickly —
  choose the profile and sources, set the archive options, and run.
```

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, insert directly above the `## [2.1.1]` heading:

```markdown
## [2.2.0] — 2026-07-06

### New Features
- **Express batch** — the toolbar **Run batch** button is now a hover dropdown
  with **Full Batch** (the full wizard) and **Express batch**, a lean window for
  users who already have a saved batch profile: pick the profile and sources, set
  the archive options, and run. Batch profiles now also remember the report
  format, "include units", and "combined report" settings.

```

- [ ] **Step 3: Bump the version**

In `src/starpost/__init__.py`, change `__version__ = "2.1.1"` to `__version__ = "2.2.0"`.

- [ ] **Step 4: Verify the version import**

Run: `.venv/bin/python -c "import starpost; print(starpost.__version__)"`
Expected: prints `2.2.0`.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md src/starpost/__init__.py
git commit -m "Document Express batch; bump to 2.2.0"
```

---

### Task 8: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`
Expected: all pass.

- [ ] **Step 2: Lint the tree**

Run: `.venv/bin/ruff check .`
Expected: only the two pre-existing F401s in `tests/test_main_window.py` (lines ~197, ~1695); no new errors.

- [ ] **Step 3: Manual smoke (optional, needs a display)**

Launch `python scripts/dev_run.py`; hover the **Run batch** toolbar button and confirm the dropdown shows **Full Batch** and **Express batch**; open **Express batch** and confirm the profile selector, source panel (no "Has similar format"), archive options, and a **Batch run** button that is disabled until a profile is chosen.
