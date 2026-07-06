# Run batch ZIP/7Z archive formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Run batch Summary tab's *Archive format* selector actually work — produce a `.zip` or a `.7z` per the user's choice — and remove the RAR option that can't be produced.

**Architecture:** Add `py7zr` as a pure-Python 7z writer. Generalize `build_batch_archive` in `batch/run.py` to dispatch on a new `BatchConfig.archive_format` field (`"zip" | "7z"`) instead of always zipping. Wire the existing (currently-dead) `_export_format` combo in `batch_run_dialog.py` into the run: read its value, build the destination filename with the matching extension, and pass the format into `BatchConfig`. RAR is removed from the combo.

**Tech Stack:** Python 3.11, PySide6 (Qt), stdlib `zipfile`, `py7zr`, pytest.

## Global Constraints

- New dependency: `py7zr>=0.21` (added to both `pyproject.toml` and `requirements.txt`).
- `py7zr` is imported **lazily** inside its packing helper, never at module top level (startup-latency convention: heavy imports stay off the startup path).
- Archive format is **run-time-only** — do NOT persist it in `BatchProfile` or `settings.py` (matches how `report_format`, `include_units`, `combined_report` are handled).
- Supported formats after this change: `zip` and `7z` only. No RAR.
- ruff: line-length 100, target py311. Run `ruff check .` before committing.
- Brand is written **StarPost** in prose; `starpost` only for package/path/command identifiers.
- Commit after every task. Log user-facing changes in `CHANGELOG.md`, newest first.
- Run headless GUI tests with `QT_QPA_PLATFORM=offscreen` if no display is available.

## File Structure

- `pyproject.toml` — add `py7zr>=0.21` to `[project].dependencies`.
- `requirements.txt` — add `py7zr>=0.21`.
- `src/starpost/batch/run.py` — add `archive_format` to `BatchConfig`; add `_sevenzip_dir` and `_pack_dir` dispatch; rename `build_batch_archive`'s `dest_zip` param to `dest`; call `_pack_dir`.
- `src/starpost/gui/views/batch_run_dialog.py` — drop the RAR combo item; read the chosen format in `_run_batch`; build the dest filename with that extension; pass `archive_format` into `BatchConfig`.
- `tests/test_main_window.py` — update the archive-format-list assertion; add a 7z archive test.
- `README.md`, `CHANGELOG.md` — documentation.

---

### Task 1: Add the `py7zr` dependency

**Files:**
- Modify: `pyproject.toml` (the `dependencies` list under `[project]`)
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `py7zr` importable in the environment (used by Task 2's `_sevenzip_dir`).

- [ ] **Step 1: Add `py7zr` to `pyproject.toml`**

In `pyproject.toml`, inside the `[project]` `dependencies = [ ... ]` list, add this line after the `"Jinja2>=3.1",` entry:

```toml
    "py7zr>=0.21",      # 7z archive output for Run batch (pure-Python writer)
```

- [ ] **Step 2: Add `py7zr` to `requirements.txt`**

Add this line to the end of `requirements.txt`:

```
py7zr>=0.21
```

- [ ] **Step 3: Install it into the venv**

Run: `pip install "py7zr>=0.21"`
Expected: installs `py7zr` (and its transitive compression deps) with no error.

- [ ] **Step 4: Verify it imports**

Run: `python -c "import py7zr; print(py7zr.__version__)"`
Expected: prints a version string (e.g. `0.21.x` or newer), no traceback.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "Add py7zr dependency for 7z batch archives"
```

---

### Task 2: Dispatch archive packing on format in `batch/run.py`

**Files:**
- Modify: `src/starpost/batch/run.py` (`BatchConfig` ~line 54-66; `_zip_dir` ~line 152; `build_batch_archive` ~line 202-317)
- Test: `tests/test_main_window.py` (add one test near the existing `test_build_batch_archive_includes_dataset_csv` at ~line 1515)

**Interfaces:**
- Consumes: `py7zr` (Task 1); existing `_zip_dir(src_dir, dest)`.
- Produces:
  - `BatchConfig.archive_format: str = "zip"` (values `"zip" | "7z"`).
  - `build_batch_archive(config, settings, runner, dest, *, log=None, progress=None, plot_renderer=None) -> Path` — the fourth positional param is renamed `dest_zip` → `dest`; behaviour unchanged for zip.
  - `_pack_dir(src_dir: Path, dest: Path, fmt: str) -> None` and `_sevenzip_dir(src_dir: Path, dest: Path) -> None`.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_main_window.py` immediately after `test_build_batch_archive_includes_dataset_csv` (it reuses the module's existing `_sim_result_with_data` helper and `Settings` import):

```python
def test_build_batch_archive_7z(app, tmp_path):
    """archive_format='7z' produces a real .7z with the same per-folder layout."""
    import py7zr

    import starpost.batch.run as run

    result = _sim_result_with_data()
    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseA", result=result)],
        reports={"Drag"}, report_format="csv",
        archive_format="7z",
    )
    dest = tmp_path / "batch.7z"
    run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)

    assert dest.exists()
    with py7zr.SevenZipFile(dest, "r") as z:
        names = set(z.getnames())
    assert "caseA/reports.csv" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main_window.py::test_build_batch_archive_7z -v`
Expected: FAIL — `TypeError` for the unexpected `archive_format` keyword to `BatchConfig` (the field doesn't exist yet).

- [ ] **Step 3: Add the `archive_format` field to `BatchConfig`**

In `src/starpost/batch/run.py`, in the `BatchConfig` dataclass, add a line directly after the `combined_report` field (currently line 66):

```python
    archive_format: str = "zip"         # zip | 7z (the packed output format)
```

- [ ] **Step 4: Add the 7z packer and the dispatch helper**

In `src/starpost/batch/run.py`, directly below the existing `_zip_dir` function (it ends at line 158, after the `zf.write(...)` loop), add:

```python
def _sevenzip_dir(src_dir: Path, dest: Path) -> None:
    """Pack every file under ``src_dir`` into a .7z at ``dest`` (paths relative to
    ``src_dir``, so the archive's top level is the per-data-set folders)."""
    # Lazy import: py7zr is only needed when the user picks 7Z, and it pulls in
    # compression libs we don't want on the startup path.
    import py7zr

    dest.parent.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(dest, "w") as z:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src_dir).as_posix())


def _pack_dir(src_dir: Path, dest: Path, fmt: str) -> None:
    """Pack ``src_dir`` into ``dest`` in archive format ``fmt`` ("zip" | "7z")."""
    if fmt == "7z":
        _sevenzip_dir(src_dir, dest)
    else:
        _zip_dir(src_dir, dest)
```

- [ ] **Step 5: Rename `dest_zip` → `dest` in `build_batch_archive` and call `_pack_dir`**

In `src/starpost/batch/run.py`, in `build_batch_archive`:

Change the signature param (line 206) from:

```python
    dest_zip: Path,
```
to:
```python
    dest: Path,
```

In the docstring (lines 212-216), replace the two `` ``dest_zip`` `` references with `` ``dest`` ``.

Change line 225 from:
```python
    dest_zip = Path(dest_zip)
```
to:
```python
    dest = Path(dest)
```

Change the packaging call (line 314) from:
```python
        _zip_dir(out_root, dest_zip)
```
to:
```python
        _pack_dir(out_root, dest, config.archive_format)
```

Change the final log + return (lines 316-317) from:
```python
    log(f"Wrote {dest_zip}")
    return dest_zip
```
to:
```python
    log(f"Wrote {dest}")
    return dest
```

- [ ] **Step 6: Run the new test to verify it passes**

Run: `python -m pytest tests/test_main_window.py::test_build_batch_archive_7z -v`
Expected: PASS.

- [ ] **Step 7: Run the existing archive tests to confirm no regression**

Run: `python -m pytest tests/test_main_window.py -k build_batch_archive -v`
Expected: all `build_batch_archive*` tests PASS (zip default path unaffected).

- [ ] **Step 8: Lint**

Run: `ruff check src/starpost/batch/run.py tests/test_main_window.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add src/starpost/batch/run.py tests/test_main_window.py
git commit -m "Dispatch Run batch packing on archive format (zip/7z)"
```

---

### Task 3: Wire the format selector in the dialog and drop RAR

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (`_export_format` combo ~line 1140-1142; `_run_batch` dest + `BatchConfig(...)` ~line 1851-1860)
- Test: `tests/test_main_window.py` (archive-format assertion ~line 537-539)

**Interfaces:**
- Consumes: `BatchConfig.archive_format` (Task 2).
- Produces: no new public interface; the Summary tab's combo now drives the output format.

- [ ] **Step 1: Update the failing test for the offered formats**

In `tests/test_main_window.py`, change the assertion at line 539 from:

```python
    ] == ["zip", "7z", "rar"]
```
to:
```python
    ] == ["zip", "7z"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_main_window.py -k "summary" -v` (this exercises the test whose body asserts the archive-format list)
Expected: FAIL — the combo still contains `"rar"`, so the list is `["zip", "7z", "rar"]`.

- [ ] **Step 3: Remove the RAR combo item**

In `src/starpost/gui/views/batch_run_dialog.py`, delete line 1142:

```python
        self._export_format.addItem("RAR", "rar")
```

(Leave the `ZIP` and `7Z` `addItem` lines above it intact.)

- [ ] **Step 4: Read the chosen format and use it for the dest filename**

In `_run_batch`, replace line 1851:

```python
        dest = Path(out_dir) / f"starpost_batch_{datetime.now():%Y%m%d_%H%M%S}.zip"
```
with:
```python
        fmt = self._export_format.currentData()
        dest = Path(out_dir) / f"starpost_batch_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
```

- [ ] **Step 5: Pass the format into `BatchConfig`**

In the same `_run_batch`, in the `config = BatchConfig(` call, add an `archive_format` argument. Change the block (lines 1852-1861) so it reads:

```python
        config = BatchConfig(
            sources=sources,
            reports=reports,
            report_format=self._report_format.currentText().lower(),
            include_units=self._report_include_units.isChecked(),
            saved_plots=saved_plots,
            saved_scenes=saved_scenes,
            include_dataset_csv=include_dataset_csv,
            combined_report=self._report_combined.isChecked(),
            archive_format=fmt,
        )
```

- [ ] **Step 6: Run the format-list test to verify it passes**

Run: `python -m pytest tests/test_main_window.py -k "summary" -v`
Expected: PASS (combo now offers exactly `["zip", "7z"]`).

- [ ] **Step 7: Run the full GUI test module**

Run: `python -m pytest tests/test_main_window.py -v`
Expected: all PASS (prefix with `QT_QPA_PLATFORM=offscreen` if headless).

- [ ] **Step 8: Lint**

Run: `ruff check src/starpost/gui/views/batch_run_dialog.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add src/starpost/gui/views/batch_run_dialog.py tests/test_main_window.py
git commit -m "Wire Run batch archive-format selector; remove RAR"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md` (Run batch bullet, lines 103-108)
- Modify: `CHANGELOG.md` (add a new entry at the top of the version list)

**Interfaces:**
- Consumes: nothing. Produces: nothing (docs only).

- [ ] **Step 1: Update the README Run batch bullet**

In `README.md`, replace lines 106-108:

```
  into a **single archive** (a `.zip`, one folder per data set). Whole setups can
  be saved and reloaded as **batch profiles**. *(The format selector also lists
  7Z and RAR; these are not produced yet — planned for a future release.)*
```
with:
```
  into a **single archive** (a `.zip` or `.7z`, one folder per data set), the
  format chosen on the Summary tab. Whole setups can be saved and reloaded as
  **batch profiles**.
```

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, insert a new version section directly above the `## [2.1.0] — 2026-07-01` heading. Use the version from `src/starpost/__init__.py` bumped by a patch (currently `2.1.0` → use `2.1.1`) and today's date:

```markdown
## [2.1.1] — 2026-07-05

### New Features
- **Run batch → Summary** — the *Archive format* selector now works: batches can
  be packed as **ZIP** or **7Z**. The unavailable **RAR** option has been removed.

```

- [ ] **Step 3: Bump the version to match the CHANGELOG**

In `src/starpost/__init__.py`, change:

```python
__version__ = "2.1.0"
```
to:
```python
__version__ = "2.1.1"
```

- [ ] **Step 4: Verify the version import still works**

Run: `python -c "import starpost; print(starpost.__version__)"`
Expected: prints `2.1.1`.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md src/starpost/__init__.py
git commit -m "Document ZIP/7Z Run batch archives; bump to 2.1.1"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only).

**Interfaces:** Consumes everything above.

- [ ] **Step 1: Run the whole test suite**

Run: `python -m pytest`
Expected: all tests PASS (prefix with `QT_QPA_PLATFORM=offscreen` if headless).

- [ ] **Step 2: Lint the whole tree**

Run: `ruff check .`
Expected: no errors.

- [ ] **Step 3: Confirm PyInstaller will bundle `py7zr`**

`py7zr` is a real `import py7zr` statement inside `_sevenzip_dir`, so PyInstaller's static analysis follows it automatically — no `hiddenimports` entry is normally required. Verify the current spec doesn't already special-case it:

Run: `grep -n "hiddenimports\|py7zr" packaging/starpost.spec`
Expected: `hiddenimports` lists `pyqtgraph` (and no `py7zr`). Only if a later packaged build actually fails to find `py7zr` at runtime, add `"py7zr"` to that `hiddenimports` list. No change is expected here.

- [ ] **Step 4: Manual smoke (optional, needs a display)**

Launch `python scripts/dev_run.py`, open **Run batch**, and confirm the Summary tab's *Archive format* offers only **ZIP** and **7Z**. (A full run needs STAR-CCM+ / extracted data; the combo contents and dispatch are already covered by the automated tests.)
