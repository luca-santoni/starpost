"""Tabbed Properties dialog: General tab carries the classic summary, the
Parts tab shows the Geometry > Parts tree from extracted sim properties."""
import pytest

from starpost.data.models import (
    MonitorPlot,
    PlotSeries,
    PropertyGroup,
    Report,
    SimProperties,
    SimResult,
)
from starpost.gui.views.properties_dialog import PropertiesDialog


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _result(with_parts: bool = True) -> SimResult:
    res = SimResult(
        sim_path="/cases/caseA.sim",
        reports=[Report(name="Drag", value=12.5, units="N")],
        plots=[MonitorPlot(name="Residuals",
                           series=[PlotSeries(name="Continuity",
                                              x=[1.0, 2.0], y=[0.1, 0.2])])],
    )
    if with_parts:
        res.properties = SimProperties(groups=[
            PropertyGroup(section="part_tree", name="Tires",
                          entries=[("type", "SolidModelCompositePart"),
                                   ("leaf_parts", "2")]),
            PropertyGroup(section="part", name="Front tire",
                          entries=[("type", "SolidModelPart"),
                                   ("path", "Tires|Front tire"),
                                   ("surfaces", "1"), ("curves", "1")]),
        ])
    return res


def _labels(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [lb.text() for lb in widget.findChildren(QLabel)]


def test_dialog_has_general_and_parts_tabs(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
        "General", "Parts",
    ]
    assert dlg.windowTitle() == "Properties — caseA.sim"


def test_general_tab_keeps_classic_summary(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(),
                           size_bytes=2048)
    general = dlg.tabs.widget(0)
    texts = _labels(general)
    assert "File size" in texts and "2.0 KB" in texts
    assert "Reports" in texts and "1" in texts
    assert "Monitors" in texts
    assert "Iterations" in texts and "2" in texts


def test_general_tab_unextracted_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", None)
    texts = _labels(dlg.tabs.widget(0))
    assert any("Open the file to extract" in t for t in texts)
    assert "—" in texts


def test_parts_tab_shows_the_tree(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    parts = dlg.tabs.widget(1)
    tree = parts.tree
    assert tree is not None and tree.topLevelItemCount() == 1
    top = tree.topLevelItem(0)
    assert top.text(0) == "Tires"
    assert top.text(1) == "SolidModelCompositePart"
    assert top.text(2) == "2 parts"
    assert top.childCount() == 1
    leaf = top.child(0)
    assert leaf.text(0) == "Front tire"
    assert leaf.text(2) == "1 surface, 1 curve"


def test_parts_tab_without_data_shows_reextract_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(with_parts=False))
    parts = dlg.tabs.widget(1)
    assert parts.tree is None
    assert any("Re-extract" in t for t in _labels(parts))


def test_intermediate_composite_counts_leaf_descendants(app, tmp_path):
    res = _result(with_parts=False)
    res.properties = SimProperties(groups=[
        PropertyGroup(section="part", name="wing a",
                      entries=[("path", "Assy.Sub one|wing a")]),
        PropertyGroup(section="part", name="wing b",
                      entries=[("path", "Assy.Sub one|wing b")]),
    ])
    dlg = PropertiesDialog(tmp_path / "caseA.sim", res)
    tree = dlg.tabs.widget(1).tree
    assy = tree.topLevelItem(0)
    assert assy.text(0) == "Assy"
    # Both leaves sit inside ONE sub-composite, so Assy has a single direct
    # child but two leaf descendants: counting direct children would say
    # "1 part" — the leaf-descendant count must say "2 parts".
    assert assy.text(2) == "2 parts"
    assert assy.child(0).text(2) == "2 parts"


def test_parts_tab_truncation_row(app, tmp_path):
    res = _result()
    res.properties.groups.append(
        PropertyGroup(section="part", entries=[("truncated", "40")])
    )
    dlg = PropertiesDialog(tmp_path / "caseA.sim", res)
    tree = dlg.tabs.widget(1).tree
    last = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert last.text(0) == "… and 40 more"
