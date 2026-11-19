"""
File > Export requests for another assistant (exchange.py): the chosen papers' packages written on a background
thread (reading a paper takes seconds), then a message saying where they are and what to do with them.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import List

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox


class ExportTask(QObject):
    """Writes each item's package (exchange.export_package) off the window's thread."""
    progress = Signal(str)
    finished = Signal(list, list)          # [package folders], [(item, problem)]

    def __init__(self, items, config, folder: Path, parent=None):
        super().__init__(parent)
        self.items, self.config, self.folder = list(items), config, Path(folder)
        self.folders: List[Path] = []
        self.problems: List[tuple] = []

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="export-requests").start()

    def _run(self) -> None:
        from dataclasses import replace
        from parameter_extractor import exchange
        from parameter_extractor.errors import PipelineError
        config = replace(self.config, api_key="")              # nothing is sent: no key is used
        for n, item in enumerate(self.items, 1):
            name = item.name if isinstance(item, Path) else str(item)
            self.progress.emit(f"Preparing requests for another assistant: {name} ({n} of {len(self.items)})…")
            try:
                self.folders.append(exchange.export_package(item, config, self.folder))
            except PipelineError as e:
                self.problems.append((name, str(e)))
            except Exception as e:                             # noqa: BLE001 -- one paper never stops the others
                self.problems.append((name, f"{type(e).__name__}: {e}"))
        self.progress.emit(f"Requests for another assistant written to {self.folder}.")
        self.finished.emit(self.folders, self.problems)


def explain_export(parent, folder: Path, folders: List[Path], problems: List[tuple]) -> None:
    """Where the packages are and what to do next; Open folder."""
    lines = []
    if folders:
        lines.append(f"{len(folders)} package(s) written to {folder}:\n" + "\n".join(f"  • {f.name}" for f in folders))
        from parameter_extractor.exchange import CAVEATS
        lines.append("Give a package folder to the assistant you use -- point an agent at the folder (its "
                     "INSTRUCTIONS.md says what to do). It answers the requests in order and writes its answers into "
                     "the package's answers/ folder, with answers/about.json naming the model. Nothing was sent "
                     "anywhere.\n\nThen: File > Import answers from another assistant…")
        lines.append("Good to know:\n" + "\n".join(f"  • {c}" for c in CAVEATS))
    if problems:
        lines.append("Not prepared:\n" + "\n".join(f"  • {name}: {why}" for name, why in problems))
    box = QMessageBox(QMessageBox.Icon.Information if folders else QMessageBox.Icon.Warning,
                      "Requests for another assistant", "\n\n".join(lines), parent=parent)
    open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole) if folders else None
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if open_btn is not None and box.clickedButton() is open_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
