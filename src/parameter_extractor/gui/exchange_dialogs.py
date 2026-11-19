"""
File > Export requests for another assistant (exchange.py): the chosen papers' packages written on a background
thread (reading a paper takes seconds), then a message saying where they are and what to do with them.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import List

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


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


def copy_paths(folders: List[Path]) -> str:
    """The package folders' full paths, one a line, put on the clipboard (Mickey, 2026-11-19); returns them."""
    from PySide6.QtWidgets import QApplication
    text = "\n".join(str(Path(f).resolve()) for f in folders)
    if text:
        QApplication.clipboard().setText(text)
    return text


class ExportDone(QDialog):
    """Where the packages are (each path selectable, with Copy; all of them already on the clipboard), what to do
    next, what to know; Open folder."""

    def __init__(self, folder: Path, folders: List[Path], problems: List[tuple], parent=None):
        from parameter_extractor.exchange import CAVEATS
        super().__init__(parent)
        self.setWindowTitle("Requests for another assistant")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        copy_paths(folders)
        if folders:
            head = QLabel(f"{len(folders)} package{'s' if len(folders) > 1 else ''} written -- "
                          f"{'their paths are' if len(folders) > 1 else 'its path is'} on the clipboard, ready to "
                          f"paste where your assistant asks for a folder.", wordWrap=True)
            head.setStyleSheet("font-weight: bold;")
            v.addWidget(head)
            self.path_edits = []
            for f in folders:
                row = QHBoxLayout()
                edit = QLineEdit(str(Path(f).resolve()), readOnly=True)
                edit.setCursorPosition(0)
                self.path_edits.append(edit)
                row.addWidget(edit, 1)
                row.addWidget(QPushButton("Copy", clicked=lambda _c=False, e=edit: copy_paths([Path(e.text())])))
                v.addLayout(row)
            v.addWidget(QLabel("Give the folder to the assistant you use -- point an agent at it (its INSTRUCTIONS.md "
                               "says what to do). It answers the requests in order and writes its answers into the "
                               "package's answers/ folder, with answers/about.json naming the model. Nothing was sent "
                               "anywhere.\n\nThen: File > Import answers from another assistant…", wordWrap=True))
            notes = QLabel("<b>Good to know</b><ul style='margin-left: -20px'>" +
                           "".join(f"<li>{c}</li>" for c in CAVEATS) + "</ul>", wordWrap=True,
                           textFormat=Qt.TextFormat.RichText)
            notes.setStyleSheet("color: palette(placeholder-text);")
            v.addWidget(notes)
        if problems:
            v.addWidget(QLabel("Not prepared:\n" + "\n".join(f"  • {n}: {why}" for n, why in problems), wordWrap=True))
        buttons = QHBoxLayout()
        if folders:
            buttons.addWidget(QPushButton("Open folder", clicked=lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(folders[0] if len(folders) == 1 else folder)))))
        buttons.addStretch(1)
        close = QPushButton("Close", clicked=self.accept, default=True)
        buttons.addWidget(close)
        v.addLayout(buttons)


def explain_export(parent, folder: Path, folders: List[Path], problems: List[tuple]) -> None:
    ExportDone(folder, folders, problems, parent).exec()
