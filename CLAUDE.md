# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

StarPost is a standalone **PySide6 desktop app** that automates STAR-CCM+ post-processing:
it extracts report values and monitor plots from solved `.sim` files, lets you view/compare
them, and exports tables (CSV/TSV/XLSX/ODS) and plots (PNG/JPG/TIFF/PDF). It also renders
scene stills. Runs on Linux and Windows. The brand is written **StarPost**; lowercase
`starpost` only for the package/path/command identifier.

## Commands

Setup (editable install with dev tools — pytest, ruff, pyinstaller):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the GUI (three equivalent entry points, all call `starpost.app:main`):
```bash
python scripts/dev_run.py        # launcher; adds src/ to path, no install needed
python -m starpost.app           # needs editable install or src/ on PYTHONPATH
starpost                         # console entry point from pip install -e .
```

Tests and lint:
```bash
python -m pytest                             # full suite
python -m pytest tests/test_store.py         # one file
python -m pytest tests/test_store.py::test_x # one test
ruff check .                                 # lint (line-length 100, py311 target)
```
GUI tests instantiate a real `QApplication`. On a headless machine, prefix with
`QT_QPA_PLATFORM=offscreen`.

The version is the single source of truth in `__version__` in `src/starpost/__init__.py`;
`pyproject.toml` derives its version from there via setuptools' dynamic `attr`. Packaging
(PyInstaller spec, AppImage) is in `packaging/` and documented in `docs/packaging.md`.

## Architecture

**The central invariant: STAR-CCM+ runs once per file; everything after is cached.**
Re-selecting, comparing, filtering, and re-exporting never re-invoke STAR-CCM+. Scene
rendering is the one exception — a separate, on-demand pass.

### Extraction pipeline (`core/`)
`.sim` files are a proprietary binary with no public reader, so StarPost drives the
STAR-CCM+ CLI instead of parsing them:

1. `macro_generator.py` renders a Java macro from a Jinja2 template in `macros/*.j2`
   (the public class name must match the `.java` filename → always `extract_all.java`).
2. `starccm_runner.py` (`StarRunner`) shells out: `starccm+ -batch <macro> <license args>
   <file.sim>`. License args come from `Settings.license` (default POD key + server).
3. The macro exports **all** reports and monitor plots to CSVs (and lists scenes,
   displayers, saved views).
4. `result_parser.py` parses those CSVs into a `SimResult`, classifying each plot
   (residual → log Y, force → linear Y) via keyword heuristics from settings (overridable).
5. `data/store.py` (`ResultStore`, keyed by `sim_path`) holds results in memory and
   persists them to a JSON crash-recovery cache.

### Data model (`data/models.py`)
`SimResult` is the unit: it holds `Report`s (scalar values), `MonitorPlot`s (each a set of
`PlotSeries` = y vs. shared x), `Scene`s/`Displayer`s, and `MediaArtifact`s (rendered
stills). `data/portable.py` reads/writes the shareable per-sim CSV (the Data tab's
export/import — re-loadable without STAR-CCM+).

### Batch subsystem (`batch/`)
Two distinct "batch" concepts — don't conflate them:
- **Extraction batch** (`queue.py` `BatchWorker`): runs `Job`s (one `.sim` each)
  **sequentially off the GUI thread** in a `QThread`. Sequential is deliberate — one
  license checkout at a time. Supports cooperative "stop after current file"; never killed
  mid-write. Scene rendering has its own `SceneRenderWorker` (parallel `starccm+ -np`).
- **"Run batch" export** (`run.py`): the toolbar wizard that bundles selected report
  tables, plot images, scene stills (and optional portable CSVs) into a single `.zip`.
  This runs **on the GUI thread** because it renders real `PlotView` widgets (Qt widgets
  can't be created off the GUI thread). `aggregator.py` builds the wide/long comparison
  DataFrames.

### GUI (`gui/`)
`main_window.py` wires the layout: `FileListPanel` | Reports table + `PlotView` tabs |
`SelectionPanel`, with a `LogConsole` + progress bar below. Ticking 2+ data sets switches
views into comparison mode automatically. Individual dialogs/panels live in `gui/views/`.
Plots use **pyqtgraph**. `theme.py` drives the light/dark theme (custom accent, checkmark,
folder colours) and text scaling; `plot_style.py` keeps plots theme-aware.

### Settings & profiles (`core/settings.py`, `utils/paths.py`)
YAML via `platformdirs` (Linux `~/.config/starpost/`, Windows `%APPDATA%\starpost\`),
seeded from `config/default_settings.yaml` on first run. Cache/logs under the per-OS cache
dir. **Settings** = how to run STAR-CCM+; **Profile** = which reports/plots to show
(reusable). Batch profiles are separate.

### Credential safety (do not weaken)
The POD key is masked in the UI, `settings.yaml` and the log are written owner-only
(`harden_file` → `0o600`), and license credentials are redacted from logs. The POD key's
appearance in the process table / argv is a **deliberate, accepted risk** — don't "fix" it.

## Conventions

- Commit after every change; log user-facing changes in `CHANGELOG.md` in its existing
  style (newest first).
- Tests isolate per-user state with an `autouse` fixture that monkeypatches
  `paths.platformdirs.user_config_dir` / `user_cache_dir` to a `tmp_path` — reuse this
  pattern for anything that touches config/cache so tests never write real files.
- Startup latency matters: several imports are deliberately lazy (e.g. jinja2 in
  `macro_generator._get_env`, pandas). Keep heavy imports off the module top level unless
  they're already on the startup path.
