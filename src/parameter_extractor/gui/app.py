"""Entry point for the desktop app: `parameter-extractor-gui`."""
from __future__ import annotations
import sys

from PySide6.QtWidgets import QApplication

from parameter_extractor import __version__


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Parameter Extractor")
    app.setOrganizationName("Parameter Extractor")   # where QSettings stores preferences
    app.setApplicationVersion(__version__)

    from parameter_extractor.gui.main_window import MainWindow  # after QApplication exists
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
