"""Application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from starpost.core.settings import Settings
from starpost.gui.main_window import MainWindow
from starpost.utils.logging import configure


def _load_stylesheet() -> str:
    qss = Path(__file__).resolve().parent / "gui" / "resources" / "theme.qss"
    return qss.read_text() if qss.exists() else ""


def main() -> int:
    configure()
    app = QApplication(sys.argv)
    app.setApplicationName("starpost")
    app.setStyleSheet(_load_stylesheet())

    window = MainWindow(Settings.load())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
