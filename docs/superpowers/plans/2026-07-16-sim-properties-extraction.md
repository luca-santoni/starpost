# Sim Properties Extraction (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** During the existing single extraction pass, capture the simulation's own metadata (solution state, mesh counts, regions, physics, mesh pipeline, parts, tags, STAR-CCM+ version) into a new `<simname>__properties.csv`, parse it into a `SimProperties` model on `SimResult`, persist it in the crash-recovery cache, and include it in portable data-CSV exports (format v3).

**Architecture:** A new `exportProperties` section in the canonical extraction macro (`extract_all.java.j2`) writes flat `section,name,key,value` rows — every section in its own try/catch, everything outside `star.common` reached only via reflection. The Python side parses the CSV into generic string groups (`PropertyGroup` / `SimProperties`), the runner appends the STAR-CCM+ version regex-matched from the batch banner, and the store/portable layers round-trip it. GUI is explicitly out of scope. Spec: `docs/superpowers/specs/2026-07-16-sim-properties-extraction-design.md`.

**Tech Stack:** Python 3.11, PySide6 app (but no GUI work here), Jinja2-templated Java macro, pytest.

## Global Constraints

- **STAR-CCM+ runs once per file** — the properties export rides the existing extraction macro; no new invocation, no extra license checkout.
- **Macro: getters only.** Never call `update()`, `initializeSolution()`, `createSimulationSummary()`, or anything that computes/meshes/renders/mutates.
- **Macro: no compile-time references outside `star.common` + `star.base.report` + `star.vis`** (the imports already in `extract_all.java.j2`). `star.meshing.*`, `star.cadmodeler.*`, `star.prismmesher.*` only via `Class.forName` + reflection — a compile error is fatal to the *whole* extraction.
- **`SimResult.signature()` must not change** — properties must never affect the batch homogeneity check.
- **Portable CSV:** `VERSION` becomes 3; the reader must accept both `2` and `3`.
- Run single test files with `python -m pytest tests/test_x.py -v`; run the **full suite only via `python scripts/run_tests.py`** (GUI tests need per-file process isolation). On a headless machine prefix GUI-touching runs with `QT_QPA_PLATFORM=offscreen` (the new tests here don't instantiate Qt).
- `ruff check .` must stay clean (line-length 100, py311 target).
- Commit after every task. User-facing change goes in `CHANGELOG.md` (Task 7), newest-first style.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/starpost/data/models.py` | Modify | Add `PropertyGroup`, `SimProperties`; add `SimResult.properties` field |
| `src/starpost/core/result_parser.py` | Modify | `_parse_properties()` + wiring into `parse_sim_output()` |
| `src/starpost/macros/extract_all.java.j2` | Modify | `exportProperties` + per-section helpers |
| `src/starpost/data/store.py` | Modify | Cache (de)serialisation of `properties` |
| `src/starpost/data/portable.py` | Modify | v3 format: `prop` rows, accept v2+v3 on read |
| `src/starpost/core/starccm_runner.py` | Modify | Capture STAR-CCM+ version from the batch banner in `extract()` |
| `tests/test_properties.py` | Create | Model, parser, macro-render, store, runner-banner tests |
| `tests/test_portable.py` | Modify | v3 round-trip, v2-still-imports, unsupported-version tests |
| `CHANGELOG.md` | Modify | Unreleased → New Features entry (Task 7) |

---

### Task 1: `PropertyGroup` / `SimProperties` model

**Files:**
- Modify: `src/starpost/data/models.py`
- Test: `tests/test_properties.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces (relied on by every later task):
  - `PropertyGroup(section: str, name: str = "", entries: list[tuple[str, str]] = [])` with `get(key: str) -> Optional[str]`
  - `SimProperties(groups: list[PropertyGroup] = [])` with `get(section: str, name: str = "") -> Optional[PropertyGroup]`
  - `SimResult.properties: Optional[SimProperties] = None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_properties.py`:

```python
"""Sim properties feature: model, properties-CSV parsing, macro generation,
cache persistence, and version-banner capture (the Properties dialog's
backend; the dialog itself is a later pass)."""
from starpost.data.models import (
    PropertyGroup,
    Report,
    SimProperties,
    SimResult,
)


def test_property_group_key_lookup():
    g = PropertyGroup(
        section="region", name="Fluid",
        entries=[("boundaries", "46"), ("continuum", "Physics 1")],
    )
    assert g.get("boundaries") == "46"
    assert g.get("continuum") == "Physics 1"
    assert g.get("missing") is None


def test_sim_properties_group_lookup():
    props = SimProperties(groups=[
        PropertyGroup(section="sim", entries=[("units_system", "SI")]),
        PropertyGroup(section="region", name="Fluid",
                      entries=[("boundaries", "46")]),
    ])
    assert props.get("sim").get("units_system") == "SI"
    assert props.get("region", "Fluid").get("boundaries") == "46"
    # Name must match exactly; sim-wide sections use the default "".
    assert props.get("region") is None
    assert props.get("nope") is None


def test_sim_result_signature_ignores_properties():
    # Differing properties must never push a batch out of comparison mode.
    a = SimResult(sim_path="/c/a.sim", reports=[Report(name="Drag", value=1.0)])
    b = SimResult(
        sim_path="/c/b.sim",
        reports=[Report(name="Drag", value=2.0)],
        properties=SimProperties(groups=[PropertyGroup(section="sim")]),
    )
    assert a.signature() == b.signature()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_properties.py -v`
Expected: FAIL — `ImportError: cannot import name 'PropertyGroup'`

- [ ] **Step 3: Implement the model**

In `src/starpost/data/models.py`, add after the `MediaArtifact` dataclass (before `SimResult`):

```python
@dataclass
class PropertyGroup:
    """One entity's extracted sim properties: a section ("mesh", "region", ...),
    the entity's name ("" for sim-wide sections), and its key/value entries in
    extraction order."""
    section: str
    name: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)

    def get(self, key: str) -> Optional[str]:
        for k, v in self.entries:
            if k == key:
                return v
        return None


@dataclass
class SimProperties:
    """Simulation metadata captured at extraction time (solution state, mesh
    counts, regions, physics, tags, ...). Deliberately generic strings, not
    typed fields: the key set drifts across STAR-CCM+ releases and extraction
    tiers, and the consumer is a display dialog — anything needing a number
    parses it at the point of use."""
    groups: list[PropertyGroup] = field(default_factory=list)

    def get(self, section: str, name: str = "") -> Optional[PropertyGroup]:
        for g in self.groups:
            if g.section == section and g.name == name:
                return g
        return None
```

In `SimResult`, add one field after `media` (before `extracted_at`):

```python
    # Simulation metadata captured during extraction (None for results
    # extracted before this feature). Never part of signature().
    properties: Optional[SimProperties] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_properties.py -v`
Expected: 3 PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/data/models.py tests/test_properties.py
git commit -m "Data model: SimProperties/PropertyGroup for extracted sim metadata"
```

---

### Task 2: Properties-CSV parser

**Files:**
- Modify: `src/starpost/core/result_parser.py`
- Test: `tests/test_properties.py`

**Interfaces:**
- Consumes: `PropertyGroup`, `SimProperties` from Task 1.
- Produces: `_parse_properties(path: Path) -> Optional[SimProperties]`; `parse_sim_output()` now sets `result.properties` from `<simname>__properties.csv` (missing file → `None`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_properties.py`:

```python
from starpost.core.result_parser import parse_sim_output

CLASSIFICATION = {"residual_keywords": ["residual"], "force_keywords": ["force"]}


def test_parse_sim_output_reads_properties(tmp_path):
    (tmp_path / "caseA__properties.csv").write_text(
        "section,name,key,value\n"
        "sim,,units_system,SI\n"
        "solution,,iteration,4500\n"
        "solution,,initialized,true\n"
        "mesh,,cell_count,12400312\n"
        'region,Fluid,boundary_types,"Velocity Inlet=1; Wall=44"\n'
        "tag,baseline,,\n"
        "future_section,thing,key,value\n"
    )
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    props = res.properties
    assert props is not None
    assert props.get("sim").get("units_system") == "SI"
    # Consecutive same-(section, name) rows form one group, order preserved.
    assert props.get("solution").entries == [
        ("iteration", "4500"), ("initialized", "true"),
    ]
    # Quoted multi-valued cells survive intact.
    assert (props.get("region", "Fluid").get("boundary_types")
            == "Velocity Inlet=1; Wall=44")
    # A key-less row registers the group with no entries.
    assert props.get("tag", "baseline").entries == []
    # Unknown sections pass through — forward-compat with future macro tiers.
    assert props.get("future_section", "thing").get("key") == "value"


def test_parse_sim_output_no_properties_csv_is_none(tmp_path):
    # Older extractions simply have no properties CSV.
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert res.properties is None


def test_parse_properties_group_order_follows_the_file(tmp_path):
    (tmp_path / "caseA__properties.csv").write_text(
        "section,name,key,value\n"
        "solver,Segregated Flow,,\n"
        "solver,Segregated Energy,,\n"
        "mesh,,cell_count,100\n"
    )
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert [(g.section, g.name) for g in res.properties.groups] == [
        ("solver", "Segregated Flow"),
        ("solver", "Segregated Energy"),
        ("mesh", ""),
    ]


def test_parse_properties_empty_value_is_kept(tmp_path):
    # "not meshed": the macro writes mesh rows with empty values, which must
    # stay distinguishable from an absent section.
    (tmp_path / "caseA__properties.csv").write_text(
        "section,name,key,value\n"
        "mesh,,cell_count,\n"
    )
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert res.properties.get("mesh").get("cell_count") == ""
    assert res.properties.get("mesh").get("vertex_count") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_properties.py -v`
Expected: the 3 new tests that write a CSV FAIL (`AttributeError: 'NoneType' object has no attribute 'get'`); `test_parse_sim_output_no_properties_csv_is_none` PASSES already (the field defaults to `None`) and pins the back-compat behaviour. The 3 Task-1 tests still PASS.

- [ ] **Step 3: Implement the parser**

In `src/starpost/core/result_parser.py`:

Add `PropertyGroup` and `SimProperties` to the `starpost.data.models` import list (alphabetical position: after `PlotSeries`, before `Report`).

In `parse_sim_output()`, after the `result.screenplays = ...` assignment, add:

```python
    result.properties = _parse_properties(
        output_dir / f"{sim_name}__properties.csv"
    )
```

Add the parser function (after `_parse_screenplays`):

```python
def _parse_properties(path: Path) -> Optional[SimProperties]:
    """Read the properties CSV (``section,name,key,value`` rows) the extraction
    macro wrote. Consecutive rows sharing (section, name) form one
    PropertyGroup, preserving file order; a key-less row just registers the
    group (e.g. a tag). Unknown sections pass through untouched — that's the
    forward-compat contract with future macro tiers. Missing file -> None
    (older extractions have no properties CSV)."""
    if not path.exists():
        return None
    props = SimProperties()
    current: Optional[PropertyGroup] = None
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            section = (row.get("section") or "").strip()
            if not section:
                if any((v or "").strip() for v in row.values()):
                    log.warning("properties row without section skipped: %r", row)
                continue
            name = (row.get("name") or "").strip()
            if current is None or (current.section, current.name) != (section, name):
                current = PropertyGroup(section=section, name=name)
                props.groups.append(current)
            key = (row.get("key") or "").strip()
            if key:
                current.entries.append((key, row.get("value") or ""))
    return props
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_properties.py tests/test_result_parser.py -v`
Expected: all PASS (including the existing parser tests — `parse_sim_output` on a dir without the CSV must still work).

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/core/result_parser.py tests/test_properties.py
git commit -m "Parser: read __properties.csv into SimProperties"
```

---

### Task 3: Macro — `exportProperties` in `extract_all.java.j2`

**Files:**
- Modify: `src/starpost/macros/extract_all.java.j2`
- Test: `tests/test_properties.py`

**Interfaces:**
- Consumes: the template's existing helpers `esc(String)`, `presentationName(Object)`, `invokeQuiet(Object, String)`.
- Produces: `<simname>__properties.csv` with header `section,name,key,value`, read by Task 2's parser. Sections written: `sim`, `solution`, `mesh`, `region`, `interface`, `continuum`, `solver`, `criterion`, `mesh_op`, `part`, `tag`.

**Rules for this task (from the spec, non-negotiable):** getters only; per-section try/catch; classes outside `star.common`/`star.base.report`/`star.vis` only via `Class.forName` (no new `import` lines); numbers via plain `String.valueOf` (locale-safe); counts and count-per-type summaries instead of per-item dumps; parts capped at 200.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_properties.py`:

```python
from pathlib import Path

from starpost.core.macro_generator import render_macro


def test_extract_macro_exports_properties(tmp_path):
    path = render_macro(Path("/out"), tmp_path)
    text = path.read_text()
    assert "exportProperties" in text
    assert "__properties.csv" in text
    assert "section,name,key,value" in text
    # Fragile packages are reached reflectively.
    assert 'Class.forName("star.meshing.MeshOperationManager")' in text
    assert '"star.common.TagManager"' in text
    assert '"star.meshing.BaseSize"' in text
    assert '"star.meshing.PartsTargetSurfaceSize"' in text
    assert '"star.meshing.PartsMinimumSurfaceSize"' in text
    assert '"star.prismmesher.NumPrismLayers"' in text
    # Getters only — nothing that computes or mutates.
    assert "initializeSolution" not in text
    assert "createSimulationSummary" not in text
    assert ".update(" not in text


def test_extract_macro_braces_balance(tmp_path):
    path = render_macro(Path("/out"), tmp_path)
    text = path.read_text()
    assert text.count("{") == text.count("}")


def test_extract_macro_no_compile_time_refs_outside_common(tmp_path):
    # A compile error kills the whole extraction, so fragile packages may
    # appear only inside string literals (Class.forName) or comments.
    import re

    text = render_macro(Path("/out"), tmp_path).read_text()
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)  # strip string literals
    text = re.sub(r"//[^\n]*", "", text)             # strip line comments
    for pkg in ("star.meshing", "star.cadmodeler", "star.prismmesher",
                "star.screenplay"):
        assert pkg not in text, f"compile-time reference to {pkg}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_properties.py -v`
Expected: `test_extract_macro_exports_properties` FAILS (`"exportProperties" in text`); the two guard tests PASS already (they must also pass after the change).

- [ ] **Step 3: Implement the macro section**

All edits in `src/starpost/macros/extract_all.java.j2`.

**3a.** In the header comment's output list, after the `__screenplays_index.csv` line, add:

```java
//   <simname>__properties.csv       section,name,key,value (sim metadata:
//                                   solution state, mesh, regions, physics...)
```

**3b.** In `execute()`, after `exportScreenplays(sim, simName, dir);`, add:

```java
        exportProperties(sim, simName, dir);
```

**3c.** Before the final closing brace of the class, append:

```java
    // ------------------------------------------------------------------
    // Sim properties: the simulation's own metadata (solution state, mesh
    // counts, regions, physics, mesh pipeline, parts, tags) as flat
    // section,name,key,value rows. Getters only — nothing here may compute,
    // initialize or mutate. Every section has its own try/catch, so a failing
    // section loses its rows only, never the file, never the extraction.
    // Classes outside star.common are reached exclusively via reflection: a
    // compile-time reference would be fatal on releases that moved them.
    private void exportProperties(Simulation sim, String simName, String dir) {
        String out = dir + File.separator + simName + "__properties.csv";
        try (PrintWriter w = new PrintWriter(new FileWriter(out))) {
            w.println("section,name,key,value");
            propsSim(sim, w);
            propsSolution(sim, w);
            propsMesh(sim, w);
            propsRegions(sim, w);
            propsInterfaces(sim, w);
            propsContinua(sim, w);
            propsSolvers(sim, w);
            propsCriteria(sim, w);
            propsMeshOps(sim, w);
            propsParts(sim, w);
            propsTags(sim, w);
        } catch (Exception e) {
            sim.println("starpost: failed to write properties CSV: "
                + e.getMessage());
        }
    }

    // One properties row.
    private void prow(PrintWriter w, String section, String name, String key,
                      String value) {
        w.println(esc(section) + "," + esc(name) + "," + esc(key) + ","
            + esc(value));
    }

    // Object -> CSV cell text; null (a failed reflective read) becomes "".
    private String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private void propsSim(Simulation sim, PrintWriter w) {
        try {
            // The selected units system (SI / USCS). The option object's exact
            // accessor varies, so probe, then fall back to its display text.
            Object opt = sim.getUnitsManager().getSystemOption();
            String v = presentationName(invokeQuiet(opt, "getSelectedElement"));
            if (v == null) {
                Object sel = invokeQuiet(opt, "getSelected");
                v = (sel != null) ? String.valueOf(sel) : str(opt);
            }
            prow(w, "sim", "", "units_system", v);
        } catch (Exception e) {
            sim.println("starpost: properties: sim section failed: "
                + e.getMessage());
        }
    }

    private void propsSolution(Simulation sim, PrintWriter w) {
        try {
            SimulationIterator it = sim.getSimulationIterator();
            Solution sol = sim.getSolution();
            prow(w, "solution", "", "iteration",
                String.valueOf(it.getCurrentIteration()));
            prow(w, "solution", "", "time_level",
                String.valueOf(it.getCurrentTimeLevel()));
            prow(w, "solution", "", "physical_time",
                String.valueOf(sol.getPhysicalTime()));
            prow(w, "solution", "", "initialized",
                String.valueOf(sol.isInitialized()));
            prow(w, "solution", "", "cpu_time_s",
                str(invokeQuiet(it, "getCpuTime")));
            prow(w, "solution", "", "elapsed_time_s",
                str(invokeQuiet(it, "getElapsedTime")));
        } catch (Exception e) {
            sim.println("starpost: properties: solution section failed: "
                + e.getMessage());
        }
    }

    private void propsMesh(Simulation sim, PrintWriter w) {
        try {
            FvRepresentation fv = null;
            for (Object rep : sim.getRepresentationManager().getObjects()) {
                if (rep instanceof FvRepresentation) {
                    fv = (FvRepresentation) rep;
                    break;
                }
            }
            // Empty values mean "no volume mesh" — distinct from a failed
            // section, whose rows are absent entirely.
            prow(w, "mesh", "", "cell_count",
                fv == null ? "" : String.valueOf(fv.getCellCount()));
            prow(w, "mesh", "", "interior_face_count",
                fv == null ? "" : String.valueOf(fv.getInteriorFaceCount()));
            prow(w, "mesh", "", "vertex_count",
                fv == null ? "" : String.valueOf(fv.getVertexCount()));
        } catch (Exception e) {
            sim.println("starpost: properties: mesh section failed: "
                + e.getMessage());
        }
    }

    private void propsRegions(Simulation sim, PrintWriter w) {
        try {
            for (Region r : sim.getRegionManager().getRegions()) {
                String name = r.getPresentationName();
                try {
                    prow(w, "region", name, "type",
                        str(presentationName(r.getRegionType())));
                    prow(w, "region", name, "continuum",
                        str(presentationName(
                            invokeQuiet(r, "getPhysicsContinuum"))));
                    // Boundary count plus a count-per-type summary — never a
                    // per-boundary dump (regions can hold thousands).
                    java.util.Map<String, Integer> types =
                        new java.util.LinkedHashMap<>();
                    int count = 0;
                    for (Boundary b : r.getBoundaryManager().getBoundaries()) {
                        count++;
                        String t = presentationName(b.getBoundaryType());
                        if (t == null) {
                            t = "Unknown";
                        }
                        Integer prev = types.get(t);
                        types.put(t, prev == null ? 1 : prev + 1);
                    }
                    prow(w, "region", name, "boundaries",
                        String.valueOf(count));
                    StringBuilder sb = new StringBuilder();
                    for (java.util.Map.Entry<String, Integer> en
                            : types.entrySet()) {
                        if (sb.length() > 0) {
                            sb.append("; ");
                        }
                        sb.append(en.getKey()).append("=").append(en.getValue());
                    }
                    prow(w, "region", name, "boundary_types", sb.toString());
                } catch (Exception e) {
                    sim.println("starpost: properties: region '" + name
                        + "' failed: " + e.getMessage());
                }
            }
        } catch (Exception e) {
            sim.println("starpost: properties: regions section failed: "
                + e.getMessage());
        }
    }

    private void propsInterfaces(Simulation sim, PrintWriter w) {
        try {
            java.util.List<String> names = new java.util.ArrayList<>();
            for (Object o : sim.getInterfaceManager().getObjects()) {
                String n = presentationName(o);
                if (n != null) {
                    names.add(n);
                }
            }
            prow(w, "interface", "", "count", String.valueOf(names.size()));
            for (String n : names) {
                prow(w, "interface", n, "", "");
            }
        } catch (Exception e) {
            sim.println("starpost: properties: interfaces section failed: "
                + e.getMessage());
        }
    }

    private void propsContinua(Simulation sim, PrintWriter w) {
        try {
            for (Object o : sim.getContinuumManager().getObjects()) {
                if (!(o instanceof Continuum)) {
                    continue;
                }
                Continuum c = (Continuum) o;
                String name = c.getPresentationName();
                try {
                    // The enabled-models list answers most "what kind of sim
                    // is this?" questions (Steady/Unsteady, Gas/Liquid, ...).
                    StringBuilder models = new StringBuilder();
                    for (Object m : c.getModelManager().getObjects()) {
                        String mn = presentationName(m);
                        if (mn == null) {
                            continue;
                        }
                        if (models.length() > 0) {
                            models.append("; ");
                        }
                        models.append(mn);
                    }
                    prow(w, "continuum", name, "models", models.toString());
                    prow(w, "continuum", name, "regions",
                        countOf(invokeQuiet(c, "getRegions")));
                } catch (Exception e) {
                    sim.println("starpost: properties: continuum '" + name
                        + "' failed: " + e.getMessage());
                }
            }
        } catch (Exception e) {
            sim.println("starpost: properties: continua section failed: "
                + e.getMessage());
        }
    }

    private void propsSolvers(Simulation sim, PrintWriter w) {
        try {
            for (Object o : sim.getSolverManager().getObjects()) {
                String n = presentationName(o);
                if (n != null) {
                    prow(w, "solver", n, "", "");
                }
            }
        } catch (Exception e) {
            sim.println("starpost: properties: solvers section failed: "
                + e.getMessage());
        }
    }

    private void propsCriteria(Simulation sim, PrintWriter w) {
        try {
            for (Object o
                    : sim.getSolverStoppingCriterionManager().getObjects()) {
                String n = presentationName(o);
                if (n == null) {
                    continue;
                }
                Object used = invokeQuiet(o, "getIsUsed");
                if (used == null) {
                    used = invokeQuiet(o, "isUsed");
                }
                prow(w, "criterion", n, "enabled", str(used));
            }
        } catch (Exception e) {
            sim.println("starpost: properties: criteria section failed: "
                + e.getMessage());
        }
    }

    private void propsMeshOps(Simulation sim, PrintWriter w) {
        try {
            for (Object op
                    : managerObjects(sim, "star.meshing.MeshOperationManager")) {
                String name = presentationName(op);
                if (name == null) {
                    continue;
                }
                try {
                    prow(w, "mesh_op", name, "type",
                        op.getClass().getSimpleName());
                    Object meshers = invokeQuiet(op, "getMeshersCollection");
                    if (meshers instanceof Iterable) {
                        StringBuilder sb = new StringBuilder();
                        for (Object m : (Iterable<?>) meshers) {
                            String mn = presentationName(m);
                            if (mn == null) {
                                continue;
                            }
                            if (sb.length() > 0) {
                                sb.append("; ");
                            }
                            sb.append(mn);
                        }
                        prow(w, "mesh_op", name, "meshers", sb.toString());
                    }
                    meshDefault(w, name, op, "star.meshing.BaseSize",
                        "base_size");
                    meshDefault(w, name, op,
                        "star.meshing.PartsTargetSurfaceSize",
                        "target_surface_size");
                    meshDefault(w, name, op,
                        "star.meshing.PartsMinimumSurfaceSize",
                        "min_surface_size");
                    meshDefault(w, name, op,
                        "star.prismmesher.NumPrismLayers", "prism_layers");
                } catch (Exception e) {
                    sim.println("starpost: properties: mesh op '" + name
                        + "' failed: " + e.getMessage());
                }
            }
        } catch (Exception e) {
            sim.println("starpost: properties: mesh ops section failed: "
                + e.getMessage());
        }
    }

    // One mesh default value from an auto-mesh operation (e.g. the base size).
    // These star.meshing / star.prismmesher class names drift across releases
    // more than the managers do, so each read is looked up and guarded on its
    // own: a moved class or accessor drops this one key, nothing else.
    private void meshDefault(PrintWriter w, String opName, Object op,
                             String className, String key) {
        try {
            Object defaults = op.getClass().getMethod("getDefaultValues")
                .invoke(op);
            Object item = defaults.getClass().getMethod("get", Class.class)
                .invoke(defaults, Class.forName(className));
            String v = displayValue(item);
            if (v != null) {
                prow(w, "mesh_op", opName, key, v);
            }
        } catch (Exception e) {
            // this release doesn't carry this default — key dropped
        }
    }

    // A readable value for a mesh default object: probes the value accessors
    // the size/count types expose (with units when present); null when none
    // fits.
    private String displayValue(Object item) {
        Object v = invokeQuiet(item, "getValue");
        if (v == null) {
            v = invokeQuiet(item, "getNumLayers");
        }
        if (v == null) {
            v = invokeQuiet(item, "getRelativeSizeValue");
        }
        if (v == null) {
            v = invokeQuiet(item, "getAbsoluteSizeValue");
        }
        if (v == null) {
            return null;
        }
        String units = presentationName(invokeQuiet(item, "getUnits"));
        return (units == null || units.isEmpty())
            ? String.valueOf(v) : v + " " + units;
    }

    // Cap on listed geometry parts: on huge sims thousands of parts mean
    // thousands of client-server round-trips; the rest are summarised in a
    // single trailing "truncated" row.
    private static final int PART_CAP = 200;

    private void propsParts(Simulation sim, PrintWriter w) {
        try {
            Object mgr = invokeQuiet(sim, "getGeometryPartManager");
            if (mgr == null) {
                return;
            }
            Object leaves = invokeQuiet(mgr, "getLeafParts");
            if (!(leaves instanceof Iterable)) {
                // Manager without getLeafParts: expand each top-level part
                // (a part without leaves stands for itself).
                java.util.List<Object> acc = new java.util.ArrayList<>();
                Object tops = invokeQuiet(mgr, "getObjects");
                if (tops instanceof Iterable) {
                    for (Object p : (Iterable<?>) tops) {
                        Object lp = invokeQuiet(p, "getLeafParts");
                        if (lp instanceof Iterable) {
                            for (Object leaf : (Iterable<?>) lp) {
                                acc.add(leaf);
                            }
                        } else {
                            acc.add(p);
                        }
                    }
                }
                leaves = acc;
            }
            int written = 0;
            int extra = 0;
            for (Object part : (Iterable<?>) leaves) {
                if (written >= PART_CAP) {
                    extra++;
                    continue;
                }
                String name = presentationName(part);
                if (name == null) {
                    continue;
                }
                prow(w, "part", name, "type",
                    part.getClass().getSimpleName());
                prow(w, "part", name, "surfaces",
                    countOf(invokeQuiet(part, "getPartSurfaces")));
                prow(w, "part", name, "curves",
                    countOf(invokeQuiet(part, "getPartCurves")));
                written++;
            }
            if (extra > 0) {
                prow(w, "part", "", "truncated", String.valueOf(extra));
            }
        } catch (Exception e) {
            sim.println("starpost: properties: parts section failed: "
                + e.getMessage());
        }
    }

    private void propsTags(Simulation sim, PrintWriter w) {
        // TagManager is star.common, but old releases may lack it entirely,
        // so it is still looked up reflectively — no tags is never an error.
        for (Object t : managerObjects(sim, "star.common.TagManager")) {
            String n = presentationName(t);
            if (n != null) {
                prow(w, "tag", n, "", "");
            }
        }
    }

    // The objects of a manager looked up by class name via sim.get(...), or
    // an empty list when this release doesn't have that manager.
    private java.util.List<Object> managerObjects(Simulation sim,
                                                  String className) {
        java.util.List<Object> out = new java.util.ArrayList<>();
        try {
            Class<?> mgrClass = Class.forName(className);
            Object mgr = Simulation.class.getMethod("get", Class.class)
                .invoke(sim, mgrClass);
            Object objs = mgr.getClass().getMethod("getObjects").invoke(mgr);
            for (Object o : (Iterable<?>) objs) {
                out.add(o);
            }
        } catch (Exception e) {
            // release without this manager — no rows
        }
        return out;
    }

    // The element count of a reflectively-fetched collection, as CSV text
    // ("" when the accessor was unavailable).
    private String countOf(Object o) {
        if (o instanceof java.util.Collection) {
            return String.valueOf(((java.util.Collection<?>) o).size());
        }
        if (o instanceof Iterable) {
            int n = 0;
            for (Object item : (Iterable<?>) o) {
                n++;
            }
            return String.valueOf(n);
        }
        return "";
    }
```

Note the direct (compile-time) types used are all in the already-imported `star.common`: `SimulationIterator`, `Solution`, `FvRepresentation`, `Region`, `Boundary`, `Continuum`. Everything else goes through `invokeQuiet` / `Class.forName`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_properties.py tests/test_screenplays.py -v`
Expected: all PASS (the screenplays macro tests guard the rest of the template).

- [ ] **Step 5: Commit**

```bash
git add src/starpost/macros/extract_all.java.j2 tests/test_properties.py
git commit -m "Extraction macro: export sim properties (solution, mesh, regions, physics, parts, tags)"
```

- [ ] **Step 6 (manual, may be deferred to Task 7): real-sim validation**

On this machine, with a real solved `.sim` available: run an extraction from the GUI (or call `StarRunner.extract` from a scratch script) against the `/opt/Siemens/20.04.007-R8` install and inspect the log for any `starpost: properties:` failure lines; confirm the parsed data set carries properties. Mind the 16 GB `/tmp` tmpfs on big sims. If `units_system`, `criterion enabled`, or the four mesh defaults come out empty, tune the probe lists in `propsSim` / `propsCriteria` / `displayValue` (they are deliberately probe-based) and commit the fix.

---

### Task 4: Store cache round-trip

**Files:**
- Modify: `src/starpost/data/store.py`
- Test: `tests/test_properties.py`

**Interfaces:**
- Consumes: `SimResult.properties`, `PropertyGroup`, `SimProperties` (Task 1).
- Produces: cache JSON gains a `"properties"` key (`None` or `{"groups": [...]}`); old caches without it load as `properties=None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_properties.py`:

```python
import json

from starpost.data.store import ResultStore


def _props() -> SimProperties:
    return SimProperties(groups=[
        PropertyGroup(section="sim", entries=[("units_system", "SI")]),
        PropertyGroup(section="region", name="Fluid",
                      entries=[("boundaries", "46")]),
        PropertyGroup(section="tag", name="baseline"),
    ])


def test_store_round_trips_properties(tmp_path):
    res = SimResult(sim_path="/c/a.sim", properties=_props())
    store = ResultStore()
    store.put(res)
    path = tmp_path / "cache.json"
    store.save_cache(path)

    loaded = ResultStore()
    loaded.load_cache(path)
    got = loaded.get("/c/a.sim").properties
    assert got.get("sim").get("units_system") == "SI"
    assert got.get("region", "Fluid").get("boundaries") == "46"
    assert got.get("tag", "baseline").entries == []
    # JSON turns tuples into lists; the loader must rebuild tuples.
    assert got.get("sim").entries == [("units_system", "SI")]
    assert isinstance(got.get("sim").entries[0], tuple)


def test_store_round_trips_none_properties(tmp_path):
    store = ResultStore()
    store.put(SimResult(sim_path="/c/a.sim"))
    path = tmp_path / "cache.json"
    store.save_cache(path)
    loaded = ResultStore()
    loaded.load_cache(path)
    assert loaded.get("/c/a.sim").properties is None


def test_old_cache_without_properties_loads_none(tmp_path):
    # Caches written before this feature have no "properties" key at all.
    store = ResultStore()
    store.put(SimResult(sim_path="/c/a.sim"))
    path = tmp_path / "cache.json"
    store.save_cache(path)
    payload = json.loads(path.read_text())
    for d in payload.values():
        d.pop("properties", None)
    path.write_text(json.dumps(payload))

    loaded = ResultStore()
    loaded.load_cache(path)
    assert loaded.get("/c/a.sim").properties is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_properties.py -v`
Expected: `test_store_round_trips_properties` FAILS (loaded `properties` is `None` — the store drops the field today). The other two pass already and pin the back-compat behaviour.

- [ ] **Step 3: Implement store (de)serialisation**

In `src/starpost/data/store.py`:

Add `PropertyGroup` and `SimProperties` to the `starpost.data.models` import list (after `PlotSeries`/`PlotKind`, keeping the alphabetical order).

In `_result_to_dict`, after the `"media"` entry, add:

```python
        "properties": asdict(r.properties) if r.properties is not None else None,
```

In `_result_from_dict`, add to the `SimResult(...)` constructor call (after `media=media,`):

```python
        properties=_properties_from_dict(d.get("properties")),
```

Add the loader next to `_scene_from_dict`:

```python
def _properties_from_dict(d) -> Optional[SimProperties]:
    """Rebuild SimProperties from its asdict form; JSON stores the (key, value)
    entry tuples as lists. None/absent (pre-properties caches) stays None."""
    if not d:
        return None
    return SimProperties(
        groups=[
            PropertyGroup(
                section=g["section"],
                name=g.get("name", ""),
                entries=[(k, v) for k, v in g.get("entries", [])],
            )
            for g in d.get("groups", [])
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_properties.py tests/test_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/data/store.py tests/test_properties.py
git commit -m "Store: persist sim properties in the crash-recovery cache"
```

---

### Task 5: Portable CSV v3

**Files:**
- Modify: `src/starpost/data/portable.py`
- Test: `tests/test_portable.py`

**Interfaces:**
- Consumes: `SimResult.properties`, `PropertyGroup`, `SimProperties` (Task 1).
- Produces: portable files written as `starpost-data,3` with `prop,<section>,<name>,<key>,<value>` rows; `read_sim_csv` accepts versions 2 and 3.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_portable.py` (and extend its models import with `PropertyGroup, SimProperties`):

```python
def test_round_trip_properties(tmp_path):
    result = _sample()
    result.properties = SimProperties(groups=[
        PropertyGroup(section="sim", entries=[("units_system", "SI")]),
        PropertyGroup(
            section="region", name="Fluid",
            entries=[("boundaries", "46"),
                     ("boundary_types", "Velocity Inlet=1; Wall=44")],
        ),
        PropertyGroup(section="tag", name="baseline"),
    ])
    path = tmp_path / "caseA.csv"
    write_sim_csv(result, path)

    assert path.read_text(encoding="utf-8").startswith("starpost-data,3")

    loaded = read_sim_csv(path)
    props = loaded.properties
    assert props.get("sim").get("units_system") == "SI"
    assert (props.get("region", "Fluid").get("boundary_types")
            == "Velocity Inlet=1; Wall=44")
    # An entry-less group (a tag) survives the round trip.
    assert props.get("tag", "baseline").entries == []
    # Reports and plots are untouched by the new rows.
    assert {r.name for r in loaded.reports} == {"Drag Force", "Bad"}
    assert loaded.plots[0].series[0].y == [0.1, 0.01]


def test_round_trip_without_properties_stays_none(tmp_path):
    path = tmp_path / "caseA.csv"
    write_sim_csv(_sample(), path)
    assert read_sim_csv(path).properties is None


def test_v2_file_still_imports(tmp_path):
    # Files exported by older StarPost (format v2) must keep importing.
    path = tmp_path / "old.csv"
    path.write_text(
        "starpost-data,2\n"
        "meta,sim_path,/cases/caseA.sim\n"
        "meta,extracted_at,2026-06-16T12:00:00+00:00\n"
        "report,Drag Force,12.5,N,\n"
        "plot,Residuals,residual,Iteration,true,\n"
        "head,Iteration,Continuity\n"
        "1,0.1\n"
        "2,0.01\n",
        encoding="utf-8",
    )
    loaded = read_sim_csv(path)
    assert loaded.sim_path == "/cases/caseA.sim"
    assert loaded.reports[0].value == 12.5
    assert loaded.plots[0].series[0].y == [0.1, 0.01]
    assert loaded.properties is None


def test_rejects_unsupported_version(tmp_path):
    path = tmp_path / "future.csv"
    path.write_text("starpost-data,4\n", encoding="utf-8")
    try:
        read_sim_csv(path)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unsupported version")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_portable.py -v`
Expected: `test_round_trip_properties` FAILS (file starts with `starpost-data,2`); `test_v2_file_still_imports` PASSES today and must keep passing after the bump.

- [ ] **Step 3: Implement v3**

In `src/starpost/data/portable.py`:

Add `PropertyGroup` and `SimProperties` to the models import.

Replace the version constant block:

```python
# Signature written on the first line. Bump VERSION if the layout changes in a
# way older readers can't handle; readers verify FORMAT and the version.
# v3 added ``prop`` rows (sim properties); v2 files still read fine, so both
# are accepted on import. v3 files do NOT import into pre-v3 StarPost.
FORMAT = "starpost-data"
VERSION = 3
_READABLE_VERSIONS = ("2", "3")
```

Update the module docstring's example first line from `starpost-data,2` to `starpost-data,3` and add to the example row list (after the `meta` lines):

```
    prop,sim,,units_system,SI
    prop,region,Fluid,boundaries,46
```

with one sentence added to the docstring's row description: `A ``prop`` row carries one sim-properties entry (section, entity name, key, value); an entry-less group writes a single row with empty key and value.`

In `_write_rows`, after the `meta` rows (before the reports loop), add:

```python
    if result.properties is not None:
        for g in result.properties.groups:
            if g.entries:
                for key, value in g.entries:
                    w.writerow(["prop", g.section, g.name, key, value])
            else:
                # An entry-less group (e.g. a tag) still needs a row to exist.
                w.writerow(["prop", g.section, g.name, "", ""])
```

In `read_sim_csv`, replace the version check:

```python
        if len(signature) < 2 or signature[1] not in _READABLE_VERSIONS:
```

and add a `prop` branch after the `elif tag == "report":` block:

```python
            elif tag == "prop":
                section = row[1] if len(row) > 1 else ""
                if not section:
                    continue
                name = row[2] if len(row) > 2 else ""
                if result.properties is None:
                    result.properties = SimProperties()
                groups = result.properties.groups
                if (not groups or groups[-1].section != section
                        or groups[-1].name != name):
                    groups.append(PropertyGroup(section=section, name=name))
                key = row[3] if len(row) > 3 else ""
                if key:
                    groups[-1].entries.append(
                        (key, row[4] if len(row) > 4 else "")
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_portable.py -v`
Expected: all PASS, including the pre-existing round-trip tests.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/data/portable.py tests/test_portable.py
git commit -m "Portable CSV v3: carry sim properties; accept v2 and v3 on import"
```

---

### Task 6: STAR-CCM+ version from the batch banner

**Files:**
- Modify: `src/starpost/core/starccm_runner.py`
- Test: `tests/test_properties.py`

**Interfaces:**
- Consumes: `_stream()`'s line-by-line sink; `SimProperties`/`PropertyGroup` (Task 1).
- Produces: after a successful `extract()`, `result.properties.get("sim").get("starccm_version")` holds e.g. `"2020.1 Build 15.02.007"` (entry absent when no banner matched; `properties` created if the macro CSV was missing).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_properties.py`:

```python
from starpost.core.settings import LicenseConfig, Settings
from starpost.core.starccm_runner import StarRunner

BANNER = "Simcenter STAR-CCM+ 2020.1 Build 15.02.007 (linux-x86_64-2.12/gnu7.1)"


def _runner() -> StarRunner:
    s = Settings(starccm_path="/opt/starccm/bin/starccm+")
    s.license = LicenseConfig()
    return StarRunner(s)


def _fake_render_macro(output_dir, dest_dir):
    macro = Path(dest_dir) / "extract_all.java"
    macro.write_text("// fake macro")
    return macro


def test_extract_captures_starccm_version_banner(tmp_path, monkeypatch):
    import starpost.core.starccm_runner as sr

    def fake_stream(self, cmd, sink):
        sink(BANNER)
        sink("Loading simulation...")
        return 0

    monkeypatch.setattr(sr, "render_macro", _fake_render_macro)
    monkeypatch.setattr(sr.StarRunner, "_stream", fake_stream)

    result = _runner().extract(tmp_path / "case.sim")
    assert result.error is None
    # The scratch dir had no properties CSV (parse gives None), so the banner
    # alone must create the properties and its sim group.
    assert (result.properties.get("sim").get("starccm_version")
            == "2020.1 Build 15.02.007")


def test_extract_appends_version_to_existing_sim_group(tmp_path, monkeypatch):
    import starpost.core.starccm_runner as sr

    def fake_stream(self, cmd, sink):
        sink(BANNER)
        return 0

    def fake_parse(sim_path, output_dir, classification):
        res = SimResult(sim_path=sim_path)
        res.properties = SimProperties(groups=[
            PropertyGroup(section="sim", entries=[("units_system", "SI")]),
        ])
        return res

    monkeypatch.setattr(sr, "render_macro", _fake_render_macro)
    monkeypatch.setattr(sr, "parse_sim_output", fake_parse)
    monkeypatch.setattr(sr.StarRunner, "_stream", fake_stream)

    result = _runner().extract(tmp_path / "case.sim")
    assert result.properties.get("sim").entries == [
        ("units_system", "SI"),
        ("starccm_version", "2020.1 Build 15.02.007"),
    ]


def test_extract_without_banner_leaves_properties_alone(tmp_path, monkeypatch):
    import starpost.core.starccm_runner as sr

    monkeypatch.setattr(sr, "render_macro", _fake_render_macro)
    monkeypatch.setattr(
        sr.StarRunner, "_stream",
        lambda self, cmd, sink: (sink("Loading simulation..."), 0)[1],
    )

    result = _runner().extract(tmp_path / "case.sim")
    assert result.properties is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_properties.py -v`
Expected: the first two new tests FAIL (`properties` is `None` / missing entry); the third PASSES already and pins the no-banner behaviour.

- [ ] **Step 3: Implement banner capture**

In `src/starpost/core/starccm_runner.py`:

Add `import re` to the stdlib imports, and extend the models import:

```python
from starpost.data.models import (
    MediaArtifact,
    PropertyGroup,
    SimProperties,
    SimResult,
)
```

Add near `_SECRET_FLAGS` (module level):

```python
# The STAR-CCM+ batch banner, e.g. "Simcenter STAR-CCM+ 2020.1 Build
# 15.02.007 (linux-x86_64-2.12/gnu7.1)". Captures the version (and Build
# number when present). Case-sensitive, so the executable path in the echoed
# command line ("starccm+") can never match.
_VERSION_RE = re.compile(r"STAR-CCM\+\s+(\d[\w.\-]*(?:\s+Build\s+[\w.\-]+)?)")


def _append_starccm_version(result: SimResult, version: str) -> None:
    """Record the STAR-CCM+ version (from the batch banner) on the result's
    properties, creating the SimProperties / "sim" group when the macro's
    properties CSV didn't produce them."""
    if result.properties is None:
        result.properties = SimProperties()
    group = result.properties.get("sim")
    if group is None:
        group = PropertyGroup(section="sim")
        result.properties.groups.insert(0, group)
    group.entries.append(("starccm_version", version))
```

In `extract()`, replace the body between `sink = log_sink or (lambda s: None)` and the `with tempfile...` line boundary as follows — define the wrapping sink right after `sink = ...`:

```python
        sink = log_sink or (lambda s: None)

        # The version banner is only visible in the stream; remember the first
        # match while forwarding every line untouched.
        detected: list[str] = []

        def banner_sink(line: str) -> None:
            if not detected:
                m = _VERSION_RE.search(line)
                if m:
                    detected.append(m.group(1))
            sink(line)
```

change the stream call to use it:

```python
            code = self._stream(cmd, banner_sink)
```

and after the `result = parse_sim_output(...)` call (still inside the method, after the `with` block is fine), before the final `sink(f"Parsed ...")`:

```python
        if detected:
            _append_starccm_version(result, detected[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_properties.py tests/test_starccm_runner.py -v`
Expected: all PASS (the scratch-dir test in `test_starccm_runner.py` must be unaffected).

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/core/starccm_runner.py tests/test_properties.py
git commit -m "Runner: record the STAR-CCM+ version from the batch banner on the result"
```

---

### Task 7: Changelog, full suite, wrap-up

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:** none — verification and documentation only.

- [ ] **Step 1: Changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]`, add a `### New Features` section **above** the existing `### Bug Fixes` (matching the 2.5.0 section order):

```markdown
### New Features
- **Sim properties captured at extraction** — loading a .sim now also records
  the simulation's own metadata: solution state (iteration, physical time,
  CPU/elapsed time), mesh cell/face/vertex counts, regions with their
  boundary-type breakdown and physics continuum, physics models per continuum,
  solvers and stopping criteria, the mesh-operation pipeline (meshers, base
  size, surface sizes, prism layers), geometry parts, interfaces, tags, and
  the STAR-CCM+ version used. Everything rides the same single extraction
  pass (no extra license checkout), survives restarts via the crash-recovery
  cache, and is included in portable data-CSV exports. The Properties dialog
  will surface this in a future release. **Note:** portable data exports are
  now format v3 — older StarPost releases cannot import them; v2 files still
  import fine.
```

- [ ] **Step 2: Full test suite**

Run: `QT_QPA_PLATFORM=offscreen python scripts/run_tests.py`
Expected: full suite passes. (Never a bare `python -m pytest` for the full run.)

- [ ] **Step 3: Lint**

Run: `ruff check .`
Expected: clean.

- [ ] **Step 4: Real-sim validation (manual)**

If not already done in Task 3 Step 6: run one extraction against the local `/opt/Siemens/20.04.007-R8` install on a solved `.sim`, check the log for `starpost: properties:` failure lines, and confirm the data set's properties round-trip through a portable export/import. Tune the probe lists (`propsSim`, `propsCriteria`, `displayValue`) if any expected value comes out empty, and commit any tuning.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "Changelog: sim properties extraction (portable format v3)"
```
