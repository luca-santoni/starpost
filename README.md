# StarPost

StarPost is a standalone desktop tool to automate STAR-CCM+ post-processing: it extracts
**report values** and **monitor plots** (residuals, forces vs. iteration) from
solved `.sim` files, lets you view and compare them, and exports tables to
**CSV / TSV / XLSX / ODS** and plots to **PNG / JPG / TIFF / PDF**. It can also
**render scene stills** (images) from a `.sim`'s scenes — choosing which
scalar/vector displayers are shown and which saved camera view to render from.

Runs on **Linux and Windows**.

## Installation

The recommended way to get StarPost is to **download the latest release** for
your platform from the GitHub
**[Releases page](https://github.com/luca-santoni/starpost/releases/latest)**.
These are standalone builds — no Python or separate dependency install required.

- **Linux** — download the `StarPost-<version>-<arch>.AppImage`, make it
  executable, and run it:

  ```bash
  chmod +x StarPost-*.AppImage
  ./StarPost-*.AppImage
  ```

- **Windows** — download the Windows build from the same page and run
  `starpost.exe`.

A licensed STAR-CCM+ installation is still required to extract data from `.sim`
files (see [Requirements](#requirements)); the app otherwise opens and is fully
navigable on its own.

### Run from the repository

You can also install and run StarPost directly from a clone or download of this
repository as a Python script — recommended for development. See
**[`docs/dev_install.md`](docs/dev_install.md)** for the full step-by-step
instructions: setting up a virtual environment, installing the dependencies, and
launching the GUI.

## How it works

STAR-CCM+ `.sim` files are a proprietary binary format with no public reader, so
StarPost does **not** parse them directly. Instead it:

1. Generates a Java macro from a template (`src/starpost/macros/`).
2. Runs it via `starccm+ -batch <macro> <file.sim>` (one license checkout per
   file, sequential — license-safe).
3. The macro exports **all** reports and monitor plots to CSV in an output dir
   (and lists the sim's scenes, their scalar/vector displayers, and its saved
   views); StarPost parses those and caches them.
4. The GUI filters the cached data by your selection/profile for viewing and
   export. Re-selecting never re-runs STAR-CCM+.
5. **Scene rendering** is a separate, on-demand pass: from the **Scenes** tab you
   pick scenes (and which displayers/saved view to show) and click **Run** to
   render them to image stills via a second macro. Because rendering goes through
   OpenGL and is memory-heavy, it is kept apart from the numeric extraction.

A licensed STAR-CCM+ installation must be present on the machine.

## Features

- **Batch extraction** of all report values and monitor plots from multiple
  `.sim` files, run sequentially (one license checkout at a time) with a live
  log and progress bar, and a crash-recovery cache.
- **Files / Data panels** — build a reusable list of `.sim` files (the *Files*
  tab), then pick which extracted **Data** sets feed the views by ticking them.
  **Both** tabs support **virtual folders** (nest, drag-drop, sort per folder)
  for organising files and data sets; each folder's layout and open/closed state
  persist across sessions. Checking two or more data sets switches the
  views into **comparison** mode automatically. Data sets can be **exported to /
  imported from portable CSVs** (shareable, re-loadable without STAR-CCM+).
- **Per-file and comparison views** — a numeric report table (sortable, with
  configurable decimals and empty-value hiding) and an interactive plot viewer.
- **Interactive plots** (pyqtgraph):
  - Overlay **several monitor groups at once**; pick which monitors to draw from
    the **Monitor plots** tree (check a group to reveal its monitors). Checking a
    **residual** group plots all its monitors at once.
  - **Per-monitor line colours** — a colour swatch beside each shown monitor (one
    per data set in comparison mode), where each line also gets a distinct colour
    by default; the colours carry over to the export preview.
  - **Smooth data** — an optional moving average over the shown monitors, with a
    configurable window width (Settings → Plots).
  - **Hover readout** that snaps a marker + coordinate label to the nearest data
    point (optional monitor name, configurable X/Y decimals).
  - **Shift+drag a region** to get a per-series statistics table (Avg, Median,
    Std Dev, Var, Min, Max, Range — choose which appear in Settings).
  - Residuals on a log axis, forces on a linear axis (auto-classified by name);
    the **Y axis is labelled with the physical quantity and unit** (e.g. *Force
    (lbf)*), inferred from the monitor's unit.
  - Background, axes and legend **follow the light/dark theme**.
- **Profiles** — save/reuse a named selection of reports and plots, *including
  which monitors are shown per group* and which region statistics are shown. A
  built-in **Default** profile selects every report and no plots.
- **Export** (toolbar → *Export…*), a tabbed dialog mirroring the main window:
  - **Reports → CSV / TSV / XLSX / ODS**, with optional units and an optional
    one-file-per-data-set mode.
  - **Plots → PNG / JPG / TIFF / PDF** with a live preview window, custom title
    and axis labels, per-monitor colours (mirrored from the main view), legend
    scale, line thickness, title/axis-label text sizes, a grid toggle, theme, and
    aspect ratio.
- **Scene rendering** (the **Scenes** tab) — render scene stills from a `.sim`:
  - A **scene → displayer tree** (like the monitor-plot groups): tick a scene,
    then tick which of its **scalar/vector displayers** to show; a **Saved views**
    list renders each scene from a chosen STAR-CCM+ saved camera view.
  - **Run** renders the selected scene(s) of the ticked data set to image stills
    (**JPG / PNG**, **1080p / 2160p**), shown in a **thumbnail gallery**
    (double-click to open; right-click → **Properties** for size, resolution,
    format, and the parent sim / scene / displayers / view). **Clear scenes**
    removes the rendered stills.
  - Rendering runs as a separate macro pass, **in parallel** (`starccm+ -np`, a
    configurable core count) with a configurable number of **scenes per license
    checkout**, closing each scene after its hardcopy to limit memory use. A
    first-open warning notes that rendering is memory-heavy (≥16 GB recommended).
- **In-app settings dialog** — STAR-CCM+ paths, licensing (with a masked POD
  key), file/report/plot/scene display options, export defaults, profile management
  (view details / delete), a **dark/light theme with custom accent, checkmark and
  folder colours** and an **adjustable text size** previewed live, a reset, and a
  *Clear all temp files* action.
- **In-app updates** — checks GitHub releases on startup (and on demand); shows a
  toolbar note when a newer version is available and, on the Windows build, can
  download and install it in place.
- **First-run setup wizard** for the essentials (executable path, licensing,
  theme), re-openable any time and toggleable from Settings.
- **Credential safety** — the POD key is masked in the UI, the settings file and
  log are written owner-only, and license credentials are redacted from logs.

## Requirements

- **Python 3.11+**
- **A local, licensed STAR-CCM+ installation** (its executable path is set in
  Settings). The UI opens and is fully navigable without one — STAR-CCM+ is only
  needed to actually extract data from `.sim` files.
- **Scene rendering** additionally needs working **graphics** (a GPU/display, or
  an offscreen GL context on headless machines) and is **memory-heavy**:
  **≥16 GB** of system RAM is recommended, and closing other programs first helps
  avoid out-of-memory errors.
- OS: **Linux or Windows**.
- Python dependencies: see [`requirements.txt`](requirements.txt) /
  [`pyproject.toml`](pyproject.toml).

## Configuration

Most settings are editable in-app via **Settings** (paged dialog), or directly
in the settings file (seeded from `config/default_settings.yaml` on first run).
Per-OS locations (via `platformdirs`):

- Linux: `~/.config/starpost/settings.yaml`
- Windows: `%APPDATA%\starpost\settings.yaml`

Key fields:

- `starccm_path` — path to the `starccm+` executable (set manually or via the
  setup wizard). Typical install locations (replace `<version>` with your
  installed STAR-CCM+ version):
  - Linux: `/opt/Siemens/<version>/STAR-CCM+<version>/star/bin/starccm+`
  - Windows: `C:/Program Files/Siemens/<version>/STAR-CCM+<version>/star/bin/starccm+.bat`
- `license` — default mode is POD key + license server
  (`-power -podkey <KEY> -licpath <port>@<server>`); a regular license-file mode
  is also supported.
- `default_output_dir` — where exports are written (user-defined per run).
- Report/plot display options (decimals, empty-value hiding + thresholds,
  moving-average smoothing width, hover label options, axis-classification
  keywords), export defaults
  (`export_report_format`, `export_plot_format`, `export_plot_theme`),
  `appearance` (theme, accent, checkmark + folder colours), and
  `check_updates_on_startup`.
- `media` — scene-rendering options: `image_format` (jpg/png),
  `image_resolution` (1080p/2160p), `magnification`, `render_np` (parallel cores
  for `starccm+ -np`), and `scenes_per_checkout`.

Extraction **profiles** (saved report/plot selections, the monitors shown per
plot, and axis overrides) live alongside the settings file in `profiles/*.yaml`
(Linux `~/.config/starpost/`, Windows `%APPDATA%\starpost\`). The crash-recovery
cache and logs live under the per-OS cache dir (Linux `~/.cache/starpost/`,
Windows `%LOCALAPPDATA%\starpost\`).

## Usage at a glance

1. On first run, the **setup wizard** prompts for the STAR-CCM+ executable path,
   licensing, and theme. (Re-open it any time; it's also editable in Settings.)
2. **Files** tab → *Add files…* to add individual `.sim` files, or *Add folder…*
   to import a folder's `.sim` files into a new internal folder named after it.
3. **Run batch** (toolbar) and choose an output folder. STAR-CCM+ runs once per
   file and the extracted data appears in the **Data** tab.
4. Tick **Data** sets to view (two or more → comparison), then use the
   **Reports** and **Plots** tabs plus the right-hand selection panel to filter.
   Save a selection as a **Profile** to reuse it later.
5. **Export…** (toolbar) writes report tables and/or plot images.
6. *(Optional)* On the **Scenes** tab, tick one **Data** set, pick scenes (and
   their displayers / a saved view), and click **Run** to render image stills.

Re-selecting, comparing, and re-exporting never re-run STAR-CCM+ — extraction
happens once and is cached. (Scene rendering does run STAR-CCM+ again, on demand.)

## Documentation

- [`docs/StarPost_Documentation.md`](docs/StarPost_Documentation.md) — the full reference:
  every menu, panel, and dialog; the data flow and architecture; and the
  program's limitations.
- [`CHANGELOG.md`](CHANGELOG.md) — per-version release notes (newest first).
- [`docs/dev_install.md`](docs/dev_install.md) — running StarPost from a source
  checkout as a Python script.
- [`docs/packaging.md`](docs/packaging.md) — building release artifacts (the
  Linux AppImage and the Windows bundle).
