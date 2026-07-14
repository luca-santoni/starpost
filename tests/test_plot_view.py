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


def test_emptiness_scan_is_cached_and_stays_off_the_cache_file():
    """The max-|y| scan runs once per series (its data is immutable once
    extracted) and works across thresholds; the cache attribute must not leak
    into the persisted dataclass dict (the JSON crash-recovery cache)."""
    from dataclasses import asdict

    s = PlotSeries(name="Force", x=[1, 2, 3], y=[0.1, -0.7, 0.3])
    assert _series_is_empty(s, 1e-5) is False
    assert s.max_abs() == 0.7
    # Different thresholds reuse the cached magnitude, not a fresh scan.
    assert _series_is_empty(s, 0.7) is False   # boundary: 0.7 < 0.7 is False
    assert _series_is_empty(s, 0.71) is True
    assert _series_is_empty(s, 0.5) is False
    assert asdict(s) == {"name": "Force", "x": [1, 2, 3], "y": [0.1, -0.7, 0.3]}


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


def test_legend_offset_round_trips_across_sizes(app):
    """The legend position is captured as a fraction of the plot area and restores
    to the same spot at a different render size (so saved plots keep it)."""
    import pyqtgraph as pg
    from PySide6.QtCore import Qt

    from starpost.data.models import MonitorPlot, PlotKind

    def _laid_out(size):
        pv = PlotView()
        pv.set_category_controls_visible(False)
        pv.show_plots([MonitorPlot(
            "G", [PlotSeries("A", [1, 2, 3], [1, 2, 3]),
                  PlotSeries("B", [1, 2, 3], [3, 2, 1])], kind=PlotKind.FORCE,
        )])
        pv.resize(*size)
        pv.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        pv.show()
        for _ in range(3):
            app.processEvents()
        return pv

    src = _laid_out((720, 480))
    rect = src._vb.boundingRect()
    src._legend.autoAnchor(pg.Point(0.6 * rect.width(), 0.3 * rect.height()))
    for _ in range(3):
        app.processEvents()
    frac = src.legend_offset()
    assert frac is not None
    assert abs(frac[0] - 0.6) < 0.02 and abs(frac[1] - 0.3) < 0.02

    dst = _laid_out((1280, 720))  # different size
    dst.set_legend_offset(frac)
    for _ in range(3):
        app.processEvents()
    frac2 = dst.legend_offset()
    assert abs(frac2[0] - frac[0]) < 0.02 and abs(frac2[1] - frac[1]) < 0.02
    src.deleteLater()
    dst.deleteLater()
