"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from starpost.core.settings import Settings
from starpost.gui.icons import app_icon
from starpost.gui.main_window import MainWindow
from starpost.gui.theme import apply_theme
from starpost.gui.widgets import ToolTipResetStyle
from starpost.utils.logging import configure


def main() -> int:
    configure()
    app = QApplication(sys.argv)
    app.setApplicationName("starpost")
    app.setWindowIcon(app_icon())
    # Make moving between buttons restart the tooltip timer instead of showing
    # the next tooltip instantly (see ToolTipResetStyle).
    app.setStyle(ToolTipResetStyle())

    settings = Settings.load()
    apply_theme(
        app,
        settings.appearance.mode,
        settings.appearance.accent,
        settings.appearance.resolved_checkmark(),
        settings.appearance.text_scale,
    )

    window = MainWindow(settings)
    window.show()

    # First-run (or whenever the user keeps it enabled) welcome/setup wizard.
    if settings.show_setup_on_startup:
        from starpost.gui.views.welcome_dialog import WelcomeDialog

        WelcomeDialog(settings, window).exec()

    # Automatic update check. Stays silent unless a newer release is available;
    # when one is, also reveal the toolbar's "New update available" note.
    if settings.check_updates_on_startup:
        from starpost.gui.update import check_for_updates

        check_for_updates(
            window,
            silent_if_current=True,
            on_update_available=lambda _info: window.show_update_available(),
        )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
