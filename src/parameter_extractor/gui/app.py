"""Entry point for the desktop app: `parameter-extractor-gui`."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from parameter_extractor import __version__


def main() -> int:
    if "--self-check" in sys.argv:   # diagnostics, no window (see diagnostics.py)
        from parameter_extractor.diagnostics import main as self_check
        return self_check(sys.argv[1:])

    app = QApplication(sys.argv)
    app.setApplicationName("Parameter Extractor")
    app.setOrganizationName("Parameter Extractor")   # where QSettings stores preferences
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "app.png")))

    from parameter_extractor.gui.main_window import MainWindow  # after QApplication exists
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
