def test_run_report_table_converts_units(tmp_path):
    from starpost.batch.aggregator import reports_long_frame
    from starpost.data.models import Report, SimResult

    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    df = reports_long_frame([res], {"Drag"}, True, "imperial")
    assert "Drag [lbf]" in df["Report"].tolist()


def test_render_saved_plot_accepts_legend_opacity(tmp_path):
    from PySide6.QtWidgets import QApplication
    from starpost.batch.run import render_saved_plot
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

    QApplication.instance() or QApplication([])
    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot("Forces", [PlotSeries("Drag", [1, 2], [10.0, 9.0])],
                           kind=PlotKind.FORCE)],
    )
    out = tmp_path / "p.png"
    ok = render_saved_plot(
        result,
        {"monitors": {"Forces": ["Drag"]}, "legend_opacity": 0.5, "format": "png"},
        None,
        out,
    )
    assert ok is True
    assert out.exists()
