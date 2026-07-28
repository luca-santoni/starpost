"""Preconditioning: integrity, restart segmentation, classification, windows."""
import numpy as np
import pytest

from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.models import EquationClass
from starpost.core.convergence.signals import (
    collect_signals,
    equation_class,
    final_segment,
    has_non_finite,
    integrity_error,
    restart_suspected,
    split_segments,
    window_bounds,
)
from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
}


def test_empty_and_too_short_series_are_rejected():
    assert integrity_error(np.array([]), np.array([])) is not None
    assert integrity_error(np.array([0.0]), np.array([1.0])) is not None


def test_a_clean_series_has_no_integrity_error():
    x = np.arange(10, dtype=float)
    assert integrity_error(x, x * 2) is None


def test_mismatched_lengths_are_rejected():
    assert integrity_error(np.arange(5.0), np.arange(4.0)) is not None


def test_non_finite_values_are_detected():
    assert has_non_finite(np.array([1.0, 2.0, np.nan])) is True
    assert has_non_finite(np.array([1.0, np.inf])) is True
    assert has_non_finite(np.array([1.0, 2.0])) is False


def test_a_monotonic_series_is_one_segment():
    x = np.arange(100, dtype=float)
    segments = split_segments(x, x)
    assert len(segments) == 1
    assert segments[0].start == 0


def test_a_restart_resets_the_index_and_starts_a_new_segment():
    """V10: an index reset is the reliable restart signature. Analysis runs on
    the final segment only, and no fit ever spans the boundary."""
    x = np.concatenate([np.arange(500.0), np.arange(500.0)])
    y = np.concatenate([np.full(500, 1.0), np.full(500, 2.0)])
    segments = split_segments(x, y)
    assert len(segments) == 2
    assert segments[1].start == 500
    final, count = final_segment(x, y)
    assert count == 2
    assert final.x.size == 500
    assert final.y[0] == 2.0


def test_a_duplicated_index_also_splits():
    x = np.array([0.0, 1.0, 2.0, 2.0, 3.0, 4.0])
    assert len(split_segments(x, np.arange(6.0))) == 2


def test_restart_suspected_fires_on_a_jump_with_no_index_reset():
    """A residual that leaps by more than kappa in one iteration, on a
    monotonic index, is advisory only — we never segment on it."""
    y = np.concatenate([np.full(100, 1e-6), np.full(100, 1e-3)])
    assert restart_suspected(y, kappa=10.0) is True


def test_restart_suspected_is_quiet_on_a_smooth_decay():
    y = 10.0 ** (-np.arange(200) / 50.0)
    assert restart_suspected(y, kappa=10.0) is False


def test_restart_suspected_requires_the_jump_to_persist():
    """R3: a single-sample spike that returns to baseline right after is not a
    restart -- a turbulence residual spikes by nature (the real data set that
    exposed this had one 31x Sdr spike with no restart at all). A restart
    shifts the level; a spike returns."""
    y = np.full(100, 1e-3)
    y[50] = 1e-3 * 31.0
    assert restart_suspected(y, kappa=10.0) is False


def test_restart_suspected_fires_on_a_sustained_level_shift():
    """The same jump, but the level actually stays up: a genuine restart."""
    y = np.concatenate([np.full(50, 1e-3), np.full(50, 1e-3 * 31.0)])
    assert restart_suspected(y, kappa=10.0) is True


def test_restart_suspected_ignores_non_positive_values():
    """QoI signals cross zero; the log-ratio test only applies to positive
    residual-like data and must not raise on the rest."""
    assert restart_suspected(np.array([1.0, 0.0, -1.0, 2.0]), kappa=10.0) is False


def test_window_is_the_larger_of_the_floor_and_the_record_fraction():
    c = ConvergenceConfig()   # window_min 200, window_fraction 0.2
    start, end, adequate = window_bounds(5000, c)
    assert end == 5000
    assert end - start == 1000          # 0.2 * 5000 beats the 200 floor
    assert adequate is True
    start, end, adequate = window_bounds(600, c)
    assert end - start == 200           # the floor wins
    assert adequate is True


def test_a_short_record_yields_an_inadequate_window():
    """Gate 5 is what stops a short flat stretch inside a long slow oscillation
    reading as convergence, so a record below the floor is flagged."""
    start, end, adequate = window_bounds(120, ConvergenceConfig())
    assert (start, end) == (0, 120)
    assert adequate is False


def test_window_requires_twenty_decorrelation_lengths():
    """N_W >= 20 * D_N, i.e. at least ~20 independent samples."""
    c = ConvergenceConfig()
    _, _, adequate = window_bounds(1000, c, d_n=5.0)     # needs 100, has 200
    assert adequate is True
    _, _, adequate = window_bounds(1000, c, d_n=40.0)    # needs 800, has 200
    assert adequate is False


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Continuity", EquationClass.PRIMARY),
        ("X-momentum", EquationClass.PRIMARY),
        ("Energy", EquationClass.PRIMARY),
        ("Tke", EquationClass.TURBULENCE),
        ("Tdr", EquationClass.TURBULENCE),
        ("Sdr", EquationClass.TURBULENCE),
        ("Turbulent Kinetic Energy", EquationClass.TURBULENCE),
        ("Specific Dissipation Rate", EquationClass.TURBULENCE),
        ("Something Unrecognised", EquationClass.PRIMARY),
    ],
)
def test_equation_class_keywords(name, expected):
    """Unrecognised equations default to primary, which is the conservative
    direction: a turbulence classification weakens the gate."""
    assert equation_class(name) is expected


def test_collect_signals_splits_residuals_from_qois():
    """Residual plots contribute one signal per series (one per equation);
    every other monitor is a QoI candidate."""
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[
            MonitorPlot(
                name="Residuals", kind=PlotKind.RESIDUAL,
                series=[
                    PlotSeries(name="Continuity", x=[0.0, 1.0], y=[1.0, 0.1]),
                    PlotSeries(name="Tke", x=[0.0, 1.0], y=[1.0, 0.5]),
                ],
            ),
            MonitorPlot(
                name="Drag Monitor Plot", kind=PlotKind.FORCE,
                series=[PlotSeries(name="Drag", x=[0.0, 1.0], y=[2.0, 2.1])],
            ),
        ],
    )
    residuals, qois = collect_signals(result, CLASSIFICATION)
    assert [s.name for s in residuals] == ["Continuity", "Tke"]
    assert [s.name for s in qois] == ["Drag"]
    assert qois[0].plot == "Drag Monitor Plot"
    assert isinstance(qois[0].y, np.ndarray)


def test_collect_signals_reclassifies_by_keyword_when_kind_is_unset():
    """Cached results predating the classification settings carry kind=OTHER;
    fall back to the same keyword rule the parser uses."""
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[MonitorPlot(
            name="Residuals", kind=PlotKind.OTHER,
            series=[PlotSeries(name="Continuity", x=[0.0, 1.0], y=[1.0, 0.1])],
        )],
    )
    residuals, qois = collect_signals(result, CLASSIFICATION)
    assert [s.name for s in residuals] == ["Continuity"]
    assert qois == []


def test_collect_signals_skips_empty_series():
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[MonitorPlot(
            name="Drag Monitor Plot", kind=PlotKind.FORCE,
            series=[PlotSeries(name="Drag", x=[], y=[])],
        )],
    )
    assert collect_signals(result, CLASSIFICATION) == ([], [])


def test_single_series_residual_plot_uses_the_plot_name_when_series_is_unnamed():
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[MonitorPlot(
            name="Continuity Residual", kind=PlotKind.RESIDUAL,
            series=[PlotSeries(name="", x=[0.0, 1.0], y=[1.0, 0.1])],
        )],
    )
    residuals, _ = collect_signals(result, CLASSIFICATION)
    assert residuals[0].name == "Continuity Residual"
