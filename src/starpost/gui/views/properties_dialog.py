"""Small 'Properties' window for a .sim file in the Files tab: its size on disk
and, once the file has been extracted, how many reports, monitors and iterations
its data holds.
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
    QVBoxLayout,
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

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        if not extracted:
            note = QLabel("Open the file to extract its reports and monitors.")
            note.setWordWrap(True)
            layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ScenePropertiesDialog(QDialog):
    """Properties for a rendered scene still: its file details (size, resolution,
    format) plus the sim, data set, scene and displayers it came from."""

    def __init__(self, artifact, parent=None) -> None:
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
        form.addRow("Report group:", QLabel(scene))
        form.addRow("Vector/Scalar name:", QLabel(displayers))

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
