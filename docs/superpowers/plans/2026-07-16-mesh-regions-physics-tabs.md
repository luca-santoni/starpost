# Properties Dialog: Mesh / Regions / Physics Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add **Mesh**, **Regions**, and **Physics** tabs to the tabbed `PropertiesDialog`, in the same format as the Parts tab: a tree per tab built from the already-extracted `SimProperties` sections, with the same re-extract hint when the data is absent.

**Architecture:** Mirrors the Parts-tab split exactly. A pure, Qt-free module (`src/starpost/data/prop_rows.py`) turns `SimProperties` into generic `Row(label, value, children)` lists — one builder per tab. One generic `_RowsTab` widget (two columns: Item / Value) renders any of them; the dialog gains three `addTab` calls. Tab order: General, Parts, Mesh, Regions, Physics.

**Tech Stack:** Python 3.11, PySide6, pytest (GUI tests offscreen).

## Global Constraints

- `PropertiesDialog(path, result=None, parent=None, size_bytes=None)` signature unchanged; General and Parts tabs unchanged; the three other dialog classes and `_human_size` untouched.
- Data source is `SimResult.properties` only — **no changes to models, parser, store, portable, or the macro.** The sections consumed: `mesh` (keys `cell_count`, `interior_face_count`, `vertex_count`; empty values mean "not meshed"), `mesh_op` (per-op `type`, `meshers`, `base_size`, `target_surface_size`, `min_surface_size`, `prism_layers`), `region` (`type`, `continuum`, `boundaries`, `boundary_types` like `Velocity Inlet=1; Wall=43`), `interface` (a name-less group with `count`, plus one entry-less group per interface name), `continuum` (`models` `; `-joined, `regions` count), `solver` (entry-less named groups), `criterion` (`enabled` true/false).
- Ordering rules: **mesh operations keep extraction (pipeline) order** — it is semantic; regions, interfaces and continua sort case-insensitively (like Parts); solvers and stopping criteria keep extraction order (STAR shows them in a fixed order).
- Multi-valued cells split on `;` with whitespace stripped; `boundary_types` entries split on the **last** `=` (type names could contain `=`; counts cannot).
- Counts ≥ 1000 display with thousands separators (`21,737,167`); non-numeric values display as-is.
- The builders are pure: no Qt imports in `prop_rows.py` or its test file.
- `tests/test_properties_gui.py::test_dialog_has_general_and_parts_tabs` currently asserts exactly `["General", "Parts"]` — Task 2 MUST update it to the five labels (this is the one intentional edit to an existing test).
- Run single test files with `python -m pytest …` (`QT_QPA_PLATFORM=offscreen` for GUI files); full suite ONLY via `python scripts/run_tests.py` (Task 3). `ruff check .` clean (line-length 100, py311). Commit after every task.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/starpost/data/prop_rows.py` | Create | Pure `SimProperties` → `Row` builders for the three tabs |
| `src/starpost/gui/views/properties_dialog.py` | Modify | Generic `_RowsTab`; three new `addTab` calls |
| `tests/test_prop_rows.py` | Create | Qt-free builder tests |
| `tests/test_properties_gui.py` | Modify | Update tab-labels test; add per-tab GUI tests |
| `CHANGELOG.md` | Modify | Fold the new tabs into the existing Properties-window bullet (Task 3) |
| `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md` | Modify | Note the further tabs shipped (Task 3) |

---

### Task 1: Pure row builders (`data/prop_rows.py`)

**Files:**
- Create: `src/starpost/data/prop_rows.py`
- Test: `tests/test_prop_rows.py` (create)

**Interfaces:**
- Consumes: `SimProperties` / `PropertyGroup` from `starpost.data.models`.
- Produces (Task 2 relies on these exact names):
  - `Row(label: str, value: str = "", children: list[Row] = [])`
  - `build_mesh_rows(props: SimProperties | None) -> list[Row]`
  - `build_region_rows(props: SimProperties | None) -> list[Row]`
  - `build_physics_rows(props: SimProperties | None) -> list[Row]`
  - Each returns `[]` when there is no data for its tab (that renders the re-extract hint).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prop_rows.py`:

```python
"""Row builders for the Mesh / Regions / Physics properties tabs: pure
SimProperties -> Row transformations, no Qt. Fixtures echo the sections the
extraction macro writes (validated against a real sim)."""
from starpost.data.models import PropertyGroup, SimProperties
from starpost.data.prop_rows import (
    Row,
    build_mesh_rows,
    build_physics_rows,
    build_region_rows,
)


def _g(section, name, *entries):
    return PropertyGroup(section=section, name=name, entries=list(entries))


def _mesh_props() -> SimProperties:
    return SimProperties(groups=[
        _g("mesh", "", ("cell_count", "21737167"),
           ("interior_face_count", "65351479"), ("vertex_count", "23272181")),
        _g("mesh_op", "Surface Wrapper",
           ("type", "SurfaceWrapperAutoMeshOperation"),
           ("meshers", "Surface Wrapper"), ("base_size", "0.01 m")),
        _g("mesh_op", "Automated Mesh",
           ("type", "AutoMeshOperation"),
           ("meshers", "Surface Remesher; Trimmed Cell Mesher"),
           ("base_size", "24.0 mm"), ("prism_layers", "1")),
    ])


def test_mesh_counts_format_with_separators():
    rows = build_mesh_rows(_mesh_props())
    assert (rows[0].label, rows[0].value) == ("Cells", "21,737,167")
    assert (rows[1].label, rows[1].value) == ("Interior faces", "65,351,479")
    assert (rows[2].label, rows[2].value) == ("Vertices", "23,272,181")


def test_mesh_ops_keep_pipeline_order_with_detail_children():
    rows = build_mesh_rows(_mesh_props())
    ops = rows[3:]
    assert [(r.label, r.value) for r in ops] == [
        ("Surface Wrapper", "SurfaceWrapperAutoMeshOperation"),
        ("Automated Mesh", "AutoMeshOperation"),
    ]
    auto = ops[1]
    meshers = auto.children[0]
    assert meshers.label == "Meshers"
    assert [c.label for c in meshers.children] == [
        "Surface Remesher", "Trimmed Cell Mesher",
    ]
    assert ("Base size", "24.0 mm") in [(c.label, c.value) for c in auto.children]
    assert ("Prism layers", "1") in [(c.label, c.value) for c in auto.children]
    # Keys the extraction didn't produce are simply absent.
    assert "Target surface size" not in [c.label for c in auto.children]


def test_mesh_not_meshed_collapses_counts():
    props = SimProperties(groups=[
        _g("mesh", "", ("cell_count", ""), ("interior_face_count", ""),
           ("vertex_count", "")),
    ])
    rows = build_mesh_rows(props)
    assert [(r.label, r.value) for r in rows] == [("Volume mesh", "not meshed")]


def test_regions_sorted_with_boundary_breakdown():
    props = SimProperties(groups=[
        _g("region", "Radiator", ("type", "Porous Region"),
           ("continuum", "Physics 1"), ("boundaries", "8"),
           ("boundary_types", "Wall=4; Baffle Boundary=1")),
        _g("region", "External flow", ("type", "Fluid Region"),
           ("continuum", "Physics 1"), ("boundaries", "54"),
           ("boundary_types", "Symmetry Plane=3; Wall=43")),
        _g("interface", "", ("count", "2")),
        _g("interface", "Fan shroud"),
        _g("interface", "Fan downstream"),
    ])
    rows = build_region_rows(props)
    assert [(r.label, r.value) for r in rows] == [
        ("External flow", "Fluid Region"),
        ("Radiator", "Porous Region"),
        ("Interfaces", "2"),
    ]
    ext = rows[0]
    assert (ext.children[0].label, ext.children[0].value) == (
        "Continuum", "Physics 1",
    )
    boundaries = ext.children[1]
    assert (boundaries.label, boundaries.value) == ("Boundaries", "54")
    assert [(c.label, c.value) for c in boundaries.children] == [
        ("Symmetry Plane", "3"), ("Wall", "43"),
    ]
    # Interface names sort case-insensitively under the count row.
    assert [c.label for c in rows[2].children] == [
        "Fan downstream", "Fan shroud",
    ]


def test_physics_continua_solvers_and_criteria():
    props = SimProperties(groups=[
        _g("continuum", "Physics 1",
           ("models", "Three Dimensional; Gas; Turbulent"), ("regions", "3")),
        _g("solver", "Wall Distance"),
        _g("solver", "Coupled Implicit"),
        _g("criterion", "Maximum Steps", ("enabled", "true")),
        _g("criterion", "Stop File", ("enabled", "false")),
    ])
    rows = build_physics_rows(props)
    assert (rows[0].label, rows[0].value) == ("Physics 1", "3 regions")
    models = rows[0].children[0]
    assert (models.label, models.value) == ("Models", "3")
    assert [c.label for c in models.children] == [
        "Three Dimensional", "Gas", "Turbulent",
    ]
    solvers = rows[1]
    assert (solvers.label, solvers.value) == ("Solvers", "2")
    # Solver order is STAR's own — not sorted.
    assert [c.label for c in solvers.children] == [
        "Wall Distance", "Coupled Implicit",
    ]
    criteria = rows[2]
    assert (criteria.label, criteria.value) == ("Stopping criteria", "2")
    assert [(c.label, c.value) for c in criteria.children] == [
        ("Maximum Steps", "Enabled"), ("Stop File", "Disabled"),
    ]


def test_singular_region_count():
    props = SimProperties(groups=[
        _g("continuum", "Physics 1", ("models", "Gas"), ("regions", "1")),
    ])
    assert build_physics_rows(props)[0].value == "1 region"


def test_no_data_returns_empty():
    assert build_mesh_rows(None) == []
    assert build_region_rows(None) == []
    assert build_physics_rows(None) == []
    only_parts = SimProperties(groups=[_g("part", "wing", ("surfaces", "1"))])
    assert build_mesh_rows(only_parts) == []
    assert build_region_rows(only_parts) == []
    assert build_physics_rows(only_parts) == []


def test_boundary_type_with_equals_in_name():
    props = SimProperties(groups=[
        _g("region", "R", ("boundaries", "1"),
           ("boundary_types", "Weird=Type=2")),
    ])
    boundaries = build_region_rows(props)[0].children[0]
    assert [(c.label, c.value) for c in boundaries.children] == [
        ("Weird=Type", "2"),
    ]


def test_row_dataclass_defaults():
    r = Row("label")
    assert r.value == "" and r.children == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_prop_rows.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.data.prop_rows'`

- [ ] **Step 3: Implement the builders**

Create `src/starpost/data/prop_rows.py`:

```python
"""Row builders for the Properties dialog's Mesh / Regions / Physics tabs.

Each builder turns the flat extracted ``SimProperties`` sections into generic
``Row(label, value, children)`` entries for a two-column tree — pure data
logic, no Qt, mirroring how ``parts_tree`` feeds the Parts tab. An empty list
means "no data for this tab" (the GUI shows its re-extract hint).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from starpost.data.models import SimProperties


@dataclass
class Row:
    """One tree row: a label, an optional value, and child rows."""
    label: str
    value: str = ""
    children: list["Row"] = field(default_factory=list)


def _split_list(value: str) -> list[str]:
    """A ``; ``-joined extracted cell as its items, whitespace stripped."""
    return [s.strip() for s in value.split(";") if s.strip()]


def _fmt_count(value: str) -> str:
    """Thousands separators for numeric counts; anything else as-is."""
    return f"{int(value):,}" if value.isdigit() else value


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def build_mesh_rows(props: Optional[SimProperties]) -> list[Row]:
    """Mesh tab: cell/face/vertex counts, then the mesh-operation pipeline.
    Operations keep extraction order — it is the pipeline order."""
    if props is None:
        return []
    rows: list[Row] = []
    mesh = props.get("mesh")
    if mesh is not None:
        if (mesh.get("cell_count") or "") == "":
            # The macro writes empty values when the sim has no volume mesh.
            rows.append(Row("Volume mesh", "not meshed"))
        else:
            rows.append(Row("Cells", _fmt_count(mesh.get("cell_count") or "")))
            rows.append(
                Row("Interior faces",
                    _fmt_count(mesh.get("interior_face_count") or ""))
            )
            rows.append(
                Row("Vertices", _fmt_count(mesh.get("vertex_count") or ""))
            )
    for g in props.groups:
        if g.section != "mesh_op" or not g.name:
            continue
        op = Row(g.name, g.get("type") or "")
        meshers = g.get("meshers")
        if meshers:
            op.children.append(
                Row("Meshers", children=[Row(m) for m in _split_list(meshers)])
            )
        for key, label in (
            ("base_size", "Base size"),
            ("target_surface_size", "Target surface size"),
            ("min_surface_size", "Minimum surface size"),
            ("prism_layers", "Prism layers"),
        ):
            value = g.get(key)
            if value:
                op.children.append(Row(label, value))
        rows.append(op)
    return rows


def build_region_rows(props: Optional[SimProperties]) -> list[Row]:
    """Regions tab: one row per region (sorted) with its continuum and
    boundary-type breakdown, then the interfaces."""
    if props is None:
        return []
    rows: list[Row] = []
    regions = [g for g in props.groups if g.section == "region" and g.name]
    for g in sorted(regions, key=lambda g: g.name.casefold()):
        region = Row(g.name, g.get("type") or "")
        continuum = g.get("continuum")
        if continuum:
            region.children.append(Row("Continuum", continuum))
        boundaries = Row("Boundaries", g.get("boundaries") or "")
        for part in _split_list(g.get("boundary_types") or ""):
            # Split on the LAST "=": type names could contain "=", the
            # trailing count cannot.
            btype, _, count = part.rpartition("=")
            if btype:
                boundaries.children.append(Row(btype, count))
        if boundaries.value or boundaries.children:
            region.children.append(boundaries)
        rows.append(region)
    names = [g for g in props.groups if g.section == "interface" and g.name]
    head = props.get("interface")
    if names or head is not None:
        count = (head.get("count") if head else None) or str(len(names))
        rows.append(
            Row("Interfaces", count,
                children=[Row(g.name) for g in
                          sorted(names, key=lambda g: g.name.casefold())])
        )
    return rows


def build_physics_rows(props: Optional[SimProperties]) -> list[Row]:
    """Physics tab: continua (sorted) with their model lists, then solvers
    and stopping criteria in STAR's own order."""
    if props is None:
        return []
    rows: list[Row] = []
    continua = [g for g in props.groups if g.section == "continuum" and g.name]
    for g in sorted(continua, key=lambda g: g.name.casefold()):
        region_count = g.get("regions") or ""
        value = (
            _plural(int(region_count), "region")
            if region_count.isdigit() else region_count
        )
        continuum = Row(g.name, value)
        models = _split_list(g.get("models") or "")
        if models:
            continuum.children.append(
                Row("Models", str(len(models)),
                    children=[Row(m) for m in models])
            )
        rows.append(continuum)
    solvers = [g for g in props.groups if g.section == "solver" and g.name]
    if solvers:
        rows.append(
            Row("Solvers", str(len(solvers)),
                children=[Row(g.name) for g in solvers])
        )
    criteria = [g for g in props.groups if g.section == "criterion" and g.name]
    if criteria:
        states = {"true": "Enabled", "false": "Disabled"}
        rows.append(
            Row("Stopping criteria", str(len(criteria)),
                children=[
                    Row(g.name,
                        states.get((g.get("enabled") or "").lower(),
                                   g.get("enabled") or ""))
                    for g in criteria
                ])
        )
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_prop_rows.py tests/test_parts_tree.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/data/prop_rows.py tests/test_prop_rows.py
git commit -m "Data: row builders for the Mesh/Regions/Physics properties tabs"
```

---

### Task 2: The three tabs in `PropertiesDialog`

**Files:**
- Modify: `src/starpost/gui/views/properties_dialog.py`
- Modify: `tests/test_properties_gui.py`

**Interfaces:**
- Consumes: `Row`, `build_mesh_rows`, `build_region_rows`, `build_physics_rows` from Task 1.
- Produces: `PropertiesDialog.tabs` now has five tabs: General, Parts, Mesh, Regions, Physics. `_RowsTab(rows, what)` widget with `self.tree` (`QTreeWidget` or `None` in the empty-hint case). General/Parts tabs and everything else in the file unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_properties_gui.py`:

**1a.** Update the existing tab-labels assertion in `test_dialog_has_general_and_parts_tabs`:

```python
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
        "General", "Parts", "Mesh", "Regions", "Physics",
    ]
```

**1b.** Append these tests (module imports for `PropertyGroup`/`SimProperties` already exist at the top of the file):

```python
def _full_props_result() -> SimResult:
    res = _result(with_parts=False)
    res.properties = SimProperties(groups=[
        PropertyGroup(section="mesh",
                      entries=[("cell_count", "21737167"),
                               ("interior_face_count", "65351479"),
                               ("vertex_count", "23272181")]),
        PropertyGroup(section="mesh_op", name="Automated Mesh",
                      entries=[("type", "AutoMeshOperation"),
                               ("meshers", "Surface Remesher"),
                               ("base_size", "24.0 mm")]),
        PropertyGroup(section="region", name="External flow",
                      entries=[("type", "Fluid Region"),
                               ("continuum", "Physics 1"),
                               ("boundaries", "54"),
                               ("boundary_types", "Wall=43; Symmetry Plane=3")]),
        PropertyGroup(section="interface", entries=[("count", "1")]),
        PropertyGroup(section="interface", name="Fan shroud"),
        PropertyGroup(section="continuum", name="Physics 1",
                      entries=[("models", "Gas; Turbulent"),
                               ("regions", "3")]),
        PropertyGroup(section="solver", name="Coupled Implicit"),
        PropertyGroup(section="criterion", name="Maximum Steps",
                      entries=[("enabled", "true")]),
    ])
    return res


def test_mesh_tab_shows_counts_and_pipeline(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _full_props_result())
    tree = dlg.tabs.widget(2).tree
    assert tree is not None
    assert tree.headerItem().text(0) == "Item"
    assert tree.headerItem().text(1) == "Value"
    top = [(tree.topLevelItem(i).text(0), tree.topLevelItem(i).text(1))
           for i in range(tree.topLevelItemCount())]
    assert top == [
        ("Cells", "21,737,167"),
        ("Interior faces", "65,351,479"),
        ("Vertices", "23,272,181"),
        ("Automated Mesh", "AutoMeshOperation"),
    ]
    op = tree.topLevelItem(3)
    assert op.child(0).text(0) == "Meshers"
    assert op.child(0).child(0).text(0) == "Surface Remesher"
    assert (op.child(1).text(0), op.child(1).text(1)) == (
        "Base size", "24.0 mm",
    )


def test_regions_tab_shows_regions_and_interfaces(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _full_props_result())
    tree = dlg.tabs.widget(3).tree
    region = tree.topLevelItem(0)
    assert (region.text(0), region.text(1)) == ("External flow", "Fluid Region")
    assert (region.child(0).text(0), region.child(0).text(1)) == (
        "Continuum", "Physics 1",
    )
    boundaries = region.child(1)
    assert (boundaries.text(0), boundaries.text(1)) == ("Boundaries", "54")
    assert (boundaries.child(0).text(0), boundaries.child(0).text(1)) == (
        "Wall", "43",
    )
    interfaces = tree.topLevelItem(1)
    assert (interfaces.text(0), interfaces.text(1)) == ("Interfaces", "1")
    assert interfaces.child(0).text(0) == "Fan shroud"


def test_physics_tab_shows_continua_solvers_criteria(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _full_props_result())
    tree = dlg.tabs.widget(4).tree
    continuum = tree.topLevelItem(0)
    assert (continuum.text(0), continuum.text(1)) == ("Physics 1", "3 regions")
    models = continuum.child(0)
    assert (models.text(0), models.text(1)) == ("Models", "2")
    assert models.child(1).text(0) == "Turbulent"
    solvers = tree.topLevelItem(1)
    assert (solvers.text(0), solvers.text(1)) == ("Solvers", "1")
    criteria = tree.topLevelItem(2)
    assert (criteria.child(0).text(0), criteria.child(0).text(1)) == (
        "Maximum Steps", "Enabled",
    )


def test_new_tabs_without_data_show_reextract_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(with_parts=False))
    for index, what in ((2, "mesh"), (3, "region"), (4, "physics")):
        tab = dlg.tabs.widget(index)
        assert tab.tree is None
        assert any("Re-extract" in t for t in _labels(tab)), what
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_properties_gui.py -v`
Expected: the updated labels test and the 4 new tests FAIL (tab count is 2); the other existing tests still PASS.

- [ ] **Step 3: Implement the tabs**

In `src/starpost/gui/views/properties_dialog.py`:

**3a.** Extend the first-party import block:

```python
from starpost.data.parts_tree import PartNode, build_parts_tree
from starpost.data.prop_rows import (
    Row,
    build_mesh_rows,
    build_physics_rows,
    build_region_rows,
)
```

**3b.** In `PropertiesDialog.__init__`, after the existing `addTab(... "Parts")` line, add:

```python
        props = result.properties if result is not None else None
        self.tabs.addTab(_RowsTab(build_mesh_rows(props), "mesh"), "Mesh")
        self.tabs.addTab(_RowsTab(build_region_rows(props), "region"), "Regions")
        self.tabs.addTab(_RowsTab(build_physics_rows(props), "physics"), "Physics")
```

**3c.** Add after the `_PartsTab` class (same file):

```python
class _RowsTab(QWidget):
    """A generic Item/Value tree tab fed by prop_rows builders, with the same
    re-extract hint as the Parts tab when there is no data for it.
    ``self.tree`` is None in the hint case."""

    def __init__(self, rows: list[Row], what: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        if not rows:
            self.tree = None
            note = QLabel(
                f"No {what} data for this data set. Re-extract the .sim with "
                "this StarPost version to capture it."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return
        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Value"])
        tree.setColumnWidth(0, 240)
        tree.setAlternatingRowColors(True)
        for row in rows:
            tree.addTopLevelItem(_row_item(row))
        layout.addWidget(tree)
        self.tree = tree


def _row_item(row: Row) -> QTreeWidgetItem:
    item = QTreeWidgetItem([row.label, row.value])
    for child in row.children:
        item.addChild(_row_item(child))
    return item
```

Nothing else in the file changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_properties_gui.py tests/test_prop_rows.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/views/properties_dialog.py tests/test_properties_gui.py
git commit -m "Properties dialog: Mesh, Regions and Physics tabs"
```

---

### Task 3: Changelog, spec note, full suite

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md`

- [ ] **Step 1: Changelog**

In `CHANGELOG.md`, the Unreleased bullet currently starting `- **Properties window: Parts tab** — the per-sim Properties window (Files and Data tabs) is now tabbed: …` is replaced by:

```markdown
- **Properties window: Parts, Mesh, Regions and Physics tabs** — the per-sim
  Properties window (Files and Data tabs) is now tabbed. **General** keeps
  the classic size/reports/monitors/iterations summary; **Parts** shows the
  sim's Geometry ▸ Parts tree — composites, nested sub-assemblies and every
  leaf part with its surface and curve counts — sorted like STAR-CCM+'s own
  tree; **Mesh** shows the cell/face/vertex counts and the mesh-operation
  pipeline with each operation's meshers and key sizes; **Regions** lists
  each region's physics continuum and boundary-type breakdown plus the
  interfaces; **Physics** lists each continuum's enabled models, the solvers
  and the stopping criteria. Everything is read from the extracted sim
  properties — data sets extracted before this version show a re-extract
  hint instead.
```

- [ ] **Step 2: Spec note**

In the spec's `## 4. Open questions`, item 1 currently ends `further tabs (Mesh / Regions / Physics / Tags) can follow the same pattern when wanted.` — replace that clause with: `Mesh / Regions / Physics tabs shipped 2026-07-16 in the same format; a Tags tab can follow the same pattern when wanted.`

- [ ] **Step 3: Full suite and lint**

Run: `QT_QPA_PLATFORM=offscreen python scripts/run_tests.py` — all files pass.
Run: `ruff check .` — clean.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md
git commit -m "Changelog: Mesh, Regions and Physics properties tabs"
```
