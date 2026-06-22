import pytest
from PySide6.QtWidgets import QApplication

from starpost.core.settings import Settings
from starpost.data.models import PlotSeries
from starpost.gui.views.export_dialog import ExportDialog
from starpost.gui.views.plot_view import PlotView, _series_is_empty, _y_label_for


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _title_pt(pv: PlotView):
    return pv._plot.getPlotItem().titleLabel.opts.get("size")


def _axis_pt(pv: PlotView, side: str):
    return pv._plot.getAxis(side).labelStyle.get("font-size")


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


# --- Y-axis label (physical quantity from unit + unit) ---------------------
def test_y_label_maps_unit_to_physical_quantity():
    # The unit drives the quantity, not the monitor's own name.
    assert _y_label_for(["Drag ALL Monitor (lbf)"]) == "Force (lbf)"
    assert _y_label_for(["Mass Flow Monitor (kg/s)"]) == "Mass Flow (kg/s)"
    assert _y_label_for(["Static Pressure (Pa)"]) == "Pressure (Pa)"


def test_y_label_same_unit_different_monitors():
    # Distinct monitors sharing a unit still get the unit's quantity.
    assert _y_label_for(["Drag (N)", "Lift (N)"]) == "Force (N)"


def test_y_label_unknown_unit_falls_back_to_unit():
    assert _y_label_for(["Widget Count (widgets)"]) == "widgets"


def test_y_label_generic_when_no_unit_or_mixed_units():
    assert _y_label_for(["Coefficient"]) == "Value"          # dimensionless
    assert _y_label_for(["Force (lbf)", "Mass (kg)"]) == "Value"  # mixed units


# --- title/axis text scaling (Appearance text-size, main UI only) ----------
def test_plot_text_scale_defaults_to_one(app):
    pv = PlotView()
    assert pv._text_scale == 1.0


def test_text_scale_enlarges_title_and_axis_labels(app):
    pv = PlotView()
    pv.set_title_override("Title")
    pv.set_title_size(11.0)
    pv.set_axis_label_size(9.0)
    assert _title_pt(pv) == "11pt"
    assert _axis_pt(pv, "left") == "9pt"
    assert _axis_pt(pv, "bottom") == "9pt"

    pv.set_text_scale(2.0)  # main UI follows the Appearance text-size setting
    assert _title_pt(pv) == "22pt"
    assert _axis_pt(pv, "left") == "18pt"
    assert _axis_pt(pv, "bottom") == "18pt"


def test_export_preview_ignores_text_scale(app):
    """The export dialog's preview must keep its exact point sizes regardless of
    the Appearance text-size setting, so exported images aren't enlarged."""
    dlg = ExportDialog(settings=Settings.from_dict({"appearance": {"text_scale": 2.0}}))
    try:
        assert dlg._preview._text_scale == 1.0
        assert _title_pt(dlg._preview) == "11pt"  # base size, unscaled
    finally:
        dlg.deleteLater()
