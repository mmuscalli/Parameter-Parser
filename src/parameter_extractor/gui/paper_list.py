"""
A list of papers to work on, shared by the focused-search window and the paper-queue window: PDFs
(Add PDFs…), identifiers typed or pasted (arXiv ID, DOI, ADS bibcode, a reference link), or a CSV list
(Add list…; an earlier run's papers.csv too). Items are kept as Path / PaperRef (with its label).
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)


class PaperListPanel(QGroupBox):
    changed = Signal()                 # papers added or removed
    message = Signal(str)              # something to tell the user (bad identifiers, papers added)

    def __init__(self, title: str = "Papers", parent=None):
        super().__init__(title, parent)
        self._settings = QSettings()
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list)
        self.id_edit = QLineEdit(placeholderText="arXiv ID, DOI, ADS bibcode or reference link -- Enter to add")
        self.id_edit.returnPressed.connect(self.add_typed)
        layout.addWidget(self.id_edit)
        row = QHBoxLayout()
        self.buttons = []
        for text, slot in (("Add PDFs…", self.add_pdfs), ("Add list (CSV)…", self.add_list),
                           ("Remove", self.remove_selected), ("Clear", self.clear)):
            button = QPushButton(text, clicked=slot)
            self.buttons.append(button)
            row.addWidget(button)
        layout.addLayout(row)

    def items(self) -> list:
        """The papers as added: PDF paths, or identifiers (PaperRef, with any reference label)."""
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def count(self) -> int:
        return self.list.count()

    def add_items(self, items) -> int:
        from parameter_extractor.ingestion.arxiv_source import PaperRef
        present = {str(x) for x in self.items()}
        added = 0
        for item in items:
            if str(item) in present:
                continue
            if not isinstance(item, (Path, PaperRef)):
                item = Path(item) if str(item).lower().endswith(".pdf") else PaperRef(str(item))
            label = getattr(item, "label", "")
            entry = QListWidgetItem(f"{label}  ({item})" if label else str(item))
            entry.setData(Qt.ItemDataRole.UserRole, item)
            entry.setToolTip(str(item))
            self.list.addItem(entry)
            present.add(str(item))
            added += 1
        self.changed.emit()
        return added

    def add_typed(self) -> None:
        from parameter_extractor.ingestion.arxiv_source import identifier_in_cell
        texts = [t.strip() for t in self.id_edit.text().replace(";", ",").split(",") if t.strip()]
        refs = {t: identifier_in_cell(t) for t in texts}      # also pasted reference links
        bad = [t for t, ref in refs.items() if ref is None]
        self.add_items([ref for ref in refs.values() if ref is not None])
        self.id_edit.setText(", ".join(bad))
        if bad:
            self.message.emit(f"Not an arXiv ID, DOI or ADS bibcode: {', '.join(bad)}")

    def add_pdfs(self) -> None:
        start = self._settings.value("last_pdf_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(self, "Add papers", start, "PDF files (*.pdf)")
        if paths:
            self._settings.setValue("last_pdf_dir", str(Path(paths[0]).parent))
            self.add_items(Path(p) for p in paths)

    def add_list(self) -> None:
        from parameter_extractor.focused_search import read_paper_list
        path, _ = QFileDialog.getOpenFileName(self, "Add papers from a list", str(Path.home()),
                                              "Lists (*.csv *.txt);;All files (*)")
        if not path:
            return
        items = read_paper_list(Path(path))
        added = self.add_items(items)
        self.message.emit(f"Added {added} paper(s) from {Path(path).name}"
                          + ("" if items else " -- no arXiv IDs, DOIs, ADS bibcodes or PDF paths found in it."))

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.changed.emit()

    def clear(self) -> None:
        self.list.clear()
        self.changed.emit()

    def set_locked(self, locked: bool) -> None:
        for w in [self.list, self.id_edit, *self.buttons]:
            w.setEnabled(not locked)
