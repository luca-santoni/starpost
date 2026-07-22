import pytest
from PySide6.QtWidgets import QApplication

from starpost.data.models import Report, SimResult
from starpost.gui.views.report_table import ReportTable


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _model_rows(table: ReportTable):
    model = table._table.model()
    cols = model.columnCount()
    return [
        [model.data(model.index(r, c)) for c in range(cols)]
        for r in range(model.rowCount())
    ]


def test_show_single_converts_value_and_unit(app):
    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    table = ReportTable(decimals=4)
    table.set_unit_system("imperial")
    table.show_single(res)
    rows = _model_rows(table)
    # Columns: Report, <value>, Units
    assert rows[0][0] == "Drag"
    assert rows[0][2] == "lbf"
    assert float(rows[0][1]) == pytest.approx(22.4809, abs=1e-3)


def test_show_single_default_is_raw(app):
    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    table = ReportTable(decimals=4)
    table.show_single(res)
    rows = _model_rows(table)
    assert rows[0][2] == "N"
    assert float(rows[0][1]) == pytest.approx(100.0)
