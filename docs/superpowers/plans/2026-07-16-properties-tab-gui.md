# Properties Dialog Tabs (General + Parts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the per-sim `PropertiesDialog` into a tabbed window: a **General** tab holding exactly today's content, and a **Parts** tab showing the Geometry ▸ Parts tree rebuilt from the extracted sim properties (`part_tree` + `part` sections with `path` values).

**Architecture:** A pure, Qt-free tree builder (`src/starpost/data/parts_tree.py`) turns `SimProperties` into `PartNode` structures — unit-testable without a QApplication. The dialog (`gui/views/properties_dialog.py`) gains a `QTabWidget`; the Parts tab renders the built tree in a `QTreeWidget`, or a "re-extract" note when no parts data exists. Constructor signature is unchanged, so both call sites (`main_window._show_file_properties`, `_show_data_properties`) need no edits.

**Tech Stack:** Python 3.11, PySide6, pytest (GUI tests offscreen).

## Global Constraints

- `PropertiesDialog(path, result=None, parent=None, size_bytes=None)` — signature MUST NOT change (two call sites in `main_window.py:1489-1517` construct it exactly like this).
- The General tab shows **exactly** today's rows and behavior: File size / Reports / Monitors / Iterations, plus the "Open the file to extract…" note when not extracted. Window title stays `f"Properties — {path.name}"`.
- Path format (validated on the real 2506 install, spec `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md`): composite ancestors joined with `.`, a single `|` before the leaf name (`Original files.Chris Penny's car|wing front 5`); **top-level leaf parts have `path == name`** (no `|`). Part names may themselves contain `.` — resolve the ancestor half against known top-level (`part_tree`) names longest-first before falling back to splitting on `.`.
- Tree entries sort alphabetically (case-insensitive), like STAR-CCM+'s tree display; the extracted CSV order is manager order and must not leak through.
- `truncated` rows (`part_tree,,truncated,N` / `part,,truncated,N`) surface as one trailing "… and N more" item.
- No changes to models, parser, store, portable, or the macro. GUI + one new pure-logic module only.
- GUI tests need a real `QApplication` — new GUI tests go in a NEW file `tests/test_properties_gui.py` (full suite isolates per file; do not add Qt tests to `tests/test_properties.py`, which is Qt-free). Run GUI tests with `QT_QPA_PLATFORM=offscreen`.
- Run single test files with `python -m pytest …`; the full suite ONLY via `python scripts/run_tests.py` (Task 3).
- `ruff check .` clean (line-length 100, py311). Commit after every task.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/starpost/data/parts_tree.py` | Create | Pure `SimProperties` → `PartsTree`/`PartNode` builder, no Qt |
| `src/starpost/gui/views/properties_dialog.py` | Modify | Tabbed `PropertiesDialog`; `_PartsTab` widget |
| `tests/test_parts_tree.py` | Create | Qt-free builder tests |
| `tests/test_properties_gui.py` | Create | Offscreen dialog/tab tests |
| `CHANGELOG.md` | Modify | Unreleased → New Features entry (Task 3) |
| `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md` | Modify | Mark open question 1 resolved: tabbed dialog (Task 3) |

---

### Task 1: Pure parts-tree builder (`data/parts_tree.py`)

**Files:**
- Create: `src/starpost/data/parts_tree.py`
- Test: `tests/test_parts_tree.py` (create)

**Interfaces:**
- Consumes: `SimProperties` / `PropertyGroup` from `starpost.data.models` (groups with sections `part_tree` and `part`; keys `type`, `leaf_parts`, `path`, `surfaces`, `curves`, `truncated`).
- Produces (Task 2 relies on these exact names):
  - `PartNode(name: str, type: str = "", leaf_count: int | None = None, surfaces: str = "", curves: str = "", children: list[PartNode])`
  - `PartsTree(roots: list[PartNode], truncated: int = 0)` with property `empty: bool`
  - `build_parts_tree(props: SimProperties | None) -> PartsTree`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parts_tree.py`:

```python
"""Parts-tree builder: SimProperties part/part_tree groups -> a nested,
alphabetically sorted tree matching STAR-CCM+'s Geometry > Parts display.
Fixtures use the real path format observed on the 2506 install."""
from starpost.data.models import PropertyGroup, SimProperties
from starpost.data.parts_tree import PartNode, build_parts_tree


def _g(section, name, *entries):
    return PropertyGroup(section=section, name=name, entries=list(entries))


def _props() -> SimProperties:
    return SimProperties(groups=[
        # part_tree: top-level entries, deliberately NOT alphabetical.
        _g("part_tree", "Original files",
           ("type", "CompositePart"), ("leaf_parts", "46")),
        _g("part_tree", "Tires",
           ("type", "SolidModelCompositePart"), ("leaf_parts", "2")),
        _g("part_tree", "SDM25-Body-CFD-12",
           ("type", "SolidModelPart"), ("leaf_parts", "1")),
        # Nested leaf: ancestors joined with ".", "|" before the leaf name.
        _g("part", "wing front 5",
           ("type", "SolidModelPart"),
           ("path", "Original files.Chris Penny's car|wing front 5"),
           ("surfaces", "2"), ("curves", "1")),
        _g("part", "Front tire",
           ("type", "SolidModelPart"),
           ("path", "Tires|Front tire"),
           ("surfaces", "1"), ("curves", "1")),
        # Top-level leaf: path == name, merges into its part_tree entry.
        _g("part", "SDM25-Body-CFD-12",
           ("type", "SolidModelPart"),
           ("path", "SDM25-Body-CFD-12"),
           ("surfaces", "5"), ("curves", "2")),
    ])


def test_roots_come_from_part_tree_and_sort_alphabetically():
    tree = build_parts_tree(_props())
    assert [n.name for n in tree.roots] == [
        "Original files", "SDM25-Body-CFD-12", "Tires",
    ]
    assert tree.roots[0].type == "CompositePart"
    assert tree.roots[0].leaf_count == 46
    assert not tree.empty and tree.truncated == 0


def test_nested_leaf_lands_under_intermediate_composite():
    tree = build_parts_tree(_props())
    orig = tree.roots[0]
    assert [c.name for c in orig.children] == ["Chris Penny's car"]
    car = orig.children[0]
    assert [c.name for c in car.children] == ["wing front 5"]
    leaf = car.children[0]
    assert leaf.type == "SolidModelPart"
    assert leaf.surfaces == "2" and leaf.curves == "1"
    assert leaf.children == []


def test_top_level_leaf_merges_with_its_part_tree_entry():
    tree = build_parts_tree(_props())
    body = next(n for n in tree.roots if n.name == "SDM25-Body-CFD-12")
    # One node, not a duplicate child: details merged onto the root entry.
    assert body.surfaces == "5" and body.curves == "2"
    assert body.children == []


def test_children_sort_alphabetically():
    props = _props()
    props.groups.append(_g("part", "Aero wing",
                           ("path", "Original files.Chris Penny's car|Aero wing")))
    tree = build_parts_tree(props)
    car = tree.roots[0].children[0]
    assert [c.name for c in car.children] == ["Aero wing", "wing front 5"]


def test_ancestor_matching_prefers_longest_top_level_name():
    # A top-level name containing "." must not be split apart.
    props = SimProperties(groups=[
        _g("part_tree", "v2.5 model", ("type", "CompositePart")),
        _g("part", "hull", ("path", "v2.5 model|hull")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["v2.5 model"]
    assert [c.name for c in tree.roots[0].children] == ["hull"]


def test_leaf_with_unknown_root_creates_it():
    # part_tree section missing (older/failed section): tree still builds.
    props = SimProperties(groups=[
        _g("part", "wing", ("path", "Imported.Sub|wing"), ("surfaces", "3")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["Imported"]
    assert [c.name for c in tree.roots[0].children] == ["Sub"]
    assert tree.roots[0].children[0].children[0].name == "wing"


def test_pathless_leaf_becomes_a_root():
    # Extractions from before the path key existed degrade to a flat list.
    props = SimProperties(groups=[
        _g("part", "wing", ("type", "CadPart"), ("surfaces", "3")),
    ])
    tree = build_parts_tree(props)
    assert [n.name for n in tree.roots] == ["wing"]
    assert tree.roots[0].surfaces == "3"


def test_truncated_rows_are_summed():
    props = _props()
    props.groups.append(_g("part_tree", "", ("truncated", "3")))
    props.groups.append(_g("part", "", ("truncated", "40")))
    assert build_parts_tree(props).truncated == 43


def test_no_properties_or_no_part_data_is_empty():
    assert build_parts_tree(None).empty
    assert build_parts_tree(SimProperties()).empty
    only_mesh = SimProperties(groups=[_g("mesh", "", ("cell_count", "5"))])
    assert build_parts_tree(only_mesh).empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_parts_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.data.parts_tree'`

- [ ] **Step 3: Implement the builder**

Create `src/starpost/data/parts_tree.py`:

```python
"""Rebuild the Geometry > Parts tree from extracted sim properties.

The extraction macro writes two flat sections: ``part_tree`` (the top-level
entries of the Parts node, with type and leaf counts) and ``part`` (every
leaf part, with a ``path`` recording its composite ancestors). This module
turns those rows back into a nested tree for the Properties dialog — pure
data logic, no Qt, so it stays unit-testable headless.

Path format (STAR's own display convention, validated on a real install):
composite ancestors joined with ``.``, a single ``|`` before the leaf name
(``Original files.Chris Penny's car|wing front 5``); a top-level leaf's path
is just its name. Part names may legitimately contain ``.``, so ancestor
strings are matched against known top-level names longest-first before
falling back to splitting on ``.``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from starpost.data.models import SimProperties


@dataclass
class PartNode:
    """One entry of the Parts tree: a composite (has children / leaf_count)
    or a leaf part (has surface/curve counts)."""
    name: str
    type: str = ""
    leaf_count: Optional[int] = None   # composites: leaf parts contained
    surfaces: str = ""                 # leaves: counts as extracted ("" unknown)
    curves: str = ""
    children: list["PartNode"] = field(default_factory=list)


@dataclass
class PartsTree:
    roots: list[PartNode] = field(default_factory=list)
    truncated: int = 0                 # parts beyond the extraction cap

    @property
    def empty(self) -> bool:
        return not self.roots and not self.truncated


def build_parts_tree(props: Optional[SimProperties]) -> PartsTree:
    """The Parts tree for ``props``, alphabetically sorted at every level.
    Empty tree when there is no part data (pre-parts extraction)."""
    tree = PartsTree()
    if props is None:
        return tree

    roots: dict[str, PartNode] = {}

    def root(name: str) -> PartNode:
        node = roots.get(name)
        if node is None:
            node = PartNode(name=name)
            roots[name] = node
        return node

    for g in props.groups:
        if g.section == "part_tree":
            if not g.name:
                tree.truncated += _count(g.get("truncated"))
                continue
            node = root(g.name)
            node.type = g.get("type") or node.type
            leaf_count = g.get("leaf_parts") or ""
            if leaf_count.isdigit():
                node.leaf_count = int(leaf_count)
        elif g.section == "part":
            if not g.name:
                tree.truncated += _count(g.get("truncated"))
                continue
            _attach_leaf(g, root, roots)

    tree.roots = sorted(roots.values(), key=lambda n: n.name.casefold())
    for node in tree.roots:
        _sort_children(node)
    return tree


def _attach_leaf(g, root, roots: dict[str, PartNode]) -> None:
    """Place one ``part`` group under its composite ancestors (from ``path``)."""
    leaf = PartNode(
        name=g.name,
        type=g.get("type") or "",
        surfaces=g.get("surfaces") or "",
        curves=g.get("curves") or "",
    )
    ancestors = _ancestors(g.get("path") or "", g.name, roots)
    if not ancestors:
        # Top-level leaf: merge details onto its part_tree entry when one
        # exists (same entity), otherwise it becomes a root itself.
        existing = roots.get(leaf.name)
        if existing is None:
            roots[leaf.name] = leaf
        else:
            existing.type = leaf.type or existing.type
            existing.surfaces, existing.curves = leaf.surfaces, leaf.curves
        return
    node = root(ancestors[0])
    for name in ancestors[1:]:
        node = _child(node, name)
    _child_add(node, leaf)


def _ancestors(path: str, leaf_name: str, roots: dict[str, PartNode]) -> list[str]:
    """The composite chain above a leaf, resolved from its path string."""
    if path.endswith("|" + leaf_name):
        anc = path[: -(len(leaf_name) + 1)]
    elif "|" in path:
        anc = path.split("|", 1)[0]
    else:
        return []  # path == name (top-level) or absent/unparseable
    if not anc:
        return []
    # A known top-level name may itself contain "." — match longest-first
    # before splitting the remainder on ".".
    for name in sorted(roots, key=len, reverse=True):
        if anc == name:
            return [name]
        if anc.startswith(name + "."):
            rest = anc[len(name) + 1:]
            return [name] + [s for s in rest.split(".") if s]
    return [s for s in anc.split(".") if s]


def _child(node: PartNode, name: str) -> PartNode:
    for c in node.children:
        if c.name == name:
            return c
    c = PartNode(name=name)
    node.children.append(c)
    return c


def _child_add(node: PartNode, leaf: PartNode) -> None:
    for i, c in enumerate(node.children):
        if c.name == leaf.name and not c.children:
            node.children[i] = leaf
            return
    node.children.append(leaf)


def _sort_children(node: PartNode) -> None:
    node.children.sort(key=lambda n: n.name.casefold())
    for c in node.children:
        _sort_children(c)


def _count(value: Optional[str]) -> int:
    return int(value) if value and value.isdigit() else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_parts_tree.py tests/test_properties.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/data/parts_tree.py tests/test_parts_tree.py
git commit -m "Data: rebuild the Parts tree from extracted sim properties"
```

---

### Task 2: Tabbed PropertiesDialog with General + Parts tabs

**Files:**
- Modify: `src/starpost/gui/views/properties_dialog.py`
- Test: `tests/test_properties_gui.py` (create)

**Interfaces:**
- Consumes: `build_parts_tree`, `PartsTree`, `PartNode` from Task 1 (exact signatures above).
- Produces: `PropertiesDialog` unchanged signature, now with `self.tabs` (`QTabWidget`, tab 0 "General", tab 1 "Parts"); `_PartsTab(result)` widget with `self.tree` (`QTreeWidget` or `None` when showing the empty-state note). Only `PropertiesDialog` changes — `ScenePropertiesDialog`, `FolderPropertiesDialog`, `DataFolderPropertiesDialog` stay untouched.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_properties_gui.py`:

```python
"""Tabbed Properties dialog: General tab carries the classic summary, the
Parts tab shows the Geometry > Parts tree from extracted sim properties."""
import pytest

from starpost.data.models import (
    MonitorPlot,
    PlotSeries,
    PropertyGroup,
    Report,
    SimProperties,
    SimResult,
)
from starpost.gui.views.properties_dialog import PropertiesDialog


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _result(with_parts: bool = True) -> SimResult:
    res = SimResult(
        sim_path="/cases/caseA.sim",
        reports=[Report(name="Drag", value=12.5, units="N")],
        plots=[MonitorPlot(name="Residuals",
                           series=[PlotSeries(name="Continuity",
                                              x=[1.0, 2.0], y=[0.1, 0.2])])],
    )
    if with_parts:
        res.properties = SimProperties(groups=[
            PropertyGroup(section="part_tree", name="Tires",
                          entries=[("type", "SolidModelCompositePart"),
                                   ("leaf_parts", "2")]),
            PropertyGroup(section="part", name="Front tire",
                          entries=[("type", "SolidModelPart"),
                                   ("path", "Tires|Front tire"),
                                   ("surfaces", "1"), ("curves", "1")]),
        ])
    return res


def _labels(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [lb.text() for lb in widget.findChildren(QLabel)]


def test_dialog_has_general_and_parts_tabs(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
        "General", "Parts",
    ]
    assert dlg.windowTitle() == "Properties — caseA.sim"


def test_general_tab_keeps_classic_summary(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(),
                           size_bytes=2048)
    general = dlg.tabs.widget(0)
    texts = _labels(general)
    assert "File size" in texts and "2.0 KB" in texts
    assert "Reports" in texts and "1" in texts
    assert "Monitors" in texts
    assert "Iterations" in texts and "2" in texts


def test_general_tab_unextracted_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", None)
    texts = _labels(dlg.tabs.widget(0))
    assert any("Open the file to extract" in t for t in texts)
    assert "—" in texts


def test_parts_tab_shows_the_tree(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    parts = dlg.tabs.widget(1)
    tree = parts.tree
    assert tree is not None and tree.topLevelItemCount() == 1
    top = tree.topLevelItem(0)
    assert top.text(0) == "Tires"
    assert top.text(1) == "SolidModelCompositePart"
    assert top.text(2) == "2 parts"
    assert top.childCount() == 1
    leaf = top.child(0)
    assert leaf.text(0) == "Front tire"
    assert leaf.text(2) == "1 surface, 1 curve"


def test_parts_tab_without_data_shows_reextract_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(with_parts=False))
    parts = dlg.tabs.widget(1)
    assert parts.tree is None
    assert any("Re-extract" in t for t in _labels(parts))


def test_parts_tab_truncation_row(app, tmp_path):
    res = _result()
    res.properties.groups.append(
        PropertyGroup(section="part", entries=[("truncated", "40")])
    )
    dlg = PropertiesDialog(tmp_path / "caseA.sim", res)
    tree = dlg.tabs.widget(1).tree
    last = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert last.text(0) == "… and 40 more"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_properties_gui.py -v`
Expected: FAIL — `AttributeError: 'PropertiesDialog' object has no attribute 'tabs'`

- [ ] **Step 3: Implement the tabbed dialog**

In `src/starpost/gui/views/properties_dialog.py`:

**3a.** Update the module docstring's first paragraph to:

```python
"""'Properties' window for a .sim file / data set: a General tab with its size
on disk and, once extracted, its report/monitor/iteration counts, and a Parts
tab showing the sim's Geometry > Parts tree (from the extracted properties).
"""
```

**3b.** Extend the imports — the PySide6 block gains `QTabWidget`, `QTreeWidget`, `QTreeWidgetItem`, `QWidget`, and a new first-party import goes **after** the PySide6 group (ruff/isort order: stdlib `pathlib`, third-party `PySide6`, first-party `starpost`):

```python
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.data.parts_tree import PartNode, build_parts_tree
```

**3c.** Replace the whole `PropertiesDialog` class body with:

```python
class PropertiesDialog(QDialog):
    def __init__(
        self, path: Path | str, result=None, parent=None, size_bytes: int | None = None
    ) -> None:
        super().__init__(parent)
        path = Path(path)
        self.setWindowTitle(f"Properties — {path.name}")

        self.tabs = QTabWidget()
        self.tabs.addTab(
            _general_tab(path, result, size_bytes), "General"
        )
        self.tabs.addTab(_PartsTab(result), "Parts")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Roomier than the old single-form window: the parts tree needs it.
        self.resize(520, 400)


def _general_tab(path: Path, result, size_bytes: int | None) -> QWidget:
    """The classic summary form: file size and, once the file has been
    extracted, its report/monitor/iteration counts."""
    # When size_bytes is given (e.g. the Data tab passes the data set's
    # portable-CSV size), use it; otherwise measure the file on disk.
    if size_bytes is not None:
        size = _human_size(size_bytes)
    else:
        try:
            size = _human_size(path.stat().st_size)
        except OSError:  # file moved/deleted/unreadable
            size = "—"

    # Reports/monitors/iterations only exist once the file is extracted. A
    # monitor is a single series; iterations is the longest series' length.
    extracted = result is not None and result.error is None
    if extracted:
        reports = str(len(result.reports))
        monitors = str(sum(len(p.series) for p in result.plots))
        iterations = str(
            max(
                (len(s.x) for p in result.plots for s in p.series),
                default=0,
            )
        )
    else:
        reports = monitors = iterations = "—"

    form = QFormLayout()
    form.addRow("File size", QLabel(size))
    form.addRow("Reports", QLabel(reports))
    form.addRow("Monitors", QLabel(monitors))
    form.addRow("Iterations", QLabel(iterations))

    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.addLayout(form)
    if not extracted:
        note = QLabel("Open the file to extract its reports and monitors.")
        note.setWordWrap(True)
        layout.addWidget(note)
    layout.addStretch(1)
    return tab


class _PartsTab(QWidget):
    """The sim's Geometry > Parts tree, or a re-extract hint when the data
    set predates parts extraction. ``self.tree`` is None in the hint case."""

    def __init__(self, result=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        props = result.properties if result is not None else None
        parts = build_parts_tree(props)
        if parts.empty:
            self.tree = None
            note = QLabel(
                "No parts data for this data set. Re-extract the .sim with "
                "this StarPost version to capture its Geometry ▸ Parts tree."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return

        tree = QTreeWidget()
        tree.setHeaderLabels(["Name", "Type", "Contents"])
        tree.setColumnWidth(0, 240)
        tree.setAlternatingRowColors(True)
        for node in parts.roots:
            tree.addTopLevelItem(_part_item(node))
        if parts.truncated:
            tree.addTopLevelItem(
                QTreeWidgetItem([f"… and {parts.truncated} more", "", ""])
            )
        layout.addWidget(tree)
        self.tree = tree


def _part_item(node: PartNode) -> QTreeWidgetItem:
    item = QTreeWidgetItem([node.name, node.type, _contents(node)])
    for child in node.children:
        item.addChild(_part_item(child))
    return item


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _contents(node: PartNode) -> str:
    """The Contents cell: leaf-part count for composites, surface/curve
    counts for leaf parts."""
    if node.children or node.leaf_count is not None and not node.surfaces:
        count = node.leaf_count
        if count is None:
            count = len(node.children)
        return _plural(count, "part")
    bits = []
    if node.surfaces.isdigit():
        bits.append(_plural(int(node.surfaces), "surface"))
    if node.curves.isdigit():
        bits.append(_plural(int(node.curves), "curve"))
    return ", ".join(bits)
```

Note operator precedence in `_contents`: `node.children or node.leaf_count is not None and not node.surfaces` evaluates as `children or ((leaf_count is not None) and (not surfaces))` — a node with children is always a composite; a childless node with a leaf count and no surface data (a `part_tree`-only entry) also renders as a composite. A merged top-level leaf (has `surfaces`) renders its surface/curve counts.

Leave `ScenePropertiesDialog`, `FolderPropertiesDialog`, `DataFolderPropertiesDialog`, and `_human_size` exactly as they are.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_properties_gui.py tests/test_parts_tree.py -v`
Expected: all PASS.

- [ ] **Step 5: Sanity-check the untouched dialogs and call sites**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py tests/test_gui_imports.py -q`
Expected: all PASS (both `PropertiesDialog` call sites construct it with the unchanged signature).

- [ ] **Step 6: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/views/properties_dialog.py tests/test_properties_gui.py
git commit -m "Properties dialog: General/Parts tabs with the Geometry parts tree"
```

---

### Task 3: Changelog, spec note, full suite

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md`

**Interfaces:** none — documentation and verification only.

- [ ] **Step 1: Changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]` → `### New Features`, add a new bullet directly after the existing "Sim properties captured at extraction" bullet:

```markdown
- **Properties window: Parts tab** — the per-sim Properties window (Files and
  Data tabs) is now tabbed: **General** keeps the classic size/reports/
  monitors/iterations summary, and a new **Parts** tab shows the sim's
  Geometry ▸ Parts tree — composites, nested sub-assemblies and every leaf
  part with its surface and curve counts — rebuilt from the extracted sim
  properties and sorted like STAR-CCM+'s own tree. Data sets extracted
  before this version show a re-extract hint instead.
```

- [ ] **Step 2: Spec open-question update**

In `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md`, section `## 4. Open questions`, replace item 1:

```markdown
1. **Dialog form** — *resolved 2026-07-16*: a tabbed dialog. Shipped with
   **General** (the classic summary) and **Parts** (the Geometry ▸ Parts
   tree); further tabs (Mesh / Regions / Physics / Tags) can follow the same
   pattern when wanted.
```

- [ ] **Step 3: Full suite and lint**

Run: `QT_QPA_PLATFORM=offscreen python scripts/run_tests.py`
Expected: all files pass (never bare pytest for the full run).

Run: `ruff check .`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md
git commit -m "Changelog: Properties window Parts tab"
```
