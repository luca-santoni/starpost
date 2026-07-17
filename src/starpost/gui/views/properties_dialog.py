"""'Properties' window for a .sim file / data set: a General tab with its size
on disk and, once extracted, its report/monitor/iteration counts, and a Parts
tab showing the sim's Geometry > Parts tree (from the extracted properties).
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
        self.tabs.addTab(
            _general_tab(path, result, size_bytes), "General"
        )
        self.tabs.addTab(_PartsTab(result), "Parts")

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


def _general_tab(path: Path, result, size_bytes: int | None) -> QWidget:
    """The classic summary form: file size and, once the file has been
    extracted, its report/monitor/iteration counts."""
    # When size_bytes is given (e.g. the Data tab passes the data set's
    # portable-CSV size), use it; otherwise measure the file on disk.
    if size_bytes is not None:
        size = _human_size(size_bytes)
    else:
        try:
            size = _human_size(path.stat().st_size)
        except OSError:  # file moved/deleted/unreadable
            size = "—"

    # Reports/monitors/iterations only exist once the file is extracted. A
    # monitor is a single series; iterations is the longest series' length.
    extracted = result is not None and result.error is None
    if extracted:
        reports = str(len(result.reports))
        monitors = str(sum(len(p.series) for p in result.plots))
        iterations = str(
            max(
                (len(s.x) for p in result.plots for s in p.series),
                default=0,
            )
        )
    else:
        reports = monitors = iterations = "—"

    form = QFormLayout()
    form.addRow("File size", QLabel(size))
    form.addRow("Reports", QLabel(reports))
    form.addRow("Monitors", QLabel(monitors))
    form.addRow("Iterations", QLabel(iterations))

    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.addLayout(form)
    if not extracted:
        note = QLabel("Open the file to extract its reports and monitors.")
        note.setWordWrap(True)
        layout.addWidget(note)
    layout.addStretch(1)
    return tab


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


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _contents(node: PartNode) -> str:
    """The Contents cell: leaf-part count for composites, surface/curve
    counts for leaf parts."""
    if node.children or node.leaf_count is not None and not node.surfaces:
        count = node.leaf_count
        if count is None:
            count = len(node.children)
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
