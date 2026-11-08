"""
The main window's Papers panel (one search page, Mickey 2026-11-08): the papers to work on -- PDFs (Add PDFs…, or
dropped on the window), identifiers typed or pasted (arXiv ID, DOI, ADS bibcode, a reference link), or a CSV list
(Add list…; an earlier run's papers.csv too). Items are kept as Path / PaperRef (with its label). A status column
shows each paper's progress in a run of several papers; selecting a finished one shows its results.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

ITEM_ROLE = Qt.ItemDataRole.UserRole


class PaperListPanel(QWidget):
    changed = Signal()                 # papers added or removed
    message = Signal(str)              # something to tell the user (bad identifiers, papers added)
    selected = Signal(int)             # a paper's row was selected (its results can be shown)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.id_edit = QLineEdit(placeholderText="PDF path, arXiv ID, DOI, ADS bibcode or link -- Enter adds it")
        self.id_edit.setToolTip("A local PDF, or a paper to read from arXiv: an arXiv ID (2308.05343), a DOI "
                                "(10.1093/pasj/psad056) or an ADS bibcode (needs an ADS token in Settings). Several "
                                "can be pasted at once, separated by commas. PDFs can also be dropped on the window.")
        self.id_edit.returnPressed.connect(self.add_typed)
        layout.addWidget(self.id_edit)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Paper", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(
            lambda: self.selected.emit(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons = []
        for text, slot in (("Add PDFs…", self.add_pdfs), ("Add list (CSV)…", self.add_list),
                           ("Remove", self.remove_selected), ("Clear", self.clear)):
            button = QPushButton(text, clicked=slot)
            self.buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

    def items(self) -> list:
        """The papers as added: PDF paths, or identifiers (PaperRef, with any reference label)."""
        return [self.table.item(r, 0).data(ITEM_ROLE) for r in range(self.table.rowCount())]

    def count(self) -> int:
        return self.table.rowCount()

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
            r = self.table.rowCount()
            self.table.insertRow(r)
            cell = QTableWidgetItem(f"{label}  ({item})" if label else (item.name if isinstance(item, Path) else str(item)))
            cell.setData(ITEM_ROLE, item)
            cell.setToolTip(str(item))
            self.table.setItem(r, 0, cell)
            self.table.setItem(r, 1, QTableWidgetItem(""))
            present.add(str(item))
            added += 1
        self.changed.emit()
        return added

    def set_status(self, row: int, text: str, tip: str = "") -> None:
        if 0 <= row < self.table.rowCount():
            item = QTableWidgetItem(text)
            item.setToolTip(tip or text)
            self.table.setItem(row, 1, item)

    def clear_statuses(self) -> None:
        for r in range(self.table.rowCount()):
            self.set_status(r, "")

    def add_typed(self) -> None:
        """The typed field's papers into the list: PDF paths and identifiers (several, comma-separated)."""
        from parameter_extractor.ingestion.arxiv_source import identifier_in_cell
        texts = [t.strip() for t in self.id_edit.text().replace(";", ",").split(",") if t.strip()]
        good, bad = [], []
        for t in texts:
            if t.lower().endswith(".pdf"):
                (good if Path(t).expanduser().is_file() else bad).append(Path(t).expanduser())
                continue
            ref = identifier_in_cell(t)                       # also pasted reference links
            (good.append(ref) if ref is not None else bad.append(t))
        self.add_items(good)
        self.id_edit.setText(", ".join(str(b) for b in bad))
        if bad:
            self.message.emit(f"Not found / not an arXiv ID, DOI or ADS bibcode: {', '.join(str(b) for b in bad)}")

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
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self.changed.emit()

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.changed.emit()

    def set_locked(self, locked: bool) -> None:
        for w in [self.id_edit, *self.buttons]:
            w.setEnabled(not locked)
