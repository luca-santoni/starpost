# General Tab Trees Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Properties window's General-tab flat Reports/Monitors counts with browsable, expandable trees (Reports names; Monitors as plot → series), keeping File size and Iterations as a summary form above them.

**Architecture:** Promote the `_general_tab()` function in `properties_dialog.py` to a `_GeneralTab(QWidget)` class (mirroring the existing `_PartsTab` / `_RowsTab`), so it can own two `QTreeWidget`s exposed as `self.reports_tree` and `self.monitors_tree` (both `None` in the not-extracted case). No data-model, extraction, or other-tab changes.

**Tech Stack:** Python 3.11, PySide6 (QtWidgets), pytest. GUI tests use a real `QApplication`.

## Global Constraints

- Line length 100, ruff target py311 (`ruff check .` must pass).
- Run the full suite with `python scripts/run_tests.py`, never bare `python -m pytest` (single-file `python -m pytest tests/test_properties_gui.py` is fine — it's one process). On headless machines prefix with `QT_QPA_PLATFORM=offscreen`.
- Commit after every change; log user-facing changes in `CHANGELOG.md` newest-first, in its existing style.
- Brand is **StarPost**; lowercase `starpost` only for package/path identifiers.
- Do not modify the data model, extraction pipeline, or the Parts/Mesh/Regions/Physics tabs.

---

### Task 1: Promote `_general_tab` to `_GeneralTab` with Reports & Monitors trees

**Files:**
- Modify: `src/starpost/gui/views/properties_dialog.py` (replace the `_general_tab` function at lines 74–116; update its one call site at line 54)
- Test: `tests/test_properties_gui.py` (update one existing test, add four)

**Interfaces:**
- Consumes: `SimResult.reports` (`list[Report]`, each `.name`), `SimResult.plots` (`list[MonitorPlot]`, each `.name` and `.series` where each `PlotSeries` has `.name`), `SimResult.error`. The module-level `_human_size(num_bytes: int) -> str` helper.
- Produces: `class _GeneralTab(QWidget)` constructed as `_GeneralTab(path: Path, result, size_bytes: int | None)`, exposing attributes `reports_tree: QTreeWidget | None` and `monitors_tree: QTreeWidget | None` (both `None` when the result is not extracted). Replaces the `_general_tab(...)` call in `PropertiesDialog.__init__`.

- [ ] **Step 1: Update the existing summary test and add the new tests**

In `tests/test_properties_gui.py`, replace the body of `test_general_tab_keeps_classic_summary` (lines 58–66) so it reflects the new layout, and append the four new tests after `test_general_tab_unextracted_note`. Note the fixture `_result()` already has one report ("Drag") and one plot ("Residuals") with one series ("Continuity").

```python
def test_general_tab_keeps_summary_form(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(), size_bytes=2048)
    general = dlg.tabs.widget(0)
    texts = _labels(general)
    assert "File size" in texts and "2.0 KB" in texts
    assert "Iterations" in texts and "2" in texts
    # The old flat count rows are gone; counts now live in the tree headings.
    assert "Reports (1)" in texts
    assert any(t.startswith("Monitors — ") for t in texts)


def test_reports_tree_lists_report_names(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    tree = dlg.tabs.widget(0).reports_tree
    assert tree is not None
    names = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert names == ["Drag"]


def test_monitors_tree_has_plots_with_series_children(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    tree = dlg.tabs.widget(0).monitors_tree
    assert tree is not None and tree.topLevelItemCount() == 1
    plot = tree.topLevelItem(0)
    assert plot.text(0) == "Residuals"
    assert [plot.child(i).text(0) for i in range(plot.childCount())] == ["Continuity"]


def test_monitors_heading_counts_plots_and_series(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    texts = _labels(dlg.tabs.widget(0))
    assert "Monitors — 1 plot, 1 series" in texts


def test_general_tab_unextracted_has_no_trees(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", None)
    general = dlg.tabs.widget(0)
    assert general.reports_tree is None
    assert general.monitors_tree is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_properties_gui.py -v`
Expected: FAIL — `_general_tab` returns a plain widget, so `.reports_tree` / `.monitors_tree` raise `AttributeError`, and the heading-text assertions fail.

- [ ] **Step 3: Add a pluralizing count helper**

There is already a `_plural(n, noun)` at line 195, but it is defined *below* `_general_tab`. Rather than reorder, add a tiny local formatter for the monitor heading. In `src/starpost/gui/views/properties_dialog.py`, add this module-level helper directly above the current `_general_tab` (i.e. just before line 74):

```python
def _count_phrase(n: int, noun: str) -> str:
    """`"1 plot"` / `"3 plots"` — singular noun for exactly one."""
    return f"{n} {noun}" + ("" if n == 1 else "s")
```

- [ ] **Step 4: Replace the `_general_tab` function with a `_GeneralTab` class**

In `src/starpost/gui/views/properties_dialog.py`, delete the entire `_general_tab` function (lines 74–116) and put this class in its place:

```python
class _GeneralTab(QWidget):
    """The summary tab: File size and Iterations as a small form, plus a
    Reports tree (names) and a Monitors tree (plot ▸ series). ``reports_tree``
    and ``monitors_tree`` are None until the file has been extracted."""

    def __init__(self, path: Path, result, size_bytes: int | None, parent=None) -> None:
        super().__init__(parent)
        self.reports_tree = None
        self.monitors_tree = None

        # When size_bytes is given (e.g. the Data tab passes the data set's
        # portable-CSV size), use it; otherwise measure the file on disk.
        if size_bytes is not None:
            size = _human_size(size_bytes)
        else:
            try:
                size = _human_size(path.stat().st_size)
            except OSError:  # file moved/deleted/unreadable
                size = "—"

        # Reports/monitors/iterations only exist once the file is extracted.
        # Iterations is the longest series' length.
        extracted = result is not None and result.error is None
        iterations = (
            str(max((len(s.x) for p in result.plots for s in p.series), default=0))
            if extracted
            else "—"
        )

        form = QFormLayout()
        form.addRow("File size", QLabel(size))
        form.addRow("Iterations", QLabel(iterations))

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        if not extracted:
            note = QLabel("Open the file to extract its reports and monitors.")
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return

        # Reports section: a heading with the count, then a names-only tree.
        layout.addWidget(QLabel(f"Reports ({len(result.reports)})"))
        self.reports_tree = _name_tree()
        for report in result.reports:
            self.reports_tree.addTopLevelItem(QTreeWidgetItem([report.name]))
        layout.addWidget(self.reports_tree)

        # Monitors section: heading counts plots and series; tree is plot ▸ series.
        series_total = sum(len(p.series) for p in result.plots)
        heading = (
            f"Monitors — {_count_phrase(len(result.plots), 'plot')}, "
            f"{_count_phrase(series_total, 'series')}"
        )
        layout.addWidget(QLabel(heading))
        self.monitors_tree = _name_tree()
        for plot in result.plots:
            plot_item = QTreeWidgetItem([plot.name])
            for s in plot.series:
                plot_item.addChild(QTreeWidgetItem([s.name]))
            self.monitors_tree.addTopLevelItem(plot_item)
        layout.addWidget(self.monitors_tree)


def _name_tree() -> QTreeWidget:
    """A single-column, header-hidden, alternating-row tree for name lists —
    the shared look of the General tab's Reports and Monitors trees."""
    tree = QTreeWidget()
    tree.setColumnCount(1)
    tree.setHeaderHidden(True)
    tree.setAlternatingRowColors(True)
    return tree
```

Note: `"series"` is the same word singular and plural, so `_count_phrase(1, "series")` yields `"1 seriess"`. Guard that specific noun — change the helper from Step 3 to:

```python
def _count_phrase(n: int, noun: str) -> str:
    """`"1 plot"` / `"3 plots"` — singular noun for exactly one. Nouns already
    ending in "s" (e.g. "series") are left unpluralized."""
    if n == 1 or noun.endswith("s"):
        return f"{n} {noun}"
    return f"{n} {noun}s"
```

- [ ] **Step 5: Update the call site in `PropertiesDialog.__init__`**

In `src/starpost/gui/views/properties_dialog.py`, change the General-tab line (currently lines 53–55):

```python
        self.tabs.addTab(
            _general_tab(path, result, size_bytes), "General"
        )
```

to:

```python
        self.tabs.addTab(_GeneralTab(path, result, size_bytes), "General")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_properties_gui.py -v`
Expected: PASS — all tests in the file, including the four new ones and the renamed summary test, pass.

- [ ] **Step 7: Lint**

Run: `ruff check src/starpost/gui/views/properties_dialog.py tests/test_properties_gui.py`
Expected: no errors. (If `_plural` at the old line 195 is now unused elsewhere, leave it — `_contents` still calls it. Do not delete it.)

- [ ] **Step 8: Commit**

```bash
git add src/starpost/gui/views/properties_dialog.py tests/test_properties_gui.py
git commit -m "feat: expandable Reports & Monitors trees in Properties General tab

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: CHANGELOG entry and full-suite verification

**Files:**
- Modify: `CHANGELOG.md` (add a bullet under `## [Unreleased]` → `### New Features`)

**Interfaces:**
- Consumes: nothing. Produces: nothing (docs + verification only).

- [ ] **Step 1: Add the CHANGELOG entry**

In `CHANGELOG.md`, add this as the first bullet under the existing `### New Features` list inside `## [Unreleased]` (newest first):

```markdown
- **Reports & Monitors trees in the Properties window** — the General tab now
  lists a data set's reports and monitors as browsable, expandable trees
  instead of bare counts. Reports show by name; monitors are grouped as
  plot ▸ series, matching STAR-CCM+'s own structure. File size and Iterations
  stay as a summary above them. Reads cached data only — no STAR-CCM+ re-run.
```

- [ ] **Step 2: Run the full test suite**

Run: `QT_QPA_PLATFORM=offscreen python scripts/run_tests.py`
Expected: PASS — the whole suite is green (per CLAUDE.md, this runner isolates each GUI test file in its own process).

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for General-tab Reports & Monitors trees

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- New layout — summary form (File size, Iterations) → Task 1 Step 4 form. ✓
- Reports section heading `Reports (N)` + names-only tree → Task 1 Step 4. ✓
- Monitors section heading `Monitors — P plots, S series` + plot ▸ series tree → Task 1 Step 4. ✓
- Redundant single child shown, not suppressed → Task 1 Step 4 unconditionally adds every series as a child. ✓
- Trees collapsed by default → no `expandAll()` call anywhere. ✓
- `setAlternatingRowColors(True)`, header hidden → `_name_tree()`. ✓
- Not-extracted case: File size + Iterations `—`, the note, no trees → Task 1 Step 4 early return with `reports_tree`/`monitors_tree` left `None`. ✓
- Promote function to `_GeneralTab` class exposing `reports_tree`/`monitors_tree` → Task 1. ✓
- Tests: update `test_general_tab_keeps_classic_summary`, add reports-tree, monitors-tree, heading-count, and unextracted-no-trees tests → Task 1 Step 1. ✓
- CHANGELOG newest-first → Task 2. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `_GeneralTab(path, result, size_bytes)` signature matches the call site in Step 5. `reports_tree`/`monitors_tree` names used identically in tests (Step 1) and implementation (Step 4). `_count_phrase` and `_name_tree` helper names consistent between Steps 3/4. ✓ (Step 4 supersedes Step 3's first draft of `_count_phrase` with the "series"-aware version — the final code is the one to keep.)
