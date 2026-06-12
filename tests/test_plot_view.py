from starpost.data.models import PlotSeries
from starpost.gui.views.plot_view import _series_is_empty


def test_empty_when_all_values_below_threshold():
    s = PlotSeries(name="Tiny", x=[1, 2, 3], y=[1e-9, 0.0, -2e-9])
    assert _series_is_empty(s, 1e-5) is True


def test_not_empty_when_a_value_exceeds_threshold():
    s = PlotSeries(name="Force", x=[1, 2], y=[0.0, 0.5])
    assert _series_is_empty(s, 1e-5) is False


def test_threshold_is_absolute_so_negative_monitors_are_kept():
    # Strongly negative values must NOT be treated as empty.
    s = PlotSeries(name="Downforce", x=[1, 2], y=[-0.5, -0.6])
    assert _series_is_empty(s, 1e-5) is False


def test_negative_values_within_threshold_are_empty():
    s = PlotSeries(name="Noise", x=[1, 2], y=[-1e-7, 5e-8])
    assert _series_is_empty(s, 1e-5) is True


def test_series_with_no_data_is_empty():
    assert _series_is_empty(PlotSeries(name="None", x=[], y=[]), 1e-5) is True
