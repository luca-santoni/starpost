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
               "Tolerance (%, primary monitor)", "Required residual drop (decades)"]
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
            "Tolerance (%, primary monitor)": _tolerance_percent(a),
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


def _tolerance_percent(assessment: ConvergenceAssessment):
    """The QoI tolerance the assessment was produced under, as a percentage.

    ``tolerance_fraction`` is not in ``thresholds_used`` — it is a
    per-monitor field on ``MonitorAssessment`` (``ConvergenceConfig`` allows a
    per-monitor override via ``MonitorConfig``), not one of the global
    thresholds in ``THRESHOLD_PROVENANCE``. There is no single run-level
    tolerance to report, because StarPost lets a monitor's row in the
    Monitors table override the global preset. Read it off the primary
    monitor instead: primary monitors are what gate the verdict, so that is
    the resolved value that actually produced this row's state, index and
    binding constraint. Reporting the global preset would be misleading —
    an override on the primary monitor would make an overridden row look
    comparable to a plain one, which is exactly what this column exists to
    prevent. Fall back to the first monitor if none is marked primary, and
    to None if the assessment has no monitors at all.
    """
    if not assessment.monitors:
        return None
    monitor = next((m for m in assessment.monitors if m.is_primary), assessment.monitors[0])
    return monitor.tolerance_fraction * 100.0


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
