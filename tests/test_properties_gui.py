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
        "General", "Parts", "Mesh", "Regions", "Physics",
    ]
    assert dlg.windowTitle() == "Properties — caseA.sim"


def test_general_tab_keeps_summary_form(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(), size_bytes=2048)
    general = dlg.tabs.widget(0)
    texts = _labels(general)
    assert "File size" in texts and "2.0 KB" in texts
    assert "Iterations" in texts and "2" in texts
    # The old flat count rows are gone; counts now live in the tree headings.
    assert "Reports (1)" in texts
    assert any(t.startswith("Monitors — ") for t in texts)


def test_general_tab_unextracted_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", None)
    texts = _labels(dlg.tabs.widget(0))
    assert any("Open the file to extract" in t for t in texts)
    assert "—" in texts


def test_reports_tree_lists_report_names(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    tree = dlg.tabs.widget(0).reports_tree
    assert tree is not None
    names = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert names == ["Drag"]


def test_monitors_tree_has_plots_with_series_children(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    tree = dlg.tabs.widget(0).monitors_tree
    assert tree is not None and tree.topLevelItemCount() == 1
    plot = tree.topLevelItem(0)
    assert plot.text(0) == "Residuals"
    assert [plot.child(i).text(0) for i in range(plot.childCount())] == ["Continuity"]


def test_monitors_heading_counts_plots_and_series(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result())
    texts = _labels(dlg.tabs.widget(0))
    assert "Monitors — 1 plot, 1 series" in texts


def test_general_tab_unextracted_has_no_trees(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", None)
    general = dlg.tabs.widget(0)
    assert general.reports_tree is None
    assert general.monitors_tree is None


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


def _full_props_result() -> SimResult:
    res = _result(with_parts=False)
    res.properties = SimProperties(groups=[
        PropertyGroup(section="mesh",
                      entries=[("cell_count", "21737167"),
                               ("interior_face_count", "65351479"),
                               ("vertex_count", "23272181")]),
        PropertyGroup(section="mesh_op", name="Automated Mesh",
                      entries=[("type", "AutoMeshOperation"),
                               ("meshers", "Surface Remesher"),
                               ("base_size", "24.0 mm")]),
        PropertyGroup(section="region", name="External flow",
                      entries=[("type", "Fluid Region"),
                               ("continuum", "Physics 1"),
                               ("boundaries", "54"),
                               ("boundary_types", "Wall=43; Symmetry Plane=3")]),
        PropertyGroup(section="interface", entries=[("count", "1")]),
        PropertyGroup(section="interface", name="Fan shroud"),
        PropertyGroup(section="continuum", name="Physics 1",
                      entries=[("models", "Gas; Turbulent"),
                               ("regions", "3")]),
        PropertyGroup(section="solver", name="Coupled Implicit"),
        PropertyGroup(section="criterion", name="Maximum Steps",
                      entries=[("enabled", "true")]),
    ])
    return res


def test_mesh_tab_shows_counts_and_pipeline(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _full_props_result())
    tree = dlg.tabs.widget(2).tree
    assert tree is not None
    assert tree.headerItem().text(0) == "Item"
    assert tree.headerItem().text(1) == "Value"
    top = [(tree.topLevelItem(i).text(0), tree.topLevelItem(i).text(1))
           for i in range(tree.topLevelItemCount())]
    assert top == [
        ("Cells", "21,737,167"),
        ("Interior faces", "65,351,479"),
        ("Vertices", "23,272,181"),
        ("Automated Mesh", "AutoMeshOperation"),
    ]
    op = tree.topLevelItem(3)
    assert op.child(0).text(0) == "Meshers"
    assert op.child(0).child(0).text(0) == "Surface Remesher"
    assert (op.child(1).text(0), op.child(1).text(1)) == (
        "Base size", "24.0 mm",
    )


def test_regions_tab_shows_regions_and_interfaces(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _full_props_result())
    tree = dlg.tabs.widget(3).tree
    region = tree.topLevelItem(0)
    assert (region.text(0), region.text(1)) == ("External flow", "Fluid Region")
    assert (region.child(0).text(0), region.child(0).text(1)) == (
        "Continuum", "Physics 1",
    )
    boundaries = region.child(1)
    assert (boundaries.text(0), boundaries.text(1)) == ("Boundaries", "54")
    assert (boundaries.child(0).text(0), boundaries.child(0).text(1)) == (
        "Wall", "43",
    )
    interfaces = tree.topLevelItem(1)
    assert (interfaces.text(0), interfaces.text(1)) == ("Interfaces", "1")
    assert interfaces.child(0).text(0) == "Fan shroud"


def test_physics_tab_shows_continua_solvers_criteria(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _full_props_result())
    tree = dlg.tabs.widget(4).tree
    continuum = tree.topLevelItem(0)
    assert (continuum.text(0), continuum.text(1)) == ("Physics 1", "3 regions")
    models = continuum.child(0)
    assert (models.text(0), models.text(1)) == ("Models", "2")
    assert models.child(1).text(0) == "Turbulent"
    solvers = tree.topLevelItem(1)
    assert (solvers.text(0), solvers.text(1)) == ("Solvers", "1")
    criteria = tree.topLevelItem(2)
    assert (criteria.child(0).text(0), criteria.child(0).text(1)) == (
        "Maximum Steps", "Enabled",
    )


def test_new_tabs_without_data_show_reextract_note(app, tmp_path):
    dlg = PropertiesDialog(tmp_path / "caseA.sim", _result(with_parts=False))
    for index, what in ((2, "mesh"), (3, "region"), (4, "physics")):
        tab = dlg.tabs.widget(index)
        assert tab.tree is None
        assert any("Re-extract" in t for t in _labels(tab)), what
