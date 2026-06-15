# starpost

Standalone desktop tool to automate STAR-CCM+ post-processing: it extracts
**report values** and **monitor plots** (residuals, forces vs. iteration) from
solved `.sim` files, lets you view and compare them, and exports to CSV / JPG /
PDF.

## How it works

STAR-CCM+ `.sim` files are a proprietary binary format with no public reader, so
starpost does **not** parse them directly. Instead it:

1. Generates a Java macro from a template (`src/starpost/macros/`).
2. Runs it via `starccm+ -batch <macro> <file.sim>` (one license checkout per
   file, sequential — license-safe).
3. The macro exports **all** reports and monitor plots to CSV in an output dir;
   starpost parses those and caches them.
4. The GUI filters the cached data by your selection/profile for viewing and
   export. Re-selecting never re-runs STAR-CCM+.

A licensed STAR-CCM+ installation must be present on the machine.

## Features

- **Batch extraction** of all report values and monitor plots from multiple
  `.sim` files, run sequentially (one license checkout at a time) with a live
  log and progress bar, and a crash-recovery cache.
- **Per-file and comparison views** — a numeric report table and an interactive
  plot viewer.
- **Interactive plots** (pyqtgraph):
  - Overlay **several monitor groups at once**, each with its own dropdown for
    choosing which monitors (series) are shown.
  - **Hover readout** that snaps a marker + coordinate label to the nearest data
    point (optional monitor name, configurable X/Y decimals).
  - Residuals on a log axis, forces on a linear axis (auto-classified by name).
  - Background, axes and legend **follow the light/dark theme**.
- **Profiles** — save/reuse a named selection of reports and plots, *including
  which monitors are shown per group*. A built-in **Default** profile selects
  every report and no plots.
- **In-app settings dialog** — STAR-CCM+ paths, licensing, report/plot display
  options, profile management (view details / delete), and a **dark/light theme
  with a custom accent colour** previewed live.
- **Export** report values to CSV and plots to JPG/PDF *(export wiring is still
  in progress — see the overview doc)*.

## Requirements

- Python 3.11+
- A local STAR-CCM+ install (path configured in settings)
- See `requirements.txt`

## Quick start (development)

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python scripts/dev_run.py         # launches the GUI (no STAR-CCM+ needed to open the UI)
```

Runs on Linux and Windows (Python 3.11+ and PySide6 on both).

## Configuration

Most settings are editable in-app via **Settings** (paged dialog), or directly
in the settings file (seeded from `config/default_settings.yaml` on first run).
Per-OS locations (via `platformdirs`):

- Linux: `~/.config/starpost/settings.yaml`
- Windows: `%APPDATA%\starpost\settings.yaml`

Key fields:

- `starccm_path` — path to the `starccm+` executable (manual; default TBD).
- `license` — default mode is POD key + license server
  (`-power -podkey <KEY> -licpath <port>@<server>`); a regular license-file mode
  is also supported.
- `default_output_dir` — where exports are written (user-defined per run).
- Report/plot display options (decimals, empty-value hiding + thresholds, hover
  label options, axis-classification keywords) and `appearance` (theme + accent).

Extraction **profiles** (saved report/plot selections, the monitors shown per
plot, and axis overrides) live alongside the settings file in `profiles/*.yaml`
(Linux `~/.config/starpost/`, Windows `%APPDATA%\starpost\`). The crash-recovery
cache and logs live under the per-OS cache dir (Linux `~/.cache/starpost/`,
Windows `%LOCALAPPDATA%\starpost\`).

## Packaging

Build a standalone bundle with PyInstaller (run on the target OS — PyInstaller
does not cross-compile):

```bash
pip install -e ".[dev]"
pyinstaller packaging/starpost.spec
```

Output lands in `dist/starpost/` (`starpost.exe` on Windows). The spec selects
the Windows `.ico` automatically.

## Status

v1. Core extraction/parsing, the in-app settings dialog, and the interactive
plot viewer are implemented; batch **export wiring** is still stubbed (see
[`docs/PROGRAM_OVERVIEW.md`](docs/PROGRAM_OVERVIEW.md)). Runs on Linux and
Windows.
