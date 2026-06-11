# starpost — Program Overview & Design Specification

> Package/application name: **starpost**
> Repository: `autonomic` (to be renamed `starpost` later)
> Status: v1 scaffold — runnable GUI shell with core extraction/parsing logic
> implemented; several actions stubbed (see [Implementation Status](#9-implementation-status)).
> Document last updated: 2026-06-11

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [What the Program Does (Capabilities)](#2-what-the-program-does-capabilities)
3. [What It Does *Not* Do (Limitations)](#3-what-it-does-not-do-limitations)
4. [How It Works (Architecture)](#4-how-it-works-architecture)
5. [Data Flow, End to End](#5-data-flow-end-to-end)
6. [Data Model](#6-data-model)
7. [Project Structure (File by File)](#7-project-structure-file-by-file)
8. [Locked Design Decisions (from requirements gathering)](#8-locked-design-decisions-from-requirements-gathering)
9. [Implementation Status](#9-implementation-status)
10. [Setup & Usage](#10-setup--usage)
11. [Open Questions / Future Work](#11-open-questions--future-work)

---

## 1. Purpose

**starpost** is a standalone desktop application that automates parts of the
post-processing workflow for **Siemens STAR-CCM+** CFD simulations.

Engineers solving CFD cases in STAR-CCM+ accumulate large numbers of `.sim`
files, each containing **reports** (scalar output values such as drag force,
lift force, average pressure) and **monitor plots** (quantities tracked over
iterations, such as residuals or force histories). Extracting and comparing
these values across many files is normally a manual, repetitive task done inside
the STAR-CCM+ GUI one file at a time.

starpost automates that extraction. It opens solved `.sim` files in batch,
pulls out every report value and monitor plot, and presents them in a custom GUI
where the engineer can **view, filter, compare, and export** the data — without
re-solving and without manually clicking through each simulation.

The initial focus is **numeric data only**: report values and monitor plots. 3D
scene rendering and complex visualization are explicitly out of scope for v1 but
are noted as possible future extensions.

---

## 2. What the Program Does (Capabilities)

### Extraction
- Reads **solved** STAR-CCM+ `.sim` files (no re-solving; reports re-evaluate
  against the stored solution).
- Extracts **all report values** (name, value, units) from each file.
- Extracts **all monitor plots** (value vs. iteration), including multi-series
  plots such as residuals (continuity, momentum components, energy, etc.).
- Uses an **extract-all-then-filter** strategy: a single pass per file (one
  license checkout) dumps everything; filtering happens in the app afterward.

### Batch processing
- Accepts **multiple `.sim` files at once** (add individually or by folder).
- Processes files **sequentially**, so at most one STAR-CCM+ license is checked
  out at a time (license-safe).
- Designed for batches of **up to ~25 files** (the expected practical ceiling).
- **"Stop after current file"** — halts gracefully without killing a batch
  session mid-write.
- Live **progress bar** and **streaming log** of STAR-CCM+ output.
- **Homogeneity check**: assumes batch files share the same reports/plots; if
  they don't, the user is warned and the union of all names is shown.

### Viewing (in-app)
- **Per-file mode** (default): browse one simulation's reports and plots.
- **Comparison mode**: a wide table of report values across all sims (one row
  per sim, one column per report), and plot overlays of the *same* monitor plot
  across multiple sims.
- **Report table**: numeric values with units.
- **Monitor plot viewer** (interactive, pyqtgraph):
  - **Residual plots** → all series overlaid in distinct colors with a
    **logarithmic Y axis**.
  - **Force / other plots** → distinct colors with a **linear Y axis**.
  - Axis type is auto-classified by plot name and is **overridable**.

### Selection & profiles
- User picks **which reports/plots** to view and export, with a **Select All**
  option per category.
- **Profiles**: save a named selection of reports/plots (and axis overrides) to
  reuse on future files with similar contents. Stored as YAML.

### Export
- **Report values → CSV**
  - Wide comparison layout: one row per sim, one column per report, units
    embedded in headers (e.g. `Drag Force [N]`).
  - Per-file long layout: `report, value, units`.
- **Monitor plots → JPG / PDF** (rendered natively by the app via matplotlib,
  honoring the per-plot log/linear axis choice and multi-series coloring).
- Exports are written to a **user-defined output folder** chosen per run.

### Configuration & resilience
- **Configurable STAR-CCM+ executable path** (manual, with an intended team
  default).
- **Licensing**: defaults to **Power-on-Demand key + license server**
  (`-power -podkey <KEY> -licpath <port>@<server>`); also supports a **regular
  license file**.
- **Crash-recovery cache**: extracted results are checkpointed to disk after
  every file, so a crash or unexpected exit doesn't lose completed work.

---

## 3. What It Does *Not* Do (Limitations)

### Fundamental / architectural
- **It does not parse `.sim` files directly.** The STAR-CCM+ `.sim` format is
  proprietary, binary, and has no public reader/SDK. starpost drives an
  installed STAR-CCM+ engine via its Java macro API in batch mode and reads back
  exported CSVs. **A licensed STAR-CCM+ installation must be present** on the
  machine running starpost.
- **Every extraction consumes a license checkout** and incurs STAR-CCM+ startup
  time. This is inherent to the batch-macro approach and is why runs are
  sequential and results are cached.
- The tool is only as fast as STAR-CCM+ batch startup allows; it is not a
  lightweight file reader.

### Scope (v1)
- **Numeric data only** — reports and monitor plots. No 3D scenes, no field
  visualization, no isosurfaces/streamlines/section rendering.
- **Monitor plots only** for plot data — i.e. value-vs-iteration/time plots
  (residuals, force histories). **XY plots** (a field along a line/probe) and
  other plot types are not handled in v1.
- Reports are read as their current **monitor value**; the tool does not modify,
  create, or re-define reports/plots inside the `.sim`.
- The tool **reads** simulations; it does not write changes back into `.sim`
  files.

### Platform & distribution
- Built and targeted for **Linux** first. Windows support is planned but not
  implemented (the code uses XDG paths and forward-slash macro paths with that
  portability in mind, but it is untested on Windows).
- No installer yet; v1 is run from source. PyInstaller packaging (→ AppImage for
  Linux) is scaffolded but not built.

### Validation caveats
- The **Java macro has not been validated against a live STAR-CCM+ install**
  (none was available during development). The API calls used
  (`getReportManager`, `getReportMonitorValue`, `StarPlot.export`) are stable
  across recent versions, but very old releases could differ.
- The **exact CSV layout produced by `StarPlot.export()`** for monitor plots is
  the main unverified assumption. The parser handles the common single-X-column
  layout but is flagged for tightening once tested on real exports.

---

## 4. How It Works (Architecture)

starpost is fundamentally an **orchestrator + viewer**, not a file parser. It
sits on top of an installed STAR-CCM+ engine.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          starpost (PySide6 GUI)                        │
│                                                                        │
│  File list ──► Batch queue ──► StarRunner ──► (subprocess)             │
│                    │                │                                   │
│                    │                ▼                                   │
│                    │      starccm+ -batch extract_all.java \           │
│                    │        -power -podkey KEY -licpath P@S  file.sim   │
│                    │                │                                   │
│                    │                ▼                                   │
│                    │      STAR-CCM+ opens .sim, runs macro,            │
│                    │      exports CSVs (reports + plot series)         │
│                    │                │                                   │
│                    ▼                ▼                                   │
│              ResultParser ◄── exported CSVs                            │
│                    │                                                    │
│                    ▼                                                    │
│              ResultStore (in-memory + JSON crash cache)               │
│                    │                                                    │
│         ┌──────────┼───────────────┐                                   │
│         ▼          ▼               ▼                                    │
│   ReportTable   PlotView    Selection/Profiles ──► Export (CSV/JPG/PDF)│
└──────────────────────────────────────────────────────────────────────┘
```

**Technology stack** (chosen as the best fit for this scenario):

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best fit for subprocess orchestration + data handling; matches the proven prototype approach |
| GUI | PySide6 (Qt) | Native Linux, cross-platform later, fully custom UI via QSS |
| Plots (in-app) | pyqtgraph | Fast, interactive value-vs-iteration plotting with log-scale support |
| Plots (export) | matplotlib | Publication-quality JPG/PDF rendering |
| Tabular data | pandas | Wide/long report tables, easy CSV export |
| Config/profiles | PyYAML | Human-readable, editable config and profiles |
| Macro templating | Jinja2 | Parameterized Java macro generation |
| Engine interface | STAR-CCM+ Java macro API via `starccm+ -batch` | Only supported way to read `.sim` data |

---

## 5. Data Flow, End to End

1. **User adds `.sim` files** to the batch list (individually or by folder) and
   clicks **Run batch**, choosing an output folder.
2. For **each file, sequentially**, `StarRunner`:
   - renders the Java macro `extract_all.java` from its template (pointing it at
     the output folder),
   - builds the command:
     `starccm+ -batch extract_all.java <license args> <extra args> file.sim`,
   - launches it as a subprocess, streaming combined stdout/stderr to the log.
3. **Inside STAR-CCM+**, the macro (one license checkout, one pass):
   - writes `<simname>_reports.csv` — `sim_file, report, value, units` for every
     report (per-report try/catch logs `ERROR` instead of aborting),
   - exports each monitor plot to `<simname>__plot__<plot>.csv`
     (X column + one column per series),
   - writes `<simname>__plots_index.csv` mapping plot name → CSV file.
4. **`ResultParser`** reads those CSVs into a `SimResult` and **classifies each
   plot** (residual → log Y, force → linear Y).
5. **`ResultStore`** holds all `SimResult`s in memory and **checkpoints a JSON
   cache** after every file (crash recovery).
6. After the batch, a **homogeneity check** warns if files differ in their
   report/plot sets.
7. The GUI shows the **union** of report/plot names in the **selection panel**;
   the user filters (or loads a **profile**).
8. **Views** render the filtered data (per-file or comparison).
9. **Export** writes the selected data to the chosen folder as CSV (numbers)
   and/or JPG/PDF (plots).

> **Key efficiency point:** because the macro extracts *everything* on the single
> license-consuming pass, the user can change their selection, build comparisons,
> and re-export **without ever re-running STAR-CCM+**.

---

## 6. Data Model

Defined in `src/starpost/data/models.py`:

- **`Report`** — `name`, `value` (`None` if extraction failed), `units`,
  optional `error`.
- **`PlotSeries`** — one line on a plot: `name`, `x[]`, `y[]` (shared X axis).
- **`MonitorPlot`** — `name`, `series[]`, `kind`
  (`RESIDUAL` / `FORCE` / `OTHER`), `x_label`, `y_log` (resolved axis choice,
  user-overridable), optional `error`.
- **`SimResult`** — everything from one `.sim`: `sim_path`, `reports[]`,
  `plots[]`, `extracted_at` timestamp, optional batch-level `error`. Provides a
  `signature()` (the set of report + plot names) used for the homogeneity check.

---

## 7. Project Structure (File by File)

```
autonomic/                          (repo; app/package = "starpost")
├── README.md                       Quick orientation + dev quickstart
├── pyproject.toml                  Package metadata, deps, entry point, ruff config
├── requirements.txt                Runtime dependency pins
├── .gitignore                      Ignores .sim files, build artifacts, caches
│
├── config/
│   └── default_settings.yaml       Shipped defaults; copied to user config on first run
│
├── docs/
│   └── PROGRAM_OVERVIEW.md          This document
│
├── packaging/
│   └── starpost.spec               PyInstaller spec (Linux → AppImage later)
│
├── scripts/
│   └── dev_run.py                  Launch the GUI from a source checkout (no install)
│
├── tests/
│   ├── test_aggregator.py          Wide report-table layout + selection filtering
│   ├── test_result_parser.py       CSV parsing + plot classification
│   └── test_settings.py            License flag generation (POD/server/file)
│
└── src/starpost/
    ├── __init__.py                 Version, APP_NAME
    ├── app.py                      Entry point: QApplication, stylesheet, MainWindow
    │
    ├── core/                       Engine interface & business logic (no GUI)
    │   ├── settings.py             Settings + LicenseConfig + Profile (YAML I/O)
    │   ├── macro_generator.py      Renders extract_all.java from the Jinja2 template
    │   ├── starccm_runner.py       Builds CLI, runs starccm+ subprocess, streams log
    │   ├── result_parser.py        Parses exported CSVs; classifies plots (log/linear)
    │   └── plot_export.py          Renders a MonitorPlot to JPG/PDF (matplotlib)
    │
    ├── macros/
    │   └── extract_all.java.j2     Canonical Java macro: ALL reports + ALL plots, one pass
    │
    ├── batch/                      Batch orchestration
    │   ├── job.py                  Job + JobState (pending/running/done/failed/skipped)
    │   ├── queue.py                BatchWorker (QObject): sequential, stop-after-current
    │   └── aggregator.py           Wide/per-file report frames + CSV export
    │
    ├── data/                       Data model & storage
    │   ├── models.py               Report, PlotSeries, MonitorPlot, SimResult, PlotKind
    │   └── store.py                ResultStore: in-memory + JSON crash cache; homogeneity
    │
    ├── gui/                        PySide6 user interface
    │   ├── main_window.py          Assembles panels, wires the batch worker & views
    │   ├── resources/
    │   │   └── theme.qss           Custom QSS theme (placeholder, iterate)
    │   └── views/
    │       ├── file_list.py        Batch list: add files/folder, remove, clear
    │       ├── selection_panel.py  Report/plot checkboxes, Select All, profile load/save
    │       ├── report_table.py     Numeric viewer (per-file long + comparison wide)
    │       ├── plot_view.py        pyqtgraph viewer (log residuals, plot comparison)
    │       ├── log_console.py      Live log + progress bar
    │       └── export_dialog.py    Export options (what + format + folder)
    │
    └── utils/
        ├── paths.py                XDG config/cache/profile locations
        └── logging.py              Stderr + rotating file logging
```

---

## 8. Locked Design Decisions (from requirements gathering)

These are the specifics gathered during the requirements conversation. They are
the authoritative answers that shaped the v1 design.

### Scope of data
- **Data types:** report values (scalars) **and** monitor plots (value vs.
  iteration — the type used for residuals and forces).
- **Plot type:** **monitor plots only** in v1 (not XY plots or others).
- **Numeric only:** no 3D scene rendering or complex visualization in v1; noted
  as a *possible later feature*.

### Selection & profiles
- Users can **pick which reports/plots are output**, with a **Select All**
  option.
- A **profile feature** lets users save exactly which reports/plots they want and
  reload that selection for files with similar contents.
- **Extraction mechanism:** **extract-all-then-filter** — one license checkout
  per file dumps all reports + monitor plots into cache; the selection/profile
  filters what is shown and exported. (Chosen over "export only picked items,"
  which would have required an extra discovery license checkout.)

### Batch behavior
- Support **batch processing**: multiple `.sim` files uploaded/added at once.
- **Assume batches are homogeneous** (same reports/plots across files), but
  **prompt/warn the user if they are not**.
- **Maximum expected batch size: fewer than 25 files.**
- Runs are **sequential** to keep at most one license checked out at a time.

### Workflow / UI
- **Per-file workflow is the default**, with an **additional comparison mode**
  for comparing values/plots across sims.
- The UI is **made from scratch and entirely custom** (custom QSS theme, not
  default-looking native widgets).
- **In-app viewing** of both numeric values and plots, plus export.

### Plot rendering specifics
- **Residual plots:** plot all values on the **same plot** in **different
  colors**, with a **logarithmic Y axis**.
- **Force plots:** use a **regular (linear) Y axis**.
- (Implemented as automatic name-based classification, overridable per plot.)

### Export
- **Numeric values → `.csv`.**
- **Plots → `.jpg` / `.pdf`** (rendered natively by the app).
- Exports go to a **user-defined location** chosen per run.
- Report comparison CSV uses a **wide layout** (one row per sim, one column per
  report, units embedded in headers like `Drag Force [N]`); per-file CSV uses a
  long `report, value, units` layout.

### Configuration & licensing
- **STAR-CCM+ executable path:** configurable **manually**, defaulting to a path
  to be provided by the team (currently blank in `default_settings.yaml`).
- **Licensing default:** **POD key + license server** —
  `-power -podkey <KEY> -licpath <port>@<server>`.
- **Alternative licensing:** option to use a **regular license file**.

### Persistence
- **Saving an extraction config (profile) is preferred** for reuse.
- A **cache** is kept as a failsafe against crashes or other problems.

### Platform & distribution
- **Linux-native** initially, with **potential extension to Windows** later.
- Distribution is to a **team of engineers**; an **installer is ideal** but **not
  required initially**.

### Technical environment
- The software **runs on an engineer's local machine** (not a shared cluster /
  HPC scheduler).
- Implementation language: **any**, choosing the best fit → **Python 3.11+ with
  PySide6**.

---

## 9. Implementation Status

**Implemented and working (logic verified where dependency-free):**
- Java macro template (reports + all monitor plots, single pass).
- Macro generation, subprocess runner with full license-flag handling.
- CSV parsing and automatic plot classification (residual=log / force=linear).
- Data model, in-memory store, JSON crash-recovery cache, homogeneity check.
- Batch worker: sequential execution, progress/log signals, stop-after-current.
- Report aggregation (wide comparison + per-file) and CSV export helpers.
- Plot export to JPG/PDF (matplotlib) honoring axis choice.
- Full GUI shell: file list, selection panel with profiles, report table, plot
  viewer (per-file + comparison), log console, export dialog, custom QSS theme.
- Settings + Profile YAML persistence.
- Unit tests for parser, classifier, aggregator, and license flags.

**Stubbed / TODO (clearly marked in code):**
- **Settings dialog** — currently directs the user to edit the YAML file; needs a
  proper in-app form (exe path, license mode/key/server, default output dir).
- **Export action wiring** — the export dialog collects options but does not yet
  call the aggregator / plot exporter; the hookup points exist.
- **Per-plot axis-override UI** — supported in the data model; no toggle widget
  yet.
- **`starccm_path` default** — blank pending the team's install path.
- **`StarPlot.export()` CSV layout** — parser handles the common case; needs
  validation against real exports and tightening.
- **PyInstaller/AppImage build** — spec exists; not yet produced.

**Not validated:**
- The Java macro has not been run against a live, licensed STAR-CCM+ install.

---

## 10. Setup & Usage

### Requirements
- Python 3.11+
- A local, licensed STAR-CCM+ installation (path set in settings)
- Dependencies in `requirements.txt` / `pyproject.toml`

### Run from source (development)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/dev_run.py        # opens the GUI; no STAR-CCM+ needed just to open it
```

### Configuration
- User settings: `~/.config/starpost/settings.yaml` (seeded from
  `config/default_settings.yaml` on first run).
- Profiles: `~/.config/starpost/profiles/*.yaml`.
- Crash cache: `~/.cache/starpost/results_cache.json`.
- Logs: `~/.cache/starpost/starpost.log`.

### Typical workflow
1. Set the STAR-CCM+ executable path and license details in settings.
2. Add `.sim` files (or a folder of them).
3. Run the batch and choose an output folder.
4. Filter reports/plots (or load a profile); switch between per-file and
   comparison modes.
5. Export numbers to CSV and plots to JPG/PDF.

### Run tests
```bash
PYTHONPATH=src python -m pytest tests/ -q
```

---

## 11. Open Questions / Future Work

- **Validate the Java macro** on a real STAR-CCM+ install and confirm the
  `StarPlot.export()` CSV layout across plot types; tighten the parser.
- **Complete the stubbed actions** (settings dialog, export wiring, axis-override
  UI).
- **Windows support** (swap XDG paths for `platformdirs`; verify subprocess and
  executable auto-detection).
- **Packaging/installer** for team distribution (AppImage on Linux; MSI/NSIS on
  Windows later).
- **Possible later features** (explicitly out of v1 scope): 3D scene/image
  export, XY plots and other plot types, scene rendering, richer report
  templating (e.g. full PDF reports), and optional multi-sim-per-session macro
  runs to reduce license churn further.
```
