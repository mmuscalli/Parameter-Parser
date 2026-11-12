"""
Flagged values (Mickey, 2026-11-11): the review of a run's flagged values in one place. Opened from "Things to check"
(Review flagged values…).

- A table in the format of "Extracted data", with only the rows that have a flagged value: the flagged cells in a
  strong colour (corrected ones in the corrections' blue, outlined in the flag colour while their flags are open).
  By default the row ids and the columns with a flag; "Show all columns" for the rest.
- Selecting a cell lists its flags -- issue, quote, where -- each with a checkbox (the same checked marks as the
  Things to check tab, flags_checked.json), and shows the saved table or figure the flag's location names (else the
  rendered page it is on), for direct comparison.
- Double-click a value to correct it, as in Extracted data (corrections.py); the main window is refreshed after.
Which cells a flag is about: flag_targets.py.
"""
from __future__ import annotations

import csv
import re
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from parameter_extractor import corrections as corr
from parameter_extractor import flag_targets as ft

FLAG_COLOR = QColor(255, 150, 70)          # a flagged value: obvious, readable in light and dark themes
CHECKED_COLOR = QColor(230, 230, 230)      # a flagged value whose flags are all checked
CORRECTED_COLOR = QColor(196, 222, 255)    # (as the main window's)
ROW_ID_COLUMNS = ["full_id", "set_id", "sample_id"]
_PLACE = re.compile(r"\b(Table|Fig\.?|Figure)\s*\.?\s*((?:S|[A-Z])?\d+[a-z]?|[IVXLC]+)\b", re.I)


class FlaggedValuesWindow(QDialog):
    def __init__(self, result, registry=None, parent=None, on_changed=None):
        super().__init__(parent)
        self.setWindowTitle(f"Flagged values — {result.paper_id}")
        self.resize(1300, 860)
        self.result, self.registry, self.on_changed = result, registry, on_changed or (lambda: None)
        self.changed = False
        self._filling = False

        v = QVBoxLayout(self)
        self.summary = QLabel(wordWrap=True)
        v.addWidget(self.summary)
        top = QHBoxLayout()
        self.all_columns_box = QCheckBox("Show all columns")
        self.all_columns_box.toggled.connect(lambda _on: self._fill_table())
        self.open_only_box = QCheckBox("Only values with flags not checked yet")
        self.open_only_box.toggled.connect(lambda _on: self._fill_table())
        self.everywhere_box = QCheckBox("Also highlight flags that cover every row")
        self.everywhere_box.toggled.connect(lambda _on: self._load())
        top.addWidget(self.all_columns_box)
        top.addWidget(self.open_only_box)
        top.addWidget(self.everywhere_box)
        top.addStretch(1)
        v.addLayout(top)
        # flags about a column on every row (e.g. a method's confidence 'for every experiment set'): listed once here,
        # not as highlights -- they would mark every row and the list would no longer be pared down
        self.everywhere_label = QLabel("<b>On every row</b> (not highlighted below; select one for its details)")
        self.everywhere_list = QListWidget()
        self.everywhere_list.setMaximumHeight(96)
        self.everywhere_list.setWordWrap(True)
        self.everywhere_list.itemChanged.connect(self._flag_ticked)
        self.everywhere_list.currentItemChanged.connect(lambda item, _p: self._show_flag(item))
        v.addWidget(self.everywhere_label)
        v.addWidget(self.everywhere_list)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.currentCellChanged.connect(lambda r, c, *_: self._show_cell(r, c))
        self.table.itemChanged.connect(self._edited)

        self.flag_list = QListWidget()
        self.flag_list.setWordWrap(True)                 # long issues wrap instead of running off sideways
        self.flag_list.itemChanged.connect(self._flag_ticked)
        self.flag_list.currentItemChanged.connect(lambda item, _p: self._show_flag(item))
        self.details = QTextBrowser(placeholderText="Select a flagged (orange) value to see its issues.")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Flags on this value</b> (tick once dealt with)"))
        lv.addWidget(self.flag_list, 1)
        lv.addWidget(self.details, 2)
        self.image_caption = QLabel(wordWrap=True)
        self.image = QLabel(alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.image_scroll = QScrollArea(widgetResizable=True)
        self.image_scroll.setWidget(self.image)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.image_caption)
        rv.addWidget(self.image_scroll, 1)
        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.addWidget(left)
        bottom.addWidget(right)
        bottom.setSizes([520, 780])
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(bottom)
        split.setSizes([360, 480])
        v.addWidget(split, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)
        self._load()

    # ---- data ------------------------------------------------------------------------------------------------------
    def _load(self) -> None:
        r = self.result
        with open(r.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.header = list(reader.fieldnames or [])
            self.rows = list(reader)
        obs = []
        if r.observations_path and Path(r.observations_path).is_file():
            with open(r.observations_path, newline="", encoding="utf-8") as f:
                obs = list(csv.DictReader(f))
        index = ft.Index(obs, self.header)
        all_rows = {row.get("full_id", "") for row in self.rows}
        self.cell_flags: Dict[Tuple[str, str], List[Tuple[object, str]]] = {}
        self.everywhere: List[Tuple[object, str, List[str]]] = []
        entries = [(f, "") for f in r.paper_flags] + [(f, rid) for rid, fs in r.row_flags.items() for f in fs]
        for flag, rid in entries:
            key = corr.flag_key(flag, rid)
            cells = ft.targets(flag, index, rid)
            if len(all_rows) > 1 and {fid for fid, _ in cells} >= all_rows and not self.everywhere_box.isChecked():
                self.everywhere.append((flag, key, sorted({col for _, col in cells})))
                continue
            for cell in cells:
                self.cell_flags.setdefault(cell, []).append((flag, key))
        self.checked = corr.load_checked(r.run_dir)
        self.everywhere_list.blockSignals(True)
        self.everywhere_list.clear()
        for flag, key, cols in self.everywhere:
            item = QListWidgetItem(f"{', '.join(cols)}: {flag.message.splitlines()[0][:150]}")
            item.setData(Qt.ItemDataRole.UserRole, (flag, key))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in self.checked else Qt.CheckState.Unchecked)
            self.everywhere_list.addItem(item)
        self.everywhere_list.blockSignals(False)
        self.everywhere_label.setVisible(bool(self.everywhere))
        self.everywhere_list.setVisible(bool(self.everywhere))
        self.corrected = corr.load(r.run_dir)
        self._fill_table()

    def _open(self, cell) -> bool:
        return any(key not in self.checked for _f, key in self.cell_flags.get(cell, []))

    def _fill_table(self) -> None:
        self._filling = True
        try:
            self._fill_table_now()
        finally:
            self._filling = False

    def _fill_table_now(self) -> None:
        open_only = self.open_only_box.isChecked()
        cells = [c for c in self.cell_flags if not open_only or self._open(c)]
        rows = [row for row in self.rows if any((row.get("full_id"), col) in self.cell_flags and
                                                (not open_only or self._open((row.get("full_id"), col)))
                                                for col in self.header)]
        flagged_cols = {col for _fid, col in cells}
        if self.all_columns_box.isChecked():
            cols = [c for c in self.header if any(r.get(c) for r in rows) or c in flagged_cols]
        else:
            cols = [c for c in ROW_ID_COLUMNS if c in self.header] + [c for c in self.header if c in flagged_cols]
        t = self.table
        t.clear()
        t.setColumnCount(len(cols))
        t.setRowCount(len(rows))
        t.setHorizontalHeaderLabels(cols)
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                text = row.get(col, "")
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, (row.get("full_id", ""), col, text))
                cell = (row.get("full_id", ""), col)
                if col in corr.FIXED_COLUMNS:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if cell in self.corrected:
                    item.setBackground(QBrush(CORRECTED_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                    item.setToolTip(f"Corrected (extracted: {self.corrected[cell].extracted or 'empty'})")
                if cell in self.cell_flags:
                    item.setBackground(QBrush(FLAG_COLOR if self._open(cell) else CHECKED_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                    font = item.font()
                    font.setBold(self._open(cell))
                    item.setFont(font)
                    n = len(self.cell_flags[cell])
                    item.setToolTip(f"{n} flag(s) on this value -- select it to see them"
                                    + (" (all checked)" if not self._open(cell) else ""))
                t.setItem(r, c, item)
        t.resizeColumnsToContents()
        for c in range(t.columnCount()):
            t.setColumnWidth(c, min(t.columnWidth(c), 260))
        n_open = sum(self._open(c) for c in self.cell_flags)
        self.summary.setText(
            f"<b>{len(self.cell_flags)}</b> flagged value(s) in <b>{len({fid for fid, _ in self.cell_flags})}</b> "
            f"row(s); <b>{n_open}</b> with flags not checked yet. Orange: flagged; grey: its flags are checked; blue: "
            f"corrected. Select a value for its issues and the table or figure it came from; double-click to "
            f"correct it.")

    # ---- a cell ----------------------------------------------------------------------------------------------------
    def _cell_of(self, r: int, c: int):
        item = self.table.item(r, c)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return (data[0], data[1]) if data else None

    def _show_cell(self, r: int, c: int) -> None:
        cell = self._cell_of(r, c)
        self.flag_list.blockSignals(True)
        self.flag_list.clear()
        for flag, key in (self.cell_flags.get(cell, []) if cell else []):
            item = QListWidgetItem(f"[{flag.kind.replace('_', ' ')}] {flag.message.splitlines()[0][:300]}")
            item.setData(Qt.ItemDataRole.UserRole, (flag, key))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in self.checked else Qt.CheckState.Unchecked)
            self.flag_list.addItem(item)
        self.flag_list.blockSignals(False)
        if self.flag_list.count():
            self.flag_list.setCurrentRow(0)
        else:
            self.details.setHtml("<p style='color:gray'>No flags on this value.</p>" if cell else "")
            self._show_place(None)

    def _show_flag(self, item) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not data:
            return
        flag = data[0]
        quote = flag.quote or flag.table_image_quote or flag.unverified_quote or ""
        where = ", ".join(x for x in (flag.source or "", f"p. {flag.page}" if flag.page else "") if x)
        self.details.setHtml(
            f"<p><b>Issue</b> ({escape(flag.kind.replace('_', ' '))})<br>{escape(flag.message).replace(chr(10), '<br>')}</p>"
            + (f"<p><b>Quote</b><br><i>“{escape(quote)}”</i></p>" if quote else "")
            + (f"<p><b>Where</b><br>{escape(where)}</p>" if where else ""))
        self._show_place(flag)

    def _image_for(self, flag) -> Tuple[Optional[str], str]:
        """(image path, caption) of the saved table / figure the flag's location names, else its page's render."""
        if flag is None:
            return None, ""
        text = " ".join(x for x in (flag.source or "", flag.message or "") if x)
        m = _PLACE.search(text)
        if m:
            kind, number = m.group(1).lower(), m.group(2)
            if kind.startswith("table"):
                for t in self.result.tables or []:
                    if str(t.get("table_id", "")).lower() == f"table {number}".lower() and t.get("image") and \
                            Path(t["image"]).is_file():
                        return t["image"], f"{t['table_id']} (as saved with the run)"
            else:
                for f in self.result.figures or []:
                    if str(f.get("figure_id", "")).lower() == f"fig. {number}".lower():
                        image = f.get("annotated_image") or f.get("image")
                        if image and Path(image).is_file():
                            return image, f"{f['figure_id']} (as saved with the run)"
        if flag.page:
            page = Path(self.result.run_dir) / "page_images" / f"page-{flag.page}.jpg"
            pieces = sorted(page.parent.glob(f"page-{flag.page}*.jpg")) if page.parent.is_dir() else []
            if pieces:
                return str(pieces[0]), f"page {flag.page} of the paper"
        return None, ""

    def _show_place(self, flag) -> None:
        path, caption = self._image_for(flag)
        if not path:
            self.image.clear()
            self.image_caption.setText("<span style='color:gray'>No saved table or figure for this flag's "
                                       "location.</span>" if flag is not None else "")
            return
        pix = QPixmap(path)
        width = max(400, self.image_scroll.viewport().width() - 8)
        self.image.setPixmap(pix.scaledToWidth(min(width, pix.width()), Qt.TransformationMode.SmoothTransformation))
        self.image_caption.setText(f"<b>{escape(caption)}</b>")
        self.image_path = path

    def _flag_ticked(self, item) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        key = data[1]
        if item.checkState() == Qt.CheckState.Checked:
            self.checked.add(key)
        else:
            self.checked.discard(key)
        corr.save_checked(self.result.run_dir, self.checked)
        self.changed = True
        current = (self.table.currentRow(), self.table.currentColumn())
        self._fill_table()
        if 0 <= current[0] < self.table.rowCount():
            self.table.blockSignals(True)
            self.table.setCurrentCell(*current)
            self.table.blockSignals(False)
        self.on_changed()

    # ---- correcting ------------------------------------------------------------------------------------------------
    def _edited(self, item) -> None:
        if self._filling:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        full_id, column, before = data
        if item.text() == before:
            return
        value, problem = corr.stored_value(column, item.text(), self.registry)
        if problem:
            QMessageBox.warning(self, "Not a valid value", f"{column}: {problem}. The value wasn't changed.")
            self._fill_table()
            return
        corr.correct(self.result.run_dir, full_id, column, before, value)
        self.changed = True
        self._load()
        self.on_changed()
