"""Part Search window: a search bar filters a tree of data sets down to those
containing a matching part, with the matched part names as children."""
import pytest

from starpost.data.models import PropertyGroup, SimProperties, SimResult
from starpost.gui.views.part_search_dialog import PartSearchDialog


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _sim(path: str, *parts: str, error=None) -> SimResult:
    """A SimResult whose parts tree has one composite root per given name."""
    groups = []
    for name in parts:
        groups.append(PropertyGroup(section="part_tree", name=name,
                                    entries=[("type", "SolidModelPart"),
                                             ("leaf_parts", "1")]))
    res = SimResult(sim_path=path, error=error)
    res.properties = SimProperties(groups=groups) if groups else None
    return res


class _Store:
    def __init__(self, results):
        self._results = results

    def all(self):
        return self._results


def _tree_texts(dlg):
    """Top-level texts -> list of child texts, as shown in the tree."""
    out = {}
    root = dlg._tree.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        out[top.text(0)] = [top.child(j).text(0) for j in range(top.childCount())]
    return out


def test_empty_query_shows_all_sims_with_parts(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire", "Rear wing"),
                    _sim("/a/caseB.sim", "Chassis")])
    dlg = PartSearchDialog(store)
    assert set(_tree_texts(dlg)) == {"caseA", "caseB"}
    assert dlg._count.text() == "2 data sets, 3 parts"


def test_typing_filters_to_matching_sims_and_parts(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire", "Rear wing"),
                    _sim("/a/caseB.sim", "Chassis")])
    dlg = PartSearchDialog(store)
    dlg._search.setText("tire")
    texts = _tree_texts(dlg)
    assert texts == {"caseA": ["Front tire"]}
    assert dlg._count.text() == "1 data sets, 1 parts"


def test_sim_without_parts_is_excluded(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire"),
                    _sim("/a/noparts.sim")])
    dlg = PartSearchDialog(store)
    assert set(_tree_texts(dlg)) == {"caseA"}


def test_failed_extraction_is_excluded(app):
    store = _Store([_sim("/a/caseA.sim", "Front tire"),
                    _sim("/a/broken.sim", "Front tire", error="boom")])
    dlg = PartSearchDialog(store)
    assert set(_tree_texts(dlg)) == {"caseA"}


def test_rows_carry_sim_path_for_double_click(app):
    from PySide6.QtCore import Qt

    store = _Store([_sim("/a/caseA.sim", "Front tire")])
    dlg = PartSearchDialog(store)
    top = dlg._tree.invisibleRootItem().child(0)
    child = top.child(0)
    assert top.data(0, Qt.ItemDataRole.UserRole) == "/a/caseA.sim"
    assert child.data(0, Qt.ItemDataRole.UserRole) == "/a/caseA.sim"
