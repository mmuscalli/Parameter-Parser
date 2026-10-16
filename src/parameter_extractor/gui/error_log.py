"""
Keeping error details where they can be found. The packaged app has no
console, so a traceback printed there is lost: unexpected errors (and the
message of any failed run) are appended to errors.log in the app-data folder
and, when the run folder is known, written to its error.txt. An exception in
the window itself (digitizer, dialogs) would otherwise vanish silently: the
excepthook records it and tells the user.
"""
from __future__ import annotations
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from parameter_extractor import __version__
from parameter_extractor.registry import default_registry_path


def error_log_path() -> Path:
    return default_registry_path().parent / "errors.log"


def record(text: str, run_dir: Optional[Path] = None) -> Path:
    """Append `text` (a message or traceback) to errors.log, and to run_dir/error.txt."""
    stamp = f"--- {datetime.now().isoformat(timespec='seconds')} (Parameter Extractor {__version__})\n"
    path = error_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(stamp + text.rstrip() + "\n\n")
        if run_dir is not None and Path(run_dir).is_dir():
            with open(Path(run_dir) / "error.txt", "a") as f:
                f.write(stamp + text.rstrip() + "\n\n")
    except OSError:
        pass
    return path


def latest_run_dir(output_dir: Path, pdf_path: Path, since: float) -> Optional[Path]:
    """The run folder this run created (<pdf stem>_<timestamp>), if any."""
    try:
        folders = [p for p in Path(output_dir).glob(f"{Path(pdf_path).stem}_*")
                   if p.is_dir() and p.stat().st_mtime >= since - 1]
    except OSError:
        return None
    return max(folders, key=lambda p: p.stat().st_mtime, default=None)


def install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        path = record(details)
        sys.__stderr__ and sys.__stderr__.write(details)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(None, "Something went wrong",
                                     f"{exc_type.__name__}: {exc}\n\nThis is a bug in the app. The details were "
                                     f"saved to:\n{path}\n\nYour work in other windows is not affected; please "
                                     f"send that file with a description of what you were doing.")
        except Exception:
            pass
    sys.excepthook = hook
