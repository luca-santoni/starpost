# Run batch archive formats: support ZIP and 7Z (drop RAR)

**Date:** 2026-07-05
**Status:** Approved

## Problem

The Run batch wizard's Summary tab shows an *Archive format* selector offering
ZIP, 7Z, and RAR, but the selector is dead: `_run_batch` hardcodes a `.zip`
output filename and never reads the combo, and `build_batch_archive` always packs
with stdlib `zipfile` via `_zip_dir`. The selector has never affected output.

## Goal

Make the selector real. Produce a `.zip` or a `.7z` per the user's choice. Remove
RAR from the UI.

## Constraints and decisions

- **RAR is dropped.** RAR *creation* is proprietary — there is no open-source RAR
  writer, and the only way to produce a `.rar` is WinRAR's licensed `rar` binary,
  which cannot be bundled and is essentially never present (especially on Linux).
  Python's `rarfile` only reads. Rather than pretend to support it, RAR is removed
  from the selector. Result: ZIP + 7Z, the two formats we can produce reliably.
- **7Z via `py7zr`.** Add `py7zr` as a dependency — a pure-Python 7z writer that
  bundles into the PyInstaller AppImage/exe with no external tool. Chosen over
  shelling out to a `7z`/`7za` CLI, which would depend on the user having 7-Zip
  installed and fail often (notably on Windows).
- **Archive format is run-time-only, not persisted in batch profiles.** This
  matches the existing convention: `BatchProfile` persists only
  `selected_reports` / `saved_plots` / `saved_scenes`; `report_format`,
  `include_units`, `combined_report`, and the archive format are all run-time
  options. No `settings.py` / profile changes.

## Changes

### 1. Dependency

- Add `py7zr>=0.21` to `[project].dependencies` in `pyproject.toml` and to
  `requirements.txt`.
- During implementation, confirm the PyInstaller build picks `py7zr` up; add it to
  `packaging/starpost.spec` `hiddenimports` only if it is not auto-detected.

### 2. Archive packing — `src/starpost/batch/run.py`

- Rename the `build_batch_archive` parameter `dest_zip` → `dest` (the destination
  is no longer always a zip). The public function name is unchanged.
- Add `archive_format: str = "zip"` to `BatchConfig` (values `"zip" | "7z"`).
- Replace the hardcoded `_zip_dir(out_root, dest)` call with a dispatch helper
  `_pack_dir(src_dir, dest, fmt)` that routes to:
  - `_zip_dir` (existing, unchanged) for `"zip"`, and
  - a new `_sevenzip_dir` for `"7z"`, using `py7zr.SevenZipFile(dest, "w")` and
    writing every file under `src_dir` with paths relative to `src_dir` (same
    top-level layout as the zip: one per-data-set folder at the archive root).
- Import `py7zr` **lazily inside `_sevenzip_dir`**, matching the codebase's
  lazy-import-for-startup convention, so opening the app or running a ZIP batch
  never imports it.

### 3. Dialog wiring — `src/starpost/gui/views/batch_run_dialog.py`

- Remove the `RAR` item from `_export_format`; it keeps `ZIP` and `7Z`.
- In `_run_batch`:
  - Read `fmt = self._export_format.currentData()`.
  - Build the destination filename as
    `starpost_batch_<timestamp>.<fmt>` (was hardcoded `.zip`).
  - Pass `archive_format=fmt` into `BatchConfig`.
  - The "Batch written to: {dest}" message already interpolates `dest`, so it
    reflects the real extension with no further change.

### 4. Error handling

- The ZIP path is unchanged.
- A `py7zr` failure propagates as the existing `_BatchRunWorker.error`, surfaced by
  the current "Run batch failed" `QMessageBox.critical`. No new error surface.
- No external-tool detection or fallback is needed, since `py7zr` is always present
  as a dependency.

## Testing

- Update `tests/test_main_window.py` (~line 538): the expected archive-format list
  changes from `["zip", "7z", "rar"]` to `["zip", "7z"]`.
- Add `test_build_batch_archive_7z`: run `build_batch_archive` with
  `archive_format="7z"` to a `.7z` destination and assert, via
  `py7zr.SevenZipFile(dest).getnames()`, that it contains the expected per-folder
  entries (mirrors the existing zip archive test).
- The existing `.zip` archive tests remain green (zip stays the default).

## Documentation

- README: update the "Run batch" feature bullet — drop the "The format selector
  also lists 7Z and RAR; these are not produced yet" caveat and state that ZIP and
  7Z are supported.
- `CHANGELOG.md`: add a user-facing entry (ZIP/7Z archive output; RAR removed).

## Out of scope

- RAR output.
- Persisting the archive format in batch profiles.
- Any change to report/plot/scene formats or the extraction pipeline.
