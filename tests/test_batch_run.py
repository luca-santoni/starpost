def test_run_report_table_converts_units(tmp_path):
    from starpost.batch.aggregator import reports_long_frame
    from starpost.data.models import Report, SimResult

    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    df = reports_long_frame([res], {"Drag"}, True, "imperial")
    assert "Drag [lbf]" in df["Report"].tolist()
