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
    assert frame.loc[0, "Tolerance (%, primary monitor)"] == pytest.approx(0.1)
    assert frame.loc[0, "Required residual drop (decades)"] == pytest.approx(3.0)

    strict = assess(_result("/tmp/a.sim"),
                    ConvergenceConfig(tolerance_fraction=5e-4, d_min=4.0),
                    CLASSIFICATION)
    other = export.summary_frame([strict])
    assert other.loc[0, "Tolerance (%, primary monitor)"] == pytest.approx(0.05)
    assert other.loc[0, "Required residual drop (decades)"] == pytest.approx(4.0)


def test_the_summary_tolerance_follows_the_primary_monitor_override():
    """The tolerance StarPost applies is per-monitor: the Monitors table's
    Tolerance cell overrides the global preset. The summary reports the
    primary monitor's resolved value because that is the number that produced
    this row's verdict — reporting the global preset would let an overridden
    row look comparable to a non-overridden one, which is the exact confusion
    this column exists to prevent."""
    from starpost.core.convergence.config import MonitorConfig

    config = ConvergenceConfig(
        tolerance_fraction=1e-3,
        monitors={"Drag": MonitorConfig(is_primary=True, tolerance_fraction=5e-4)},
    )
    a = assess(_result("/tmp/a.sim"), config, CLASSIFICATION)
    frame = export.summary_frame([a])
    # 0.05%, the override that judged the primary monitor -- not the 0.1%
    # global preset it superseded.
    assert frame.loc[0, "Tolerance (%, primary monitor)"] == pytest.approx(0.05)


def test_the_summary_tolerance_is_blank_when_there_are_no_monitors():
    """An assessment with no QoI monitors has no tolerance to report, and must
    say so rather than inventing one."""
    a = assess(_result("/tmp/a.sim"), ConvergenceConfig(), CLASSIFICATION)
    a.monitors = []
    frame = export.summary_frame([a])
    assert frame.loc[0, "Tolerance (%, primary monitor)"] is None


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
