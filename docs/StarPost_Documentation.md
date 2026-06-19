# StarPost — Program Overview & Reference

> Application name: **StarPost** (Python package / import name: `starpost`)
> Repository: `starpost`
> Version: **1.2.0**
> Status: cross-platform (Linux + Windows) GUI with batch extraction, the
> Files/Data workspace (virtual folders + portable data import/export), an
> interactive plot viewer, the full in-app settings dialog, report/plot export,
> an in-app update check, and packaged builds (Linux AppImage + Windows Inno
> Setup installer). The Java extraction macro has not yet been validated against
> a live STAR-CCM+ install (see [Limitations](#4-limitations)).
> Document last updated: 2026-06-18

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [What the Program Does (Capabilities)](#2-what-the-program-does-capabilities)
3. [User Interface Reference](#3-user-interface-reference)
   - [3.1 Window layout](#31-window-layout)
   - [3.2 Toolbar](#32-toolbar)
   - [3.3 Files panel](#33-files-panel)
   - [3.4 Data panel](#34-data-panel)
   - [3.5 Reports view](#35-reports-view)
   - [3.6 Plots view](#36-plots-view)
   - [3.7 Selection panel (right)](#37-selection-panel-right)
   - [3.8 Log console](#38-log-console)
   - [3.9 Export dialog](#39-export-dialog)
   - [3.10 Settings dialog](#310-settings-dialog)
   - [3.11 Welcome / setup wizard](#311-welcome--setup-wizard)
   - [3.12 Updates](#312-updates)
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

The focus is **numeric data only**: report values and monitor plots. 3D scene
rendering and complex visualization are out of scope (see
[Limitations](#4-limitations)).

---

## 2. What the Program Does (Capabilities)

### Extraction
- Reads **solved** STAR-CCM+ `.sim` files (no re-solving; reports re-evaluate
  against the stored solution).
- Extracts **all report values** (name, value, units) from each file.
- Extracts **all monitor plots** (value vs. iteration), including multi-series
  plots such as residuals (continuity, momentum components, energy, etc.).
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
  `.sim`. **Ticking** Data entries chooses which results feed the views; ticking
  two or more switches the Reports/Plots views into **comparison** mode.
- **Portable data import/export**: a loaded data set can be written to a
  self-contained StarPost CSV and re-imported later (into any StarPost instance)
  **without STAR-CCM+** — useful for sharing results or archiving them.
- **Properties** on any file, data set, or folder (size plus report / monitor /
  iteration counts).

### Viewing (in-app)
- **Per-file mode** (one Data set ticked): that simulation's reports and plots.
- **Comparison mode** (two or more ticked): a wide table of report values across
  the selected sims, and monitor-plot overlays coloured per sim.
- **Report table**: numeric values with units, configurable decimal places, and
  optional hiding of ~0 reports; sortable by name/value/units.
- **Monitor plot viewer** (interactive, pyqtgraph):
  - **Residual plots** → all series overlaid in distinct colours with a
    **logarithmic Y axis**; **force/other plots** → **linear Y axis**.
  - Axis type is auto-classified by plot name (keyword lists configurable in
    Settings).
  - **Multiple monitor groups at once**, each with its **own dropdown** for
    choosing which of its series (monitors) are drawn.
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
  title and axis labels, per-monitor colours, theme, and aspect ratio.
- **Configurable defaults** (Settings → Export): the report format, plot image
  format, and plot theme the Export dialog pre-fills.

### Configuration, appearance & resilience
- **Configurable STAR-CCM+ executable path** and **extra CLI args**.
- **Licensing**: defaults to **Power-on-Demand key + license server**
  (`-power -podkey <KEY> -licpath <port>@<server>`); also supports a **regular
  license file** (`-licpath <file>`).
- **Dark/light theme** with a custom **accent colour**, **checkmark colour**, and
  **folder-icon colour**, previewed live across the whole UI.
- **Credential safety**: the POD key is masked in the UI (reveal on demand), the
  settings file and log are written **owner-only** (`0600`), and license
  credentials are **redacted** from the log and on-screen command output.
- **In-app update check** against GitHub releases (on startup and on demand):
  a "New update available" note appears in the toolbar, and on the packaged
  Windows build the update can be downloaded and installed in place.
- **"Clear all temp files"** (Settings → Misc) removes cached logs, the
  crash-recovery cache, generated icons, and downloaded updates after a
  confirmation that lists what will go.
- **Hover tooltips** on every toolbar/button control describing what it does.
- **First-run setup wizard** for the essentials, re-openable any time.
- **Cross-platform**: per-OS config/cache/log locations via `platformdirs`;
  packaged as a Linux **AppImage** and a Windows **Inno Setup installer**.

---

## 3. User Interface Reference

This section documents every panel, control, button, and context (right-click)
menu in the application. StarPost has **no traditional menu bar**; actions are
reached through the **toolbar** and through **context menus** on the various
panels.

### 3.1 Window layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [Run batch] | [Export…]  [Settings…]                        ← toolbar    │
├───────────────┬───────────────────────────────────┬───────────────────┤
│  Files | Data │   Reports | Plots                 │  Selection panel    │
│  (left tabs)  │   (centre tabs)                   │  (Profile + lists)  │
│               │                                   │                     │
├───────────────┴───────────────────────────────────┴───────────────────┤
│  x/N counter + progress bar                                             │
│  Live batch log (read-only)                              ← log console  │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Left** — a tab widget with **Files** and **Data** tabs.
- **Centre** — a tab widget with **Reports** and **Plots** tabs.
- **Right** — the **Selection panel** (profile controls + report/plot
  checklists).
- **Bottom** — the **Log console** (progress + streaming log).
- The three top regions and the bottom are separated by draggable splitters.
- Window title: **StarPost**; default size 1280×800.

### 3.2 Toolbar

A single toolbar at the top with three actions:

| Action | Behaviour |
|---|---|
| **Run batch** | Extracts **every** `.sim` in the Files list. Prompts for an output folder (defaults to the configured output dir, else home). Warns if the Files list is empty or the STAR-CCM+ path isn't set. Disabled while a run is in progress. |
| **Export…** | Opens the [Export dialog](#39-export-dialog). |
| **Settings…** | Opens the [Settings dialog](#310-settings-dialog). |

At the **far right** of the toolbar a greyed **`StarPost v<version>`** label
shows the running version. If the startup update check finds a newer release, a
**"New update available"** note (tinted with the accent colour) appears directly
beneath it.

Every toolbar action and button in the app has a **hover tooltip** describing
what it does (shown after a short delay; moving to another control restarts the
delay rather than showing the next tooltip instantly).

> The default Qt toolbar/dock right-click menu is intentionally **suppressed**
> (its only entry would hide the toolbar with no way to restore it).

### 3.3 Files panel

The **Files** tab: the batch list of `.sim` files to process, optionally
organised into **virtual folders**. The full layout (files, folders, nesting,
expansion, and per-folder sort) is **persisted to disk** and restored on the
next launch. Folders live **only inside StarPost** — they are never created on
the filesystem.

**Buttons (bottom of the panel):**
- **Add files…** — file picker filtered to `*.sim`; adds the chosen files.
- **Add folder…** — folder picker; adds every `*.sim` directly inside it.
- **Remove** — removes the selected rows (after a confirmation). A selected
  folder is removed with its contents.
- **Clear** — removes all files and folders (after a confirmation). Styled as a
  danger button.

**Interactions:**
- **Multi-select** with Ctrl/Shift (extended selection).
- **Double-click a file** → *Open* just that file (extract + view it).
- **Drag and drop** files/folders to **re-parent** them (move into a folder, out
  to the top level, or between folders); a folder can't be dropped into its own
  subtree.
- **Right-click a file** → **Open** (or **Open All** when two or more files are
  selected — extracts and views every selected file, in top-to-bottom order) and
  **Properties**. Right-clicking a row outside the current selection first
  selects just that row.
- **Right-click a folder** → **Open All** (extract + view every `.sim` in it,
  recursively), **New Nested Folder**, a **Sort** submenu (A–Z, Z–A, File Size
  Largest, File Size Smallest — orders just this folder's contents), **Rename**,
  **Delete folder** (keeps the contents, moving them up to the parent), and
  **Properties** (combined size + file count).
- **Right-click empty space** → **New Folder** (at the top level).
- **Right-click the "Files" tab** → **sort menu** (the active mode is
  checkmarked): **Name (A–Z)**, **Name (Z–A)**, **File size (largest)**,
  **File size (smallest)** — applied to every folder.

**Notes:**
- Only `.sim` files are added; duplicates (by resolved path) are ignored.
- Folders sort their contents **folders first, then files**; nested files are
  marked with a small dash for legibility, and folder icons can be **tinted** to
  a chosen colour (Settings → Appearance → Folders).
- Each row shows the file name by default, or the full path if *Show file path*
  is enabled in Settings → Files; the full path is always in the tooltip.
- *Opening* a file that is already loaded prompts to load only the new files,
  force-reload, or cancel.

### 3.4 Data panel

The **Data** tab: one entry per result extracted so far, named after its source
`.sim`. This is the set of results the Reports/Plots views draw from.

**Interactions:**
- Each entry has a **checkbox**; **clicking anywhere on a row toggles it**.
- **No** entry checked or **one** checked → **per-file** view; **two or more**
  checked → **comparison** view.
- **Right-click a data set** → **Properties** (its portable-CSV size plus report,
  monitor, and iteration counts).
- **Right-click the "Data" tab** → **sort menu**: **Name (A–Z)** / **Name (Z–A)**.

**Buttons (bottom of the panel):**
- **Import** — load one or more **portable StarPost CSVs** (as written by Export
  Data) straight into the workspace, with no `.sim` or STAR-CCM+ needed. Files
  that don't match the format are reported and skipped; name collisions prompt
  to overwrite or keep.
- **Export Data** — opens a dialog listing the loaded data sets (pre-ticked to
  the current selection) where you choose which to dump to portable StarPost CSV
  (one re-importable file per data set).
- **Delete** — deletes the **checked** data sets from the store (after a
  confirmation). Blocked while a batch is running. The underlying `.sim` files
  stay in the Files list.
- **Clear data** — wipes **all** loaded results (after a confirmation), leaving
  the Files list intact so they can be re-run. Blocked while a batch is running.

### 3.5 Reports view

The **Reports** tab (centre): a numeric table of report values.

- **Per-file mode** — three columns: **Report**, the **value** column (headed
  with the data set's name), and **Units**.
- **Comparison mode** — a **Report** column, then **one value column per
  selected sim**, then a **Units** column. Report names that are ~0 across all
  selected sims are dropped when *Hide empty reports* is on.
- Values are formatted to the configured **decimal places**; magnitudes below
  the **zero threshold** display as `0`.
- **Right-click the table header** → **sort menu** (active sort checkmarked):
  **Name (A–Z / Z–A)**, **Value (ascending / descending)**, **Units (A–Z /
  Z–A)**. In comparison mode, "Value" orders rows by the across-sim mean.

### 3.6 Plots view

The **Plots** tab (centre): the interactive monitor-plot viewer (pyqtgraph).

**The plot area:**
- Overlays the selected monitor plots; grid, legend, title, and axis labels
  shown. **Residuals** render on a **log Y axis**, **forces/other** on a
  **linear Y axis**.
- In per-file mode each series gets a distinct colour; in comparison mode lines
  are coloured **by sim**.
- A centred hint **"Select a monitor to begin"** shows while nothing is plotted.
- The view auto-fits (auto-ranges) to the data on each redraw.

**Per-category dropdowns (row beneath the plot):**
- One dropdown per displayed monitor group, labelled **`Group (selected/total)`**.
- Clicking it opens a **stay-open menu**: **Select all**, **Deselect all**, a
  separator, then each monitor as a checkable item. The menu stays open so you
  can toggle several; it closes on click-away/Esc/clicking the button again.
- **Right-click a dropdown button** → **Sort A–Z / Sort Z–A** (reorders the
  menu only; selection is unchanged).
- A newly checked monitor group starts with **no** monitors shown until you pick
  some.

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

**Other:**
- Without Shift, the usual pyqtgraph **pan (drag)** and **zoom (scroll)** apply,
  and right-clicking the plot exposes pyqtgraph's built-in view-box menu.

### 3.7 Selection panel (right)

Chooses which reports and monitor plots are shown/exported, and manages profiles.
It operates on the **union** of names across the loaded (and ticked) data.

**Profile row (top):**
- **Profile dropdown** — lists the built-in **Default** first, then saved
  profiles.
- **Load** — applies the selected profile (its reports, monitor groups, the
  monitors shown per group, and its region statistics). Loading **Default**
  selects every available report and no plots.
- **Save as…** — prompts for a name and saves the current selection as a profile.
  "Default" is reserved; overwriting an existing profile asks for confirmation.

**"Reports" group:**
- **Select all** / **Clear** buttons.
- A checklist of report names (checked by default). Clicking a row toggles it.
- **Right-click the group title** → sort **Name (A–Z) / (Z–A)**.

**"Monitor plots" group:**
- Same controls as Reports, but monitor plots default to **unchecked** (the plot
  view starts blank, since drawing every plot at once is slow).

### 3.8 Log console

The bottom panel:
- An **x/N counter** and a thin **progress bar** appear when a run starts (the
  bar shows a sliver immediately), update per file, and fade out ~5 s after the
  run finishes.
- A **read-only log** streams the combined stdout/stderr of each STAR-CCM+
  invocation plus StarPost's own status lines (capped at 5000 lines).

### 3.9 Export dialog

Opened from the toolbar **Export…**. A tabbed dialog mirroring the main window's
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
  group **reveals its monitors** (unticked, so you pick deliberately); unchecking
  hides them. A checked monitor shows a **colour swatch**; **clicking the swatch**
  opens a colour menu (palette colours + **Custom…**) that recolours that
  monitor in the preview. When **two or more data sets** are plotted, each
  monitor shows **one swatch per data set** (left to right, matching the
  comparison's per-sim colours), so every line on the plot can be recoloured
  individually.
- **Options**:
  - **Aspect ratio** — `1:1`, `3:2`, `4:3`, `16:9`, or **Custom** (free resize).
    Drives the preview window's shape.
  - **Plot title**, **X axis label**, **Y axis label** — live-override the
    preview's labels; empty reverts to the auto value.
  - **Theme** — Light / Dark for the exported image (defaults to the *Default
    plot theme* set in Settings → Export).
  - **Legend scale** — a slider that resizes the plot legend, from half size
    (left) to double size (right); its **mid-point is the natural 1.0× size**.
    The chosen size carries through to the exported image.
  - **Format** — **PNG / JPG / TIFF / PDF** (defaults to the *Default plot
    format* set in Settings → Export).
- A separate **Plot preview** window opens to the right while the Plots tab is in
  front, and live-updates as you change the selection/options.
- **Export** captures the preview to a high-resolution image and saves it (named
  after the single data set, or "plot" for several).

### 3.10 Settings dialog

Opened from the toolbar **Settings…**. A left-hand navigation list selects one of
**ten pages**, shown in a scrollable stack on the right. **Save** writes
everything back to `settings.yaml`; **Cancel** discards (and reverts any live
theme preview). A few actions take effect **immediately**, independent of
Save/Cancel: **deleting a profile**, **Reset settings**, **Clear all temp
files**, and the manual **Check for updates**.

The pages, in nav order:

| Page | Contents |
|---|---|
| **STAR-CCM+** | **Executable path** (+ Browse…, platform-aware filter), **Default output folder** (+ Browse…), **Extra arguments** (appended verbatim to every call, space-separated). |
| **License** | **Mode** — *POD key + license server* or *License file*. For POD: **POD key** (masked as `••••` with a **Show/Hide** toggle) and **License server** (`<port>@<server>`). For license file: **License file** (+ Browse…). Irrelevant fields are disabled per mode. |
| **Appearance** | **Theme** (Dark / Light); **Accent presets** (eight swatches: Amber, Blue, Teal, Green, Orange, Red, Purple, Pink); **Custom accent** (hex field + Pick… + preview chip); **Checkmarks → Match with theme** toggle + **Checkmark colour** (used when not matching); **Folders → Use default colour** toggle + **Folder colour** (tints the Files-tab folder icons). All changes **preview live** across the whole UI. |
| **Files** | **Show file path** — list full paths in the Files panel instead of just names. |
| **Reports** | **Decimal places** (0–15), **Hide empty reports**, **Zero threshold** (scientific notation accepted; magnitudes below it show as 0 and, if hiding is on, are hidden). |
| **Plots** | **Hide empty monitors** + **Zero threshold**; **Show name when hovering**; **Hover X decimals** / **Hover Y decimals**; **Statistics** (checkable list — Avg, Median, Std Dev, Var, Min, Max, Range — controlling the Shift+drag region table); **Residual keywords** and **Force keywords** (comma-separated; drive the log/linear axis classification). |
| **Export** | Defaults the Export dialog pre-fills: **Default report format** (CSV / TSV / XLSX / ODS), **Default plot format** (PNG / JPG / TIFF / PDF), and **Default plot theme** (Light / Dark). These only pre-fill the dialog; any export can still override them. |
| **Profiles** | One row per profile (Default first). **Show Details** opens a read-only window listing the profile's selected **Reports**, **Plots** (with the monitors shown per group), and **Statistics**. **Delete** (not shown for Default) removes the profile after confirmation, immediately. |
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
  check runs quietly in the background. If a newer release exists, the toolbar
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
- **Numeric data only** — reports and monitor plots. No 3D scenes, field
  visualization, isosurfaces, streamlines, or section rendering.
- **Monitor plots only** for plot data (value-vs-iteration/time, e.g. residuals
  and force histories). **XY plots** (a field along a line/probe) and other plot
  types are not handled.
- Reports are read as their current **monitor value**; the tool does not modify,
  create, or re-define reports/plots inside the `.sim`.
- The tool **reads** simulations; it never writes changes back into `.sim` files.

### Features not exposed in the UI
- **"Stop after current file"** is implemented in the batch worker
  (`BatchWorker.request_stop`) but is **not wired to any UI control**. Once a
  batch starts, it runs to completion (results are still checkpointed after each
  file, and closing the app stops further files).
- **Per-plot axis (log/linear) override** has no UI. Classification is by the
  Settings keyword lists only. (A `Profile.axis_overrides` field is persisted in
  the profile YAML but is not applied when a profile loads.)
- The **~25-file batch ceiling** is a design expectation only; `MAX_FILES` is not
  enforced and no warning fires when it is exceeded.

### Validation caveats
- The **Java macro has not been validated against a live STAR-CCM+ install**
  (none was available during development). The API calls used
  (`getReportManager`, `getReportMonitorValue`, `StarPlot.export`) are stable
  across recent versions, but very old releases could differ.
- The **exact CSV layout produced by `StarPlot.export()`** for monitor plots is
  the main unverified assumption. The parser handles the common single-X-column
  layout and is flagged for tightening once tested on real exports.

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
   clicks **Run batch** (or right-click → **Open** / double-click a file),
   choosing an output folder.
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
- **`SimResult`** — everything from one `.sim`: `sim_path`, `reports[]`,
  `plots[]`, `extracted_at` timestamp, optional batch-level `error`. Helpers:
  `sim_name`, `report_names()`, `plot_names()`, and `signature()` (the set of
  report + plot names, used for the homogeneity check).

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

- `starccm_path` — path to the `starccm+` executable.
- `license` — `mode` (`podkey_server` | `license_file`), `podkey`, `licpath`
  (`<port>@<server>`), `license_file`.
- `default_output_dir` — starting folder for export/extraction pickers.
- `extra_args` — appended verbatim to every `starccm+` call.
- Report/plot display options (`report_decimals`, `hide_empty_reports`,
  `zero_threshold`, `hide_empty_monitors`, `monitor_zero_threshold`,
  `hover_show_monitor_name`, `hover_x_decimals`, `hover_y_decimals`,
  `region_stats`, `plot_classification`), `show_full_file_names`.
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
    │   ├── updater.py              GitHub release check + installer download (UI-free)
    │   └── plot_export.py          Renders a MonitorPlot to JPG/PDF (matplotlib helper)
    │
    ├── macros/
    │   └── extract_all.java.j2     Canonical Java macro: ALL reports + ALL plots, one pass
    │
    ├── batch/                      Batch orchestration
    │   ├── job.py                  Job + JobState (pending/running/done/failed/skipped)
    │   ├── queue.py                BatchWorker (QObject): sequential, stop-after-current
    │   └── aggregator.py           Wide report frames + CSV/TSV/XLSX/ODS table export
    │
    ├── data/                       Data model & storage
    │   ├── models.py               Report, PlotSeries, MonitorPlot, SimResult, PlotKind
    │   ├── portable.py             Round-trippable StarPost-CSV (Import / Export Data)
    │   └── store.py                ResultStore: in-memory + JSON crash cache; homogeneity
    │
    ├── gui/                        PySide6 user interface
    │   ├── main_window.py          Toolbar (+ version/update note), panels, view refresh
    │   ├── theme.py                Dark/light + accent QSS generator (build/apply)
    │   ├── icons.py                Loads the bundled app icon + logo (QIcon/QPixmap)
    │   ├── update.py               Qt glue for the updater (threads, prompts, download)
    │   ├── widgets.py              Shared widgets: UniformTabBar, SecretLineEdit (masked
    │   │                           key field), ToolTipResetStyle (tooltip timing)
    │   ├── resources/
    │   │   ├── StarPost-logo.png   Application / window icon
    │   │   └── StarPost-logo.ico   Windows executable icon (used by the PyInstaller build)
    │   └── views/
    │       ├── file_list.py        Files tab: virtual folders, drag-drop, sort, open,
    │       │                       Properties, folder-colour tinting
    │       ├── data_list.py        Data tab: tick data sets, import/export, delete/clear
    │       ├── selection_panel.py  Report/plot checklists, Select all, profile load/save
    │       ├── report_table.py     Numeric viewer (per-file long + comparison wide), sort
    │       ├── plot_view.py        pyqtgraph viewer: multi-group overlay, per-group
    │       │                       dropdowns, hover readout, Shift+drag region stats
    │       ├── settings_dialog.py  In-app settings (10 paged groups) + profile mgmt
    │       ├── properties_dialog.py  File / data-set / folder Properties dialogs
    │       ├── data_export_dialog.py  Export Data: pick data sets → portable CSVs
    │       ├── log_console.py      Live log + progress counter/bar
    │       ├── export_dialog.py    Tabbed export (Reports/Plots) + live plot preview
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
3. **Run batch** and choose an output folder.
4. Tick the extracted **Data** sets to view (two or more → comparison); filter
   reports/plots in the Selection panel, or load a **Profile**.
5. **Export…** the report tables and/or plot images.

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
- Batch worker: sequential execution, progress/log signals, cooperative
  stop-after-current (worker-level).
- The full GUI: toolbar (with the version label + update note), Files/Data tabs,
  Reports table (per-file + comparison, sortable), interactive plot viewer
  (multi-group overlay, per-group monitor dropdowns, hover readout, Shift+drag
  region statistics, theme-following), the Selection panel with profiles, and the
  log console. Hover tooltips on every button.
- **Files virtual folders** — in-app nested folders with drag-drop re-parenting,
  per-folder sorting, Rename/Delete, Properties, and colour-tinted folder icons.
- **Portable data import/export** — round-trippable StarPost-CSV per data set
  (Import / Export Data), plus Properties on files/data sets/folders.
- **Export** — reports to CSV/TSV/XLSX/ODS (combined or per-file, optional
  units) and plots to PNG/JPG/TIFF/PDF via a live preview with custom title/axis
  labels, per-monitor colours, theme, and aspect ratio; configurable defaults.
- **Settings dialog** — ten paged groups covering every `settings.yaml` field,
  plus profile management (Show Details / Delete), Reset, and Clear all temp files.
- **Appearance theming** — dark/light + accent + checkmark + folder colour
  generated into QSS at runtime, previewed live (the plot follows the mode too).
- **Profiles** — YAML persistence including per-group monitor selection and
  region statistics; built-in Default; in-dialog management.
- **Credential safety** — masked POD key, owner-only (`0600`) settings/log files,
  and license-arg redaction in the log and on-screen command output.
- **In-app update check** — GitHub release comparison with a toolbar note, and
  download-and-install of the new installer on the packaged Windows build.
- **First-run setup wizard.**
- **Cross-platform** config/cache/log locations via platformdirs; packaged Linux
  AppImage and Windows Inno Setup installer.
- Unit tests for parser, classifier, aggregator, license flags, profile
  round-trip, empty-series detection, portable CSV, credential redaction, file
  permissions, the updater, tooltip timing, and temp-file clearing.

**Not yet exposed / pending:** see [Limitations](#4-limitations) — stop-after-
current UI, per-plot axis-override UI, and an enforced batch-size warning.

**Not validated:** the Java macro has not been run against a live, licensed
STAR-CCM+ install, and the `StarPlot.export()` CSV layout is assumed.

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

- **Validate the Java macro** on a real STAR-CCM+ install and confirm the
  `StarPlot.export()` CSV layout across plot types; tighten the parser.
- **Surface stop-after-current** in the UI (a Stop button).
- **Per-plot axis-override UI** (and apply `Profile.axis_overrides` on load).
- **Enforce/warn on the batch-size ceiling** if it remains a real constraint.
- **Validate the packaged builds** end to end on clean machines, and consider
  **code-signing** the Windows installer to avoid SmartScreen warnings.
- **Possible later features** (out of scope today): 3D scene/image export, XY
  plots and other plot types, richer report templating (e.g. full PDF reports),
  and optional multi-sim-per-session macro runs to reduce license churn further.
```