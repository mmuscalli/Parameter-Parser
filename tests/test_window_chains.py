"""
Input passes back along chains of windows (Mickey, 2026-11-09: Help > How data packs work > All data packs and modules >
Check, then closing each in turn, left the main window without input). Each chain is driven by timers through the real
windows; at the end no modal window may remain and the main window must take input. No API calls.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

app = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("ParameterExtractorTests")

from parameter_extractor import packs  # noqa: E402
from parameter_extractor.gui import main_window  # noqa: E402
from parameter_extractor.gui.pack_windows import PackEditor  # noqa: E402
from parameter_extractor.gui.packs_window import DataPacksWindow  # noqa: E402


class Act:
    """One step: waits until `check(active modal window)` holds, then acts on it."""

    def __init__(self, name, check, act):
        self.name, self.check, self.act = name, check, act


def drive(start, acts, timeout_ms=15000) -> list:
    done = []

    def step(i):
        if i == len(acts):
            QTimer.singleShot(300, app.quit)
            return

        def run():
            w = QApplication.activeModalWidget()
            if not acts[i].check(w):
                QTimer.singleShot(100, run)
                return
            done.append(acts[i].name)
            QTimer.singleShot(200, lambda: step(i + 1))      # scheduled first: the act may block (exec)
            acts[i].act(w)
        QTimer.singleShot(200, run)
    step(0)
    QTimer.singleShot(timeout_ms, app.quit)
    QTimer.singleShot(100, start)
    app.exec()
    for _ in range(20):
        app.processEvents()
    return done


def _settled(m) -> None:
    assert QApplication.activeModalWidget() is None, QApplication.activeModalWidget()
    assert m.isEnabled() and m.pack_combo.isEnabled()
    assert not [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]


def is_packs(w):
    return isinstance(w, DataPacksWindow) and w.isVisible()


def test_help_to_packs_to_check_and_back():
    m = main_window.MainWindow()
    m.show()
    acts = [Act("help", lambda w: isinstance(w, QDialog) and w.windowTitle() == "How data packs work",
                lambda w: next(b for b in w.findChildren(QPushButton) if b.text().startswith("All data packs")).click()),
            Act("check", is_packs, lambda w: w._edit("Check")),
            Act("close editor", lambda w: isinstance(w, PackEditor), lambda w: w.reject()),
            Act("close packs", is_packs, lambda w: w.accept())]
    done = drive(m.show_how_packs_work, acts)
    assert done == [a.name for a in acts], done
    _settled(m)
    m.close()


def test_menu_packs_edit_and_follow_up_editor():
    """Data Packs window > Edit; the editor hands over to a next editor (what a copy / a helper does); back."""
    m = main_window.MainWindow()
    m.show()
    folder = packs.available()["exoplanets"].folder

    def hand_over(w):
        w.next_folder = folder
        w.reject()
    acts = [Act("edit", is_packs, lambda w: w._edit()),
            Act("hand over", lambda w: isinstance(w, PackEditor), hand_over),
            Act("next editor", lambda w: isinstance(w, PackEditor) and w.draft.folder == folder, lambda w: w.reject()),
            Act("close packs", is_packs, lambda w: w.reject())]
    done = drive(m.open_packs_window, acts)
    assert done == [a.name for a in acts], done
    _settled(m)
    m.close()


def test_packs_window_twice_is_one_window():
    m = main_window.MainWindow()
    m.open_packs_window()
    first = m._packs_window
    m.open_packs_window()
    assert m._packs_window is first
    first.accept()
    for _ in range(10):
        app.processEvents()
    _settled(m)
    m.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
