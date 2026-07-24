"""'Properties' window for a .sim file / data set: a General tab with its size
on disk and, once extracted, its report/monitor/iteration counts, a Parts tab
showing the sim's Geometry > Parts tree, and Mesh / Regions / Physics tabs
listing the mesh pipeline, regions/boundaries/interfaces and physics setup
(all read from the extracted sim properties).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.data.parts_tree import PartNode, build_parts_tree
from starpost.data.prop_rows import (
    Row,
    build_mesh_rows,
    build_physics_rows,
    build_region_rows,
)


def _human_size(num_bytes: int) -> str:
    """Bytes as a short human-readable size (e.g. "14.4 MB")."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class PropertiesDialog(QDialog):
    def __init__(
        self, path: Path | str, result=None, parent=None, size_bytes: int | None = None
    ) -> None:
        super().__init__(parent)
        path = Path(path)
        self.setWindowTitle(f"Properties — {path.name}")

        self.tabs = QTabWidget()
        self.tabs.addTab(_GeneralTab(path, result, size_bytes), "General")
        self.tabs.addTab(_PartsTab(result), "Parts")
        props = result.properties if result is not None else None
        self.tabs.addTab(_RowsTab(build_mesh_rows(props), "mesh"), "Mesh")
        self.tabs.addTab(_RowsTab(build_region_rows(props), "region"), "Regions")
        self.tabs.addTab(_RowsTab(build_physics_rows(props), "physics"), "Physics")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Roomier than the old single-form window: the parts tree needs it.
        self.resize(520, 400)


def _count_phrase(n: int, noun: str) -> str:
    """`"1 plot"` / `"3 plots"` — singular noun for exactly one. Nouns already
    ending in "s" (e.g. "series") are left unpluralized."""
    if n == 1 or noun.endswith("s"):
        return f"{n} {noun}"
    return f"{n} {noun}s"


class _GeneralTab(QWidget):
    """The summary tab: File size and Iterations as a small form, plus a
    Reports tree (names) and a Monitors tree (plot ▸ series). ``reports_tree``
    and ``monitors_tree`` are None until the file has been extracted."""

    def __init__(self, path: Path, result, size_bytes: int | None, parent=None) -> None:
        super().__init__(parent)
        self.reports_tree = None
        self.monitors_tree = None

        # When size_bytes is given (e.g. the Data tab passes the data set's
        # portable-CSV size), use it; otherwise measure the file on disk.
        if size_bytes is not None:
            size = _human_size(size_bytes)
        else:
            try:
                size = _human_size(path.stat().st_size)
            except OSError:  # file moved/deleted/unreadable
                size = "—"

        # Reports/monitors/iterations only exist once the file is extracted.
        # Iterations is the longest series' length.
        extracted = result is not None and result.error is None
        iterations = (
            str(max((len(s.x) for p in result.plots for s in p.series), default=0))
            if extracted
            else "—"
        )

        form = QFormLayout()
        form.addRow("File size", QLabel(size))
        form.addRow("Iterations", QLabel(iterations))

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        if not extracted:
            note = QLabel("Open the file to extract its reports and monitors.")
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return

        # Reports section: a heading with the count, then a names-only tree.
        layout.addWidget(QLabel(f"Reports ({len(result.reports)})"))
        self.reports_tree = _name_tree()
        for report in result.reports:
            self.reports_tree.addTopLevelItem(QTreeWidgetItem([report.name]))
        layout.addWidget(self.reports_tree)

        # Monitors section: heading counts plots and series; tree is plot ▸ series.
        series_total = sum(len(p.series) for p in result.plots)
        heading = (
            f"Monitors — {_count_phrase(len(result.plots), 'plot')}, "
            f"{_count_phrase(series_total, 'series')}"
        )
        layout.addWidget(QLabel(heading))
        self.monitors_tree = _name_tree()
        for plot in result.plots:
            plot_item = QTreeWidgetItem([plot.name])
            for s in plot.series:
                plot_item.addChild(QTreeWidgetItem([s.name]))
            self.monitors_tree.addTopLevelItem(plot_item)
        layout.addWidget(self.monitors_tree)


def _name_tree() -> QTreeWidget:
    """A single-column, header-hidden, alternating-row tree for name lists —
    the shared look of the General tab's Reports and Monitors trees."""
    tree = QTreeWidget()
    tree.setColumnCount(1)
    tree.setHeaderHidden(True)
    tree.setAlternatingRowColors(True)
    return tree


class _PartsTab(QWidget):
    """The sim's Geometry > Parts tree, or a re-extract hint when the data
    set predates parts extraction. ``self.tree`` is None in the hint case."""

    def __init__(self, result=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        props = result.properties if result is not None else None
        parts = build_parts_tree(props)
        if parts.empty:
            self.tree = None
            note = QLabel(
                "No parts data for this data set. Re-extract the .sim with "
                "this StarPost version to capture its Geometry ▸ Parts tree."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return

        tree = QTreeWidget()
        tree.setHeaderLabels(["Name", "Type", "Contents"])
        tree.setColumnWidth(0, 240)
        tree.setAlternatingRowColors(True)
        for node in parts.roots:
            tree.addTopLevelItem(_part_item(node))
        if parts.truncated:
            tree.addTopLevelItem(
                QTreeWidgetItem([f"… and {parts.truncated} more", "", ""])
            )
        layout.addWidget(tree)
        self.tree = tree


def _part_item(node: PartNode) -> QTreeWidgetItem:
    item = QTreeWidgetItem([node.name, node.type, _contents(node)])
    for child in node.children:
        item.addChild(_part_item(child))
    return item


class _RowsTab(QWidget):
    """A generic Item/Value tree tab fed by prop_rows builders, with the same
    re-extract hint as the Parts tab when there is no data for it.
    ``self.tree`` is None in the hint case."""

    def __init__(self, rows: list[Row], what: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        if not rows:
            self.tree = None
            note = QLabel(
                f"No {what} data for this data set. Re-extract the .sim with "
                "this StarPost version to capture it."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return
        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Value"])
        tree.setColumnWidth(0, 240)
        tree.setAlternatingRowColors(True)
        for row in rows:
            tree.addTopLevelItem(_row_item(row))
        layout.addWidget(tree)
        self.tree = tree


def _row_item(row: Row) -> QTreeWidgetItem:
    item = QTreeWidgetItem([row.label, row.value])
    for child in row.children:
        item.addChild(_row_item(child))
    return item


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _leaf_total(node: PartNode) -> int:
    """Recursive leaf-descendant count for a composite built from paths
    (no leaf_count of its own): a childless node counts as one leaf."""
    if not node.children:
        return 1
    return sum(_leaf_total(c) for c in node.children)


def _contents(node: PartNode) -> str:
    """The Contents cell: leaf-part count for composites, surface/curve
    counts for leaf parts."""
    if node.children or (node.leaf_count is not None and not node.surfaces):
        count = node.leaf_count
        if count is None:
            count = sum(_leaf_total(c) for c in node.children)
        return _plural(count, "part")
    bits = []
    if node.surfaces.isdigit():
        bits.append(_plural(int(node.surfaces), "surface"))
    if node.curves.isdigit():
        bits.append(_plural(int(node.curves), "curve"))
    return ", ".join(bits)


class ScenePropertiesDialog(QDialog):
    """Properties for a rendered scene still: its file details (size, resolution,
    format) plus the sim, data set, scene and displayers it came from."""

    def __init__(self, artifact, parent=None, source_label: str = "Report group") -> None:
        super().__init__(parent)
        path = Path(artifact.path) if artifact.path else None
        title = artifact.name or (path.name if path else "Scene")
        self.setWindowTitle(f"Properties — {title}")

        # File details, read from the image on disk.
        fmt = path.suffix.lstrip(".").upper() if path and path.suffix else "—"
        if path and path.exists():
            size = _human_size(path.stat().st_size)
            dims = QImageReader(str(path)).size()
            resolution = (
                f"{dims.width()} × {dims.height()}" if dims.isValid() else "—"
            )
        else:
            size = resolution = "—"

        # Provenance.
        sim_file = Path(artifact.sim_path).name if artifact.sim_path else "—"
        data_set = Path(artifact.sim_path).stem if artifact.sim_path else "—"
        scene = artifact.source or "—"
        displayers = artifact.displayers or "—"
        view = artifact.view or "—"  # "—" == rendered from the scene's current view

        form = QFormLayout()
        form.setHorizontalSpacing(24)  # a little more gap between names and values
        form.addRow("File size:", QLabel(size))
        form.addRow("Image resolution:", QLabel(resolution))
        form.addRow("File format:", QLabel(fmt))
        # A thin dark-gray bar, not the default sunken HLine.
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background: #3c3c3c; border: none;")
        form.addRow(sep)
        form.addRow("Parent .sim file:", QLabel(sim_file))
        form.addRow("Data set:", QLabel(data_set))
        form.addRow(f"{source_label}:", QLabel(scene))
        # Wrap the (possibly long) field list onto further lines instead of
        # stretching the window ever wider.
        displayers_label = QLabel(displayers)
        displayers_label.setWordWrap(True)
        displayers_label.setMaximumWidth(420)
        form.addRow("Vector/Scalar name:", displayers_label)
        form.addRow("Saved View:", QLabel(view))

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class FolderPropertiesDialog(QDialog):
    """Properties for a Files-tab folder: the combined on-disk size of every
    .sim it holds (recursively) and how many there are."""

    def __init__(
        self, name: str, total_bytes: int, file_count: int, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {name}")

        form = QFormLayout()
        form.addRow("Total size", QLabel(_human_size(total_bytes)))
        form.addRow("Sim files", QLabel(str(file_count)))

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DataFolderPropertiesDialog(QDialog):
    """Properties for a Data-tab folder: how many data sets it holds
    (recursively) and their combined size as portable CSVs."""

    def __init__(
        self, name: str, total_bytes: int, data_count: int, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {name}")

        form = QFormLayout()
        form.addRow("Total size", QLabel(_human_size(total_bytes)))
        form.addRow("Data sets", QLabel(str(data_count)))

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
