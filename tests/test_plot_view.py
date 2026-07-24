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


def test_export_line_width_scales_with_resolution(app, tmp_path):
    """export() captures the plot at scale× device-pixel-ratio; the curves must
    thicken with it. pyqtgraph draws them with cosmetic pens, which paint at a
    fixed device-pixel width regardless of the image's ratio — left alone, an
    exported line comes out scale× thinner than the on-screen preview."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    from starpost.data.models import MonitorPlot, PlotKind

    pv = PlotView()
    pv.set_category_controls_visible(False)
    pv.set_monitor_selection({"G": ["A"]}, render=False)
    # A constant series: a flat horizontal line whose pixel thickness is easy
    # to measure in a vertical slice.
    pv.show_plots([MonitorPlot(
        "G", [PlotSeries("A", list(range(50)), [20.0] * 50)], kind=PlotKind.FORCE,
    )])
    pv.resize(720, 480)
    pv.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    pv.show()
    for _ in range(3):
        app.processEvents()

    def curve_thickness(path) -> int:
        """Median (over three columns) of the longest vertical run of
        curve-coloured pixels — the curve is the only saturated colour; the
        grid, text and background are all grey/white."""
        img = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB888)
        runs = []
        for fx in (0.35, 0.5, 0.65):
            x = int(img.width() * fx)
            best = cur = 0
            for y in range(img.height()):
                c = img.pixelColor(x, y)
                channels = (c.red(), c.green(), c.blue())
                if max(channels) - min(channels) > 60:
                    cur += 1
                    best = max(best, cur)
                else:
                    cur = 0
            runs.append(best)
        return sorted(runs)[1]

    pv.export(tmp_path / "at1.png", "png", scale=1.0)
    pv.export(tmp_path / "at3.png", "png", scale=3.0)
    t1 = curve_thickness(tmp_path / "at1.png")
    t3 = curve_thickness(tmp_path / "at3.png")
    assert t1 >= 1
    # 3× the resolution → ~3× the pixels of line. Antialiasing skews the
    # measured core a pixel or two either way (the 1.5px line at 1× reads ~1px;
    # the 4.5px line at 3× reads ~5px), hence the slack around the 3× target.
    assert 2.2 * t1 <= t3 <= 3 * t1 + 3
    pv.deleteLater()


def test_export_text_has_no_subpixel_fringing(app, tmp_path):
    """Exported text must use grayscale antialiasing. Rendering the plot via
    QWidget.render bakes the screen's RGB-subpixel hinting into the image —
    colour fringes on every glyph that read as blur once the image is viewed
    at any other scale."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    from starpost.data.models import MonitorPlot, PlotKind

    pv = PlotView()
    pv.set_category_controls_visible(False)
    pv.set_monitor_selection({"G": ["A"]}, render=False)
    pv.show_plots([MonitorPlot(
        "G", [PlotSeries("A", list(range(50)), [20.0] * 50)], kind=PlotKind.FORCE,
    )])
    pv.resize(720, 480)
    pv.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    pv.show()
    for _ in range(3):
        app.processEvents()

    pv.export(tmp_path / "out.png", "png", scale=3.0)
    img = QImage(str(tmp_path / "out.png")).convertToFormat(
        QImage.Format.Format_RGB888
    )
    # The left margin (tick labels) and title strip hold only text and grey
    # chrome — any strongly colour-imbalanced pixel there is subpixel fringing.
    fringes = 0
    regions = (
        (0, 100, 100, img.height() - 200),   # y-axis tick labels
        (img.width() // 3, 0, img.width() // 3, 80),  # title strip
    )
    for rx, ry, rw, rh in regions:
        for y in range(ry, ry + rh):
            for x in range(rx, rx + rw):
                c = img.pixelColor(x, y)
                ch = (c.red(), c.green(), c.blue())
                if max(ch) - min(ch) > 12:
                    fringes += 1
    assert fringes == 0
    pv.deleteLater()


def test_export_scales_curve_pens_only(app):
    """The export widens the curves' cosmetic pens but leaves the axis pens
    (which also draw the grid and ticks) alone — the exported grid stays
    hairline-subtle rather than thickening with the resolution."""
    from PySide6.QtCore import Qt

    from starpost.data.models import MonitorPlot, PlotKind

    pv = PlotView()
    pv.set_category_controls_visible(False)
    pv.set_monitor_selection({"G": ["A"]}, render=False)
    pv.show_plots([MonitorPlot(
        "G", [PlotSeries("A", [1, 2, 3], [1.0, 2.0, 3.0])], kind=PlotKind.FORCE,
    )])
    pv.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    pv.show()
    app.processEvents()

    curve = next(
        it for it in pv._plot.listDataItems()
        if it.opts.get("pen") is not None and it.opts["pen"].widthF() == 1.5
    )
    axis_widths = {
        name: pv._plot.getAxis(name).pen().widthF()
        for name in ("left", "bottom", "right", "top")
    }
    restore = pv._scale_curve_pens(3.0)
    assert curve.opts["pen"].widthF() == pytest.approx(4.5)
    for name, width in axis_widths.items():
        assert pv._plot.getAxis(name).pen().widthF() == width
    restore()
    assert curve.opts["pen"].widthF() == pytest.approx(1.5)
    pv.deleteLater()


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


def test_y_label_reflects_converted_unit():
    names = ["Drag (N)"]
    assert _y_label_for(names) == "Force (N)"
    assert _y_label_for(names, "imperial") == "Force (lbf)"


def test_set_unit_system_converts_drawn_y_values(app):
    from starpost.data.models import MonitorPlot, PlotSeries

    pv = PlotView()
    plot = MonitorPlot(
        name="Drag", series=[PlotSeries(name="Drag (N)", x=[1, 2], y=[100.0, 200.0])]
    )
    # Series start deselected until picked (see "Don't auto-plot monitors");
    # pre-select this one so show_plots actually draws a curve to inspect.
    pv.set_monitor_selection({"Drag": ["Drag (N)"]}, render=False)
    pv.set_unit_system("imperial")
    pv.show_plots([plot])
    # The recorded (drawn) curve holds converted y-values.
    ys = list(pv._curves[-1]["y"])
    assert ys[0] == pytest.approx(22.4808943, rel=1e-6)
    assert ys[1] == pytest.approx(44.9617886, rel=1e-6)


# --- legend opacity (background brush alpha) --------------------------------
def test_default_legend_opacity_is_mostly_opaque(app):
    # Default models STAR-CCM+'s legend: a mostly-opaque box that hides the
    # grid behind it. This is also the render-time fallback for old saved
    # plots with no captured legend_opacity.
    pv = PlotView()
    assert pv._legend_opacity == 0.8
    assert pv._legend.brush().color().alpha() == round(0.8 * 255)  # 204


def test_set_legend_opacity_sets_brush_alpha(app):
    pv = PlotView()
    pv.set_legend_opacity(0.2)
    assert pv._legend.brush().color().alpha() == 51  # round(0.2 * 255)
    pv.set_legend_opacity(1.0)
    assert pv._legend.brush().color().alpha() == 255


def test_set_legend_opacity_clamps(app):
    pv = PlotView()
    pv.set_legend_opacity(5.0)
    assert pv._legend.brush().color().alpha() == 255
    pv.set_legend_opacity(-1.0)
    assert pv._legend.brush().color().alpha() == 0


def test_apply_theme_preserves_opacity_and_retints_box(app):
    pv = PlotView()
    pv.set_legend_opacity(0.4)
    pv.apply_theme("light")
    c = pv._legend.brush().color()
    assert c.alpha() == round(0.4 * 255)
    assert (c.red(), c.green(), c.blue()) == (255, 255, 255)  # light bg
    pv.apply_theme("dark")
    c = pv._legend.brush().color()
    assert c.alpha() == round(0.4 * 255)
    assert (c.red(), c.green(), c.blue()) == (30, 30, 30)  # dark bg #1e1e1e


def test_legend_has_visible_border_tracking_theme(app):
    from PySide6.QtCore import Qt

    pv = PlotView()
    # A faint box must still show a clear perimeter, so the border stays fully
    # opaque regardless of the fill opacity and follows the theme foreground.
    pv.set_legend_opacity(0.0)
    pv.apply_theme("light")
    pen = pv._legend.pen()
    assert pen.style() != Qt.PenStyle.NoPen  # a border is drawn
    assert pen.color().alpha() == 255  # edge stays visible even at 0 fill
    assert (pen.color().red(), pen.color().green(), pen.color().blue()) == (31, 31, 31)
    pv.apply_theme("dark")
    c = pv._legend.pen().color()
    assert (c.red(), c.green(), c.blue()) == (230, 230, 230)  # dark fg #e6e6e6
