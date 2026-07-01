from starpost.batch.aggregator import reports_long_frame, reports_wide_frame
from starpost.data.models import Report, SimResult


def _sim(name, reports):
    return SimResult(
        sim_path=f"/x/{name}.sim",
        reports=[Report(n, v, u) for n, v, u in reports],
    )


def test_wide_frame_units_in_headers_and_one_row_per_sim():
    a = _sim("caseA", [("Drag Force", 12.0, "N"), ("Lift Force", 3.0, "N")])
    b = _sim("caseB", [("Drag Force", 14.0, "N"), ("Lift Force", 4.0, "N")])
    df = reports_wide_frame([a, b])

    assert list(df.index) == ["caseA", "caseB"]
    assert "Drag Force [N]" in df.columns
    assert df.loc["caseA", "Drag Force [N]"] == 12.0


def test_wide_frame_respects_selection():
    a = _sim("caseA", [("Drag Force", 12.0, "N"), ("Lift Force", 3.0, "N")])
    df = reports_wide_frame([a], selected={"Drag Force"})
    assert "Drag Force [N]" in df.columns
    assert "Lift Force [N]" not in df.columns


def test_long_frame_is_vertical_one_row_per_report():
    a = _sim("caseA", [("Drag Force", 12.0, "N"), ("Lift Force", 3.0, "N")])
    b = _sim("caseB", [("Drag Force", 14.0, "N"), ("Lift Force", 4.0, "N")])
    df = reports_long_frame([a, b])

    # A "Report" column of names, then one value column per sim; a row per report.
    assert list(df.columns) == ["Report", "caseA", "caseB"]
    assert list(df["Report"]) == ["Drag Force [N]", "Lift Force [N]"]
    row = df[df["Report"] == "Drag Force [N]"].iloc[0]
    assert row["caseA"] == 12.0 and row["caseB"] == 14.0


def test_long_frame_respects_selection_and_units_toggle():
    a = _sim("caseA", [("Drag Force", 12.0, "N"), ("Lift Force", 3.0, "N")])
    df = reports_long_frame([a], selected={"Drag Force"}, include_units=False)
    assert list(df["Report"]) == ["Drag Force"]  # no units, only the selection
