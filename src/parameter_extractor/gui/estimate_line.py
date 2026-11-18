"""
The estimate before a run (estimate.py, W4), under the Run button: "About $0.15–0.40 and 4–8 minutes for this paper
(estimate)". Refreshed a moment after the papers or settings change; the papers' PDFs are read for it (their text
and figure count) on a worker thread, once each, and never while a run is going (pdfium isn't thread-safe) -- until
then a paper counts as a typical one.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLabel

CHECKED = ("Estimated from the tokens such requests took in earlier runs, at the chosen model profile's prices. "
           "Checked against 224 recorded papers (2026-11-18): 88% cost within the range.")


class EstimateLine(QLabel):
    _papers_read = Signal()

    def __init__(self, config: Callable, items: Callable[[], List], busy: Callable[[], bool], parent=None):
        super().__init__(parent, wordWrap=True)
        self._config, self._items, self._busy = config, items, busy
        self.setStyleSheet("color: palette(placeholder-text);")
        self._known: Dict[Tuple[str, float], object] = {}       # (path, modified) -> PaperInfo
        self._reading = False
        self._timer = QTimer(self, singleShot=True, interval=400, timeout=self._update)
        self._papers_read.connect(self._update)
        self.setHidden(True)

    def refresh(self, shown: bool = True) -> None:
        """Recompute soon (settings change in bursts); `shown` False hides it (a focused search)."""
        if not shown:
            self._timer.stop()
            self.setHidden(True)
            return
        self._timer.start()

    @staticmethod
    def _key(item):
        path = Path(str(item)).expanduser()
        if path.suffix.lower() != ".pdf" or not path.is_file():
            return None
        return str(path), path.stat().st_mtime

    def _update(self) -> None:
        from parameter_extractor.estimate import PaperInfo, estimate
        try:
            items = self._items()
            if not items:
                self.setHidden(True)
                return
            keys = [self._key(i) for i in items]
            papers = [self._known.get(k, PaperInfo()) if k else PaperInfo() for k in keys]
            est = estimate(self._config(), items, papers=papers)
        except Exception:                             # noqa: BLE001 -- an estimate never gets in the way
            self.setHidden(True)
            return
        self.setText(est.text())
        self.setToolTip("\n".join([CHECKED] + est.notes))
        self.setHidden(False)
        unread = [(k, i) for k, i in zip(keys, items) if k and k not in self._known]
        if unread and not self._reading and not self._busy():
            self._reading = True
            threading.Thread(target=self._read, args=(unread,), daemon=True, name="estimate-read").start()

    def _read(self, unread) -> None:
        from parameter_extractor.estimate import read_paper
        try:
            for key, item in unread:
                if self._busy():                      # a run started: pdfium is the run's now
                    break
                self._known[key] = read_paper(item)
        finally:
            self._reading = False
            self._papers_read.emit()
