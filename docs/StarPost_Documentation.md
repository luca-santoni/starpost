# StarPost — Program Overview & Reference

> Application name: **StarPost** (Python package / import name: `starpost`)
> Repository: `starpost`
> Version: **2.6.0**
> Status: cross-platform (Linux + Windows) GUI with batch extraction, the
> Files/Data workspace (virtual folders + portable data import/export), an
> interactive plot viewer (per-monitor colours, optional moving-average
> smoothing), **sim-properties capture** (solution state, mesh, regions,
> physics and the Geometry ▸ Parts tree, shown in a tabbed Properties window),
> **on-demand scene-still rendering** (the Scenes tab: scene →
> scalar/vector displayer selection, saved-view rendering, parallel/`-np`
> rendering, a thumbnail gallery with Properties), **on-demand screenplay
> recording** (the Screenplays tab: screenplay → displayer selection, saved-view
> recording, a poster-framed gallery that opens movies in the system player), a
> **guided Run batch dialog** (a Source → Reports → Plots → Scenes → Screenplays
> → Summary wizard producing a single archive), a single menu-bar-style top bar
> with a **File** menu, **keyboard shortcuts** for the main views and actions,
> the full in-app settings dialog, a heavily
> customizable report/plot export, an in-app update check, and packaged builds
> (Linux AppImage + Windows Inno Setup installer). The Java extraction macro has
> been run against a live STAR-CCM+ 2310 install (reports, plots, and scene/view
> discovery); the scene-render *apply-saved-view* call is the one remaining
> version-specific operation still being validated (see
> [Limitations](#4-limitations)). Screenplay recording additionally requires
> STAR-CCM+ 2022 or newer (see [3.6b Screenplays view](#36b-screenplays-view)).
> Document last updated: 2026-07-22

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [What the Program Does (Capabilities)](#2-what-the-program-does-capabilities)
3. [User Interface Reference](#3-user-interface-reference)
   - [3.1 Window layout](#31-window-layout)
   - [3.2 Top bar](#32-top-bar)
   - [3.3 Files panel](#33-files-panel)
   - [3.4 Data panel](#34-data-panel)
   - [3.5 Reports view](#35-reports-view)
   - [3.6 Plots view](#36-plots-view)
   - [3.6a Scenes view](#36a-scenes-view)
   - [3.6b Screenplays view](#36b-screenplays-view)
   - [3.7 Selection panel (right)](#37-selection-panel-right)
   - [3.8 Log console](#38-log-console)
   - [3.9 Export dialog](#39-export-dialog)
   - [3.9a Run batch dialog](#39a-run-batch-dialog)
   - [3.9b Express batch dialog](#39b-express-batch-dialog)
   - [3.10 Settings dialog](#310-settings-dialog)
   - [3.11 Welcome / setup wizard](#311-welcome--setup-wizard)
   - [3.12 Updates](#312-updates)
   - [3.13 Keyboard shortcuts](#313-keyboard-shortcuts)
4. [Limitations](#4-limitations)
5. [How It Works (Architecture)](#5-how-it-works-architecture)
6. [Data Flow, End to End](#6-data-flow-end-to-end)
7. [Data Model](#7-data-model)
8. [Configuration Files & Locations](#8-configuration-files--locations)
9. [Project Structure (File by File)](#9-project-structure-file-by-file)
10. [Setup & Usage](#10-setup--usage)
11. [Implementation Status](#11-implementation-status)
12. [Design Decisions (Requirements History)](#12-design-decisions-requirements-history)
13. [Open Questions / Future Work](#13-open-questions--future-work)

---

## 1. Purpose

**StarPost** is a standalone desktop application that automates parts of the
post-processing workflow for **Siemens STAR-CCM+** CFD simulations.

Engineers solving CFD cases in STAR-CCM+ accumulate large numbers of `.sim`
files, each containing **reports** (scalar output values such as drag force,
lift force, average pressure) and **monitor plots** (quantities tracked over
iterations, such as residuals or force histories). Extracting and comparing
these values across many files is normally a manual, repetitive task done inside
the STAR-CCM+ GUI one file at a time.

StarPost automates that extraction. It opens solved `.sim` files in batch,
pulls out every report value and monitor plot, and presents them in a custom GUI
where the engineer can **view, filter, compare, and export** the data — without
re-solving and without manually clicking through each simulation.

The core focus is **numeric data**: report values and monitor plots. As of
**v2.0.0** StarPost also **renders scene stills** (images) from a `.sim`'s
scenes — letting the engineer pick which scalar/vector displayers are shown and
which saved camera view to render from — exported as JPG/PNG image files (see
[Scene rendering](#scene-rendering) and the [Scenes tab](#36a-scenes-view)). As
of **v2.3.0** it also **records screenplays** (STAR-CCM+ animations) to movie
files from the same scene → displayer and saved-view picker, with a poster-frame
gallery (see [Screenplay recording](#screenplay-recording) and the
[Screenplays tab](#36b-screenplays-view)). Other field-visualization output
(e.g. XY plots) remains out of scope (see [Limitations](#4-limitations)).

---

## 2. What the Program Does (Capabilities)

### Extraction
- Reads **solved** STAR-CCM+ `.sim` files (no re-solving; reports re-evaluate
  against the stored solution).
- Extracts **all report values** (name, value, units) from each file.
- Extracts **all monitor plots** (value vs. iteration), including multi-series
  plots such as residuals (continuity, momentum components, energy, etc.).
- Captures the sim's own **metadata** in the same pass (no extra license
  checkout): the **solution state** (iteration, physical time, CPU/elapsed
  time), **mesh** cell/face/vertex counts and the mesh-operation pipeline
  (meshers, base size, surface sizes, prism layers), **regions** with their
  boundary-type breakdown and physics continuum, the **physics** models,
  solvers and stopping criteria per continuum, the **Geometry ▸ Parts** tree
  (composites, sub-assemblies and leaf parts with surface/curve counts),
  interfaces, tags, and the **STAR-CCM+ version** used. Shown in the tabbed
  [Properties window](#33-files-panel) and carried in the portable data CSV.
- Uses an **extract-all-then-filter** strategy: a single pass per file (one
  license checkout) dumps everything; filtering happens in the app afterward, so
  changing the selection never re-runs STAR-CCM+.

### Batch processing
- Accepts **multiple `.sim` files at once** (add individually or by folder).
- Processes files **sequentially**, so at most one STAR-CCM+ license is checked
  out at a time (license-safe).
- Designed for batches of **up to ~25 files** (the expected practical ceiling).
- Live **progress** (an *x/N* counter and a thin progress bar) and a
  **streaming log** of STAR-CCM+ output.
- **Crash-recovery cache**: extracted results are checkpointed to disk after
  every file, so a crash or unexpected exit doesn't lose completed work, and the
  loaded data is restored on the next launch.
- **Homogeneity check**: assumes batch files share the same reports/plots; if
  they don't, the user is warned and the **union** of all names is shown.

### The Files / Data workspace
- A persistent **Files** list of `.sim` files to process (survives restarts),
  with an optional system of **virtual folders** (created in-app only, never on
  disk) to organise files: nest folders to any depth, drag files/folders to
  re-parent them, sort each folder independently, and open or inspect a whole
  folder at once.
- A **Data** list of the results extracted so far, named after their source
  `.sim`, organisable into the same kind of **virtual folders** as the Files tab
  (nest, drag-drop, per-folder sort). **Ticking** Data entries chooses which
  results feed the views; ticking two or more switches the Reports/Plots views
  into **comparison** mode.
- **Portable data import/export**: a loaded data set can be written to a
  self-contained StarPost CSV and re-imported later (into any StarPost instance)
  **without STAR-CCM+** — useful for sharing results or archiving them.
- **Properties** on any file, data set, or folder — a **tabbed window**:
  **General** (size plus report / monitor / iteration counts), **Parts** (the
  Geometry ▸ Parts tree), **Mesh** (cell/face/vertex counts and the
  mesh-operation pipeline), **Regions** (each region's continuum, boundary-type
  breakdown and the interfaces) and **Physics** (each continuum's models,
  solvers and stopping criteria). The Parts/Mesh/Regions/Physics tabs are read
  from the captured sim properties; data sets extracted before that feature show
  a re-extract hint instead. Folder Properties still show combined size + count.

### Viewing (in-app)
- **Per-file mode** (one Data set ticked): that simulation's reports and plots.
- **Comparison mode** (two or more ticked): a wide table of report values across
  the selected sims, and monitor-plot overlays where every line (each data
  set / monitor pair) gets its own colour.
- **Report table**: numeric values with units, configurable decimal places, and
  optional hiding of ~0 reports; sortable by name/value/units.
- **Monitor plot viewer** (interactive, pyqtgraph):
  - **Residual plots** → all series overlaid in distinct colours with a
    **logarithmic Y axis**; **force/other plots** → **linear Y axis**.
  - Axis type is auto-classified by plot name (keyword lists configurable in
    Settings).
  - **Multiple monitor groups at once**; which of each group's series (monitors)
    are drawn is chosen in the selection panel's **Monitor plots** tree (check a
    group to reveal its monitors). Checking a **residual** group plots all its
    monitors at once.
  - **Per-monitor line colours**: a colour swatch beside each shown monitor (one
    per data set in comparison mode) recolours its line; in comparison mode each
    line gets a distinct colour by default.
  - **Smooth data**: an optional moving average over the shown monitors, with a
    configurable window width.
  - **Hover readout**: a marker + coordinate label snapped to the nearest data
    point (log-axis aware; optional monitor name; configurable X/Y decimals).
  - **Region statistics**: **Shift+drag** a rectangle to get a per-series table
    (Avg, Median, Std Dev, Var, Min, Max, Range — choose which appear).
  - **Theme-aware**: background, axes, and legend follow the app's light/dark
    mode and update live.
  - **Empty-monitor / empty-report hiding** by a configurable zero threshold.

### Selection & profiles
- Pick **which reports/plots** to view and export, with **Select all / Clear**
  per category and A–Z / Z–A sorting.
- **Profiles**: save a named selection (reports, monitor groups, which monitors
  show per group, and which region statistics show) as YAML, reusable on future
  files. A reserved built-in **Default** profile selects every report and no
  plots; it cannot be deleted or overwritten.

### Export
- **Reports → CSV / TSV / XLSX / ODS**, with optional embedded units and an
  optional **one-file-per-data-set** mode.
- **Plots → PNG / JPG / TIFF / PDF**, via a live **preview window**, with custom
  title and axis labels, **per-monitor colours** (mirrored from the main view),
  **legend scale**, **line thickness**, **title / axis-label text sizes**, a
  **grid toggle**, theme, and aspect ratio.
- **Configurable defaults** (Settings → Export): the report format, plot image
  format, and plot theme the Export dialog pre-fills.

### Scene rendering
- **On-demand scene stills** from the **Scenes** tab: render a `.sim`'s scenes to
  image files (**JPG / PNG**), at **1080p** or **2160p**.
- **Scene → displayer selection**: a tree (like the monitor-plot groups) where
  each scene is a checkable parent and its **scalar/vector displayers** are
  checkable children — only the ticked displayers are shown in the render.
- **Saved-view rendering**: a **Saved views** list (the sim's saved cameras);
  each checked scene is rendered once per checked view (its camera applied
  first), or from the scene's current view when none is checked.
- **Discovered during extraction**: the normal extraction pass also lists each
  sim's scenes (and their scalar/vector displayers) and saved views, so the
  Scenes tab populates without rendering anything.
- **Thumbnail gallery** of the rendered stills (per ticked data set):
  double-click to open in the system viewer; right-click → **Properties** (file
  size, image resolution, format, and the parent `.sim`, data set, scene/report
  group, displayers, and saved view); **Clear scenes** removes the stills.
- **Rendering pass** (separate from numeric extraction): runs the render macro in
  **parallel** (`starccm+ -np`, a configurable core count), rendering a
  configurable number of **scenes per license checkout** and closing each scene
  after its hardcopy to limit memory growth. A first-open warning notes that
  rendering is memory-heavy (≥16 GB recommended; close other programs first).

### Screenplay recording
- **On-demand screenplay recording** from the **Screenplays** tab: record a
  `.sim`'s STAR-CCM+ screenplays (animations) to **movie files** (**MP4 / AVI /
  MOV**), at **1080p** or **2160p**, with a configurable frame rate, encoder
  quality, **start time** and **animation length** (length **Auto** = each
  screenplay's own length, matching STAR-CCM+'s Write Animation dialog).
- **Screenplay → displayer selection**: a tree, identical in behaviour to the
  Scenes tree — each screenplay is a checkable parent and its scene's
  **scalar/vector displayers** are checkable children — only the ticked
  displayers are visible in the recording.
- **Saved-view recording**: shares the Scenes tab's **Saved views** list; each
  checked screenplay is recorded once per checked view (its camera applied
  first), or from the screenplay's own/current view when none is checked.
- **Discovered during extraction**: the normal extraction pass also lists each
  sim's screenplays (and their scene's scalar/vector displayers), so the
  Screenplays tab populates without recording anything. Screenplay discovery
  and recording require **STAR-CCM+ 2022 or newer**; on older releases the tree
  is simply empty.
- **Poster-framed gallery** of the recorded movies (per ticked data set): each
  tile shows a poster frame (the movie's first frame) with a play badge;
  double-click opens the movie in the **system video player**; right-click →
  **Properties** (file size, format, frame rate, and the parent `.sim`, data
  set, screenplay, displayers, and saved view).
- **Recording pass** (separate from numeric extraction and from scene
  rendering): runs the record macro in **parallel** (`starccm+ -np`), recording
  a configurable number of **screenplays per license checkout**. The recorder is
  invoked **reflectively** (STAR-CCM+'s screenplay API is scanned at runtime,
  not compiled against), so a mismatch on a given release fails that
  screenplay only, never the whole run. Shares the Scenes tab's first-open
  memory warning.

### Configuration, appearance & resilience
- **Configurable STAR-CCM+ executable path** and **extra CLI args**.
- **Licensing**: defaults to **Power-on-Demand key + license server**
  (`-power -podkey <KEY> -licpath <port>@<server>`); also supports a **regular
  license file** (`-licpath <file>`).
- **Dark/light theme** with a custom **accent colour**, **checkmark colour**, and
  **folder-icon colour**, plus an **adjustable text size** (1.0×–1.5×),
  previewed live across the whole UI.
- **Credential safety**: the POD key is masked in the UI (reveal on demand), the
  settings file and log are written **owner-only** (`0600`), and license
  credentials are **redacted** from the log and on-screen command output.
- **In-app update check** against GitHub releases (on startup and on demand):
  a "New update available" note appears in the top bar, and on the packaged
  Windows build the update can be downloaded and installed in place.
- **"Clear all temp files"** (Settings → Misc) removes cached logs, the
  crash-recovery cache, generated icons, and downloaded updates after a
  confirmation that lists what will go.
- **Hover tooltips** on every top-bar/button control describing what it does
  (with the control's keyboard shortcut appended, where it has one).
- **Menu-bar-style top bar** — a single frameless top bar carries a **File**
  menu (Add files/folder, Import/Export data) and the **Run batch** menu, both
  opening on click and behaving like a traditional menu bar, with a small glyph
  icon beside each entry. The StarPost badge sits at the left; the version label
  and integrated minimise / maximise / close buttons at the right.
- **Keyboard shortcuts** for the main views and actions (tab switching, batch
  dialogs, add/import/export, select-all/clear, run/record, smoothing, and the
  Files/Data list actions) — shown in the menus and tooltips and listed in full
  in [3.13 Keyboard shortcuts](#313-keyboard-shortcuts).
- **First-run setup wizard** for the essentials, re-openable any time.
- **Cross-platform**: per-OS config/cache/log locations via `platformdirs`;
  packaged as a Linux **AppImage** and a Windows **Inno Setup installer**.

---

## 3. User Interface Reference

This section documents every panel, control, button, and context (right-click)
menu in the application. StarPost's actions are reached through the **top bar**
(a single menu-bar-style strip with a **File** menu and a **Run batch** menu,
plus **Export…** and **Settings…**), through **context menus** on the various
panels, and through **keyboard shortcuts** (see
[3.13](#313-keyboard-shortcuts)). The panels themselves have no button rows —
their full height goes to the lists.

### 3.1 Window layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ★ File  Run batch  Export…  Settings…      StarPost v2.5.0  — ▢ ✕  ← top bar│
├───────────────┬───────────────────────────────────┬───────────────────┤
│  Files | Data │ Reports|Plots|Scenes|Screenplays  │  Selection panel    │
│  (left tabs)  │   (centre tabs)                   │  (Profile + lists)  │
│               │                                   │                     │
├───────────────┴───────────────────────────────────┴───────────────────┤
│  x/N counter + progress bar                                             │
│  Live batch log (read-only)                              ← log console  │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Left** — a tab widget with **Files** (`F1`) and **Data** (`F2`) tabs.
- **Centre** — a tab widget with **Reports** (`1`), **Plots** (`2`), **Scenes**
  (`3`), and **Screenplays** (`4`) tabs.
- **Right** — the **Selection panel** (profile controls + the list(s) for the
  active centre tab — Reports list on Reports, Monitor plots on Plots, the
  Scenes tree + Saved views list on Scenes, and the Screenplays tree + the same
  Saved views list on Screenplays).
- **Bottom** — the **Log console** (progress + streaming log).
- The three top regions and the bottom are separated by draggable splitters.
- Window title: **StarPost**; default size 1280×800.

### 3.2 Top bar

A single frameless **top bar** doubles as the window's title bar. From the left
it carries the StarPost badge, then the menu items and actions; at the far right
sit the version label and the window buttons. The **File** and **Run batch**
menus behave like a traditional **menu bar**: a click opens the menu, it stays
open wherever the mouse goes, hovering the other menu button switches to it, and
a click anywhere else dismisses it. While a menu is open its button shows the
near-invisible pressed shade (not the bright hover highlight), so it is clear
which menu is active. Each menu entry carries a small **glyph icon** to its left
(add, import/export, play/fast-forward…) that follows the light/dark theme and
takes the accent's contrast colour on the highlighted row.

| Action | Behaviour |
|---|---|
| **File** | A menu (first in the bar) with **Add ▸ Files…** (`Ctrl+N`) / **Folder…** (`Ctrl+Shift+N`) — the Files tab's add dialogs — and **Import data…** (`Alt+Shift+I`) / **Export data…** (`Alt+Shift+E`) — the Data tab's portable-CSV import/export. The same operations reachable from the panels, without switching tabs. |
| **Run batch** | A menu with two entries: **Full Batch** (`Ctrl+Shift+B`) — opens the [Run batch dialog](#39a-run-batch-dialog), the guided six-tab wizard; and **Express batch** (`Ctrl+Shift+E`) — opens the [Express batch dialog](#39b-express-batch-dialog), a lean window for running a saved batch profile quickly. (To extract straight to the workspace without a wizard, right-click → **Load file** a file in the Files panel instead.) The whole button is disabled while a run is in progress. |
| **Export…** | Opens the [Export dialog](#39-export-dialog). |
| **Settings…** | Opens the [Settings dialog](#310-settings-dialog). |

At the **far right** of the bar a greyed **`StarPost v<version>`** label shows
the running version, followed by the integrated **minimise / maximise / close**
buttons (which fill the bar's full height; close turns red on hover). If the
startup update check finds a newer release, a **"New update available"** note
(tinted with the accent colour) appears beneath the version label.

Dragging the bar moves the window, double-clicking it maximises, and pressing
near a window edge resizes — all via the window manager, so native snapping is
preserved.

Every action and button in the app has a **hover tooltip** describing what it
does, with its keyboard shortcut appended where it has one (shown after a short
delay; moving to another control restarts the delay rather than showing the next
tooltip instantly).

### 3.3 Files panel

The **Files** tab: the batch list of `.sim` files to process, optionally
organised into **virtual folders**. The full layout (files, folders, nesting,
expansion, and per-folder sort) is **persisted to disk** and restored on the
next launch. Folders live **only inside StarPost** — they are never created on
the filesystem.

**Adding files** — the panel has no button row; files and folders are added from
the top bar's **File ▸ Add** menu (or its hotkeys):
- **Add files…** (`Ctrl+N`) — file picker filtered to `*.sim`; adds the chosen
  files.
- **Add folder…** (`Ctrl+Shift+N`) — folder picker; creates a new internal folder
  named after the chosen directory and adds every `*.sim` directly inside it into
  that folder (skipping any already in the list; nothing is added if the
  directory holds no `.sim` files or they are all already present).

**Interactions:**
- **Multi-select** — **Shift+click** selects a contiguous range and **Ctrl+click**
  toggles individual rows (standard extended selection).
- **Double-click a file** → *load* just that file (extract + view it).
- **Drag and drop** files/folders to **re-parent** them (move into a folder, out
  to the top level, or between folders); a folder can't be dropped into its own
  subtree.
- **Right-click a file** → **Load file** (or **Load files** when two or more are
  selected — extracts and views every selected file, in top-to-bottom order;
  `Ctrl+L`), **Properties** (`Ctrl+P`), and **Remove** (removes the selected
  rows after a confirmation; `Delete`). Each entry shows its key. Right-clicking
  a row outside the current selection first selects just that row.
- **Right-click a folder** → **Open All** (extract + view every `.sim` in it,
  recursively), **New Nested Folder**, a **Sort** submenu (A–Z, Z–A, File Size
  Largest, File Size Smallest — orders just this folder's contents), **Rename**,
  **Delete folder** (dissolves the folder but keeps the contents, moving them up
  to the parent), **Remove** (`Delete`; removes the folder *with* its contents),
  and **Properties** (`Ctrl+P`; combined size + file count).
- **Right-click empty space** → **New Folder** (at the top level).
- **Right-click the "Files" tab** → the **sort menu** (the active mode is
  checkmarked): **Name (A–Z)**, **Name (Z–A)**, **File size (largest)**,
  **File size (smallest)** — applied to every folder — then, below a separator, a
  red **Clear** entry that empties the whole list after a confirmation (it
  inverts to a red fill with white text when hovered).

The list-focus keys work without opening a menu: `Ctrl+L` loads, `Ctrl+P` shows
properties, and `Delete` removes the selected files/folders (each after the
usual confirmation).

**Notes:**
- Only `.sim` files are added; duplicates (by resolved path) are ignored.
- Folders sort their contents **folders first, then files**; nested files are
  marked with a small dash for legibility, and folder icons can be **tinted** to
  a chosen colour (Settings → Appearance → Folders).
- Each leaf (file) row carries a small **node dot**; by default it follows the
  theme accent, or a chosen colour set in Settings → Appearance → **Node dots**.
- Each row shows the file name by default, or the full path if *Show file path*
  is enabled in Settings → Files; the full path is always in the tooltip.
- *Opening* a file that is already loaded prompts to load only the new files,
  force-reload, or cancel.

### 3.4 Data panel

The **Data** tab: one entry per result extracted so far, named after its source
`.sim`. This is the set of results the Reports/Plots views draw from. Like the
Files tab, data sets can be organised into **virtual folders** (created in-app
only): right-click empty space for **New Folder**, drag data sets/folders to
re-parent them, and nest folders to any depth. The folder layout — including each
folder's open/closed state — persists across sessions; the data sets themselves
come and go with what's loaded.

**Interactions:**
- Each data set has a **checkbox**; **clicking anywhere on a row toggles it**
  (drag a row instead to move it between folders). Click one row then
  **Shift+click** another to set every checkbox between them to the first row's
  new state — the same range-tick shortcut used across the app's checkbox lists
  (the report / monitor / plot / scene selection lists, the export dialogs, and
  the region-statistics list).
- **No** entry checked or **one** checked → **per-file** view; **two or more**
  checked → **comparison** view.
- **Right-click a data set** → **Properties** (its portable-CSV size plus report,
  monitor, and iteration counts) and **Remove** (`Delete`) — deletes the
  **selected** data sets from the store after a confirmation (the underlying
  `.sim` files stay in the Files list). Note that removal now acts on the
  *selected* rows (highlighted), not the *checked* ones.
- **Right-click a folder** → **Check all** / **Uncheck all** its data sets,
  **New Nested Folder**, **Sort** (A–Z / Z–A), **Rename**, **Delete folder**
  (contents move up to the parent), and **Properties** (data-set count + combined
  portable-CSV size).
- **Right-click the "Data" tab** → the **sort menu** — **Name (A–Z)** / **Name
  (Z–A)** (orders each folder's contents, folders before data sets) — then, below
  a separator, a red **Clear** entry that wipes **all** loaded results after a
  confirmation (leaving the Files list intact so they can be re-run; it inverts
  to a red fill with white text when hovered). Both removal and Clear are blocked
  while a batch is running.

**Importing / exporting** — the panel has no button row; these live in the top
bar's **File** menu (or their hotkeys):
- **Import data…** (`Alt+Shift+I`) — load one or more **portable StarPost CSVs**
  (as written by Export data) straight into the workspace, with no `.sim` or
  STAR-CCM+ needed. Files that don't match the format are reported and skipped;
  name collisions prompt to overwrite or keep. The portable CSV is now
  **format v3** (it carries the captured sim properties as `prop` rows);
  **v2** files still import, but **v3** files do not import into a pre-v3
  StarPost release.
- **Export data…** (`Alt+Shift+E`) — opens a dialog listing the loaded data sets
  (pre-ticked to the current selection) where you choose which to dump to
  portable StarPost CSV (one re-importable file per data set).

### 3.5 Reports view

The **Reports** tab (centre): a numeric table of report values.

- **Per-file mode** — three columns: **Report**, the **value** column (headed
  with the data set's name), and **Units**.
- **Comparison mode** — a **Report** column, then **one value column per
  selected sim**, then a **Units** column. Report names that are ~0 across all
  selected sims are dropped when *Hide empty reports* is on.
- Values are formatted to the configured **decimal places**; magnitudes below
  the **zero threshold** display as `0`.
- The **Unit system** setting (Settings → Reports — Default / SI / Imperial)
  converts displayed values and the **Units** column accordingly (e.g. a force
  report shows `lbf` under Imperial); unknown or dimensionless units pass
  through unchanged. This only affects the live table — exports and the
  portable data CSV stay in the sim's original units.
- **Right-click the table header** → **sort menu** (active sort checkmarked):
  **Name (A–Z / Z–A)**, **Value (ascending / descending)**, **Units (A–Z /
  Z–A)**. In comparison mode, "Value" orders rows by the across-sim mean.

### 3.6 Plots view

The **Plots** tab (centre): the interactive monitor-plot viewer (pyqtgraph).

**The plot area:**
- Overlays the selected monitor plots; grid, legend, title, and axis labels
  shown. **Residuals** render on a **log Y axis**, **forces/other** on a
  **linear Y axis**. The **Y axis label is the physical quantity and unit**
  (e.g. *Force (lbf)*), inferred from the monitor's unit — Force, Pressure, Mass
  Flow, Velocity, Temperature, etc.; an unrecognised unit shows the unit alone,
  and mixed or unit-less series show *Value*.
- The **Unit system** setting (Settings → Plots — Default / SI / Imperial)
  converts each plotted series and the Y-axis label to match (e.g. *Force
  (lbf)* under Imperial); unrecognised or dimensionless series are left as-is.
  Like the Reports table, this only affects the live plot — exports keep the
  original units.
- In per-file mode each series gets a distinct colour; in comparison mode every
  line — each **(data set, monitor)** pair — gets its own colour, so monitors
  stay distinguishable even within one data set.
- A centred hint **"Select a monitor to begin"** shows while nothing is plotted.
- The view auto-fits (auto-ranges) to the data on each redraw.

**Choosing which monitors are drawn:**
- This lives in the selection panel's **Monitor plots** tree (right), not under
  the plot: check a group to reveal its monitors, then tick the ones to draw.
- A newly checked monitor group starts with **no** monitors shown until you pick
  some — **except residual plots**, which tick all their monitors at once so the
  whole residual set plots together.

**Hover readout:**
- Moving the cursor near a line pins a **marker** and a **coordinate label** to
  the nearest data point (within ~25 px; log-axis aware). The label optionally
  includes the monitor name and uses the configured X/Y decimal places.

**Region statistics (Shift+drag):**
- **Shift + left-drag** rubber-bands a rectangle; on release a shaded region is
  drawn and a **statistics table** appears (one row per series; columns are the
  enabled statistics plus a point-count `n`). The stats panel can be **dragged**
  anywhere on the plot.
- **Shift + click** (a zero-area drag) clears the selection.
- The **Clear selection** button (bottom-right of the tab) is enabled while a
  region is active and removes it.
- Which statistics appear is set in Settings → Plots → Statistics (catalog:
  Avg, Median, Std Dev, Var, Min, Max, Range).

**Smooth data:**
- A **Smooth data** checkbox at the bottom-left of the plot (toggled with
  `Alt+Shift+S` while the Plots tab is active). When ticked, every shown monitor
  is drawn through a **moving average**, so the lines (and the hover/region
  readouts) reflect the smoothed data.
- The window size is **Moving average width** in Settings → Plots (a width of 1
  leaves the data unchanged).

**Other:**
- Without Shift, the usual pyqtgraph **pan (drag)** and **zoom (scroll)** apply,
  and right-clicking the plot exposes pyqtgraph's built-in view-box menu.

### 3.6a Scenes view

The **Scenes** tab (centre): a **thumbnail gallery** of the scene stills rendered
for the ticked data set(s).

- The first time the Scenes tab is opened **each session**, a **warning** notes
  that rendering is very computationally expensive, is not recommended under
  **16 GB** of system memory, and that closing other programs first helps prevent
  memory-related errors. A **"Do not show this again"** checkbox suppresses it for
  good (persisted as `show_scenes_warning`).
- Until something is rendered, a centred hint **"Select scenes and press Run to
  render stills"** is shown.
- Each rendered still appears as a **thumbnail** labelled
  `Scene-Displayers-View`. **Double-click** opens it in the system image viewer.
- **Clicking empty space** clears the thumbnail selection (removes the accent
  highlight).
- **Right-click a thumbnail → Properties** opens a small window listing the
  **file size**, **image resolution** (read from the file), **file format**, and —
  below a separator — the **parent `.sim` file**, **data set**, **report group**
  (the scene), **vector/scalar name** (the visible displayers), and **saved
  view**. (The displayer/view rows populate for stills rendered by v2.0.0+;
  older cached stills show `—`.)

Rendering is driven from the **Scenes** section of the selection panel (right);
see [3.7](#37-selection-panel-right).

### 3.6b Screenplays view

The **Screenplays** tab (centre, after Scenes): a **thumbnail gallery** of the
screenplay movies recorded for the ticked data set(s). It mirrors the Scenes
gallery, with poster frames standing in for the (not previewable) video.

- Recording shares the Scenes tab's first-open **"rendering is very
  computationally expensive"** memory warning (recording a movie is heavier
  than a still) and its **"Do not show this again"** setting.
- Until something is recorded, a centred hint **"Select screenplays and press
  Record to create movies"** is shown.
- Each recorded movie appears as a **tile** showing its **poster frame** (the
  movie's first frame, exported alongside it) with a **play badge** overlay; a
  movie with no poster falls back to a generic play icon. A failed recording
  shows **"(record failed)"**; a movie or poster file missing from disk shows
  **"(file missing)"**.
- **Double-click** a tile to open the movie in the **system video player**
  (`QDesktopServices`, i.e. whatever the OS associates with the file type).
- **Clicking empty space** clears the tile selection (removes the accent
  highlight).
- **Right-click a tile → Properties** opens a window listing the **file
  size**, **format**, and **frame rate**, and — below a separator — the
  **parent `.sim` file**, **data set**, **screenplay**, **displayers** (the
  visible scalar/vector displayers), and **saved view**.

**Output naming:** each recording writes
`<dataset>-<screenplay>[-<displayers>][-<view>].<ext>` (the movie, extension
per the configured container) plus a matching
`<dataset>-<screenplay>[-<displayers>][-<view>]_poster.png` (the poster frame),
to the configured output folder, or alongside the `.sim` when none is set.

**One data set at a time:** like scene rendering, **Record** requires exactly
one ticked Data-tab entry — recording is heavy and the output is per-`.sim`;
ticking zero or more than one and pressing Record shows a message asking you to
tick exactly one.

**Settings → Screenplays** (see [3.10](#310-settings-dialog)) configures the
recorded movie's **resolution** (1080p / 2160p), **container** (MP4 / AVI /
MOV), **frame rate**, **encoder quality**, the recording **start time** and
**animation length** (length **Auto** = each screenplay's own length), and how
many **screenplays per license checkout** are recorded in one STAR-CCM+ session.
Recording always begins at the configured start time (default 0) rather than
the screenplay's own preferred start time.

> Screenplay discovery and recording require **STAR-CCM+ 2022 or newer** (the
> release that introduced first-class Screenplays). On older installs the
> Screenplays tree is simply empty — nothing errors, there is just nothing to
> record.

#### How the recorder is invoked (and why it is reflective)

The screenplay record/export API is version-specific and its class names shift
across releases, and a Java compile error is fatal to the whole macro. So the
record macro never references the screenplay API at compile time — it locates
the recorder **reflectively** at runtime (`Class.forName`, method scanning) and
tries, in order:

1. **Native movie export** — `star.common.AnimationDirectorBase.record(int
   width, int height, double frameRate, double startTime, double
   animationLength, String file, int movieType[, boolean antiAliasing, boolean
   transparentBackground])`, reached via the screenplay's animation director,
   after arming it (`markRecordingScene`, `setFramesPerSecond`,
   `prepareForExport`). The parameter meanings were read off the GUI export
   dialog. **`movieType 0` (Movie File) is the only one used**; `movieType 1`
   (Directory of PNG Frames) is deliberately never tried — it produces the wrong
   output and would cost a full wasted render. This is the **fast** path on an
   adequately-resourced machine, but it renders the whole movie inside one call
   and emits **no per-frame progress** in batch (see the limitation below).
2. **Frame-loop export** — the protocol the GUI itself drives:
   `initializeForMovieExport` → `beginMovieExport` → per-frame `updateAnimation`
   + `exportMovieFrame` → `endMovieExport`/`finalizeMovieExport`. This is the
   fallback that produces the movie when the native call does not; because
   StarPost drives it frame by frame, it is the **only** path that yields a
   determinate per-frame progress bar.
3. A generic name/type scan, as a last resort for other releases.

A call only counts as success when a non-empty **movie file** (not a directory)
exists afterwards. On total failure the log dumps every candidate signature so
the installed release's real API is visible. This was verified against
**Simcenter STAR-CCM+ 2506**: on a memory-starved machine record path 2 (the
frame loop) succeeds, and on an adequately-resourced machine record path 1 (the
fast native call) succeeds.

#### Recording progress feedback — and its limitation

**What the progress bar shows depends on which record path runs**, and this is a
real limitation of driving STAR-CCM+ from a `-batch` macro rather than a StarPost
shortcoming:

- **Native path (path 1) → an indeterminate "Recording…" busy indicator.**
  STAR's `record()` renders the entire movie inside a single call and reports
  frame-by-frame progress **only to its graphical progress presenter**
  (`star.base.neo.ProgressPresenter`) — which does not exist under `starccm+
  -batch`. None of that progress reaches the macro, `starccm+` stdout, or the
  StarPost log, so a **per-frame count is not obtainable on this path**. This was
  confirmed empirically: a native record produced a full movie while emitting
  nothing between the start and end of the call. Rather than a frozen bar or a
  fabricated percentage, StarPost shows an honest **indeterminate
  "Recording &lt;screenplay&gt;…" animation** for the duration of each record.
  Because this is the fast path, it is the one you normally see.
- **Frame-loop path (path 2) → a true per-frame bar.** Here StarPost drives the
  export one frame at a time, so the macro emits a progress marker per rendered
  frame and the bar advances as a **determinate counter**. You generally see
  this only on machines where the native call could not complete (it is slower
  and RAM-bound).

So on the fast path you get a *"recording…"* activity animation, not a frame
number; a genuine frame-by-frame bar appears only on the slower fallback. The
only way to recover a real frame count on the native path would be to inject a
custom progress presenter into STAR — unverified and fragile, and not currently
attempted. Note also that **neither the movie nor its poster is previewable
in-app while recording**; the gallery tile appears once the file lands on disk.

#### Performance and hardware requirements

Recording is bound by how much of the case fits in RAM, not by the macro.
Batch recording launches a **fresh** STAR-CCM+ session that must **load the
whole mesh** before any frame renders, and if the machine lacks the RAM to hold
the case, STAR pages it to disk — that swap thrashing, not the encoder, is what
makes a large case slow. Observed rule of thumb: STAR-CCM+ needs roughly
**1.5–2 GB of RAM per million cells** for a case with field data, so e.g. a
~21-million-cell case wants **~30–40 GB**; on a 16 GB machine the mesh load
alone can take tens of minutes of swapping (this affects scene stills too, not
only screenplays).

Consequences and levers:

- **Adequate RAM is the real fix.** Record a large case on a workstation or the
  cluster where it was solved (32–64 GB+), not a memory-starved laptop.
- **More parallel cores does *not* add memory on a single machine.** The
  "Parallel cores" setting (`-np`) helps on a *cluster* (more nodes = more total
  RAM); on one machine all ranks share the same RAM, so raising it will not
  relieve a memory shortfall and can slightly worsen it.
- **A `.sim` saved at a different partition count is re-partitioned on load**
  (the `Loading/configuring connectivity (old|new partitions: A|B)` step). Cases
  solved on a cluster (e.g. 480 partitions) re-partition to the local core count
  every load. Re-saving the case at the render machine's partition count once
  skips that re-partition compute on subsequent loads (it does not relieve the
  memory shortfall).
- **Batch recordings to pay the load once.** The mesh load is per STAR-CCM+
  session, so recording several screenplays/views in **one** checkout (raise
  **Screenplays per license** in Settings → Screenplays) pays it a single time
  for the whole set — the same way the interactive GUI amortizes a load it keeps
  resident. For a single movie there is no way around one load.

Recording is driven from the **Screenplays** section of the selection panel
(right); see [3.7](#37-selection-panel-right).

### 3.7 Selection panel (right)

Chooses which reports and monitor plots are shown/exported, and manages profiles.
It operates on the **union** of names across the loaded (and ticked) data.

The panel shows the list(s) **matching the active centre tab**: the **Reports**
list on the Reports tab, the **Monitor plots** list on the Plots tab, the
**Scenes** tree + **Saved views** list (split, scenes on top) on the Scenes
tab, and the **Screenplays** tree + the same **Saved views** list (split,
screenplays on top) on the Screenplays tab. The shown list(s) expand to fill
the panel. Selections are remembered — switching tabs only changes which list
is visible, never what is ticked — and profiles still cover reports and plots
together (scenes/views/screenplays are not part of profiles).

**Profile row (top):**
- **Profile dropdown** — lists the built-in **Default** first, then saved
  profiles.
- **Load** — applies the selected profile (its reports, monitor groups, the
  monitors shown per group, and its region statistics). Loading **Default**
  selects every available report and no plots.
- **Save as…** — prompts for a name and saves the current selection as a profile.
  "Default" is reserved; overwriting an existing profile asks for confirmation.

**"Reports" group:**
- **Select all** (`Ctrl+Shift+A`) / **Clear** (`Ctrl+Shift+D`) buttons — the keys
  act on whichever group matches the active centre tab.
- A checklist of report names (checked by default). Clicking a row toggles it.
- **Right-click the group title** → sort **Name (A–Z) / (Z–A)**.

**"Monitor plots" group:**
- A **tree** of monitor-plot groups (each a checkbox). Checking a group **reveals
  its monitors** as checkable children; the **ticked monitors are the ones
  drawn** — so the per-monitor choice lives here rather than under the plot.
- Groups default to **unchecked** (the plot view starts blank, since drawing
  every plot at once is slow), and a freshly checked group reveals its monitors
  **unticked** so you pick deliberately — **except residual plots**, whose
  monitors are all ticked automatically so the whole residual set plots at once.
- **Select all** (`Ctrl+Shift+A`) ticks every group and monitor; **Clear**
  (`Ctrl+Shift+D`) unticks all. **Right-click the group title** → sort **Name
  (A–Z) / (Z–A)**.
- A checked monitor shows a **colour swatch** to the left of its name; **clicking
  the swatch** opens a colour menu (palette colours + **Custom…**) that recolours
  that monitor's line in the plot. When **two or more data sets** are plotted,
  each monitor shows **one swatch per data set** (left to right), so every line
  can be recoloured individually — the same as the export menu's Monitors column.

**"Scenes" group (Scenes tab):**
- A **tree** of the scenes in the ticked data set(s), scoped to the current Data
  selection (it updates when you tick a different sim). Each scene is a checkbox;
  checking it **reveals its scalar/vector displayers** as checkable children,
  **unticked**, so you pick which to show deliberately.
- A **Run** button (`Ctrl+R`) at the top renders the checked scenes of the
  **single** ticked data set (it errors if more than one is ticked) to image
  stills, showing only the checked displayers, from the checked **Saved views**
  (or the current view if none). No folder prompt — files go to the configured
  output folder, or alongside the `.sim`. Output runs in parallel and per the
  *Scenes per license* setting; progress and per-scene log lines appear in the log
  console.
- **Select all** (`Ctrl+Shift+A`) / **Clear** (`Ctrl+Shift+D`) tick/untick every
  scene and displayer.
- **Clear scenes** (red) deletes all rendered stills from the workspace after a
  confirmation (the image files already saved on disk are kept), like *Clear
  data*.

**"Screenplays" group (Screenplays tab):**
- A **tree** of the screenplays in the ticked data set(s), scoped to the current
  Data selection — identical behaviour to the Scenes tree. Each screenplay is a
  checkbox; checking it **reveals its scene's scalar/vector displayers** as
  checkable children, **unticked**, so you pick which to show deliberately.
- A **Record** button (`Ctrl+R`) at the top records the checked screenplays of the
  **single** ticked data set (it errors if zero or more than one is ticked) to
  movie files, showing only the checked displayers, from the checked **Saved
  views** (or the screenplay's own/current view if none). No folder prompt —
  files go to the configured output folder, or alongside the `.sim`. Recording
  runs in parallel and per the *Screenplays per license* setting; progress and
  per-screenplay log lines appear in the log console.
- **Select all** (`Ctrl+Shift+A`) / **Clear** (`Ctrl+Shift+D`) tick/untick every
  screenplay and displayer.
- **Clear screenplays** (red) deletes all recorded movies from the workspace
  after a confirmation (the movie/poster files already saved on disk are kept),
  like *Clear scenes*.

**"Saved views" group (Scenes and Screenplays tabs, beneath Scenes/Screenplays):**
- A checklist of the sim's **saved camera views**, shared by both tabs. Each
  checked scene/screenplay is rendered or recorded once **per checked view**
  (its camera applied first); with **none** checked, it uses its current view.
  Like the scene/screenplay tree, it is scoped to the ticked data set(s).
- This pane has **no Select all / Clear** buttons (unlike the scene/screenplay
  tree above it): a render or record uses a single view, so bulk check/uncheck
  served no purpose.

### 3.8 Log console

The bottom panel:
- An **x/N counter** and a thin **progress bar** appear when a run starts (the
  bar shows a sliver immediately), update per file, and fade out ~5 s after the
  run finishes.
- A **read-only log** streams the combined stdout/stderr of each STAR-CCM+
  invocation plus StarPost's own status lines (capped at 5000 lines).

### 3.9 Export dialog

Opened from the top bar's **Export…**. A tabbed dialog mirroring the main window's
**Reports** / **Plots** split. The selections are pre-ticked to match the main
window when the dialog opens.

**Top bar:** a right-aligned **Profile** dropdown + **Load** (load only — saving
profiles stays in the main window). Loading applies a profile's report and
monitor selections to the dialog.

**Bottom:** **Export** (acts on the front tab) and **Cancel**.

#### Reports tab — three columns
- **Data** — checklist of loaded data sets (kept in lock-step with the Plots
  tab's Data column).
- **Reports** — checklist of available reports.
- **Options**:
  - **File format** — **CSV / TSV / XLSX / ODS** (defaults to the *Default report
    format* set in Settings → Export).
  - **Include units** — embed units in column headers (e.g. `Drag Force [N]`).
  - **Separate files** — one file per data set instead of one combined file
    (enabled only with two or more data sets selected).
- **Export** writes a wide table (rows = sims, columns = reports). With
  *Separate files* on, you name each file in turn; otherwise one file is written
  (named after the single sim, or "reports" for several). The save dialog opens
  in the default output folder.

#### Plots tab — three columns (+ preview window)
- **Data** — checklist of loaded data sets (mirrors the Reports tab).
- **Monitors** — a **tree** of monitor groups, each with a checkbox. Checking a
  group **reveals its monitors** (unticked, so you pick deliberately — residual
  plots are the exception and tick all their monitors at once); unchecking
  hides them. A checked monitor shows a **colour swatch**; **clicking the swatch**
  opens a colour menu (palette colours + **Custom…**) that recolours that
  monitor in the preview. When **two or more data sets** are plotted, each
  monitor shows **one swatch per data set** (left to right, matching the
  comparison's per-sim colours), so every line on the plot can be recoloured
  individually. The swatches **start from the colours chosen in the main UI's
  Monitor plots tree** (the preview mirrors them); recolouring here affects only
  the export.
- **Options**:
  - **Aspect ratio** — `1:1`, `3:2`, `4:3`, `16:9`, or **Custom** (free resize).
    Drives the preview window's shape.
  - **Plot title**, **X axis label**, **Y axis label** — live-override the
    preview's labels; empty reverts to the auto value.
  - **Title size** — a slider that sets the plot title's text size.
  - **Axis label size** — a slider that sets both axis labels' text size at
    once, so the X and Y labels always match.
  - **Theme** — Light / Dark for the exported image (defaults to the *Default
    plot theme* set in Settings → Export).
  - **Legend scale** — a slider that resizes the plot legend, from half size
    (left) to double size (right); its **mid-point is the natural 1.0× size**.
    The chosen size carries through to the exported image.
  - **Line thickness** — a slider that sets the pen width of **every line on the
    plot** at once, from thin (left) to thick (right). The chosen width carries
    through to the exported image.
  - **Show grid** — a checkbox (on by default) toggling the plot's background
    grid.
  - **Format** — **PNG / JPG / TIFF / PDF** (defaults to the *Default plot
    format* set in Settings → Export).
- A separate **Plot preview** window opens to the right while the Plots tab is in
  front, and live-updates as you change the selection/options.
- **Export** captures the preview to a high-resolution image and saves it (named
  after the single data set, or "plot" for several).

### 3.9a Run batch dialog

Opened from the top bar's **Run batch → Full Batch**. Unlike the [Export dialog](#39-export-dialog)
(which writes the current view), this is a **guided wizard** that assembles a
self-contained **archive** of extracted data. It steps through **six tabs** in
order — **Source → Reports → Plots → Scenes → Screenplays → Summary** — advanced
with the bottom-right **Continue** button (which becomes **Batch run** on the
Summary tab); **Back** returns to the previous tab. The tab bar itself is locked,
so the wizard is always driven by these buttons.

**Batch profile bar (top).** A **Batch profile** selector with **Load** and
**Save as…** stores a whole Run-batch setup — the chosen reports (along with the
**report format**, **unit system**, **Include units** and **Combined report**
settings), and the saved plots (each with its own unit system), scenes and
screenplays — under a name for reuse, so loading a profile restores all of
them. These batch profiles are **separate** from the report/plot
profiles used by the main view, and are also listed under Settings → Profiles →
**Batch profiles**.

**The tabs:**

- **Source** — pick what to process: **`.sim files`** or **`Loaded data sets`**.
  Load the candidates (**Load Files** / **Load Data Set**), tick which to
  include, and use **Select All** / **Clear**. For `.sim` sources, **Has similar
  format** extracts the *first* selected file up front to populate the Reports /
  Plots / Scenes choices (assuming every file shares the same reports, plots and
  scenes), so you can configure the run without extracting all of them first.
- **Reports** — a checklist of every report (all ticked by default), plus
  **File format** (CSV / TSV / XLSX / ODS), a global **Unit system** (Default /
  SI / Imperial, applied to every report written by this run), **Include
  units**, and **Combined report** (on by default) — which also writes one
  report combining every data set (one column per sim) at the archive root,
  alongside the per-data-set report files in their folders.
- **Plots** — the same monitor tree, per-monitor colour swatches, live preview
  window and plot options as the Export dialog's Plots tab, plus a per-plot
  **Unit system** (Default / SI / Imperial) that converts that plot's series
  and Y-axis label. **Add Plot** captures the current setup as a named entry in
  the **Saved Plots** list (each remembers its title, axis labels, sizes,
  theme, legend, line width, grid, format, unit system, and monitor selection +
  colours). Right-click a saved plot for **Preview** (loads its captured
  settings — including its unit system — back into the controls and preview),
  **Properties** (a read-only view of what it captured, including its unit
  system), or **Delete**.
- **Scenes** — the same scene → displayer tree and **Saved views** list as the
  main Scenes view, plus **Image resolution** and **Image format**. **Save Scene**
  captures the current selection as a named entry in the **Saved Scenes** list;
  right-click one for **Properties** (its resolution/format, saved views, and each
  captured scene with its scalar/vector displayers) or **Delete**.
- **Screenplays** — the same screenplay → displayer tree and a **Saved views**
  list as the main Screenplays view, plus per-entry **Movie resolution**,
  **Movie format** (MP4 / AVI / MOV), **Frame rate**, **Quality**, **Start
  time (s)** and **Animation length (s)** (Auto = the screenplay's own length)
  options. **Save Screenplay** captures the current selection (with those movie
  options, including the start time and length)
  as a named entry in the **Saved Screenplays** list; right-click one for
  **Properties** (its movie options, saved views, and each captured screenplay
  with its scalar/vector displayers) or **Delete**. Each saved screenplay records
  one movie per data set into that data set's folder.
- **Summary** — a final review before the run. **Export options**: the **Archive
  format** selector (**ZIP** or **7Z**) — the run writes the chosen format (a
  `.zip` or a `.7z`) — and **Include dataset .csv** — when ticked, each data set's portable
  StarPost CSV (identical to the Data tab's **Export Data** file) is written into
  its folder in the archive, ready to re-import. Alongside sit read-only
  **Reports**, **Plots**, **Scenes** and **Screenplays** lists mirroring the other
  tabs; right-click a plot, scene or screenplay here for **Properties** or
  **Delete** (deleting also removes it from its source Saved list).

**Batch run** then extracts/renders/records as needed and writes a **single
archive** (ZIP or 7Z, as chosen on the Summary tab) containing **one folder per
data set**, each holding its report table, an image of every saved plot, the
saved-scene stills, the saved-screenplay movies, and (if enabled) the data set's
CSV — plus, when **Combined report** is on, one all-sims report at the archive
root. A progress dialog tracks the run; STAR-CCM+ is only invoked when a `.sim`
source must be extracted, a scene rendered, or a screenplay recorded. A screenplay
that fails to record is logged and skipped, without aborting the rest of the run.

> **Multi-select** in the wizard's lists uses **Shift+click** (range) and
> **Ctrl+click** (toggle); the checkbox lists also support **Shift+click to tick
> a range** (see the [Data panel](#34-data-panel)).

### 3.9b Express batch dialog

Opened from the top bar's **Run batch → Express batch**. This is the fast path for
users who already have a saved **batch profile**: rather than stepping through the
six-tab wizard, you pick a profile and sources, set the archive options, and run.
The profile supplies everything about the output — the reports (with their
**report format**, **unit system**, **Include units** and **Combined report**
settings), the saved plots (each with its own unit system), the saved scenes,
and the saved screenplays.

**Layout (top to bottom):**

- **Batch profile** — a selector listing the saved batch profiles (the same ones
  used by the [Run batch dialog](#39a-run-batch-dialog) and Settings → Profiles →
  **Batch profiles**). Choosing a profile is **required**: the **Batch run** button
  stays disabled until one is selected. If no batch profiles exist yet, a note
  directs you to create one in **Full Batch**.
- **Sources** — the same source picker as the wizard's **Source** tab: choose
  **`.sim files`** or **`Loaded data sets`**, load candidates (**Load Files** /
  **Load Data Set**), tick which to include, and use **Select All** / **Clear**.
  There is **no "Has similar format"** step here — the profile already defines the
  outputs, so no file needs to be extracted up front to configure the run.
- **Export options** (in the Options column, beneath the source input) — the
  **Archive format** selector (**ZIP** or **7Z**) and **Include dataset .csv**
  (each data set's portable StarPost CSV, added to its folder in the archive),
  matching the wizard's Summary tab.
- **Batch run** — starts the run.

**Batch run** produces the **same output** as the wizard: a **single archive**
(ZIP or 7Z, as chosen) with **one folder per data set**, each holding its report
table, an image of every saved plot, the saved-scene stills, the saved-screenplay
movies, and (if enabled) the data set's CSV — plus, when the profile's **Combined
report** is on, one all-sims report at the archive root. As in the wizard,
STAR-CCM+ is invoked only when a `.sim` source must be extracted, a scene rendered
or a screenplay recorded (its executable path must be set in Settings), and the
run warns on **No data selected** or when the chosen profile yields **nothing to
output**.

### 3.10 Settings dialog

Opened from the top bar's **Settings…**. A left-hand navigation list selects one of
**twelve pages**, shown in a scrollable stack on the right. **Save** writes
everything back to `settings.yaml`; **Cancel** discards (and reverts any live
theme preview). A few actions take effect **immediately**, independent of
Save/Cancel: **deleting a profile**, **Reset settings**, **Clear all temp
files**, and the manual **Check for updates**.

The pages, in nav order:

| Page | Contents |
|---|---|
| **STAR-CCM+** | **Executable path** (+ Browse…, platform-aware filter), **Default output folder** (+ Browse…), **Extra arguments** (appended verbatim to every call, space-separated), **Parallel cores** (spinbox 1…N machine cores; the `-np` count for scene rendering — 1 = serial; numeric extraction always runs serially), **Scenes per license** (how many scenes render per STAR-CCM+ session/license checkout; 1 = one each, safest for memory). |
| **License** | **Mode** — *POD key + license server* or *License file*. For POD: **POD key** (masked as `••••` with a **Show/Hide** toggle) and **License server** (`<port>@<server>`). For license file: **License file** (+ Browse…). Irrelevant fields are disabled per mode. |
| **Appearance** | **Theme** (Dark / Light); **Accent presets** (eight swatches: Amber, Blue, Teal, Green, Orange, Red, Purple, Pink); **Custom accent** (hex field + Pick… + preview chip); **Checkmarks → Match with theme** toggle + **Checkmark colour** (used when not matching); **Node dots → Match with theme** toggle + **Node colour** (the Files-tab leaf-row dots; follow the accent when matching, mirroring the checkmark controls); **Folders → Use default colour** toggle + **Folder colour** (tints the Files-tab folder icons); **Text size** (1.0×–1.5× multiplier scaling every button/label, and the main view's plot title/axis labels; 1.0× is the original size). All changes **preview live** across the whole UI. |
| **Files** | **Show file path** — list full paths in the Files panel instead of just names. |
| **Reports** | **Unit system** (Default / SI / Imperial — converts values and units shown in the live Reports table, single and comparison); **Decimal places** (0–15), **Hide empty reports**, **Zero threshold** (scientific notation accepted; magnitudes below it show as 0 and, if hiding is on, are hidden). |
| **Plots** | **Unit system** (Default / SI / Imperial — converts each live monitor series and its Y-axis label); **Hide empty monitors** + **Zero threshold**; **Moving average width** (window size for the plot's **Smooth data** toggle; 1 = no smoothing); **Show name when hovering**; **Hover X decimals** / **Hover Y decimals**; **Statistics** (checkable list — Avg, Median, Std Dev, Var, Min, Max, Range — controlling the Shift+drag region table); **Residual keywords** and **Force keywords** (comma-separated; drive the log/linear axis classification). |
| **Scenes** | Scene-rendering output options: **Image resolution** (1080p / 2160p) and **Image format** (JPG / PNG). |
| **Screenplays** | Screenplay-recording output options: **Movie resolution** (1080p / 2160p), **Movie format** (MP4 / AVI / MOV), **Frame rate (fps)**, **Quality** (Low / Medium / High), **Start time (s)** and **Animation length (s)** (Auto = each screenplay's own length; recording always begins at the start time rather than the screenplay's preferred start), and **Screenplays per license** (how many screenplays record per STAR-CCM+ session/license checkout; 1 = one each, safest for memory). |
| **Export** | Defaults the Export dialog pre-fills: **Default report format** (CSV / TSV / XLSX / ODS), **Default plot format** (PNG / JPG / TIFF / PDF), and **Default plot theme** (Light / Dark). These only pre-fill the dialog; any export can still override them. |
| **Profiles** | Two sections. **Report/plot profiles** — one row per profile (Default first); **Show Details** opens a read-only window listing the profile's selected **Reports**, **Plots** (with the monitors shown per group), and **Statistics**; **Delete** (not shown for Default) removes the profile after confirmation, immediately. **Batch profiles** — the saved [Run batch dialog](#39a-run-batch-dialog) selections, each with **Show Details** (its reports, saved plots and saved scenes — right-click a saved plot or scene there for **Properties**) and **Delete**. |
| **Misc** | **Show setup menu on startup** (the welcome wizard); **Check for updates on application startup**; **Check for updates** (manual check now); **Reset settings** — restores Files/Reports/Plots/Export/Appearance/Misc to defaults and reloads the Default profile (STAR-CCM+, License, and saved Profiles are left untouched), applied and saved immediately; **Clear all temp files** — deletes cached logs, the crash-recovery cache, generated icons, downloaded updates, and leftover macro folders after a confirmation listing what will go (settings and profiles are untouched). |
| **About** | The StarPost logo, a short description, the author, a link to the GitHub repository, and the current **version**. |

### 3.11 Welcome / setup wizard

Shown on startup while *Show setup menu on startup* is enabled (on by default for
new users). It collects the essentials so a new user can get going without
hunting through Settings:

- **Header** — a short description of StarPost.
- **STAR-CCM+** — **Executable Location** (+ Browse…) and **Output folder**
  (+ Browse…).
- **Licensing** — **Mode**, **POD key** (masked, with a Show/Hide toggle),
  **License server** (prefilled with the stock Siemens cloud server
  `1999@flex.cd-adapco.com`), **License file** (+ Browse…). Fields enable/disable
  per mode.
- **Appearance** — **Theme**, accent preset swatches, and **Pick…** for a custom
  accent. Previews live.
- **Show this setup on startup** checkbox (mirrors the Misc setting).
- **Get Started** — saves the entries and closes.

Closing without finishing (rejecting) discards the setup entries and reverts the
theme preview, but still honours the *show on startup* choice.

### 3.12 Updates

StarPost can check **GitHub releases** for a newer version, comparing the
running `__version__` against the latest release tag.

- **On startup** (when *Check for updates on application startup* is enabled) the
  check runs quietly in the background. If a newer release exists, the top bar
  shows the **"New update available"** note and a prompt offers to update.
- **On demand** via Settings → Misc → **Check for updates**, which also reports
  "you're up to date" / connection errors (the startup check stays silent on
  those).
- **Applying the update** depends on the build:
  - the packaged **Windows installer build** can download the new `Setup.exe` (a
    cancellable progress dialog) and launch it, then close to update in place;
  - a **source checkout or other platform** instead opens the release page in the
    browser to download manually.
- The network work runs on background threads, so the UI never blocks.

### 3.13 Keyboard shortcuts

The main views and actions have keyboard shortcuts. Each one is shown in its
menu entry and appended to the control's hover tooltip, so the keys are
discoverable in place. The bindings live in one table
(`src/starpost/gui/shortcuts.py`) and are mirrored in the user-facing reference
[`docs/starpost_hotkeys.txt`](starpost_hotkeys.txt) (a test keeps the two in
sync).

**Main UI navigation** (app-wide):

| Shortcut | Action |
|---|---|
| `F1` | Switch the left panel to **Files** |
| `F2` | Switch the left panel to **Data** |
| `1` | Switch the centre tab to **Reports** |
| `2` | Switch the centre tab to **Plots** |
| `3` | Switch the centre tab to **Scenes** |
| `4` | Switch the centre tab to **Screenplays** |

**Top bar — File menu** (app-wide):

| Shortcut | Action |
|---|---|
| `Ctrl+N` | **Add files…** to the Files list |
| `Ctrl+Shift+N` | **Add folder…** of `.sim` files to the Files list |
| `Alt+Shift+I` | **Import data…** (a portable data CSV) |
| `Alt+Shift+E` | **Export data…** (the selected data set to a portable CSV) |

**Top bar — Run batch menu** (app-wide):

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+B` | Open the **Full Batch** wizard |
| `Ctrl+Shift+E` | Open the **Express batch** dialog |

**Selection panel** (acts on the group matching the active centre tab):

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+A` | **Select all** entries in the current checklist |
| `Ctrl+Shift+D` | **Clear** (deselect) the current checklist |
| `Ctrl+R` | **Run** (Scenes tab) / **Record** (Screenplays tab) |
| `Alt+Shift+S` | Toggle **Smooth data** (Plots tab only) |

**Files list** (only while the Files list has focus):

| Shortcut | Action |
|---|---|
| `Ctrl+L` | **Load** the selected file(s) |
| `Ctrl+P` | **Properties** of the selected item |
| `Delete` | **Remove** the selected files/folders |

**Data list** (only while the Data list has focus):

| Shortcut | Action |
|---|---|
| `Delete` | **Remove** the selected data set(s) |

> The `Delete` key is bound on both the Files and Data lists — the same key, each
> binding active only in its own tree.

---

## 4. Limitations

### Fundamental / architectural
- **It does not parse `.sim` files directly.** The STAR-CCM+ `.sim` format is
  proprietary, binary, and has no public reader/SDK. StarPost drives an
  installed STAR-CCM+ engine via its Java macro API in batch mode and reads back
  exported CSVs. **A licensed STAR-CCM+ installation must be present** on the
  machine running StarPost.
- **Every extraction consumes a license checkout** and incurs STAR-CCM+ startup
  time. This is inherent to the batch-macro approach and is why runs are
  sequential and results are cached. The tool is not a lightweight file reader.

### Scope
- **Numeric data + rendered media.** Reports, monitor plots, **rendered scene
  stills** (images of a sim's scenes, with selectable scalar/vector displayers
  and saved-view cameras), and **recorded screenplay movies** (video, via the
  same displayer/saved-view picker). No creation/editing of scenes, displayers,
  views, or screenplays inside the `.sim` — StarPost only renders/records what
  already exists. Streamline/other displayer types are shown if a scene contains
  them but are **not selectable** (only scalar/vector displayers are).
- **Scene rendering and screenplay recording are heavy.** Both go through
  OpenGL (need working graphics / an offscreen GL context on headless machines)
  and are memory-intensive — recording a movie is heavier than a still, a large
  case can exhaust RAM, so ≥16 GB is recommended and the per-checkout scene/
  screenplay count is kept low by default. Both re-run STAR-CCM+ (one or more
  extra license checkouts), unlike the cached numeric data.
- **Screenplay recording requires STAR-CCM+ 2022 or newer** (the release that
  introduced first-class Screenplays). On older installs the Screenplays tree
  is simply empty. The record macro finds the recorder method **reflectively**
  (never compiled against the screenplay API), so an API mismatch on a given
  release fails only that screenplay, logged as an error row, not the whole run.
- **No per-frame progress on the fast record path.** STAR-CCM+'s native movie
  export reports frame progress only to its GUI, which is absent under `-batch`,
  so during a fast (native) record StarPost shows an indeterminate
  "Recording…" busy indicator rather than a frame count. A true per-frame bar
  appears only when the slower frame-by-frame fallback path runs. See
  [3.6b](#36b-screenplays-view).
- **Monitor plots only** for plot data (value-vs-iteration/time, e.g. residuals
  and force histories). **XY plots** (a field along a line/probe) and other plot
  types are not handled.
- Reports are read as their current **monitor value**; the tool does not modify,
  create, or re-define reports/plots inside the `.sim`.
- The tool **reads** simulations; it never writes changes back into `.sim` files.

### Features not exposed in the UI
- **No way to stop a batch mid-run.** Once a batch starts it runs every file to
  completion; there is no Stop control (results are still checkpointed after each
  file, and closing the app stops further files).
- **Per-plot axis (log/linear) override** has no UI. Classification is by the
  Settings keyword lists only. (A `Profile.axis_overrides` field is persisted in
  the profile YAML but is not applied when a profile loads.)
- The **~25-file batch ceiling** is a design expectation only; it is not enforced
  and no warning fires when it is exceeded.

### Validation caveats
- The **extraction macro has now been run against a live STAR-CCM+ 2310 install**
  — reports, monitor plots, and scene/displayer/saved-view discovery all work.
  Very old releases could still differ.
- The **scene-render *apply-saved-view* call** (`getCurrentView().setView(...)`)
  is the **one remaining unvalidated, version-specific operation**: it only runs
  when rendering with a saved view checked. Scene discovery and rendering from the
  current view do not depend on it. If it fails to compile on a given build, that
  call is the place to adjust.
- The **exact CSV layout produced by `StarPlot.export()`** for monitor plots is
  still the main unverified assumption for plots. The parser handles the common
  single-X-column layout and is flagged for tightening once tested on real
  exports.
- **Screenplay recording is not yet validated against a live STAR-CCM+
  install.** The record macro finds the recorder reflectively (scanning the
  screenplay object's public methods) precisely because the screenplay API's
  class/method names shift across releases; automated tests cover macro
  template rendering only. Manual verification against a real 2022+ install is
  the remaining step.

### Packaging
- **PyInstaller does not cross-compile** — each OS's artifact must be built on
  that OS. A Linux **AppImage** build script and a Windows **Inno Setup**
  installer script are provided (see [`docs/packaging.md`](packaging.md)); the
  in-place self-update is only available on the packaged **Windows** build.

---

## 5. How It Works (Architecture)

StarPost is fundamentally an **orchestrator + viewer**, not a file parser. It
sits on top of an installed STAR-CCM+ engine.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          StarPost (PySide6 GUI)                        │
│                                                                        │
│  Files list ─► Batch queue ─► StarRunner ─► (subprocess)              │
│                    │                │                                   │
│                    │                ▼                                   │
│                    │      starccm+ -batch extract_all.java \           │
│                    │        -power -podkey KEY -licpath P@S  file.sim   │
│                    │                │                                   │
│                    │                ▼                                   │
│                    │      STAR-CCM+ opens .sim, runs macro,            │
│                    │      exports CSVs (reports + plot series)         │
│                    ▼                ▼                                   │
│              ResultParser ◄── exported CSVs                            │
│                    │                                                    │
│                    ▼                                                    │
│              ResultStore (in-memory + JSON crash cache)               │
│                    │                                                    │
│         ┌──────────┼───────────────┐                                   │
│         ▼          ▼               ▼                                    │
│   ReportTable   PlotView    Selection/Profiles ─► Export (tables/plots)│
└──────────────────────────────────────────────────────────────────────┘
```

**Technology stack:**

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best fit for subprocess orchestration + data handling |
| GUI | PySide6 (Qt) | Cross-platform, fully custom UI via QSS |
| Plots (in-app) | pyqtgraph | Fast, interactive value-vs-iteration plotting with log scale |
| Hover/region math | numpy | Nearest-point search and region statistics |
| Plots (export) | Qt (QImage/QPdfWriter), Pillow fallback | High-resolution PNG/JPG/TIFF/PDF capture of the live plot |
| Tabular data / export | pandas (+ openpyxl, odfpy) | Wide/long tables; CSV/TSV/XLSX/ODS export |
| Config/profiles | PyYAML | Human-readable, editable config and profiles |
| Macro templating | Jinja2 | Parameterized Java macro generation |
| Per-OS paths | platformdirs | Native config/cache/log locations on Linux and Windows |
| Engine interface | STAR-CCM+ Java macro API via `starccm+ -batch` | Only supported way to read `.sim` data |

---

## 6. Data Flow, End to End

1. **User adds `.sim` files** to the Files list (individually or by folder) and
   extracts them into the workspace — **double-click** a file, or select some and
   **right-click → Load file**. (The top bar's **Run batch** follows the same extraction
   steps below, but assembles the results into an archive instead of loading them
   into the Data tab — see the [Run batch dialog](#39a-run-batch-dialog).)
2. For **each file, sequentially**, `StarRunner`:
   - renders the Java macro `extract_all.java` from its template (pointing it at
     the output folder),
   - builds the command
     `starccm+ -batch extract_all.java <license args> <extra args> file.sim`,
   - launches it as a subprocess (with the console window suppressed on Windows),
     streaming combined stdout/stderr to the log.
3. **Inside STAR-CCM+**, the macro (one license checkout, one pass):
   - writes `<simname>_reports.csv` — `sim_file, report, value, units` for every
     report (per-report try/catch logs `ERROR` instead of aborting),
   - exports each monitor plot to `<simname>__plot__<plot>.csv`
     (X column + one column per series),
   - writes `<simname>__plots_index.csv` mapping plot name → CSV file.
4. **`ResultParser`** reads those CSVs (UTF-8) into a `SimResult` and
   **classifies each plot** (residual → log Y, force → linear Y).
5. **`ResultStore`** holds all `SimResult`s in memory and **checkpoints a JSON
   cache** after every file (crash recovery).
6. After the batch, a **homogeneity check** warns if files differ in their
   report/plot sets.
7. The GUI shows the **union** of report/plot names in the **Selection panel**;
   the user ticks **Data** sets and filters reports/plots (or loads a **profile**).
8. **Views** render the filtered data (per-file or comparison).
9. **Export** writes the selected data to the chosen folder as a table
   (CSV/TSV/XLSX/ODS) and/or a plot image (PNG/JPG/TIFF/PDF).

> **Key efficiency point:** because the macro extracts *everything* on the single
> license-consuming pass, the user can change their selection, build comparisons,
> and re-export **without ever re-running STAR-CCM+**.

---

## 7. Data Model

Defined in `src/starpost/data/models.py`:

- **`Report`** — `name`, `value` (`None` if extraction failed), `units`,
  optional `error`.
- **`PlotSeries`** — one line on a plot: `name`, `x[]`, `y[]` (shared X axis).
- **`MonitorPlot`** — `name`, `series[]`, `kind` (`RESIDUAL` / `FORCE` /
  `OTHER`), `x_label`, `y_log` (resolved axis choice), optional `error`.
- **`Displayer`** — a scene's scalar/vector displayer: `name`, `kind`
  (`scalar` / `vector`).
- **`Scene`** — `name` + its `displayers[]` (scalar/vector only).
- **`Screenplay`** — `name`, `scene` (the scene it animates, `""` if
  unresolved) + that scene's `displayers[]` (scalar/vector only) — parallel to
  `Scene`.
- **`MediaArtifact`** — a rendered/recorded output: `name` (display label),
  `path`, `source` (the scene, or the screenplay for movies), `kind` (`still` |
  `movie`), optional `error`, plus provenance for the Properties window:
  `sim_path`, `displayers` (the visible ones), `view`, and `poster` (movie-kind
  only: absolute path to the exported poster-frame PNG).
- **`PropertyGroup`** — one entity's captured sim properties: `section`
  (`"mesh"`, `"region"`, `"physics"`, …), `name` (the entity, `""` for
  sim-wide sections), and `entries[]` (key/value string pairs in extraction
  order). Values are kept as **generic strings** — the key set drifts across
  STAR-CCM+ releases, so anything numeric is parsed at the point of use.
- **`SimProperties`** — the sim's metadata for one file: `groups[]` of
  `PropertyGroup`, with a `get(section, name)` lookup. Consumed by the
  Properties window's Parts/Mesh/Regions/Physics tabs
  (`data/parts_tree.py`, `data/prop_rows.py` build the tree/row models).
- **`SimResult`** — everything from one `.sim`: `sim_path`, `reports[]`,
  `plots[]`, `scenes[]` (with displayers), `views[]` (saved-view names),
  `screenplays[]` (with their scene's displayers), `media[]` (rendered stills +
  recorded movies), `properties` (a `SimProperties`, or `None` for results
  extracted before that feature — never part of `signature()`), `extracted_at`
  timestamp, optional batch-level `error`.
  Helpers: `sim_name`, `report_names()`, `plot_names()`, `scene_names()`,
  `screenplay_names()`, and `signature()` (report + plot names, for the
  homogeneity check — scenes/views/screenplays/media are excluded).

Persistence type in `src/starpost/core/settings.py`:

- **`Profile`** — a saved selection: `name`, `reports[]`, `plots[]` (selected
  monitor groups), `monitors` (`{plot_name: [monitor, ...]}` — which series show
  per group; absent groups show all), `axis_overrides` (`{plot_name: "log" |
  "linear"}` — persisted but not currently applied), and `region_stats` (the
  region-table statistics shown, or `None` for older profiles). Stored one per
  YAML file under the profiles dir. The reserved **Default** profile is built-in
  and has no file.

---

## 8. Configuration Files & Locations

StarPost uses `platformdirs`, so locations are native to each OS. On Linux it
honours `XDG_CONFIG_HOME` / `XDG_CACHE_HOME`.

| What | Linux | Windows |
|---|---|---|
| Settings | `~/.config/starpost/settings.yaml` | `%APPDATA%\starpost\settings.yaml` |
| Profiles | `~/.config/starpost/profiles/*.yaml` | `%APPDATA%\starpost\profiles\*.yaml` |
| Results crash cache | `~/.cache/starpost/results_cache.json` | `%LOCALAPPDATA%\starpost\results_cache.json` |
| Files-list cache | `~/.cache/starpost/file_list.json` | `%LOCALAPPDATA%\starpost\file_list.json` |
| Log (rotating) | `~/.cache/starpost/starpost.log` | `%LOCALAPPDATA%\starpost\starpost.log` |
| Generated theme icons | `~/.cache/starpost/checkmark_*.png` | `%LOCALAPPDATA%\starpost\checkmark_*.png` |
| Downloaded updates | `~/.cache/starpost/updates/` | `%LOCALAPPDATA%\starpost\updates\` |

The config and cache directories are created **owner-only** (`0700`), and the
settings file and log are written **owner-only** (`0600`), since the settings
file holds the license credentials in plaintext. Everything under the cache dir
is "temporary" and can be wiped via Settings → Misc → **Clear all temp files**.

`settings.yaml` is seeded from the packaged `config/default_settings.yaml` on
first run, then edited via the Settings dialog (or by hand). Key fields:

- `starccm_path` — path to the `starccm+` executable. Typical install locations
  (replace `<version>` with your installed STAR-CCM+ version):
  - Linux: `/opt/Siemens/<version>/STAR-CCM+<version>/star/bin/starccm+`
  - Windows: `C:/Program Files/Siemens/<version>/STAR-CCM+<version>/star/bin/starccm+.bat`
- `license` — `mode` (`podkey_server` | `license_file`), `podkey`, `licpath`
  (`<port>@<server>`), `license_file`.
- `default_output_dir` — starting folder for export/extraction pickers.
- `extra_args` — appended verbatim to every `starccm+` call.
- Report/plot display options (`report_decimals`, `hide_empty_reports`,
  `zero_threshold`, `hide_empty_monitors`, `monitor_zero_threshold`,
  `moving_average_width`, `hover_show_monitor_name`, `hover_x_decimals`,
  `hover_y_decimals`, `region_stats`, `plot_classification`),
  `show_full_file_names`.
- `appearance` — `mode`, `accent`, `checkmark_color` + `checkmark_match_theme`,
  and `folder_color` + `folder_use_default`.
- Export defaults — `export_report_format`, `export_plot_format`,
  `export_plot_theme`.
- `show_setup_on_startup` and `check_updates_on_startup`.

---

## 9. Project Structure (File by File)

```
starpost/                           (repo; app/package = "starpost")
├── README.md                       Quick orientation, install (Linux/Windows), usage
├── CHANGELOG.md                    Per-version release notes (newest first)
├── pyproject.toml                  Package metadata, deps, entry point, ruff config
├── requirements.txt                Runtime dependency pins
├── .gitignore                      Ignores .sim files, build artifacts, caches
│
├── config/
│   └── default_settings.yaml       Shipped defaults; copied to user config on first run
│
├── docs/
│   ├── StarPost_Documentation.md   This document
│   ├── dev_install.md              Running from a source checkout
│   └── packaging.md                Building the AppImage / Windows installer
│
├── packaging/
│   ├── starpost.spec               Cross-platform PyInstaller spec (per-OS icon)
│   ├── build_appimage.sh           Linux: PyInstaller bundle → portable AppImage
│   ├── AppRun                      AppImage entry point
│   ├── starpost.desktop            AppImage/menu desktop entry
│   └── starpost.iss                Windows: Inno Setup installer script
│
├── scripts/
│   └── dev_run.py                  Launch the GUI from a source checkout (no install)
│
├── tests/
│   ├── test_aggregator.py          Wide report-table layout + selection filtering
│   ├── test_result_parser.py       CSV parsing + plot classification
│   ├── test_plot_view.py           Empty-series detection for plot hiding
│   ├── test_settings.py            License flags, profile round-trip, file perms
│   ├── test_portable.py            Portable-CSV import/export round-trip
│   ├── test_starccm_runner.py      License-credential redaction in logged commands
│   ├── test_updater.py             Version comparison / update detection
│   ├── test_update_flow.py         GUI update-available callback
│   ├── test_widgets.py             Tooltip-delay proxy style
│   └── test_temp_files.py          Temp-file enumeration + clearing
│
└── src/starpost/
    ├── __init__.py                 Version, APP_NAME
    ├── app.py                      Entry point: QApplication, theme, MainWindow, wizard
    │
    ├── core/                       Engine interface & business logic (no GUI)
    │   ├── settings.py             Settings + LicenseConfig + Profile (YAML I/O)
    │   ├── macro_generator.py      Renders extract_all.java from the Jinja2 template
    │   ├── starccm_runner.py       Builds CLI, runs starccm+ subprocess, streams log
    │   │                           (license args redacted from logs)
    │   ├── result_parser.py        Parses exported CSVs; classifies plots (log/linear)
    │   └── updater.py              GitHub release check + installer download (UI-free)
    │
    ├── macros/
    │   ├── extract_all.java.j2     Canonical Java macro: ALL reports + ALL plots, one pass
    │   │                           (also lists scenes + displayers + saved views + screenplays)
    │   ├── render_scenes.java.j2   Separate render macro: scene stills via printAndWait
    │   │                           (displayer visibility, saved-view camera, -np parallel)
    │   └── record_screenplays.java.j2  Separate record macro: screenplay movies (reflective
    │                               recorder lookup, displayer visibility, saved-view camera)
    │
    ├── batch/                      Batch orchestration
    │   ├── job.py                  Job: one .sim -> one SimResult
    │   ├── queue.py                BatchWorker / SceneRenderWorker / ScreenplayRecordWorker
    │   │                           (QObject workers): sequential, off the GUI thread
    │   └── aggregator.py           Wide report frames + CSV/TSV/XLSX/ODS table export
    │
    ├── data/                       Data model & storage
    │   ├── models.py               Report, PlotSeries, MonitorPlot, SimResult, PlotKind,
    │   │                           Scene/Displayer, MediaArtifact, SimProperties/PropertyGroup
    │   ├── parts_tree.py           Builds the Geometry > Parts tree for the Properties window
    │   ├── prop_rows.py            Builds the Mesh / Regions / Physics rows for Properties
    │   ├── portable.py             Round-trippable StarPost-CSV (Import / Export Data; format v3)
    │   └── store.py                ResultStore: in-memory + JSON crash cache; homogeneity
    │
    ├── gui/                        PySide6 user interface
    │   ├── main_window.py          Top bar (File/Run batch menus + version/update note),
    │   │                           panels, view refresh, shortcut registration
    │   ├── shortcuts.py            Single source of truth for keyboard shortcuts (plain data)
    │   ├── theme.py                Dark/light + accent QSS generator (build/apply)
    │   ├── plot_style.py           Keeps the pyqtgraph plots theme-aware
    │   ├── icons.py                Loads the bundled app icon + logo; builds menu glyph icons
    │   ├── update.py               Qt glue for the updater (threads, prompts, download)
    │   ├── widgets.py              Shared widgets: UniformTabBar, SecretLineEdit (masked
    │   │                           key field), ToolTipResetStyle (tooltip timing), DangerMenuItem
    │   ├── resources/
    │   │   ├── StarPost-logo.png   Application / window icon
    │   │   └── StarPost-logo.ico   Windows executable icon (used by the PyInstaller build)
    │   └── views/
    │       ├── file_list.py        Files tab: virtual folders, drag-drop, sort, open,
    │       │                       Properties, folder-colour tinting
    │       ├── data_list.py        Data tab: virtual folders, drag-drop, sort, tick
    │       │                       data sets, import/export, delete/clear
    │       ├── selection_panel.py  Report checklist + monitor-plot tree + scene/screenplay
    │       │                       →displayer trees + shared Saved views list (Run/Record/
    │       │                       Clear), profiles
    │       ├── report_table.py     Numeric viewer (per-file long + comparison wide), sort
    │       ├── plot_view.py        pyqtgraph viewer: multi-group overlay, per-monitor
    │       │                       colours, smoothing, hover readout, Shift+drag region stats
    │       ├── scene_view.py       Scenes tab: rendered-still thumbnail gallery (open,
    │       │                       right-click Properties, empty-space deselect)
    │       ├── screenplay_view.py  Screenplays tab: poster-framed movie gallery (open in
    │       │                       system player, right-click Properties)
    │       ├── thumbnails.py       Shared gallery/thumbnail widgets for scenes + screenplays
    │       ├── title_bar.py        Frameless top-bar window buttons (minimise/maximise/close)
    │       ├── settings_dialog.py  In-app settings (twelve paged groups, incl. Scenes +
    │       │                       Screenplays) + profiles
    │       ├── properties_dialog.py  File / data-set / folder / rendered-scene/-movie Properties
    │       ├── data_export_dialog.py  Export Data: pick data sets → portable CSVs
    │       ├── log_console.py      Live log + progress counter/bar
    │       ├── export_dialog.py    Tabbed export (Reports/Plots) + live plot preview
    │       ├── batch_run_dialog.py  Run batch wizard (Source→Reports→Plots→Scenes→
    │       │                       Screenplays→Summary) → archive
    │       ├── express_batch_dialog.py  Express batch: run a saved batch profile → archive
    │       └── welcome_dialog.py   First-run setup wizard
    │
    └── utils/
        ├── paths.py                platformdirs locations; owner-only perms; temp-file
        │                           enumeration/clearing
        └── logging.py              Stderr + owner-only rotating file logging
```

---

## 10. Setup & Usage

### Requirements
- Python 3.11+
- A local, licensed STAR-CCM+ installation (path set in Settings). The UI opens
  without one; STAR-CCM+ is only needed to extract data.
- Linux or Windows.
- Dependencies in `requirements.txt` / `pyproject.toml`.

### Install & run from source

**Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python scripts/dev_run.py
```

**Windows** (PowerShell or Command Prompt)
```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts\dev_run.py
```

### Typical workflow
1. Complete the **setup wizard** (or set the STAR-CCM+ path and licensing in
   Settings).
2. Add `.sim` files (or a folder of them) in the **Files** tab.
3. Extract them into the workspace: **double-click** a file, or select some and
   **right-click → Load file** (progress shows in the log console).
4. Tick the extracted **Data** sets to view (two or more → comparison); filter
   reports/plots in the Selection panel, or load a **Profile**.
5. **Export…** the report tables and/or plot images — or use **Run batch** to
   package the reports, saved plots and saved scenes into a single archive.

### Build a standalone bundle
```bash
pip install -e ".[dev]"
pyinstaller packaging/starpost.spec      # run on the target OS
```
Output lands in `dist/starpost/` (`starpost.exe` on Windows; the spec picks the
`.ico` automatically). For distributable artifacts — a Linux **AppImage**
(`packaging/build_appimage.sh`) or a Windows **Inno Setup installer**
(`packaging/starpost.iss`) — see [`docs/packaging.md`](packaging.md). Running
from a source checkout is covered in [`docs/dev_install.md`](dev_install.md).

### Run the tests
```bash
PYTHONPATH=src python -m pytest tests/ -q
```

---

## 11. Implementation Status

**Implemented and working:**
- Java macro template (reports + all monitor plots, single pass).
- Macro generation, subprocess runner with full license-flag handling
  (Windows console suppressed), UTF-8 CSV parsing, automatic plot classification.
- Data model, in-memory store, JSON crash-recovery cache, homogeneity check,
  persisted Files list.
- Batch worker: sequential execution (off the GUI thread) with progress/log
  signals; a started batch runs every file to completion.
- The full GUI: the menu-bar-style top bar (with the version label + update
  note), Files/Data tabs,
  Reports table (per-file + comparison, sortable), interactive plot viewer
  (multi-group overlay, per-monitor colours, optional moving-average smoothing,
  hover readout, Shift+drag region statistics, theme-following), the Selection
  panel (per-tab report/monitor lists with per-monitor picking) and profiles, and
  the log console. Hover tooltips on every button.
- **Files virtual folders** — in-app nested folders with drag-drop re-parenting,
  per-folder sorting, Rename/Delete, Properties, and colour-tinted folder icons.
- **Portable data import/export** — round-trippable StarPost-CSV per data set
  (Import / Export Data), plus Properties on files/data sets/folders.
- **Export** — reports to CSV/TSV/XLSX/ODS (combined or per-file, optional
  units) and plots to PNG/JPG/TIFF/PDF via a live preview with custom title/axis
  labels, per-monitor colours (mirrored from the main view), legend scale, line
  thickness, title/axis-label text sizes, a grid toggle, theme, and aspect ratio;
  configurable defaults.
- **Plot customization & smoothing** — per-monitor colour swatches in the main
  view (one per data set; distinct per line in comparison mode), an optional
  moving-average **Smooth data** toggle with a configurable width, and residual
  groups that plot all their monitors at once when selected.
- **Selection panel** — shows the report or monitor-plot list for the active
  centre tab; monitors are picked from a tree (check a group to reveal them).
- **Settings dialog** — twelve paged groups covering every `settings.yaml` field,
  plus profile management (Show Details / Delete), Reset, and Clear all temp files.
- **Top bar & keyboard shortcuts (v2.5.0)** — a single menu-bar-style top bar
  with a **File** menu (Add files/folder, Import/Export data) and glyph-iconed
  menus, and keyboard shortcuts for tab switching, the batch dialogs, add/
  import/export, select-all/clear, run/record, smoothing, and the Files/Data list
  actions (one shortcut table in `gui/shortcuts.py`, mirrored in
  `docs/starpost_hotkeys.txt`).
- **Appearance theming** — dark/light + accent + checkmark + folder colour
  generated into QSS at runtime, previewed live (the plot follows the mode too).
- **Profiles** — YAML persistence including per-group monitor selection and
  region statistics; built-in Default; in-dialog management.
- **Credential safety** — masked POD key, owner-only (`0600`) settings/log files,
  and license-arg redaction in the log and on-screen command output.
- **In-app update check** — GitHub release comparison with a top-bar note, and
  download-and-install of the new installer on the packaged Windows build.
- **First-run setup wizard.**
- **Scene rendering (v2.0.0)** — the Scenes tab: scene/displayer/saved-view
  discovery during extraction; a scene→displayer tree + Saved views list; an
  on-demand render macro (`printAndWait`) driven in parallel (`-np`) with a
  configurable core count and scenes-per-checkout; per-displayer visibility and
  saved-view cameras; a thumbnail gallery with open / right-click Properties /
  Clear scenes; Settings → Scenes (image format + resolution); a first-open
  memory warning; and "Add folder…" importing into a named internal folder.
- **Screenplay recording (v2.3.0)** — the Screenplays tab: screenplay/
  displayer discovery during extraction (reusing scene discovery for each
  screenplay's owning scene); a screenplay→displayer tree + the shared Saved
  views list; an on-demand, reflective record macro (no compile-time binding to
  the screenplay API) driven in parallel (`-np`) with screenplays-per-checkout
  batching; per-displayer visibility and saved-view cameras; one exported
  poster frame per movie; a poster-framed gallery with open-in-system-player /
  right-click Properties / Clear screenplays; Settings → Screenplays (movie
  format, resolution, frame rate, quality, and — v2.6.0 — a recording start
  time and animation length, honoured by the run-batch and Save Screenplay
  options too); and reuse of the Scenes tab's first-open memory warning.
- **Sim-properties capture & Properties window (v2.6.0)** — the extraction pass
  also records the sim's solution state, mesh counts + mesh-operation pipeline,
  regions/boundaries/interfaces, physics models/solvers/stopping criteria, the
  Geometry ▸ Parts tree, tags and STAR-CCM+ version, all on the same license
  checkout and persisted through the crash-recovery cache. Shown in the tabbed
  Properties window (General / Parts / Mesh / Regions / Physics) and carried in
  the portable data CSV (bumped to format v3; v2 files still import).
- **Cross-platform** config/cache/log locations via platformdirs; packaged Linux
  AppImage and Windows Inno Setup installer.
- Unit tests for parser, classifier, aggregator, license flags, profile
  round-trip, empty-series detection, portable CSV, credential redaction, file
  permissions, the updater, tooltip timing, temp-file clearing, the scene
  pipeline (scene/media parsing, render-macro generation, media config), and the
  screenplay pipeline (screenplay/media parsing, record-macro generation, movie
  settings, the Screenplays selection tree, and the gallery).

**Not yet exposed / pending:** see [Limitations](#4-limitations) — a stop-a-batch
control, per-plot axis-override UI, and an enforced batch-size warning.

**Not validated:** the scene-render *apply-saved-view* call
(`getCurrentView().setView(...)`) — the one remaining version-specific scene
macro operation — the `StarPlot.export()` monitor-plot CSV layout, and the
screenplay record macro's reflective recorder lookup (automated tests cover
macro template rendering only; exercising it against a real STAR-CCM+ 2022+
install is a manual step still pending). Reports, plots, and scene/view
**discovery** have been run against a live STAR-CCM+ 2310 install.

---

## 12. Design Decisions (Requirements History)

These were locked during requirements gathering and shaped the v1 design.

- **Data types:** report values (scalars) **and** monitor plots (value vs.
  iteration). **Monitor plots only** (not XY plots). **Numeric only** — no 3D
  scene rendering.
- **Selection & profiles:** users pick which reports/plots are output, with
  Select All; profiles save and reload a named selection. **Extract-all-then-
  filter** — one license checkout per file dumps everything; selection/profile
  filters what is shown and exported.
- **Batch behavior:** multiple `.sim` files at once; **assume homogeneous** but
  warn if not; **expected ceiling < 25 files**; runs **sequential** (≤1 license).
- **Workflow / UI:** per-file default plus a comparison mode; a fully custom QSS
  UI; in-app viewing of numbers and plots, plus export.
- **Plot rendering:** residuals on one plot in different colours with a **log Y
  axis**; forces on a **linear** axis (implemented as name-based classification).
- **Export:** numbers to spreadsheet formats; plots to image/PDF; to a
  user-chosen location. Report comparison uses a **wide** layout (units embedded
  in headers like `Drag Force [N]`).
- **Configuration & licensing:** manual executable path; licensing defaults to
  **POD key + license server**, with a license-file alternative.
- **Persistence:** profiles for reuse; a cache as a crash failsafe.
- **Platform & distribution:** Linux first with extension to Windows (now both);
  team distribution, installer ideal but not required initially.
- **Environment:** runs on an engineer's local machine (not an HPC scheduler).

---

## 13. Open Questions / Future Work

- **Confirm the `StarPlot.export()` CSV layout** across plot types on a real
  install and tighten the parser; **validate the scene-render apply-saved-view
  call** (`getCurrentView().setView(...)`) on the target STAR-CCM+ version.
- **Add a way to stop a running batch** (a Stop button plus the worker-side
  cooperative halt to back it — the earlier stop-after-current scaffolding was
  removed once it was found to be unwired).
- **Per-plot axis-override UI** (and apply `Profile.axis_overrides` on load).
- **Enforce/warn on the batch-size ceiling** if it remains a real constraint.
- **Validate the packaged builds** end to end on clean machines, and consider
  **code-signing** the Windows installer to avoid SmartScreen warnings.
- **Validate screenplay recording** against a real STAR-CCM+ 2022+ install (the
  reflective recorder lookup is currently only exercised via macro-template
  unit tests). Consider bundling recorded movies into the [Run batch](#39a-run-batch-dialog)
  `.zip` export (out of scope today — recorded movies live in the gallery/output
  folder only).
- **Possible later features** (out of scope today): image-sequence screenplay
  output (movie file only today), XY plots and other plot types, richer report
  templating (e.g. full PDF reports), and optional multi-sim-per-session macro
  runs to reduce license churn further.
```