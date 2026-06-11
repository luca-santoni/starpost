from starpost.core.result_parser import classify_plot, parse_sim_output
from starpost.data.models import PlotKind

CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
}


def test_classify_residual_is_log():
    kind, y_log = classify_plot("Residuals", CLASSIFICATION)
    assert kind == PlotKind.RESIDUAL and y_log is True


def test_classify_force_is_linear():
    kind, y_log = classify_plot("Drag Force Monitor", CLASSIFICATION)
    assert kind == PlotKind.FORCE and y_log is False


def test_parse_sim_output(tmp_path):
    sim = tmp_path / "caseA.sim"
    (tmp_path / "caseA_reports.csv").write_text(
        "sim_file,report,value,units\ncaseA,Drag Force,12.5,N\ncaseA,Bad,ERROR,\n"
    )
    (tmp_path / "caseA__plots_index.csv").write_text(
        "plot,csv_file\nResiduals,caseA__plot__Residuals.csv\n"
    )
    (tmp_path / "caseA__plot__Residuals.csv").write_text(
        "Iteration,Continuity,X-momentum\n1,0.1,0.2\n2,0.01,0.02\n"
    )

    res = parse_sim_output(str(sim), tmp_path, CLASSIFICATION)

    assert {r.name for r in res.reports} == {"Drag Force", "Bad"}
    drag = next(r for r in res.reports if r.name == "Drag Force")
    assert drag.value == 12.5
    bad = next(r for r in res.reports if r.name == "Bad")
    assert bad.value is None and bad.error

    assert len(res.plots) == 1
    plot = res.plots[0]
    assert plot.name == "Residuals" and plot.y_log is True
    assert {s.name for s in plot.series} == {"Continuity", "X-momentum"}
    cont = next(s for s in plot.series if s.name == "Continuity")
    assert cont.x == [1.0, 2.0] and cont.y == [0.1, 0.01]
