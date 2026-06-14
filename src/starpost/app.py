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
    apply_theme(
        app,
        settings.appearance.mode,
        settings.appearance.accent,
        settings.appearance.resolved_checkmark(),
    )

    window = MainWindow(settings)
    window.show()

    # First-run (or whenever the user keeps it enabled) welcome/setup wizard.
    if settings.show_setup_on_startup:
        from starpost.gui.views.welcome_dialog import WelcomeDialog

        WelcomeDialog(settings, window).exec()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
