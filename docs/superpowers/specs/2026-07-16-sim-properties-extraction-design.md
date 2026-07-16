# Sim Properties Extraction — Design

**Date:** 2026-07-16
**Status:** Proposed (research + design; no implementation yet)
**Feeds:** the Properties dialog for Data-tab data sets (and, by extension, the
Files-tab Properties dialog once a file is extracted).

## Goal

When StarPost extracts a `.sim`, it currently captures only post-processing
objects: reports, monitor plots, scenes, views, screenplays. The `.sim` also
describes the *simulation itself* — geometry parts, mesh settings and size,
regions and boundaries, physics models, tags, solution state. This design
captures that metadata during the same extraction pass (one license checkout,
per the central invariant) and surfaces it in the Data tab's Properties dialog.

Everything below the API-surface section was validated against the local
install (`/opt/Siemens/20.04.007-R8`, STAR-CCM+ 2020.04) by inspecting the
shipped jars (`starbase.jar`, `meshing.jar`, `cadmodeler.jar`) with `javap`,
not from memory. Release variance is a real risk and is addressed under
[Risks](#risks).

---

## 1. What can be extracted

All of this is readable from an open sim in `-batch` mode with **no solving, no
meshing, no rendering** — it is stored state, so the added extraction cost is
negligible next to opening the file.

### 1.1 Geometry / CAD

| Item | API (validated) | Notes |
|---|---|---|
| Geometry part tree | `sim.getGeometryPartManager().getObjects()`; `GeometryPart.getLeafParts()`, `getPathInHierarchy()` | Composite parts recurse. |
| Part origin/type | concrete class of each part | `star.meshing.CadPart` = imported CAD, `star.cadmodeler.SolidModelPart` = 3D-CAD, `star.meshing.SimpleBlockPart` etc. = shape parts, `star.meshing.LeafMeshPart` = imported surface mesh, `star.meshing.MeshOperationPart` = output of a mesh operation. |
| Surface/curve/point counts per part | `getPartSurfaces()`, `getPartCurves()`, `getPartPoints()` | Report **counts**, not names — surfaces can number in the thousands. |
| Part metadata | `GeometryPart.getMetaDataString()` | Free-form metadata attached at import (material, PDM attributes…). Often empty. |
| 3D-CAD models | `star.cadmodeler.SolidModelManager` → `CadModel` names | Distinct from geometry parts: the parametric 3D-CAD trees. |

**Not practical:** the actual 3D geometry (tessellation). It exists in the file,
but getting it out means a surface export per part (slow, large, needs a viewer
on our side). Out of scope; scenes already cover "what does it look like".

### 1.2 Mesh

| Item | API (validated) | Notes |
|---|---|---|
| Cell / face / vertex counts | `sim.getRepresentationManager()` → `FvRepresentation.getCellCount()`, `getInteriorFaceCount()`, `getVertexCount()` | Stored in the sim — instant. Absent when the sim has no volume mesh; that absence itself is worth showing ("not meshed"). |
| Mesh operation pipeline | `star.meshing.MeshOperationManager` (via `sim.get(...)`) → operation names + concrete classes | e.g. Automated Mesh, Surface Wrapper, Extract Volume, Boolean ops — in pipeline order. |
| Meshers per auto-mesh op | `AutoMeshOperation.getMeshersCollection()` | e.g. Surface Remesher, Polyhedral, Prism Layer. |
| Key mesh defaults | `AutoMeshOperation.getDefaultValues().get(star.meshing.BaseSize.class)` etc. | Base size, target/minimum surface size, prism layer count. Read via reflection with per-item fallback — these class names shift more across releases than the managers do. |

**Not practical:** mesh-quality metrics (skewness, volume-change histograms) —
they may require computing a field, violating "read stored state only". Cheap
Tier-3 candidate later if a stored-metrics API is confirmed.

### 1.3 Regions, boundaries, interfaces

| Item | API (validated) | Notes |
|---|---|---|
| Regions | `sim.getRegionManager()` → `Region`: name, `getRegionType()`, `getIndex()` | |
| Physics assignment | `Region.getPhysicsContinuum()` | Which continuum each region solves. |
| Boundaries | `Region.getBoundaryManager()` → `Boundary.getBoundaryType()` | Per region: boundary count plus a count-per-type summary (e.g. 3 × Velocity Inlet, 1 × Pressure Outlet, 42 × Wall). Full per-boundary listing only under a cap (see Risks). |
| Interfaces | `sim.getInterfaceManager()` | Name + count. |

### 1.4 Physics

| Item | API (validated) | Notes |
|---|---|---|
| Continua | `sim.getContinuumManager()` → names, regions served (`Continuum.getRegions()`) | |
| Enabled models | `Continuum.getModelManager().getObjects()` → presentation names | This one list answers most "what kind of sim is this?" questions: Steady/Implicit Unsteady, Gas/Liquid, Segregated/Coupled, K-Omega/K-Epsilon/LES, Energy… |
| Solvers | `sim.getSolverManager().getObjects()` → names | |
| Stopping criteria | `sim.getSolverStoppingCriterionManager()` → names (+ enabled state) | |
| Units system | `sim.getUnitsManager().getSystemOption()` | SI vs USCS. |

### 1.5 Tags

| Item | API (validated) | Notes |
|---|---|---|
| All tags defined | `star.common.TagManager` (via `sim.get(...)`) → tag names | |
| Per-object tags | `TagManager.getTags(obj)` or `obj.getTagGroup().getObjects()` — every `ClientServerObject` is `Taggable` | Tier 2: tags on regions, parts, reports. Tag-everything is unbounded; restrict to the object types we already enumerate. |

### 1.6 Solution state

| Item | API (validated) | Notes |
|---|---|---|
| Iteration count | `sim.getSimulationIterator().getCurrentIteration()` | |
| Time level / physical time | `getCurrentTimeLevel()`; `sim.getSolution().getPhysicalTime()` | Transient sims. |
| Solved at all? | `sim.getSolution().isInitialized()` | Distinguishes a set-up-only sim from a solved one. |
| Accumulated CPU / elapsed time | `SimulationIterator.getCpuTime()`, `getElapsedTime()` | How expensive the run was. |

### 1.7 Facts needing no macro at all (Python side)

- **File size, mtime** — `Path.stat()` (size already shown today).
- **STAR-CCM+ version that ran the extraction** — the batch banner in stdout,
  which `StarRunner` already streams line by line ([starccm_runner.py:249](src/starpost/core/starccm_runner.py:249));
  one regex on the first lines captures it with zero risk.
- **Version that last wrote the sim** — a `Simulation` accessor for this was
  *not* found in the 2020.04 jars (only `getMpiVersion()`). The running-version
  banner is the reliable substitute. (A `strings`-style scan of the `.sim`
  header sometimes reveals the writer version, but that's a heuristic against a
  proprietary format — not part of this design.)
- **Already-extracted counts** — reports/monitors/iterations shown today, plus
  scenes/views/screenplays counts already on `SimResult`.

### 1.8 Deliberately excluded

- 3D geometry/tessellation export (heavy; needs a viewer).
- Field data / per-cell values (that's what scenes and reports are for).
- Mesh quality histograms (may trigger computation).
- Anything requiring `initializeSolution()`, mesh pipeline execution, or any
  mutation of the sim.

---

## 2. Implementation strategy

### 2.1 Approaches considered

**A. Extend `extract_all.java.j2` with a properties exporter writing one more
CSV (recommended).** Fits every existing invariant: single pass, one license
checkout, per-item try/catch, extract-all-then-filter, CSV-in / dataclass-out.
The screenplays exporter is the exact template for release-safety (reflection +
`Class.forName`, header-only file on failure).

**B. Use the built-in Simulation Summary** —
`sim.getSimulationSummaryManager().createSimulationSummary().printToHtml(File)`
(validated to exist in 2020.04). Pros: Siemens maintains the coverage. Cons:
`createSimulationSummary()` **mutates the sim tree** (we never save, so it's
discarded, but it breaks our read-only principle); the HTML layout is
undocumented and release-dependent, so the parser would be far more fragile
than reading typed getters; and it emits far more than we need. Rejected as
primary; worth remembering as a manual "export full summary" power feature
later.

**C. Parse the `.sim` binary directly.** No public reader; proprietary format.
Rejected (this is why StarPost drives the CLI at all).

### 2.2 Chosen pipeline (Approach A), end to end

**1. Macro** — new `exportProperties(sim, simName, dir)` in
`extract_all.java.j2` writing `<simname>__properties.csv`:

```csv
section,name,key,value
sim,,units_system,SI
solution,,iteration,4500
solution,,physical_time,0.0
solution,,initialized,true
solution,,cpu_time_s,86234.1
mesh,,cell_count,12400312
mesh,,vertex_count,...
mesh_op,Automated Mesh,type,AutoMeshOperation
mesh_op,Automated Mesh,meshers,Surface Remesher; Polyhedral Mesher; Prism Layer Mesher
mesh_op,Automated Mesh,base_size,0.01 m
region,Fluid,type,Fluid Region
region,Fluid,continuum,Physics 1
region,Fluid,boundaries,46
region,Fluid,boundary_types,Velocity Inlet=1; Pressure Outlet=1; Wall=44
continuum,Physics 1,models,Steady; Gas; Segregated Flow; K-Omega Turbulence; ...
part,wing_v3,type,CadPart
part,wing_v3,surfaces,128
tag,baseline,,
```

Flat, order-preserving, reuses the existing `esc()` helper, and unknown
sections are ignorable by the parser — that's the forward-compat story.
Multi-valued cells use `; ` separators inside one escaped cell (same trick the
media index uses for displayers). The STAR-CCM+ version (§1.7) is *not* written
by the macro: the Python side parses it from the runner's stdout banner and
appends it to `SimProperties` as a `sim,,starccm_version,...` entry during
parsing, so it still displays alongside the macro-sourced rows.

Rules carried over from the existing exporters:
- Every section wrapped in its own try/catch; a failure loses that section
  only, never the file, never the extraction.
- Classes outside `star.common` (`star.meshing.*`, `star.cadmodeler.*`,
  `star.summary.*`) are reached **only** via `Class.forName` + reflection —
  a compile error is fatal to the whole macro (the screenplays comment in the
  template says exactly this). `star.common` managers validated above may be
  referenced directly.
- Never call anything that computes: no `update()`, no `initializeSolution()`,
  no summary creation. Getters only.

**2. Parser** — `_parse_properties()` in
[result_parser.py](src/starpost/core/result_parser.py): missing file → `None`
(the same back-compat behaviour `_parse_scenes` has for pre-scenes
extractions).

**3. Model** — in [models.py](src/starpost/data/models.py):

```python
@dataclass
class PropertyGroup:
    section: str                 # "mesh", "region", ...
    name: str = ""               # entity name ("" for sim-wide sections)
    entries: list[tuple[str, str]] = field(default_factory=list)  # ordered key/value

@dataclass
class SimProperties:
    groups: list[PropertyGroup] = field(default_factory=list)
    def get(self, section, name="") -> PropertyGroup | None: ...
```

`SimResult.properties: SimProperties | None = None`. Deliberately **generic
strings, not typed fields**: the set of keys will drift across STAR-CCM+
releases and tiers, and the consumer is a display dialog, not computation. The
few places that want a number (e.g. cell count formatted with thousands
separators) parse at the point of use. `signature()` is **unchanged** —
properties must not affect the batch homogeneity check.

**4. Store** — extend `_result_to_dict` / `_result_from_dict` in
[store.py](src/starpost/data/store.py) (`asdict` for the new dataclass; small
and fixed-size). Old caches load with `d.get("properties")` → `None`, matching
the existing back-compat pattern.

**5. Portable CSV** — [portable.py](src/starpost/data/portable.py) gains a
`prop,<section>,<name>,<key>,<value>` row tag. This **requires bumping
`VERSION` 2 → 3**: the v2 reader treats any unrecognised tag as a numeric data
row (`float(tag)`), so it would crash on `prop` rows — silently skipping is not
an option. Write v3 always; **accept both 2 and 3 on read** so existing
exports keep importing. Consequence to document in the changelog: files
exported by the new version won't import into older StarPost releases.

**6. GUI** — extend `PropertiesDialog`
([properties_dialog.py](src/starpost/gui/views/properties_dialog.py)):
- Keep the current compact summary form (size, reports, monitors, iterations)
  and add the headline properties to it: cells, iteration, physical time,
  regions, units system, version.
- Below it, a collapsible detail view (`QTreeWidget`: one top-level item per
  section, key/value children) shown only when `result.properties` is not
  `None`. Not-yet-re-extracted data sets show today's dialog unchanged plus a
  "re-extract to capture sim properties" note.
- Both entry points benefit for free: the Data tab
  ([main_window.py:1502](src/starpost/gui/main_window.py:1502)) and the Files
  tab (`_show_file_properties`) share this dialog.

### 2.3 Tiering (ship in this order)

1. **Tier 1 — headline scalars:** units system, solution state (iteration,
   physical time, initialized, CPU time), mesh counts, region/boundary/
   interface counts, solver names, tag names, STAR-CCM+ version from the
   banner. Small, flat, near-zero release risk (all `star.common`).
2. **Tier 2 — structure:** per-region boundary-type breakdown and continuum
   assignment, physics models per continuum, mesh-operation pipeline +
   meshers + base size, geometry part tree with types and counts, stopping
   criteria.
3. **Tier 3 — nice-to-have:** per-object tag assignments, part metadata
   strings, 3D-CAD model names, coordinate systems / reference frames /
   motions.

Each tier is only new CSV rows + new tree sections — no schema change after
Tier 1 lands, which is the point of the generic row format.

### 2.4 Testing

- Parser: fixture `__properties.csv` files → `SimProperties`, including the
  missing-file → `None` path (mirror `test_result_parser` patterns; no
  STAR-CCM+ in CI).
- Store: round-trip with and without `properties`; load a pre-properties cache.
- Portable: v3 round-trip; v2 file still imports; v3-into-old-reader is the
  documented breaking case.
- Macro: template renders and the generated Java balances braces (existing
  macro tests' approach); real-sim validation is manual on this machine
  (`/opt/Siemens` install, per machine notes — mind the 16 GB `/tmp` tmpfs on
  big sims).
- GUI: dialog builds with `properties=None` and with a populated
  `SimProperties` (offscreen platform).

---

## 3. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **API variance across STAR-CCM+ releases.** Validated only against 2020.04 here; class names (esp. `star.meshing` defaults like `BaseSize`) move. | High (it's the defining risk) | Same discipline as screenplays: reflection + `Class.forName` for everything outside `star.common`; per-section try/catch; a missing section degrades to "—" in the UI, never a failed extraction. Tier 1 sticks to `star.common`. |
| **A compile error in the macro kills the *whole* extraction** (existing behaviour: one macro, one pass). | High | No compile-time references outside `star.common` + `star.base.report` + `star.vis` (the imports already present). Template-render test in CI. |
| **Slow enumeration on huge sims** — thousands of parts/boundaries mean thousands of client-server round-trips. | Medium | Export counts and count-per-type summaries, not per-item dumps; cap any listed collection (e.g. first 200 parts + "… and N more"). Never call `getPartSurfaces()` on composites just to count — count leaf parts' collections once, guarded. |
| **Accidental computation/mutation** — some managers lazily build state; `createSimulationSummary` adds a tree object. | Medium | Getters only; the excluded list in §1.8 is normative. Code-review checklist item for the macro. |
| **Portable-format break** (v3 unreadable by older StarPost). | Medium | Accept v2+v3 on read; changelog + docs note. This is the established policy ("bump VERSION if the layout changes in a way older readers can't handle"). |
| **Stale properties vs. re-solved sim** — properties describe the sim *at extraction time*; the user may re-run the solver afterwards. | Low | Already true of every extracted value; `extracted_at` is displayed in the dialog to anchor it. |
| **Homogeneity/comparison regressions** — properties differing across sims must not push the workspace out of comparison mode. | Low | `signature()` untouched; test asserting that. |
| **Cache size growth.** | Low | Properties are ~1–10 KB of strings per sim; plot series dominate by orders of magnitude. |
| **Units/locale in values** (e.g. `0.01 m`, decimal commas from a localized server). | Low | Store display strings as-is for the dialog; anything parsed as a number (cell count) is written by the macro with `Locale.ROOT`-safe formatting (plain `long`/`double` toString). |

## 4. Open questions (flag before implementation)

1. **Dialog form:** is a summary-form + collapsible tree right, or should this
   become a tabbed dialog (Summary / Mesh / Regions / Physics / Tags)? Design
   assumes tree; cheap to swap.
2. **Tier 2 value selection:** which mesh defaults matter to your workflow
   beyond base size (prism layers? target surface size?) — drives which
   fragile `star.meshing` reads are worth carrying.
3. **Should properties export into the portable CSV at all**, or stay
   cache-only? Design says export (the portable file is pitched as
   full-fidelity), at the cost of the version bump.
4. **Folder properties aggregation** — sum cells/iterations across a Data-tab
   folder? Deferred; per-sim first.
