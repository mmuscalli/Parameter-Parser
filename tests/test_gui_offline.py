"""
Offline test of the desktop window -- no API calls, no visible window.

Drives MainWindow like a user (fill in the fields, click "Extract data", wait)
with Qt's offscreen platform, replaying the saved eder1994_auto responses
through the real pipeline (same replay as test_pipeline_offline.py). The
system keychain and the user's saved preferences are never touched.

Set GUI_SCREENSHOT_DIR to also save PNGs of each tab for a visual check.

Run with: python tests/test_gui_offline.py   (needs: pip install -e ".[gui]")
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("SKIP: PySide6 not installed (pip install -e \".[gui]\")")
    raise SystemExit(0)

from parameter_extractor import api_client
from parameter_extractor.gui import key_store, main_window
from test_pipeline_offline import PDF, _replay_send

APP = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("ParameterExtractorTests")  # keep the user's prefs untouched
QCoreApplication.setApplicationName("ParameterExtractorTests")


class FakeKeyStore:
    def __init__(self, stored=""):
        self.stored, self.saved, self.deleted = stored, [], 0
    def load_key(self): return self.stored
    def save_key(self, key): self.saved.append(key); return True
    def delete_key(self): self.deleted += 1


def _window(keys: FakeKeyStore, out: Path):
    QSettings().clear()
    with patch.object(main_window, "key_store", keys):
        w = main_window.MainWindow()
    w.out_edit.setText(str(out))
    return w


def _pump(seconds=0.05):
    """Let Qt deliver events. NOT QTest.qWait: it keeps holding Python's GIL,
    so the worker thread never runs (the real app's app.exec() releases it)."""
    APP.processEvents()
    time.sleep(seconds)
    APP.processEvents()


def _wait_until_idle(w, timeout_s=60):
    for _ in range(timeout_s * 20):
        if not w._running:
            return
        _pump()
    raise AssertionError("run did not finish in time")


def _screenshot(w, name):
    d = os.environ.get("GUI_SCREENSHOT_DIR")
    if d:
        w.grab().save(str(Path(d) / f"{name}.png"))


def test_full_run_fills_results():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    keys = FakeKeyStore()
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(api_client, "_send", _replay_send), \
            patch.object(main_window, "key_store", keys):
        w = _window(keys, Path(tmp))
        w.show()
        assert not w.run_btn.isEnabled(), "Extract should be disabled until inputs are filled"
        _screenshot(w, "0_empty")

        w.pdf_edit.setText(str(PDF))
        w.key_edit.setText("replay-not-a-real-key")
        assert w.run_btn.isEnabled()
        assert w.key_edit.echoMode() == w.key_edit.EchoMode.Password

        progress = []
        w.progress.valueChanged.connect(progress.append)
        w.run_btn.click()
        assert w._running and not w.run_btn.isEnabled() and w.cancel_btn.isEnabled()
        _wait_until_idle(w)

        assert "Done: 42 rows" in w.status.text(), w.status.text()
        assert w.rows_table.rowCount() == 42
        headers = [w.rows_table.horizontalHeaderItem(i).text() for i in range(w.rows_table.columnCount())]
        assert "sampled_2peptide_Gly_pct_yield" in headers and "full_id" in headers
        assert w.flags_tree.topLevelItemCount() >= 1
        assert headers[0] == "full_id" and headers.index("sampled_2peptide_Gly_pct_yield") < headers.index("paper_title")
        first_flag = w.flags_tree.topLevelItem(0).child(0)
        w.flags_tree.setCurrentItem(first_flag)
        assert "confidence" in w.flag_details.toPlainText()
        assert "Quote from the paper" in w.flag_details.toPlainText()
        assert w.tabs.isEnabled() and w.open_folder_btn.isEnabled()
        assert progress and max(progress) == w.progress.maximum()
        assert keys.saved == [] and keys.deleted == 0, "keychain touched without 'remember' ticked"
        assert w.run_btn.isEnabled() and not w.cancel_btn.isEnabled()

        for i, name in enumerate(["1_rows", "2_flags", "3_summary"]):
            w.tabs.setCurrentIndex(i); _pump(); _screenshot(w, name)
        w.close()


def test_errors_are_shown_to_the_user():
    keys = FakeKeyStore()
    shown = []
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(main_window, "key_store", keys), \
            patch.object(main_window.QMessageBox, "critical",
                         lambda parent, title, msg: shown.append((title, msg))):
        w = _window(keys, Path(tmp))
        bad_pdf = Path(tmp) / "not-a-pdf.pdf"
        bad_pdf.write_text("this is not a PDF")
        w.pdf_edit.setText(str(bad_pdf))
        w.key_edit.setText("replay-not-a-real-key")
        w.run_btn.click()
        _wait_until_idle(w)
        assert shown and "not-a-pdf.pdf" in shown[0][1], shown
        assert "error" in w.status.text().lower()
        w.close()


def test_remember_key_uses_keychain_and_unticking_forgets_it():
    keys = FakeKeyStore(stored="sk-ant-stored")
    with tempfile.TemporaryDirectory() as tmp, patch.object(main_window, "key_store", keys):
        w = _window(keys, Path(tmp))
        assert w.key_edit.text() == "sk-ant-stored" and w.remember_key_box.isChecked()
        w._save_preferences()
        assert keys.saved == ["sk-ant-stored"]
        w.remember_key_box.setChecked(False)
        w._save_preferences()
        assert keys.deleted == 1
        w.close()


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print(f"PASS: {name}")
        print("All offline GUI tests passed.")
    finally:
        QSettings().clear()
