from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    Report,
    SimProperties,
    SimResult,
)
from starpost.data.portable import read_sim_csv, write_sim_csv


def _sample() -> SimResult:
    return SimResult(
        sim_path="/cases/caseA.sim",
        extracted_at="2026-06-16T12:00:00+00:00",
        reports=[
            Report(name="Drag Force", value=12.5, units="N"),
            Report(name="Bad", value=None, units="", error="extraction failed"),
        ],
        plots=[
            MonitorPlot(
                name="Residuals",
                kind=PlotKind.RESIDUAL,
                y_log=True,
                series=[
                    PlotSeries(name="Continuity", x=[1.0, 2.0], y=[0.1, 0.01]),
                    PlotSeries(name="X-momentum", x=[1.0, 2.0], y=[0.2, 0.02]),
                ],
            ),
        ],
    )


def test_round_trip_preserves_full_model(tmp_path):
    original = _sample()
    path = tmp_path / "caseA.csv"
    write_sim_csv(original, path)

    loaded = read_sim_csv(path)

    assert loaded.sim_path == original.sim_path
    assert loaded.sim_name == "caseA"
    assert loaded.extracted_at == original.extracted_at
    assert loaded.error is None

    assert {r.name for r in loaded.reports} == {"Drag Force", "Bad"}
    drag = next(r for r in loaded.reports if r.name == "Drag Force")
    assert drag.value == 12.5 and drag.units == "N"
    bad = next(r for r in loaded.reports if r.name == "Bad")
    assert bad.value is None and bad.error == "extraction failed"

    assert len(loaded.plots) == 1
    plot = loaded.plots[0]
    assert plot.name == "Residuals" and plot.kind == PlotKind.RESIDUAL
    assert plot.y_log is True and plot.x_label == "Iteration"
    cont = next(s for s in plot.series if s.name == "Continuity")
    assert cont.x == [1.0, 2.0] and cont.y == [0.1, 0.01]


def test_round_trip_empty_series_and_sim_error(tmp_path):
    result = SimResult(
        sim_path="/cases/empty.sim",
        plots=[MonitorPlot(name="Forces", series=[PlotSeries(name="Lift")])],
        error=None,
    )
    path = tmp_path / "empty.csv"
    write_sim_csv(result, path)

    loaded = read_sim_csv(path)
    assert len(loaded.plots) == 1
    assert loaded.plots[0].series[0].name == "Lift"
    assert loaded.plots[0].series[0].x == [] and loaded.plots[0].series[0].y == []


def test_rejects_foreign_csv(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("sim,Drag\ncaseA,12.5\n", encoding="utf-8")
    try:
        read_sim_csv(path)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a non-StarPost CSV")


def test_round_trip_properties(tmp_path):
    result = _sample()
    result.properties = SimProperties(groups=[
        PropertyGroup(section="sim", entries=[("units_system", "SI")]),
        PropertyGroup(
            section="region", name="Fluid",
            entries=[("boundaries", "46"),
                     ("boundary_types", "Velocity Inlet=1; Wall=44")],
        ),
        PropertyGroup(section="tag", name="baseline"),
    ])
    path = tmp_path / "caseA.csv"
    write_sim_csv(result, path)

    assert path.read_text(encoding="utf-8").startswith("starpost-data,3")

    loaded = read_sim_csv(path)
    props = loaded.properties
    assert props.get("sim").get("units_system") == "SI"
    assert (props.get("region", "Fluid").get("boundary_types")
            == "Velocity Inlet=1; Wall=44")
    # An entry-less group (a tag) survives the round trip.
    assert props.get("tag", "baseline").entries == []
    # Reports and plots are untouched by the new rows.
    assert {r.name for r in loaded.reports} == {"Drag Force", "Bad"}
    assert loaded.plots[0].series[0].y == [0.1, 0.01]


def test_round_trip_without_properties_stays_none(tmp_path):
    path = tmp_path / "caseA.csv"
    write_sim_csv(_sample(), path)
    assert read_sim_csv(path).properties is None


def test_v2_file_still_imports(tmp_path):
    # Files exported by older StarPost (format v2) must keep importing.
    path = tmp_path / "old.csv"
    path.write_text(
        "starpost-data,2\n"
        "meta,sim_path,/cases/caseA.sim\n"
        "meta,extracted_at,2026-06-16T12:00:00+00:00\n"
        "report,Drag Force,12.5,N,\n"
        "plot,Residuals,residual,Iteration,true,\n"
        "head,Iteration,Continuity\n"
        "1,0.1\n"
        "2,0.01\n",
        encoding="utf-8",
    )
    loaded = read_sim_csv(path)
    assert loaded.sim_path == "/cases/caseA.sim"
    assert loaded.reports[0].value == 12.5
    assert loaded.plots[0].series[0].y == [0.1, 0.01]
    assert loaded.properties is None


def test_rejects_unsupported_version(tmp_path):
    path = tmp_path / "future.csv"
    path.write_text("starpost-data,4\n", encoding="utf-8")
    try:
        read_sim_csv(path)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unsupported version")
