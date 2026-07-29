# Convergence Assessment Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Convergence window export its assessment of every loaded data set as a table, in csv / tsv / xlsx / ods.

**Architecture:** A new Qt-free `core/convergence/export.py` builds four pandas DataFrames from a list of `ConvergenceAssessment` and writes them (one file with four sheets for xlsx/ods; four sibling files for csv/tsv). The Convergence window gets an `Export assessment…` button that feeds it `self._assessments`, which is already current — the export never re-runs `assess()`.

**Tech Stack:** Python 3.11+, pandas (already a dependency), openpyxl (xlsx) and odfpy (ods), both already dependencies. PySide6 for the button and file dialog. pytest.

**Design spec:** `docs/superpowers/specs/2026-07-28-convergence-assessment-export-design.md`

## Global Constraints

- Line length 100, `ruff check .` must stay clean, target `py311`.
- Use the repo venv explicitly: `.venv/bin/python`. There is no system pip/venv on this machine.
- GUI tests need `QT_QPA_PLATFORM=offscreen`.
- Run a **single** test file per `pytest` invocation. Never run a bare multi-file `pytest` — use `.venv/bin/python scripts/run_tests.py` for the full suite.
- Commit after every task (repo convention).
- **`core/` must never import from `gui/`.** The convergence package is Qt-free and STAR-CCM+-free; keep it that way.
- **pandas is imported lazily**, inside functions, not at module top level (`CLAUDE.md`: startup latency; several imports are deliberately lazy).
- Every frame's first column is `Data set`.
- Supported formats are exactly `csv`, `tsv`, `xlsx`, `ods`.
- The export reads existing assessments; it must not call `assess()`.

## File Structure

| file | responsibility |
|---|---|
| `src/starpost/core/convergence/export.py` (new) | Build the four DataFrames; write them in any supported format; own the shared `iterative_error_text` formatting rule |
| `src/starpost/gui/views/convergence_dialog.py` (modify) | `Export assessment…` button, save dialog, success/error reporting; `_iterative_cell` delegates to `export.iterative_error_text` |
| `tests/test_convergence_export.py` (new) | Frame shapes, column contents, format packaging |
| `tests/test_convergence_gui.py` (modify) | Button enablement and a real write through a stubbed file dialog |

---

### Task 1: Frame builders and the shared iterative-error text

**Files:**
- Create: `src/starpost/core/convergence/export.py`
- Test: `tests/test_convergence_export.py` (new)

**Interfaces:**
- Consumes: `ConvergenceAssessment`, `MonitorAssessment`, `ResidualAssessment`, `Reason` from `starpost.core.convergence.models`; `GATE_ITERATIVE` from `starpost.core.convergence.steady`.
- Produces:
  - `iterative_error_text(monitor) -> str`
  - `summary_frame(assessments) -> pandas.DataFrame`
  - `gates_frame(assessments) -> pandas.DataFrame`
  - `residuals_frame(assessments) -> pandas.DataFrame`
  - `reasons_frame(assessments) -> pandas.DataFrame`
  - `TABLES: tuple[tuple[str, str, Callable], ...]` — `(slug, sheet_name, frame_builder)` for each of the four, in order: `("summary", "Summary", summary_frame)`, `("qoi-gates", "QoI gates", gates_frame)`, `("residuals", "Residuals", residuals_frame)`, `("reasons", "Reasons", reasons_frame)`.

  Task 2 consumes `TABLES` and all four builders. Task 3 consumes `iterative_error_text`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_convergence_export.py`:

```python
"""Shaping a convergence assessment into exportable tables. Pure pandas —
no Qt, no STAR-CCM+, no per-user state."""
import math

import numpy as np
import pytest

from starpost.core.convergence import assess
from starpost.core.convergence import export
from starpost.core.convergence.config import ConvergenceConfig
from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    SimProperties,
    SimResult,
)

CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
    "aggregate_keywords": ["ALL", "Total", "Sum", "Overall", "Combined"],
}


def _result(path: str, drifting: bool = False, with_residual: bool = True) -> SimResult:
    n = 3000
    rng = np.random.default_rng(0)
    x = list(map(float, range(n)))
    if drifting:
        qoi = 100.0 + 0.01 * np.arange(n, dtype=float)
    else:
        qoi = (100.0 + 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0))
               + rng.normal(scale=1e-9, size=n))
    plots = [MonitorPlot(name="Drag Monitor Plot", kind=PlotKind.FORCE,
                         series=[PlotSeries(name="Drag", x=x, y=qoi.tolist())])]
    if with_residual:
        residual = 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12
        plots.append(MonitorPlot(name="Residuals", kind=PlotKind.RESIDUAL,
                                 series=[PlotSeries(name="Continuity", x=x,
                                                    y=residual.tolist())]))
    return SimResult(
        sim_path=path,
        plots=plots,
        properties=SimProperties(groups=[
            PropertyGroup(section="continuum", name="P",
                          entries=[("models", "Steady; Segregated Flow")]),
            PropertyGroup(section="convergence", name="",
                          entries=[("precision", "double"),
                                   ("residual_normalization", "auto")]),
        ]),
    )


@pytest.fixture
def assessments():
    """Two data sets: one settled with a residual, one drifting without."""
    config = ConvergenceConfig()
    return [
        assess(_result("/tmp/a.sim"), config, CLASSIFICATION),
        assess(_result("/tmp/b.sim", drifting=True, with_residual=False),
               config, CLASSIFICATION),
    ]


def test_every_frame_leads_with_the_data_set_column(assessments):
    """The four tables are separate files in csv/tsv, so the reader needs a
    key to join them back together."""
    for _slug, _sheet, builder in export.TABLES:
        frame = builder(assessments)
        assert list(frame.columns)[0] == "Data set"


def test_summary_has_one_row_per_data_set(assessments):
    frame = export.summary_frame(assessments)
    assert len(frame) == 2
    assert list(frame["Data set"]) == ["a", "b"]
    assert frame.loc[0, "State"] == assessments[0].state.value
    assert frame.loc[0, "Confidence"] == assessments[0].confidence.value
    assert frame.loc[0, "Binding constraint"] == assessments[0].binding_constraint


def test_summary_records_the_settings_the_assessment_used(assessments):
    """A comparison table whose rows were produced under different tolerances
    is misleading precisely because it looks comparable, so the settings
    travel with the verdict."""
    frame = export.summary_frame(assessments)
    assert frame.loc[0, "Tolerance (%)"] == pytest.approx(0.1)
    assert frame.loc[0, "Required residual drop (decades)"] == pytest.approx(3.0)

    strict = assess(_result("/tmp/a.sim"),
                    ConvergenceConfig(tolerance_fraction=5e-4, d_min=4.0),
                    CLASSIFICATION)
    other = export.summary_frame([strict])
    assert other.loc[0, "Tolerance (%)"] == pytest.approx(0.05)
    assert other.loc[0, "Required residual drop (decades)"] == pytest.approx(4.0)


def test_gates_has_one_row_per_monitor_across_data_sets(assessments):
    frame = export.gates_frame(assessments)
    expected = sum(len(a.monitors) for a in assessments)
    assert len(frame) == expected
    assert set(frame["Data set"]) == {"a", "b"}
    assert "Margin" in frame.columns
    assert "Binding gate" in frame.columns
    assert "Iterative error" in frame.columns


def test_residuals_covers_only_the_data_set_that_has_them(assessments):
    """The second fixture has no residual plot at all, so it contributes no
    rows — and must not contribute a row of blanks either."""
    frame = export.residuals_frame(assessments)
    assert len(frame) == len(assessments[0].residuals)
    assert set(frame["Data set"]) == {"a"}
    assert frame.loc[0, "Equation"] == "Continuity"


def test_reasons_carries_the_action_not_just_the_message(assessments):
    """"Recommendations are the product" — an exported assessment that
    dropped the suggested actions would export the diagnosis without the
    help."""
    frame = export.reasons_frame(assessments)
    assert len(frame) == sum(len(a.reasons) for a in assessments)
    assert "Suggested action" in frame.columns
    assert "Estimated extra iterations" in frame.columns
    assert any(str(v).strip() for v in frame["Suggested action"])


def test_iterative_error_text_matches_the_three_cases():
    """The same rule the window's QoI-gates cell uses: the gate's own tested
    value, marked when it is not the geometric-tail estimate, and 'unbounded'
    when the value is infinite."""
    from starpost.core.convergence.models import GateResult, IterativeError
    from starpost.core.convergence.steady import GATE_ITERATIVE, assess_monitor

    monitor = assess_monitor("Drag", np.full(3000, 42.0), ConvergenceConfig(),
                             is_primary=True)

    def with_gate(value, valid):
        monitor.gates = [GateResult(name=GATE_ITERATIVE, passed=True,
                                    value=value, limit=1.0, margin=1.0)]
        monitor.iterative = IterativeError(
            u_iter=value if valid else None, epsilon_iter=None,
            safety_factor=1.25, rho=None, fit_sigma=0.0, fit_r2=0.0,
            valid=valid, reason="" if valid else "NO_ESTIMATE: no structure")
        return export.iterative_error_text(monitor)

    assert with_gate(0.00123, True) == "0.00123"
    assert with_gate(0.00123, False) == "0.00123 (largest change)"
    assert with_gate(math.inf, False) == "unbounded"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_convergence_export.py -q
```

Expected: every test FAILS with `ModuleNotFoundError: No module named 'starpost.core.convergence.export'`.

- [ ] **Step 3: Write the module**

Create `src/starpost/core/convergence/export.py`:

```python
"""Shape a convergence assessment into exportable tables.

The Convergence window assesses every loaded data set; this turns that into a
cross-run comparison a user can take away — into a design review, a study
spreadsheet, or a record of how a run was judged at the time.

Qt-free by design, like the rest of this package: the GUI passes in the
assessments it already has and writes the result where the user asked. pandas
is imported inside the functions rather than at module level, since it is
heavy and the convergence package is reachable from the startup path.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Iterable

from starpost.core.convergence.models import ConvergenceAssessment, MonitorAssessment
from starpost.core.convergence.steady import GATE_ITERATIVE

# Format -> how the four tables are packaged. A spreadsheet holds them as four
# sheets of one file; a delimited format holds one table per file, so csv/tsv
# write four suffixed siblings instead.
_SHEET_FORMATS = {"xlsx": "openpyxl", "ods": "odf"}
_DELIMITED_FORMATS = {"csv": ",", "tsv": "\t"}
SUPPORTED_FORMATS = (*_DELIMITED_FORMATS, *_SHEET_FORMATS)


def iterative_error_text(monitor: MonitorAssessment) -> str:
    """The 'Iterative error' cell, for the window and the export alike.

    ``monitor.iterative.u_iter`` is None whenever the geometric-tail estimator
    declined, which is common (a settled monitor, or a creeping one per the
    Mann-Kendall check in ``steady.assess_monitor``). But the iterative gate
    can still be the binding constraint, so showing a blank there while the
    verdict names it as binding is confusing. Show the gate's own value
    instead — the quantity actually tested against the tolerance — and mark it
    when it is not the geometric-tail estimate.

    Lives here rather than in the dialog so the window and the exported table
    cannot drift apart: ``core`` may not import from ``gui``, so the shared
    rule has to sit on this side of that boundary.
    """
    gate = next(g for g in monitor.gates if g.name == GATE_ITERATIVE)
    if monitor.iterative.valid:
        return f"{gate.value:.4g}"
    if not math.isfinite(gate.value):
        return "unbounded"
    return f"{gate.value:.4g} (largest change)"


def _frame(rows: list[dict], columns: list[str]):
    """A DataFrame with fixed columns, so an empty table still exports with
    its header rather than as a shapeless blank."""
    import pandas as pd

    return pd.DataFrame(rows, columns=columns)


def summary_frame(assessments: Iterable[ConvergenceAssessment]):
    """One row per data set: the headline verdict, plus the settings it was
    produced under."""
    columns = ["Data set", "State", "Confidence", "Confidence rule",
               "Convergence index", "Unbounded primary monitors",
               "Binding constraint", "Flags", "Segments", "Integrity errors",
               "Tolerance (%)", "Required residual drop (decades)"]
    rows = []
    for a in assessments:
        thresholds = a.thresholds_used
        rows.append({
            "Data set": a.sim_name,
            "State": a.state.value,
            "Confidence": a.confidence.value,
            "Confidence rule": a.confidence_rule,
            "Convergence index": a.convergence_index,
            "Unbounded primary monitors": a.unbounded_primary_count,
            "Binding constraint": a.binding_constraint,
            "Flags": "; ".join(f.value for f in a.flags),
            "Segments": a.n_segments,
            "Integrity errors": "; ".join(a.integrity_errors),
            "Tolerance (%)": _threshold(thresholds, "tolerance_fraction", 100.0),
            "Required residual drop (decades)": _threshold(thresholds, "d_min"),
        })
    return _frame(rows, columns)


def _threshold(thresholds: dict, name: str, scale: float = 1.0):
    """Pull a value out of ``ConvergenceAssessment.thresholds_used``, whose
    entries are ``(value, provenance)`` pairs."""
    entry = thresholds.get(name)
    if entry is None:
        return None
    value = entry[0] if isinstance(entry, tuple) else entry
    return value * scale


def gates_frame(assessments: Iterable[ConvergenceAssessment]):
    """One row per data set x monitor: the QoI-gates tab plus the quantities
    behind it."""
    columns = ["Data set", "Monitor", "Primary", "Mean", "Std",
               "Reference scale", "Scale source", "Tolerance (abs)",
               "Band (95%)", "Projected drift", "Two-halves delta",
               "Iterative error", "N_eff", "D_N", "Window start", "Window end",
               "Window samples", "Margin", "Binding gate", "Passed"]
    rows = []
    for a in assessments:
        for m in a.monitors:
            rows.append({
                "Data set": a.sim_name,
                "Monitor": m.name,
                "Primary": m.is_primary,
                "Mean": m.mean,
                "Std": m.std,
                "Reference scale": m.reference_scale,
                "Scale source": m.scale_source.value,
                "Tolerance (abs)": m.tolerance_abs,
                "Band (95%)": m.band_p95,
                "Projected drift": m.projected_drift,
                "Two-halves delta": m.two_halves_delta,
                "Iterative error": iterative_error_text(m),
                "N_eff": m.n_eff,
                "D_N": m.d_n,
                "Window start": m.window_start,
                "Window end": m.window_end,
                "Window samples": m.n_window,
                "Margin": m.margin,
                "Binding gate": m.binding_gate,
                "Passed": m.passed,
            })
    return _frame(rows, columns)


def residuals_frame(assessments: Iterable[ConvergenceAssessment]):
    """One row per data set x residual equation."""
    columns = ["Data set", "Equation", "Class", "R_ref", "R_terminal",
               "Decades dropped", "Log slope", "Decay factor", "Fit r^2",
               "State", "Iterations to target"]
    rows = []
    for a in assessments:
        for r in a.residuals:
            rows.append({
                "Data set": a.sim_name,
                "Equation": r.name,
                "Class": r.equation_class.value,
                "R_ref": r.r_ref,
                "R_terminal": r.r_terminal,
                "Decades dropped": r.decades_dropped,
                "Log slope": r.log_slope,
                "Decay factor": r.decay_factor,
                "Fit r^2": r.fit_r2,
                "State": r.state.value,
                "Iterations to target": r.iterations_to_target,
            })
    return _frame(rows, columns)


def reasons_frame(assessments: Iterable[ConvergenceAssessment]):
    """One row per reason. This is the table carrying the suggested actions —
    "recommendations are the product", so an export without them would ship
    the diagnosis and drop the help."""
    columns = ["Data set", "Severity", "Target", "Message", "Suggested action",
               "Estimated extra iterations"]
    rows = []
    for a in assessments:
        for reason in a.reasons:
            rows.append({
                "Data set": a.sim_name,
                "Severity": reason.severity.value,
                "Target": reason.target,
                "Message": reason.message,
                "Suggested action": reason.suggested_action,
                "Estimated extra iterations": reason.estimated_extra_iterations,
            })
    return _frame(rows, columns)


# (slug, sheet name, builder). The slug is the filename suffix in csv/tsv; the
# sheet name is the tab in xlsx/ods. Order is the order they are written.
TABLES: tuple[tuple[str, str, Callable], ...] = (
    ("summary", "Summary", summary_frame),
    ("qoi-gates", "QoI gates", gates_frame),
    ("residuals", "Residuals", residuals_frame),
    ("reasons", "Reasons", reasons_frame),
)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_convergence_export.py -q
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Lint**

```bash
.venv/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/starpost/core/convergence/export.py tests/test_convergence_export.py
git commit -m "feat: shape a convergence assessment into exportable tables

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Writing the tables in every supported format

**Files:**
- Modify: `src/starpost/core/convergence/export.py` (append `write_assessment`)
- Test: `tests/test_convergence_export.py` (append)

**Interfaces:**
- Consumes: `TABLES`, and the four frame builders, from Task 1.
- Produces: `write_assessment(assessments, path, fmt) -> list[Path]`. `path` is a `Path` or `str`; `fmt` is one of `"csv"`, `"tsv"`, `"xlsx"`, `"ods"`. Returns the paths actually written, in `TABLES` order. Raises `ValueError` on an unsupported format. Task 3 calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_convergence_export.py`:

```python
# --- writing ---------------------------------------------------------------

def test_csv_writes_four_suffixed_siblings(assessments, tmp_path):
    """A delimited format holds one table, so the four tables become four
    files named as a set."""
    written = export.write_assessment(assessments, tmp_path / "study.csv", "csv")

    assert [p.name for p in written] == [
        "study-summary.csv", "study-qoi-gates.csv",
        "study-residuals.csv", "study-reasons.csv",
    ]
    for path in written:
        assert path.exists() and path.stat().st_size > 0
    # The name the user typed is not itself written; the set is suffixed.
    assert not (tmp_path / "study.csv").exists()


def test_tsv_is_tab_delimited(assessments, tmp_path):
    written = export.write_assessment(assessments, tmp_path / "study.tsv", "tsv")
    header = written[0].read_text().splitlines()[0]
    assert "\t" in header
    assert header.startswith("Data set")


def test_xlsx_writes_one_file_with_four_named_sheets(assessments, tmp_path):
    import pandas as pd

    written = export.write_assessment(assessments, tmp_path / "study.xlsx", "xlsx")

    assert len(written) == 1
    assert written[0] == tmp_path / "study.xlsx"
    sheets = pd.read_excel(written[0], sheet_name=None, engine="openpyxl")
    assert list(sheets) == ["Summary", "QoI gates", "Residuals", "Reasons"]
    assert len(sheets["Summary"]) == 2
    assert list(sheets["Summary"]["Data set"]) == ["a", "b"]


def test_ods_writes_one_file_with_four_named_sheets(assessments, tmp_path):
    import pandas as pd

    written = export.write_assessment(assessments, tmp_path / "study.ods", "ods")

    assert len(written) == 1
    sheets = pd.read_excel(written[0], sheet_name=None, engine="odf")
    assert list(sheets) == ["Summary", "QoI gates", "Residuals", "Reasons"]


def test_an_unsupported_format_raises_without_writing_anything(assessments, tmp_path):
    """Fail before writing rather than leaving a partial set on disk."""
    with pytest.raises(ValueError, match="pdf"):
        export.write_assessment(assessments, tmp_path / "study.pdf", "pdf")
    assert list(tmp_path.iterdir()) == []


def test_the_format_argument_wins_over_the_path_suffix(assessments, tmp_path):
    """The window takes the format from the save dialog's selected filter, so
    a mismatched typed extension must not silently change the contents."""
    written = export.write_assessment(assessments, tmp_path / "study.ods", "csv")
    assert [p.name for p in written][0] == "study-summary.csv"


def test_exporting_no_data_sets_still_writes_headers(tmp_path):
    """An empty export is an empty table, not a corrupt file."""
    written = export.write_assessment([], tmp_path / "empty.csv", "csv")
    assert len(written) == 4
    assert written[0].read_text().strip().startswith("Data set,State,Confidence")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_convergence_export.py -q -k "csv or tsv or xlsx or ods or unsupported or format_argument or no_data_sets"
```

Expected: FAIL with `AttributeError: module 'starpost.core.convergence.export' has no attribute 'write_assessment'`.

- [ ] **Step 3: Implement `write_assessment`**

Append to `src/starpost/core/convergence/export.py`:

```python
def write_assessment(assessments: Iterable[ConvergenceAssessment],
                     path: Path | str, fmt: str) -> list[Path]:
    """Write the four tables and return the paths actually written.

    ``fmt`` decides the packaging and the contents, not ``path``'s suffix: the
    window takes it from the save dialog's selected filter, and a mismatched
    typed extension must not silently change what is inside the file.

    xlsx/ods get one file with four sheets. csv/tsv hold one table per file,
    so they get four siblings named from the stem — ``study.csv`` becomes
    ``study-summary.csv``, ``study-qoi-gates.csv``, ``study-residuals.csv``,
    ``study-reasons.csv``. The name given is not itself written; four files
    named as a set read better in a folder than one bare name plus three
    suffixed ones, and the caller reports the real names back to the user.
    """
    fmt = fmt.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported convergence export format: {fmt!r} "
            f"(expected one of {', '.join(sorted(SUPPORTED_FORMATS))})"
        )
    assessments = list(assessments)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt in _SHEET_FORMATS:
        return _write_sheets(assessments, path, fmt)
    return _write_delimited(assessments, path, fmt)


def _write_sheets(assessments: list[ConvergenceAssessment], path: Path,
                  fmt: str) -> list[Path]:
    import pandas as pd

    with pd.ExcelWriter(path, engine=_SHEET_FORMATS[fmt]) as writer:
        for _slug, sheet, builder in TABLES:
            builder(assessments).to_excel(writer, sheet_name=sheet, index=False)
    return [path]


def _write_delimited(assessments: list[ConvergenceAssessment], path: Path,
                     fmt: str) -> list[Path]:
    separator = _DELIMITED_FORMATS[fmt]
    written: list[Path] = []
    for slug, _sheet, builder in TABLES:
        target = path.with_name(f"{path.stem}-{slug}.{fmt}")
        builder(assessments).to_csv(target, sep=separator, index=False)
        written.append(target)
    return written
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_convergence_export.py -q
```

Expected: PASS, 14 tests.

- [ ] **Step 5: Lint**

```bash
.venv/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/starpost/core/convergence/export.py tests/test_convergence_export.py
git commit -m "feat: write a convergence assessment as csv, tsv, xlsx or ods

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The Export button in the Convergence window

**Files:**
- Modify: `src/starpost/gui/views/convergence_dialog.py` — imports (lines 13-44), `_build_left`'s button row (around line 196) and panel layout (around line 205), `_show_placeholder` (around line 382), `_populate_summary`, plus new methods; `_iterative_cell` (around line 570) delegates to `export.iterative_error_text`
- Modify: `tests/test_convergence_gui.py` (append)
- Modify: `CHANGELOG.md`, `docs/convergence-notes.md`

**Interfaces:**
- Consumes: `write_assessment(assessments, path, fmt) -> list[Path]` and `iterative_error_text(monitor) -> str` from Task 1/2.
- Produces: `ConvergenceDialog._export_btn` (a `QPushButton`) and `ConvergenceDialog._on_export()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_convergence_gui.py`:

```python
def test_the_export_button_follows_the_loaded_data_sets(app):
    dlg = open_dialog(store_with())
    assert dlg._export_btn.isEnabled() is False
    dlg.close()

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._export_btn.isEnabled() is True
    dlg.close()


def test_exporting_writes_the_four_tables(app, monkeypatch, tmp_path):
    """The window exports every loaded data set, not just the selected row:
    the summary is a cross-run comparison."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    target = tmp_path / "study.csv"
    monkeypatch.setattr(
        module.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "CSV file (*.csv)")),
    )
    shown: list[str] = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[2])))

    dlg._on_export()

    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["study-qoi-gates.csv", "study-reasons.csv",
                       "study-residuals.csv", "study-summary.csv"]
    # Parse rather than substring-match: a bare "a" appears in almost any CSV.
    import csv as csv_module

    with (tmp_path / "study-summary.csv").open() as fh:
        rows = list(csv_module.DictReader(fh))
    assert [r["Data set"] for r in rows] == ["a", "b"]
    assert shown and "study-summary.csv" in shown[0]
    dlg.close()


def test_every_save_filter_maps_to_a_format_the_writer_supports():
    """The dialog offers four filters and the writer accepts four formats;
    a filter naming a format the writer rejects would fail only at the moment
    the user tried to save."""
    from starpost.core.convergence.export import SUPPORTED_FORMATS
    from starpost.gui.views.convergence_dialog import _EXPORT_FILTERS

    assert set(_EXPORT_FILTERS.values()) == set(SUPPORTED_FORMATS)


def test_a_cancelled_save_dialog_writes_nothing(app, monkeypatch, tmp_path):
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    dlg._on_export()
    assert list(tmp_path.iterdir()) == []
    dlg.close()


def test_an_export_failure_is_reported_rather_than_swallowed(app, monkeypatch,
                                                             tmp_path):
    """Silently failing an export is worse than failing slowly — the user
    would believe they have a record they do not have."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    monkeypatch.setattr(
        module.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "x.csv"), "CSV file (*.csv)")),
    )

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, "write_assessment", boom)
    errors: list[str] = []
    monkeypatch.setattr(module.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: errors.append(a[2])))

    dlg._on_export()

    assert errors and "disk full" in errors[0]
    dlg.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_convergence_gui.py -q -k "export"
```

Expected: FAIL with `AttributeError: 'ConvergenceDialog' object has no attribute '_export_btn'`.

- [ ] **Step 3: Add the imports**

In `src/starpost/gui/views/convergence_dialog.py`, add `QFileDialog` and `QMessageBox` to the `PySide6.QtWidgets` import block in alphabetical order (`QFileDialog` after `QDoubleSpinBox`, `QMessageBox` after `QLabel`):

```python
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
```

```python
    QLabel,
    QMessageBox,
    QPushButton,
```

Then add the export imports next to the existing convergence imports (after the `from starpost.core.convergence.steady import GATE_ITERATIVE` line):

```python
from starpost.core.convergence.export import (
    SUPPORTED_FORMATS,
    iterative_error_text,
    write_assessment,
)
```

Then add the save-dialog filter map as a module-level constant, next to the
other module constants (after `_SPIN_DEBOUNCE_MS`), so a test can check it
against the writer's own list rather than a runtime assertion:

```python
# Save-dialog filters, mapped to the format write_assessment expects. The
# selected filter decides the format — not the typed suffix — so a mismatch
# cannot silently write one format's contents under another's name.
_EXPORT_FILTERS = {
    "CSV file (*.csv)": "csv",
    "Tab-separated file (*.tsv)": "tsv",
    "Excel workbook (*.xlsx)": "xlsx",
    "OpenDocument spreadsheet (*.ods)": "ods",
}
```

`math` and `GATE_ITERATIVE` become unused once `_iterative_cell` delegates in Step 6 — remove both imports then, not now.

- [ ] **Step 4: Add the Export button**

In `_build_left`, immediately before the line `buttons.addStretch(1)`, the bulk-selection row already exists. Add a *separate* row for the export button. Insert this just after the `self._reset_btn.clicked.connect(...)` line and before the `buttons = QHBoxLayout()` line:

```python
        # Export sits with the data-set table it acts on — it writes every
        # loaded data set, not the selected row, because the summary table is
        # a cross-run comparison.
        self._export_btn = QPushButton("Export assessment…")
        self._export_btn.setToolTip(
            "Write the assessment of every loaded data set to a table "
            "(csv, tsv, xlsx or ods)."
        )
        self._export_btn.clicked.connect(self._on_export)

        export_row = QHBoxLayout()
        export_row.addWidget(self._export_btn)
        export_row.addStretch(1)
```

Then in the same method's panel layout, add the row under the Data sets table. Replace:

```python
        box.addWidget(QLabel("Data sets"))
        box.addWidget(self._summary)
        box.addWidget(QLabel("Monitors"))
```

with:

```python
        box.addWidget(QLabel("Data sets"))
        box.addWidget(self._summary)
        box.addLayout(export_row)
        box.addWidget(QLabel("Monitors"))
```

- [ ] **Step 5: Add the export handler and enablement**

Add both methods to the `--- editing ---` section of `convergence_dialog.py`, immediately after `_set_bulk_buttons_enabled`:

```python
    def _set_export_enabled(self, enabled: bool) -> None:
        self._export_btn.setEnabled(enabled)

    def _on_export(self) -> None:
        """Write every loaded data set's assessment to a table.

        Reads the assessments already held — this never re-runs assess(). The
        format comes from the dialog's selected filter rather than the typed
        suffix, so a mismatch cannot silently write one format's contents
        under another's name."""
        if not self._results:
            return
        start = self._settings.default_output_dir or ""
        if start:
            start = str(Path(start) / "convergence-assessment.csv")
        chosen, selected_filter = QFileDialog.getSaveFileName(
            self, "Export convergence assessment", start,
            ";;".join(_EXPORT_FILTERS),
        )
        if not chosen:
            return
        fmt = _EXPORT_FILTERS.get(selected_filter, "csv")
        path = Path(chosen)
        if path.suffix.lower() != f".{fmt}":
            path = path.with_suffix(f".{fmt}")

        assessments = [self._assessments[r.sim_path] for r in self._results
                       if r.sim_path in self._assessments]
        try:
            written = write_assessment(assessments, path, fmt)
        except Exception as exc:      # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(
                self, "Export failed",
                f"Could not write the convergence assessment:\n\n{exc}",
            )
            return
        names = "\n".join(p.name for p in written)
        QMessageBox.information(
            self, "Export complete",
            f"Wrote {len(written)} file(s) to {written[0].parent}:\n\n{names}",
        )
```

Add `from pathlib import Path` to the module's imports (after `import math`, before `from typing import Optional`).

Now drive enablement. In `_show_placeholder`, immediately after the existing `self._set_bulk_buttons_enabled(False)` line, add:

```python
        self._set_export_enabled(False)
```

And at the end of `_populate_summary`'s `try:` block (after the `for row, result in enumerate(self._results):` loop completes, still inside `try`), add:

```python
            self._set_export_enabled(bool(self._results))
```

- [ ] **Step 6: Delegate `_iterative_cell` to the shared rule**

Replace the whole `_iterative_cell` function at the bottom of `convergence_dialog.py` with:

```python
def _iterative_cell(monitor) -> str:
    """The QoI-gates table's 'Iterative error' cell.

    The rule itself lives in core/convergence/export.py so the window and the
    exported table cannot drift apart — see iterative_error_text there for why
    the gate's own value is shown rather than u_iter."""
    return iterative_error_text(monitor)
```

Then remove the now-unused `import math` and the `from starpost.core.convergence.steady import GATE_ITERATIVE` line from the top of the file.

- [ ] **Step 7: Run the GUI tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_convergence_gui.py -q
```

Expected: PASS, 41 tests (36 existing + 5 new).

- [ ] **Step 8: Lint**

```bash
.venv/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 9: Update the docs**

In `CHANGELOG.md`, under `## [Unreleased]` → `### New Features`, add after the "Select all, Clear and Reset to auto" bullet:

```markdown
- **Convergence tool: export the assessment.** An *Export assessment…* button
  under the Data sets table writes every loaded data set's verdict to a table,
  in csv, tsv, xlsx or ods. Four tables come out: a summary row per data set
  (state, confidence, convergence index, binding constraint, flags — plus the
  tolerance and residual-drop the assessment used, so rows produced under
  different settings can't be mistaken for comparable ones), the per-monitor
  QoI gate numbers, residual health per equation, and the full reasons list
  with its suggested actions. A spreadsheet gets the four as named sheets in
  one file; csv and tsv get four files named as a set. Reads the assessment
  already on screen — no STAR-CCM+ re-run and no re-analysis.
```

In `docs/convergence-notes.md` §9 ("Deliberately not implemented"), the bullet currently reads:

```markdown
- **Export of the assessment** and the evidence plot with the trailing window
  shaded.
```

Replace it with:

```markdown
- **The evidence plot** with the trailing window shaded. (Export of the
  assessment itself is now implemented — see `core/convergence/export.py`.)
```

- [ ] **Step 10: Run the full suite**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/run_tests.py
```

Expected: `All files passed.` If `test_main_window.py`, `test_shortcuts.py` or `test_plot_view.py` fail, re-run that file on its own before calling it a regression — those three are known to fail intermittently under the parallel runner and pass per-file.

- [ ] **Step 11: Commit**

```bash
git add src/starpost/gui/views/convergence_dialog.py tests/test_convergence_gui.py CHANGELOG.md docs/convergence-notes.md
git commit -m "feat: export the convergence assessment from the window

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Verification

**Files:** none modified.

**Interfaces:**
- Consumes: the complete implementation from Tasks 1-3.
- Produces: nothing — this is the verification gate.

- [ ] **Step 1: Full suite**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/run_tests.py
```

Expected: `All files passed.` across 41 files (40 plus the new `test_convergence_export.py`).

- [ ] **Step 2: Export real data and inspect it**

The ten real car-aero exports live in `/home/luca/Downloads/temp output/` (user's machine, not in the repo) and load without STAR-CCM+. Export all ten and confirm the tables are populated and correct:

```bash
.venv/bin/python -c "
from pathlib import Path
from starpost.data.portable import read_sim_csv
from starpost.core.convergence import assess
from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.export import write_assessment, summary_frame
from starpost.core.settings import Settings
s = Settings().plot_classification
a = [assess(read_sim_csv(p), ConvergenceConfig(), s)
     for p in sorted(Path('/home/luca/Downloads/temp output').glob('*.csv'))]
out = Path('/tmp/claude-conv-export'); out.mkdir(exist_ok=True)
for fmt in ('csv', 'xlsx', 'ods'):
    w = write_assessment(a, out / f'study.{fmt}', fmt)
    print(fmt, '->', [p.name for p in w], [p.stat().st_size for p in w])
df = summary_frame(a)
print(df[['Data set','State','Confidence','Convergence index',
          'Tolerance (%)','Required residual drop (decades)']].to_string(index=False))
"
```

Expected: ten summary rows whose states match `docs/convergence-notes.md` §3 (one CONVERGED, one SLOW_DRIFT, one CONVERGING, seven STALLED), every file non-empty, and `Tolerance (%)` of 0.1 with a residual drop of 3.0 throughout.

If the directory is missing, say so and skip this step rather than inventing a substitute — do not mark it done.

- [ ] **Step 3: Drive the real window**

Confirm the button renders and works end to end, per `.claude/skills/verify/`:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -c "
import sys, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
import starpost.utils.paths as paths
paths.platformdirs.user_config_dir = lambda *a, **k: str(tmp / 'config')
paths.platformdirs.user_cache_dir = lambda *a, **k: str(tmp / 'cache')
from PySide6.QtWidgets import QApplication
from starpost.core.settings import Settings
from starpost.data.portable import read_sim_csv
from starpost.data.store import ResultStore
import starpost.gui.views.convergence_dialog as cd
from starpost.gui.theme import apply_theme
app = QApplication(sys.argv[:1]); s = Settings()
apply_theme(app, s.appearance.mode, s.appearance.accent,
            s.appearance.resolved_checkmark(), s.appearance.text_scale)
store = ResultStore()
for f in sorted(Path('/home/luca/Downloads/temp output').glob('*.csv'))[:3]:
    store.put(read_sim_csv(f))
dlg = cd.ConvergenceDialog(store, s); dlg.show(); QApplication.processEvents()
print('export button enabled:', dlg._export_btn.isEnabled())
dlg.grab().save('/tmp/claude-conv-export/window.png')
print('screenshot written')
"
```

Expected: `export button enabled: True`, and the screenshot shows the `Export assessment…` button under the Data sets table without disturbing the existing layout. Open the screenshot and confirm.

- [ ] **Step 4: Report**

State plainly: full suite result, the real-data export result (or that it was skipped and why), what the screenshot showed, and anything left undone. Do not claim completion without the command output to back it.
