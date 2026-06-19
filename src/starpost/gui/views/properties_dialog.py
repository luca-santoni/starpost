"""Small 'Properties' window for a .sim file in the Files tab: its size on disk
and, once the file has been extracted, how many reports, monitors and iterations
its data holds.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
