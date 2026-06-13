"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from starpost.core.settings import Settings
from starpost.gui.icons import app_icon
from starpost.gui.main_window import MainWindow
from starpost.gui.theme import apply_theme
from starpost.utils.logging import configure


def main() -> int:
    configure()
    app = QApplication(sys.argv)
    app.setApplicationName("starpost")
    app.setWindowIcon(app_icon())

    settings = Settings.load()
    apply_theme(app, settings.appearance.mode, settings.appearance.accent)

    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
