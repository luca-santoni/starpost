"""Small shared Qt widgets reused across the GUI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QTabBar,
    QToolButton,
    QWidget,
)


class ToolTipResetStyle(QProxyStyle):
    """Proxy style that makes each hover wait the full tooltip delay.

    Qt normally keeps tooltips "awake" for a short window after one is hidden, so
    moving the cursor straight to another widget shows its tooltip instantly.
    Returning 0 for the fall-asleep delay removes that window: Qt sleeps as soon
    as a tooltip hides, so hovering a new button restarts the wake-up timer.
    Every other style decision is delegated unchanged to the base style, so the
    app's appearance (driven by the QSS theme) is untouched.

    The base style defaults to **Fusion** rather than the platform default, so the
    app uses one consistent style on every OS. Without this, Qt proxies the native
    style (Fusion on Linux, windows11/vista on Windows), whose differing item/tab
    metrics make lists and tabs space wider on Windows than on Linux. Fusion is a
    lightweight, fully cross-platform style, so this gives identical spacing with
    no meaningful rendering cost (the dark QSS theme already drives the look).
    """

    def __init__(self, base=None) -> None:
        super().__init__(base or QStyleFactory.create("Fusion"))

    def styleHint(  # noqa: N802 (Qt override)
        self, hint, option=None, widget=None, returnData=None
    ) -> int:
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 0
        return super().styleHint(hint, option, widget, returnData)


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
    """A tab bar whose tabs all render at one shared width — the widest tab's
    natural size — so e.g. "Reports" and "Plots" are equal.

    The width is recomputed from the live tab size hints on every layout pass, so
    it tracks the current font (it grows with the Appearance text-size setting
    instead of clipping). Bars linked with :meth:`link` share a single width
    across the group, letting sibling tab bars (Files/Data and Reports/Plots)
    match each other exactly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._peers: list[UniformTabBar] = []

    def link(self, *bars: "UniformTabBar") -> None:
        """Size this bar and ``bars`` to one shared width: the widest tab across
        the whole group, recomputed live so it follows font changes."""
        group = [self, *bars]
        for bar in group:
            bar._peers = [other for other in group if other is not bar]
            bar.updateGeometry()

    def _natural_max_width(self) -> int:
        """The widest natural tab width in this bar (bypassing the override below
        so linked bars can query each other without recursing)."""
        return max(
            (QTabBar.tabSizeHint(self, i).width() for i in range(self.count())),
            default=0,
        )

    def tabSizeHint(self, index):  # noqa: N802 (Qt override)
        size = super().tabSizeHint(index)
        width = max(
            [self._natural_max_width(), *(p._natural_max_width() for p in self._peers)]
        )
        size.setWidth(width)
        return size
