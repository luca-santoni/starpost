# Part Search Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up the inert Tools → Part Search menu entry so it opens a window that filters loaded data sets down to those containing a searched-for part name, revealing which parts matched.

**Architecture:** A Qt-free matcher pair (`iter_part_names`, `matching_parts`) is added to `parts_tree.py` and unit-tested headless. A new non-modal `PartSearchDialog` (a `QTreeWidget` of data set → matching parts, driven by a `QLineEdit`) consumes that matcher over cached `build_parts_tree` output. `main_window.py` wires the existing menu action to open it. No STAR-CCM+ invocation — reads cached parts only.

**Tech Stack:** Python 3.11, PySide6, pyqtgraph (unused here), pytest.

## Global Constraints

- Line length 100, ruff, py311 target. Follow existing file style.
- Brand is **StarPost**; lowercase `starpost` only for package/path/identifier.
- Commit after every change; log user-facing changes in `CHANGELOG.md` (newest first).
- Run the full suite with `python scripts/run_tests.py`; single files may use `python -m pytest`. On headless machines prefix GUI tests with `QT_QPA_PLATFORM=offscreen`.
- No new keyboard shortcut, so `shortcuts.py` / `docs/starpost_hotkeys.txt` stay untouched.
- Keep heavy imports lazy where the codebase already does (e.g. import `PropertiesDialog` inside the method that uses it).

---

### Task 1: Qt-free part-name matcher in `parts_tree.py`

**Files:**
- Modify: `src/starpost/data/parts_tree.py` (append two functions)
- Test: `tests/test_parts_tree.py` (append)

**Interfaces:**
- Consumes: `PartsTree`, `PartNode` (already defined in this module).
- Produces:
  - `iter_part_names(tree: PartsTree) -> list[str]` — every node name (composites and leaves), depth-first in tree order.
  - `matching_parts(tree: PartsTree, query: str) -> list[str]` — case-insensitive substring filter over `iter_part_names`; empty/whitespace query returns all names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parts_tree.py`:

```python
from starpost.data.parts_tree import iter_part_names, matching_parts


def test_iter_part_names_includes_composites_and_leaves():
    names = iter_part_names(build_parts_tree(_props()))
    # Composites (roots) and their leaves are all present.
    assert "Tires" in names            # composite
    assert "Front tire" in names       # nested leaf
    assert "wing front 5" in names     # nested leaf
    assert "SDM25-Body-CFD-12" in names  # top-level leaf/root


def test_matching_parts_is_case_insensitive_substring():
    tree = build_parts_tree(_props())
    assert matching_parts(tree, "tire") == ["Tires", "Front tire"]
    assert matching_parts(tree, "TIRE") == ["Tires", "Front tire"]


def test_matching_parts_empty_query_returns_all():
    tree = build_parts_tree(_props())
    assert matching_parts(tree, "") == iter_part_names(tree)
    assert matching_parts(tree, "   ") == iter_part_names(tree)


def test_matching_parts_no_part_data_is_empty():
    empty = build_parts_tree(None)
    assert iter_part_names(empty) == []
    assert matching_parts(empty, "tire") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_parts_tree.py -k "iter_part_names or matching_parts" -v`
Expected: FAIL with `ImportError: cannot import name 'iter_part_names'`.

- [ ] **Step 3: Write the implementation**

Append to `src/starpost/data/parts_tree.py`:

```python
def iter_part_names(tree: PartsTree) -> list[str]:
    """Every node name in the parts tree — composites and leaves — depth-first
    in tree (alphabetical) order. Empty list for a tree with no parts."""
    names: list[str] = []

    def walk(node: PartNode) -> None:
        names.append(node.name)
        for child in node.children:
            walk(child)

    for root in tree.roots:
        walk(root)
    return names


def matching_parts(tree: PartsTree, query: str) -> list[str]:
    """Part names containing ``query`` (case-insensitive substring). An empty
    or whitespace-only query returns every name."""
    q = query.strip().casefold()
    names = iter_part_names(tree)
    if not q:
        return names
    return [n for n in names if q in n.casefold()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_parts_tree.py -k "iter_part_names or matching_parts" -v`
Expected: PASS (4 tests). Then `ruff check src/starpost/data/parts_tree.py tests/test_parts_tree.py` — no errors.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/data/parts_tree.py tests/test_parts_tree.py
git commit -m "feat: add part-name flatten/match helpers to parts_tree"
```

---

### Task 2: `PartSearchDialog` window

**Files:**
- Create: `src/starpost/gui/views/part_search_dialog.py`
- Test: `tests/test_part_search_gui.py`

**Interfaces:**
- Consumes:
  - `matching_parts`, `build_parts_tree` from `starpost.data.parts_tree` (Task 1).
  - A `store` object exposing `.all() -> list[SimResult]`; each `SimResult` has `.sim_name`, `.sim_path`, `.properties`, `.error`.
  - `PropertiesDialog(path, result, parent)` from `starpost.gui.views.properties_dialog`.
- Produces:
  - `PartSearchDialog(store, parent=None)` — a non-modal `QDialog`.
  - Public `reload() -> None` — re-snapshots the store and re-filters (called by the opener when re-raising).
  - Attributes used by tests: `_search` (`QLineEdit`), `_tree` (`QTreeWidget`), `_count` (`QLabel`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_part_search_gui.py`:

```python
"""Part Search window: a search bar filters a tree of data sets down to those
containing a matching part, with the matched part names as children."""
import pytest

from starpost.data.models import PropertyGroup, SimProperties, SimResult
from starpost.gui.views.part_search_dialog import PartSearchDialog


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _sim(path: str, *parts: str, error=None) -> SimResult:
    """A SimResult whose parts tree has one composite root per given name."""
    groups = []
    for name in parts:
        groups.append(PropertyGroup(section="part_tree", name=name,
                                    entries=[("type", "SolidModelPart"),
                                             ("leaf_parts", "1")]))
    res = SimResult(sim_path=path, error=error)
    res.properties = SimProperties(groups=groups) if groups else None
    return res


class _Store:
    def __init__(self, results):
        self._results = results

    def all(self):
        return self._results


def _tree_texts(dlg):
    """Top-level texts -> list of child texts, as shown in the tree."""
    out = {}
    root = dlg._tree.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        out[top.text(0)] = [top.child(j).text(0) for j in range(top.childCount())]
    return out


def test_empty_query_shows_all_sims_with_parts(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire", "Rear wing"),
                    _sim("/a/caseB.sim", "Chassis")])
    dlg = PartSearchDialog(store)
    assert set(_tree_texts(dlg)) == {"caseA", "caseB"}
    assert dlg._count.text() == "2 data sets, 3 parts"


def test_typing_filters_to_matching_sims_and_parts(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire", "Rear wing"),
                    _sim("/a/caseB.sim", "Chassis")])
    dlg = PartSearchDialog(store)
    dlg._search.setText("tire")
    texts = _tree_texts(dlg)
    assert texts == {"caseA": ["Front tire"]}
    assert dlg._count.text() == "1 data sets, 1 parts"


def test_sim_without_parts_is_excluded(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire"),
                    _sim("/a/noparts.sim")])
    dlg = PartSearchDialog(store)
    assert set(_tree_texts(dlg)) == {"caseA"}


def test_failed_extraction_is_excluded(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire"),
                    _sim("/a/broken.sim", "Front tire", error="boom")])
    dlg = PartSearchDialog(store)
    assert set(_tree_texts(dlg)) == {"caseA"}


def test_rows_carry_sim_path_for_double_click(app):
    from PySide6.QtCore import Qt

    store = _Store([_sim("/a/caseA.sim", "Front tire")])
    dlg = PartSearchDialog(store)
    top = dlg._tree.invisibleRootItem().child(0)
    child = top.child(0)
    assert top.data(0, Qt.ItemDataRole.UserRole) == "/a/caseA.sim"
    assert child.data(0, Qt.ItemDataRole.UserRole) == "/a/caseA.sim"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_part_search_gui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'starpost.gui.views.part_search_dialog'`.

- [ ] **Step 3: Write the implementation**

Create `src/starpost/gui/views/part_search_dialog.py`:

```python
"""'Part Search' window: find which loaded data sets contain a given part.

A search bar filters a two-level tree — data set → matching part names — driven
by the cached parts tree (``build_parts_tree``). Reads cached sim properties
only; it never re-runs STAR-CCM+. Double-clicking any row opens that sim's
Properties window (which carries the browsable Parts tab).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from starpost.data.parts_tree import build_parts_tree, matching_parts


class PartSearchDialog(QDialog):
    """Non-modal search window over the parts of every loaded data set."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Part Search")
        self.resize(420, 520)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search part names…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._refresh())

        self._count = QLabel()
        self._count.setObjectName("partSearchCount")

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._open_properties)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._count)
        layout.addWidget(self._tree)

        # (sim_name, sim_path, parts_tree) snapshot; refreshed on reopen.
        self._sims: list[tuple[str, str, object]] = []
        self.reload()

    def reload(self) -> None:
        """Re-snapshot the loaded data sets and re-filter. Called on reopen so a
        re-raised window reflects the current store."""
        self._sims = [
            (r.sim_name, r.sim_path, build_parts_tree(r.properties))
            for r in self._store.all()
            if r.error is None
        ]
        self._refresh()

    def _refresh(self) -> None:
        query = self._search.text()
        expand = bool(query.strip())
        self._tree.clear()
        sim_count = 0
        part_count = 0
        for sim_name, sim_path, tree in self._sims:
            parts = matching_parts(tree, query)
            if not parts:
                continue
            sim_count += 1
            part_count += len(parts)
            top = QTreeWidgetItem([sim_name])
            top.setData(0, Qt.ItemDataRole.UserRole, sim_path)
            for name in parts:
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.ItemDataRole.UserRole, sim_path)
                top.addChild(child)
            self._tree.addTopLevelItem(top)
            top.setExpanded(expand)
        self._count.setText(f"{sim_count} data sets, {part_count} parts")

    def _open_properties(self, item: QTreeWidgetItem, _col: int) -> None:
        from starpost.gui.views.properties_dialog import PropertiesDialog

        sim_path = item.data(0, Qt.ItemDataRole.UserRole)
        result = next(
            (r for r in self._store.all() if r.sim_path == sim_path), None
        )
        if result is None:
            return
        PropertiesDialog(Path(sim_path), result, self).exec()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_part_search_gui.py -v`
Expected: PASS (5 tests). Then `ruff check src/starpost/gui/views/part_search_dialog.py tests/test_part_search_gui.py` — no errors.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/gui/views/part_search_dialog.py tests/test_part_search_gui.py
git commit -m "feat: add Part Search window"
```

---

### Task 3: Wire the menu action + changelog

**Files:**
- Modify: `src/starpost/gui/main_window.py` (line 547 action; add `_open_part_search`)
- Modify: `CHANGELOG.md`
- Test: `tests/test_main_window.py` (append)

**Interfaces:**
- Consumes: `PartSearchDialog(store, parent)` and its `reload()` (Task 2); `self.store`, `self._tools_menu` (existing).
- Produces: `MainWindow._open_part_search()`; attribute `self._part_search_dialog`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_window.py`:

```python
def test_part_search_action_opens_window(app):
    """Tools → Part Search opens (and stashes) a PartSearchDialog."""
    from starpost.gui.views.part_search_dialog import PartSearchDialog

    win = mw.MainWindow(Settings())
    act = next(a for a in win._tools_menu.actions() if a.text() == "Part Search")
    act.trigger()
    assert isinstance(win._part_search_dialog, PartSearchDialog)
    win._part_search_dialog.close()
    win.close()


def test_part_search_reopen_reuses_visible_window(app):
    """Re-triggering while the window is open reuses it rather than duplicating."""
    win = mw.MainWindow(Settings())
    act = next(a for a in win._tools_menu.actions() if a.text() == "Part Search")
    act.trigger()
    first = win._part_search_dialog
    act.trigger()
    assert win._part_search_dialog is first
    win._part_search_dialog.close()
    win.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -k part_search -v`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_part_search_dialog'`.

- [ ] **Step 3: Wire the action**

In `src/starpost/gui/main_window.py`, replace line 547:

```python
        tools_menu.addAction("Part Search")
```

with:

```python
        part_search_act = tools_menu.addAction("Part Search")
        part_search_act.triggered.connect(self._open_part_search)
```

- [ ] **Step 4: Add the opener method**

In `src/starpost/gui/main_window.py`, in the `# --- actions (scaffolded)` section (near `_show_file_properties`, ~line 1509), add:

```python
    def _open_part_search(self) -> None:
        """Tools → Part Search: open the non-modal window for finding which
        loaded data sets contain a given part (reads cached parts only)."""
        from starpost.gui.views.part_search_dialog import PartSearchDialog

        dlg = getattr(self, "_part_search_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.reload()
            dlg.raise_()
            dlg.activateWindow()
            return
        self._part_search_dialog = PartSearchDialog(self.store, self)
        self._part_search_dialog.show()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -k part_search -v`
Expected: PASS (2 tests). Then `ruff check src/starpost/gui/main_window.py` — no errors.

- [ ] **Step 6: Update the changelog**

In `CHANGELOG.md`, under `## [Unreleased]` → `### New Features`, add a new top entry:

```markdown
- **Part Search window** — Tools → Part Search opens a searchable window: type
  part-name text into the search bar and the list of loaded data sets filters
  to only those containing a matching part, expanded to show which parts
  matched. Double-click any row to open that data set's Properties. Reads
  cached part data only — no STAR-CCM+ re-run.
```

Then update the existing "Tools menu" entry so it no longer says Part Search is unwired — change its last sentence from noting all entries are unwired to noting Correlation and Convergence remain scaffolding while Part Search is now functional:

```markdown
- **"Tools" menu in the top bar** — a new toolbar dropdown sits between Export
  and Settings, with entries for Correlation, Convergence, and Part Search.
  Correlation and Convergence are UI scaffolding only for now; Part Search is
  functional (see above).
```

- [ ] **Step 7: Commit**

```bash
git add src/starpost/gui/main_window.py tests/test_main_window.py CHANGELOG.md
git commit -m "feat: wire Tools -> Part Search to open the search window"
```

---

### Task 4: Full-suite regression + manual GUI verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `python scripts/run_tests.py`
Expected: all tests pass (each file isolated in its own process).

- [ ] **Step 2: Lint the whole tree**

Run: `ruff check .`
Expected: no errors.

- [ ] **Step 3: Manual GUI smoke via the verify skill**

Use the `verify` skill (offscreen `QApplication`, real `MainWindow`, synthetic clicks, screenshots) to confirm end-to-end:
1. Load/seed 2+ data sets that have extracted parts.
2. Tools → Part Search opens the window; the tree lists both data sets.
3. Type a part substring; the tree filters to matching sims, expanded to the matched parts; the count label updates.
4. Clear the search; all data sets return.
5. Double-click a data-set row and a part row; each opens that sim's Properties window (Parts tab browsable).

Capture a screenshot of the filtered window as evidence.

- [ ] **Step 4: Final commit (if verification produced fixes)**

Only if steps 1–3 required changes:

```bash
git add -A
git commit -m "fix: address Part Search verification findings"
```

## Notes for the implementer

- `Qt.ItemDataRole.UserRole` is the enum-qualified form used in the tests; keep it consistent in the dialog.
- The dialog only needs `store.all()`; tests use a lightweight `_Store` stub rather than the real `ResultStore` to avoid cache side effects. Production passes the real `self.store`.
- Do not add a keyboard shortcut — none is in scope, so the hotkey docs/table stay untouched (avoids `test_hotkey_doc_lists_every_binding`).
