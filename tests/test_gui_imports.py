"""Import-smoke tests for the GUI view modules.

These catch import-time breakage — e.g. a dialog importing a name that another
module has removed — without needing a running QApplication. (StarPost 1.4.0
shipped with export_dialog importing a class that the rewritten data_list no
longer defined; this guards against that class of regression.)
"""
import importlib

import pytest

_MODULES = [
    "starpost.gui.views.data_list",
    "starpost.gui.views.export_dialog",
    "starpost.gui.views.data_export_dialog",
    "starpost.gui.views.selection_panel",
    "starpost.gui.views.file_list",
    "starpost.gui.views.plot_view",
    "starpost.gui.views.report_table",
    "starpost.gui.views.settings_dialog",
    "starpost.gui.views.properties_dialog",
    "starpost.gui.main_window",
]


@pytest.mark.parametrize("module", _MODULES)
def test_view_module_imports(module):
    """Importing each GUI module resolves all of its top-level imports."""
    assert importlib.import_module(module) is not None


def test_export_dialogs_share_checklist():
    """The export dialogs depend on data_list._CheckList; keep that link intact."""
    from starpost.gui.views import data_export_dialog, export_dialog
    from starpost.gui.views.data_list import _CheckList

    assert export_dialog._CheckList is _CheckList
    assert data_export_dialog._CheckList is _CheckList
