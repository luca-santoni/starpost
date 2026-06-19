"""Small shared Qt widgets reused across the GUI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QTabBar,
    QToolButton,
    QWidget,
)


class SecretLineEdit(QWidget):
    """A text field for a secret (e.g. the POD key): masked by default, with a
    Show/Hide toggle to reveal it on demand.

    Exposes the slice of the QLineEdit API the dialogs use (``text``,
    ``setText``, ``setPlaceholderText``), so it drops in where a plain
    QLineEdit was. Disabling the widget disables the field and toggle together.
    Re-created masked each time a dialog opens, so a stored key is never shown
    until the user asks.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setText("Show")
        self._toggle.setToolTip("Show or hide the key")
        self._toggle.toggled.connect(self._on_toggled)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._edit)
        row.addWidget(self._toggle)

    def _on_toggled(self, shown: bool) -> None:
        self._edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self._toggle.setText("Hide" if shown else "Show")

    # --- QLineEdit-compatible surface used by the dialogs ----------------
    def text(self) -> str:
        return self._edit.text()

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._edit.setText(text)

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._edit.setPlaceholderText(text)


class UniformTabBar(QTabBar):
    """A tab bar whose tabs all render at one shared width (set externally), so
    sibling tab bars (e.g. Files/Data and Reports/Plots) can match each other
    exactly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tab_width = 0  # 0 = use each tab's natural width

    def set_tab_width(self, width: int) -> None:
        self._tab_width = width
        self.updateGeometry()

    def tabSizeHint(self, index):  # noqa: N802 (Qt override)
        size = super().tabSizeHint(index)
        if self._tab_width:
            size.setWidth(self._tab_width)
        return size
