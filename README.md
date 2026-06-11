# starpost

Standalone desktop tool to automate STAR-CCM+ post-processing: it extracts
**report values** and **monitor plots** (residuals, forces vs. iteration) from
solved `.sim` files, lets you view and compare them, and exports to CSV / JPG /
PDF.

> Repo currently named `autonomic`; the application/package is `starpost` and the
> repo will be renamed to match later.

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

## Requirements

- Python 3.11+
- A local STAR-CCM+ install (path configured in settings)
- See `requirements.txt`

## Quick start (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/dev_run.py        # launches the GUI (no STAR-CCM+ needed to open the UI)
```

## Configuration

User settings live at `~/.config/starpost/settings.yaml` (seeded from
`config/default_settings.yaml`). Key fields:

- `starccm_path` — path to the `starccm+` executable (manual; default TBD).
- `license` — default mode is POD key + license server
  (`-power -podkey <KEY> -licpath <port>@<server>`); a regular license-file mode
  is also supported.
- `default_output_dir` — where exports are written (user-defined per run).

Extraction **profiles** (saved selections of which reports/plots to export) live
in `~/.config/starpost/profiles/*.yaml`.

## Status

v1 scaffold. See module-level `TODO`s. Built for Linux; Windows support planned.
