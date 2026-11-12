"""
Flagged values (Mickey, 2026-11-11): the review of a run's flagged values in one place. Opened from "Things to check"
(Review flagged values…).

- A table in the format of "Extracted data", with only the rows that have a flagged value: the flagged cells in a
  strong colour (corrected ones in the corrections' blue, outlined in the flag colour while their flags are open).
  By default the row ids and the columns with a flag; "Show all columns" for the rest.
- Selecting a cell lists its flags -- issue, quote, where -- each with a checkbox (the same checked marks as the
  Things to check tab, flags_checked.json), and shows the saved table or figure the flag's location names (else the
  rendered page it is on), for direct comparison.
- Double-click a value to correct it, as in Extracted data (corrections.py); several values at once: select them
  (Shift / Cmd-click, or a column's header) and "Change selected values…" (also on right-click). The main window is
  refreshed after.
- Flags about a column on every row are in a collapsed "On every row" list; "Review all" puts their values in the
  table too (Mickey, 2026-11-11). source_notes is always the last column (it says what the row is).
- The table / figure image zooms: buttons, Cmd + scroll, pinch. The SELECTED value alone decides what is shown (not
  the mouse: hovering had shown another value's table beside this one's flags -- Mickey, 2026-11-12); on a saved
  table it is boxed where the PDF's text layer has it (ingestion/table_locate.py; local, no model).
- The details panel: this value (column, row, value, quote, where), then each flag on it -- in plain words, only the
  part of a grouped flag about this value ("Show the whole flag" for the rest), its quote only when it is this
  value's.
Which cells a flag is about: flag_targets.py.
"""
from __future__ import annotations

import csv
import re
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QObject, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from parameter_extractor import corrections as corr
from parameter_extractor import flag_targets as ft

FLAG_COLOR = QColor(255, 150, 70)          # a flagged value: obvious, readable in light and dark themes
CHECKED_COLOR = QColor(230, 230, 230)      # a flagged value whose flags are all checked
CORRECTED_COLOR = QColor(196, 222, 255)    # (as the main window's)
MARK_PEN = QColor(255, 110, 0)             # a located value on the table image
MARK_FILL = QColor(255, 214, 0, 90)
ROW_ID_COLUMNS = ["full_id", "set_id", "sample_id"]
LAST_COLUMN = "source_notes"               # always shown, last: a short description of the row
ZOOM_STEPS = (0.25, 0.33, 0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)


DETAILS_STYLE = """<style>
h3 { margin: 6px 0 4px 0; font-size: 13pt; } h4 { margin: 10px 0 2px 0; font-size: 12pt; }
p { margin: 2px 0 6px 0; } td { padding: 2px 10px 2px 0; vertical-align: top; } td.k { color: gray; }
p.more { color: gray; margin-top: 8px; } div.value { background: rgba(120,120,120,0.12); }
</style>"""
# flag kinds in plain words (the Things to check groups say the same)
KIND_LABELS = {
    "identity_not_quoted": "Which compound it is was inferred",
    "quote_unrelated": "The quote doesn't contain the value",
    "low_confidence": "The model wasn't sure",
    "assumed_value": "Assumed, not stated in the paper",
    "assumed_default": "Filled in by a convention",
    "table_check": "A second reading of the table disagrees",
    "table_not_found": "Not found in its row of the table's text",
    "conflicting_values": "The paper gives different values",
    "out_of_range": "Outside the usual range",
    "unit_conversion": "Unit or format problem",
    "value_range": "A range, not one value",
    "concentration_not_stated": "Concentration not stated",
    "pass_disagreement": "The passes disagreed",
    "derived_value": "Calculated by the app",
    "multimodal": "Several modes reported",
    "other_estimates": "Other estimates reported",
    "archive_check": "Differs from the NASA Exoplanet Archive",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, (kind or "flag").replace("_", " ").capitalize())


def _table(rows) -> str:
    return "<table>" + "".join(f"<tr><td class='k'>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>"


def _html_text(text: str) -> str:
    return escape(text).replace("\n", "<br>")


def _split_merged(message: str) -> Tuple[str, List[Tuple[str, str]]]:
    """(the lead flag's message, [(kind, message)] of the flags merged into it -- flag_targets.consolidate)."""
    head, sep, rest = message.partition("\nAlso flagged for the same value(s):\n")
    if not sep:
        return message, []
    merged = []
    for line in rest.split("\n- "):
        m = re.match(r"-?\s*\(([^)]*)\)\s*(.*)", line.strip(), re.S)
        if m:
            merged.append((m.group(1).replace(" ", "_"), m.group(2)))
    return head, merged


def _top_level_items(text: str) -> List[str]:
    """Split on '; ' outside brackets ('Ba2+ 2.50 ... (Set labelled Ba2+ in plan; printed table row ...)' is one)."""
    items, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += ch in "([" and 1 or (ch in ")]" and -1 or 0)
        if depth == 0 and text.startswith("; ", i):
            items.append(text[start:i])
            start = i + 2
    items.append(text[start:])
    return [i for i in (x.strip() for x in items) if i]


def _about(message: str, labels: List[str], numbers: List[str]) -> Tuple[str, int]:
    """The part of a grouped flag about one value: its message lists several ('CaCl2: ...: Ca2+ 1.67 mol dm-3, 85 C
    (...); Ca2+ 1.50 mol dm-3, 89 C (...); ...'). Keeps the lead-in, the items naming this value's set label (else all
    its quote's numbers), and a closing 'Check the paper.'; returns (text, how many items were left out)."""
    body, tail = message, ""
    m = re.search(r"(?<=[.)])\s+(Check [^.;]*\.|Correct it[^;]*\.)\s*$", message)
    if m:
        body, tail = message[:m.start()], m.group(1)
    items = _top_level_items(body)
    if len(items) < 2:
        return message, 0
    lead = ""
    first = items[0]
    cut = first.rfind(": ")
    if cut > 0:
        lead, items[0] = first[:cut + 2], first[cut + 2:]

    def names_it(item: str) -> bool:
        text = ft._label_text(item)
        if any(ft._label_text(l) in text for l in labels if l):
            return True
        found = re.findall(r"\d+(?:\.\d+)?", item)
        as_numbers = {f"{float(x):g}" for x in found}
        return bool(numbers) and all(n in as_numbers for n in numbers)

    keep = [i for i in items if names_it(i)]
    if not keep or len(keep) == len(items):
        return message, 0
    text = lead + "; ".join(keep)
    if tail:
        text += ("" if text.rstrip().endswith(".") else ".") + " " + tail
    return text, len(items) - len(keep)


class _ZoomFilter(QObject):
    """Cmd + scroll and pinch on the image zoom it; plain scrolling still scrolls."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.window.zoom_by(1 if event.angleDelta().y() > 0 else -1)
            return True
        if event.type() == QEvent.Type.NativeGesture and \
                event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.window.set_zoom(self.window.current_zoom() * (1.0 + event.value()))
            return True
        return False


class ChangeValuesDialog(QDialog):
    """One new value for several selected cells."""

    def __init__(self, cells, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change selected values")
        v = QVBoxLayout(self)
        columns = sorted({col for _fid, col, _before in cells})
        rows = len({fid for fid, _col, _before in cells})
        v.addWidget(QLabel(f"New value for <b>{len(cells)}</b> value(s) in {rows} row(s) -- column(s): "
                           f"{escape(', '.join(columns[:6]))}{' …' if len(columns) > 6 else ''}.<br>"
                           f"Units convert to each column's unit ('45 min' in an _hr column is stored as 0.75). "
                           f"Leave it empty to clear the values.", wordWrap=True))
        self.edit = QLineEdit()
        befores = {before for _f, _c, before in cells}
        if len(befores) == 1:
            self.edit.setText(next(iter(befores)))
            self.edit.selectAll()
        v.addWidget(self.edit)
        self.note = QLineEdit(placeholderText="Note (optional): why, or where in the paper")
        v.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"Change {len(cells)} value(s)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.resize(560, self.sizeHint().height())
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
        self.change_btn = QPushButton("Change selected values…", clicked=self.change_selected)
        self.change_btn.setToolTip("Select several values (Shift / Cmd-click, or click a column's header), then "
                                   "give them one new value")
        top.addWidget(self.all_columns_box)
        top.addWidget(self.open_only_box)
        top.addStretch(1)
        top.addWidget(self.change_btn)
        v.addLayout(top)
        # flags about a column on every row (e.g. a method's confidence 'for every experiment set'): listed once, in
        # a collapsed list, not as highlights -- they would mark every row and the table would no longer be pared
        # down. "Review all" puts their values in the table too.
        self.review_all = False
        every = QHBoxLayout()
        self.everywhere_toggle = QToolButton(checkable=True, checked=False)
        self.everywhere_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.everywhere_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.everywhere_toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.everywhere_toggle.toggled.connect(self._toggle_everywhere)
        self.review_all_btn = QPushButton("Review all", checkable=True)
        self.review_all_btn.setToolTip("Put the values of these flags in the table too, highlighted like the others "
                                       "(select a column's values there to change them together)")
        self.review_all_btn.toggled.connect(self._set_review_all)
        every.addWidget(self.everywhere_toggle)
        every.addWidget(self.review_all_btn)
        every.addStretch(1)
        self.everywhere_row = QWidget()
        self.everywhere_row.setLayout(every)
        every.setContentsMargins(0, 0, 0, 0)
        self.everywhere_list = QListWidget()
        self.everywhere_list.setMaximumHeight(130)
        self.everywhere_list.setWordWrap(True)
        self.everywhere_list.setVisible(False)
        self.everywhere_list.itemChanged.connect(self._flag_ticked)
        self.everywhere_list.currentItemChanged.connect(lambda item, _p: self._everywhere_selected(item))
        v.addWidget(self.everywhere_row)
        v.addWidget(self.everywhere_list)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.currentCellChanged.connect(lambda r, c, *_: self._show_cell(r, c))
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)

        self.flag_list = QListWidget()
        self.flag_list.setWordWrap(True)                 # long issues wrap instead of running off sideways
        self.flag_list.itemChanged.connect(self._flag_ticked)
        self.flag_list.currentItemChanged.connect(lambda item, _p: self._show_flag(item))
        self.details = QTextBrowser(placeholderText="Select a flagged (orange) value to see its issues.")
        self.details.setOpenLinks(False)
        self.details.anchorClicked.connect(self._details_link)
        self.details.document().setDocumentMargin(10)
        self._whole_flag = False                     # "Show the whole flag" (a grouped flag's other values too)
        self._shown_flag = None
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Flags on this value</b> (tick once dealt with)"))
        self.flag_list.setMaximumHeight(110)            # a short line per flag; the details get the room
        lv.addWidget(self.flag_list)
        lv.addWidget(self.details, 1)
        self.image_caption = QLabel(wordWrap=True)
        self.image = QLabel(alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.image_scroll = QScrollArea(widgetResizable=True)
        self.image_scroll.setWidget(self.image)
        self.image_path = None
        self._flag = None                            # the flag whose location is shown
        self._cell = None                            # the selected value
        self._image_entry = None                     # the tables.json entry shown (None: a figure or page)
        self._boxes: list = []
        self._table_words: dict = {}
        self.zoom: Optional[float] = None            # None = fit the pane's width
        self._zoom_filter = _ZoomFilter(self)
        self.image_scroll.viewport().installEventFilter(self._zoom_filter)
        self.image.installEventFilter(self._zoom_filter)
        zoom_row = QHBoxLayout()
        self.zoom_out_btn = QToolButton(text="−", clicked=lambda: self.zoom_by(-1))
        self.zoom_in_btn = QToolButton(text="+", clicked=lambda: self.zoom_by(1))
        self.fit_btn = QToolButton(text="Fit width", clicked=lambda: self.set_zoom(None))
        self.actual_btn = QToolButton(text="100%", clicked=lambda: self.set_zoom(1.0))
        self.zoom_label = QLabel()
        for wdg in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.actual_btn):
            zoom_row.addWidget(wdg)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addStretch(1)
        zoom_row.addWidget(QLabel("<span style='color:gray'>Cmd + scroll or pinch to zoom</span>"))
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.image_caption)
        self.zoom_bar = QWidget()
        self.zoom_bar.setLayout(zoom_row)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        self.zoom_bar.setVisible(False)
        rv.addWidget(self.zoom_bar)
        rv.addWidget(self.image_scroll, 1)
        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.addWidget(left)
        bottom.addWidget(right)
        bottom.setSizes([430, 870])
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(bottom)
        split.setSizes([300, 560])
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
        index = ft.Index(obs, self.header, set_labels=ft.plan_set_labels(r.run_dir))
        # each cell's own provenance (its value, quote, location): shown above its flags -- a flag's quote can be
        # another cell's (one flag about several values)
        self.cell_info = {(o.get("full_id", ""), o.get("column", "")): o for o in obs}
        self._cell_html = ""
        all_rows = {row.get("full_id", "") for row in self.rows}
        self.cell_flags: Dict[Tuple[str, str], List[Tuple[object, str]]] = {}
        self.everywhere: List[Tuple[object, str, List[str]]] = []
        entries = [(f, "") for f in r.paper_flags] + [(f, rid) for rid, fs in r.row_flags.items() for f in fs]
        for flag, rid in entries:
            key = corr.flag_key(flag, rid)
            cells = ft.targets(flag, index, rid)
            if len(all_rows) > 1 and {fid for fid, _ in cells} >= all_rows:
                self.everywhere.append((flag, key, sorted({col for _, col in cells}), cells))
                if not self.review_all:
                    continue
            for cell in cells:
                self.cell_flags.setdefault(cell, []).append((flag, key))
        self.checked = corr.load_checked(r.run_dir)
        self.everywhere_list.blockSignals(True)
        self.everywhere_list.clear()
        for flag, key, cols, _cells in self.everywhere:
            item = QListWidgetItem(f"{', '.join(cols)}: {flag.message.splitlines()[0][:150]}")
            item.setData(Qt.ItemDataRole.UserRole, (flag, key))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in self.checked else Qt.CheckState.Unchecked)
            self.everywhere_list.addItem(item)
        self.everywhere_list.blockSignals(False)
        self.everywhere_row.setVisible(bool(self.everywhere))
        self.everywhere_list.setVisible(bool(self.everywhere) and self.everywhere_toggle.isChecked())
        n_open = sum(key not in self.checked for _f, key, _c, _cells in self.everywhere)
        self.everywhere_toggle.setText(f"On every row ({len(self.everywhere)}, {n_open} not checked yet)")
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
        if LAST_COLUMN in self.header:
            cols = [c for c in cols if c != LAST_COLUMN] + [LAST_COLUMN]
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
            t.setColumnWidth(c, min(t.columnWidth(c), 420 if cols[c] == LAST_COLUMN else 260))
        self._selection_changed()
        n_open = sum(self._open(c) for c in self.cell_flags)
        self.summary.setText(
            f"<b>{len(self.cell_flags)}</b> flagged value(s) in <b>{len({fid for fid, _ in self.cell_flags})}</b> "
            f"row(s); <b>{n_open}</b> with flags not checked yet. Orange: flagged; grey: its flags are checked; blue: "
            f"corrected. Select a value for its issues and the table or figure it came from; double-click to "
            f"correct it, or select several and use Change selected values…")

    # ---- a cell ----------------------------------------------------------------------------------------------------
    def _cell_of(self, r: int, c: int):
        item = self.table.item(r, c)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return (data[0], data[1]) if data else None

    def _show_cell(self, r: int, c: int) -> None:
        cell = self._cell_of(r, c)
        self._cell = cell
        self._cell_html = self._this_value(cell) if cell else ""
        self.flag_list.blockSignals(True)
        self.flag_list.clear()
        for flag, key in (self.cell_flags.get(cell, []) if cell else []):
            merged = _split_merged(flag.message or "")[1]
            item = QListWidgetItem(kind_label(flag.kind) + (f"  (also: {', '.join(kind_label(k) for k, _m in merged)})"
                                                            if merged else ""))
            item.setToolTip(flag.message.splitlines()[0][:400])
            item.setData(Qt.ItemDataRole.UserRole, (flag, key))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in self.checked else Qt.CheckState.Unchecked)
            self.flag_list.addItem(item)
        self.flag_list.blockSignals(False)
        if self.flag_list.count():
            self._shown_flag = None
            self.flag_list.setCurrentRow(0)
        else:
            self._shown_flag = None
            self.details.setHtml(DETAILS_STYLE + self._cell_html
                                 + ("<p class='more'>No flags on this value.</p>" if cell else ""))
            self._show_place(None)

    def _show_flag(self, item) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not data:
            return
        if data[0] is not self._shown_flag:
            self._whole_flag = False
        self._shown_flag = data[0]
        self._render_details()
        self._show_place(data[0])

    def _details_link(self, url) -> None:
        if url.toString() == "#whole":
            self._whole_flag = not self._whole_flag
            self._render_details()

    def _render_details(self) -> None:
        flag = self._shown_flag
        if flag is None:
            return
        cell = self._cell if self._cell in self.cell_flags and any(
            f is flag for f, _k in self.cell_flags.get(self._cell, [])) else None
        self.details.setHtml(DETAILS_STYLE + self._flag_html(flag, cell) + (self._cell_html if cell else ""))

    def _flag_html(self, flag, cell) -> str:
        """A flag in plain words: the part about this value (a grouped flag lists several), the other flags merged
        into it, and its quote and location when they are this value's."""
        main, merged = _split_merged(flag.message or "")
        o = self.cell_info.get(cell) or {} if cell else {}
        hints = self._cell_hints(cell) if cell else ([], [])
        parts, hidden = [], 0
        text, left = (main, 0) if self._whole_flag or not cell else _about(main, *hints)
        hidden = max(hidden, left)
        parts.append(f"<h3>{escape(kind_label(flag.kind))}</h3><p>{_html_text(text)}</p>")
        # the flag's quote and location: shown when they add something -- not when they are this value's own (shown
        # above), and another value's only with the whole flag
        quote = flag.quote or flag.table_image_quote or flag.unverified_quote or ""
        where = ", ".join(x for x in (flag.source or "", f"p. {flag.page}" if flag.page else "") if x)
        cell_quote = ft._norm_text(o.get("quote", ""))
        same_quote = bool(cell_quote) and ft._norm_text(quote) == cell_quote
        own = not cell or not cell_quote or ft._quote_matches(cell_quote, ft._norm_text(quote))
        cell_where = ", ".join(x for x in (re.sub(r"\s*\[[^\]]*\]", "", o.get("source", "")),
                                           f"p. {o['page']}" if o.get("page") else "") if x)
        rows = []
        if quote and not same_quote and (own or self._whole_flag):
            label = "Flag's quote" if own else "Flag's quote (another value's)"
            rows.append((label, f"<i>“{escape(quote)}”</i>" + (" -- not found word for word in the paper"
                                                              if quote == flag.unverified_quote else "")))
        if where and ft._norm_text(where) != ft._norm_text(cell_where) and (own or self._whole_flag or not quote):
            rows.append(("Flag's location", escape(where)))
        if rows:
            parts.append(_table(rows))
        for kind, msg in merged:
            text, left = (msg, 0) if self._whole_flag or not cell else _about(msg, *hints)
            hidden = max(hidden, left)
            parts.append(f"<h4>Also flagged: {escape(kind_label(kind))}</h4><p>{_html_text(text)}</p>")
        if hidden or self._whole_flag:
            parts.append("<p class='more'>" + (f"This flag also lists {hidden} other value(s). "
                                               "<a href='#whole'>Show the whole flag</a>" if not self._whole_flag
                                               else "<a href='#whole'>Show only the part about this value</a>")
                         + "</p>")
        return "".join(parts)

    def _cell_hints(self, cell) -> Tuple[List[str], List[str]]:
        """What identifies this value in a flag's text: its set's label, its quote's numbers."""
        from parameter_extractor.ingestion.table_locate import numbers_in
        labels = []
        n = (self.cell_info.get(cell) or {}).get("set_id", "")[-3:]
        plan = ft.plan_set_labels(self.result.run_dir)
        if n.isdigit() and 0 < int(n) <= len(plan):
            labels.append(plan[int(n) - 1])
        quote = (self.cell_info.get(cell) or {}).get("quote", "")
        return labels, [f"{x:g}" for x in numbers_in(quote)]

    def _this_value(self, cell) -> str:
        """The selected cell's own value, quote and location (from the observations file)."""
        o = self.cell_info.get(cell) or {}
        row = next((r for r in self.rows if r.get("full_id") == cell[0]), {})
        value = row.get(cell[1], "")
        rows = [("Column", f"<b>{escape(cell[1])}</b>"),
                ("Row", escape(cell[0]) + (f" -- set {escape(row.get('set_id', ''))}, sample "
                                           f"{escape(row.get('sample_id', ''))}" if row.get("set_id") else "")),
                ("Value", (f"<b>{escape(value)}</b>" if value else "<i>empty</i>")
                 + (f" (corrected; extracted as {escape(o['extracted_value'])})" if o.get("extracted_value") else ""))]
        if o.get("quote"):
            check = {"no": " -- not found word for word in the paper", "table image": " -- read from the table image"}
            rows.append(("Quote", f"<i>“{escape(o['quote'])}”</i>{check.get(o.get('quote_in_paper', ''), '')}"))
        source = o.get("source", "")
        notes = re.findall(r"\[([^\]]*)\]", source)
        where = ", ".join(x for x in (re.sub(r"\s*\[[^\]]*\]", "", source), f"p. {o['page']}" if o.get("page") else "")
                          if x)
        if where:
            rows.append(("Where", escape(where)))
        for note in notes:
            rows.append(("Note", escape(note)))
        return "<div class='value'><h4>This value</h4>" + _table(rows) + "</div>"

    def _saved_table(self, text: str):
        """The tables.json entry of the first saved table `text` names."""
        for m in _PLACE.finditer(text or ""):
            if m.group(1).lower().startswith("table"):
                for t in self.result.tables or []:
                    if str(t.get("table_id", "")).lower() == f"table {m.group(2)}".lower() and t.get("image") and \
                            Path(t["image"]).is_file():
                        return t
        return None

    def _image_for(self, flag, cell=None) -> Tuple[Optional[str], str, Optional[dict]]:
        """(image path, caption, tables.json entry) of the saved table the value's own location names, else the saved
        table / figure the flag's location names, else the flag's page render."""
        own = self._saved_table((self.cell_info.get(cell) or {}).get("source", "")) if cell else None
        if own is not None:
            return own["image"], f"{own['table_id']} (as saved with the run)", own
        if flag is None:
            return None, "", None
        text = " ".join(x for x in (flag.source or "", flag.message or "") if x)
        m = _PLACE.search(text)
        if m:
            kind, number = m.group(1).lower(), m.group(2)
            if kind.startswith("table"):
                t = self._saved_table(text)
                if t is not None:
                    return t["image"], f"{t['table_id']} (as saved with the run)", t
            else:
                for f in self.result.figures or []:
                    if str(f.get("figure_id", "")).lower() == f"fig. {number}".lower():
                        image = f.get("annotated_image") or f.get("image")
                        if image and Path(image).is_file():
                            return image, f"{f['figure_id']} (as saved with the run)", None
        if flag.page:
            page = Path(self.result.run_dir) / "page_images" / f"page-{flag.page}.jpg"
            pieces = sorted(page.parent.glob(f"page-{flag.page}*.jpg")) if page.parent.is_dir() else []
            if pieces:
                return str(pieces[0]), f"page {flag.page} of the paper", None
        return None, "", None

    def _show_place(self, flag) -> None:
        self._flag = flag
        self._refresh_place()

    def _refresh_place(self) -> None:
        cell = self._cell
        path, caption, entry = self._image_for(self._flag, cell)
        self.zoom_bar.setVisible(bool(path))
        if not path:
            self._pixmap, self.image_path, self._image_entry, self._boxes = None, None, None, []
            self.image.clear()
            self.image_caption.setText("<span style='color:gray'>No saved table or figure for this flag's "
                                       "location.</span>" if self._flag is not None else "")
            return
        if path != self.image_path:
            self.image_path = path
            self._pixmap = QPixmap(path)
        self._image_entry = entry
        self._boxes, note = self._marks(cell, entry)
        self.image_caption.setText(f"<b>{escape(caption)}</b>" + (f"<br><span style='color:gray'>{escape(note)}"
                                                                   f"</span>" if note else ""))
        self._render_image(scroll=True)

    def _marks(self, cell, entry) -> Tuple[list, str]:
        """Boxes on the table image for the value `cell` (its own location must be this table), and a note."""
        if cell is None or entry is None:
            return [], ""
        o = self.cell_info.get(cell) or {}
        if self._saved_table(o.get("source", "")) is not entry:
            return [], ""
        words = self._words_of(entry)
        if words.problem:
            return [], f"Not marked: {words.problem}."
        from parameter_extractor.ingestion.table_locate import locate
        boxes, how = locate(words.words, o.get("extracted_value") or o.get("value", ""), o.get("quote", ""))
        name = f"{cell[1]} of row {cell[0]}"
        if not boxes:
            return [], f"{name}: not found in the table's text layer -- look for it by eye."
        return boxes, f"{name}: boxed where the table's text has {how}" + \
            (f" ({len(boxes)} places)" if len(boxes) > 1 else "") + "."

    def _words_of(self, entry):
        from parameter_extractor.ingestion.table_locate import TableWords
        key = entry.get("table_id", "")
        if key not in self._table_words:
            pdf = self._pdf_for(entry)
            words = TableWords(pdf, entry) if pdf else None
            if words is None:
                from types import SimpleNamespace
                words = SimpleNamespace(words=[], problem="the paper's PDF isn't where the run read it")
            self._table_words[key] = words
        return self._table_words[key]

    def _pdf_for(self, entry) -> Optional[Path]:
        import json
        try:
            pdf = Path(json.loads((Path(self.result.run_dir) / "source.json").read_text()).get("pdf") or "")
        except (OSError, ValueError):
            return None
        if not pdf.is_file():
            return None
        if str(entry.get("page_label", "")).startswith("S"):        # a supplement's table: its own PDF
            from parameter_extractor.ingestion.supplements import find_supplements
            found = find_supplements(pdf)
            return found[0] if found else None
        return pdf

    def current_zoom(self) -> float:
        """The zoom in use: 1.0 = the image's own pixels at the screen's logical size."""
        if self.zoom is not None:
            return self.zoom
        pix = getattr(self, "_pixmap", None)
        if pix is None or pix.isNull() or not pix.width():
            return 1.0
        return max(0.1, (self.image_scroll.viewport().width() - 8) / pix.width())

    def set_zoom(self, zoom: Optional[float]) -> None:
        self.zoom = None if zoom is None else max(0.1, min(6.0, zoom))
        self._render_image()

    def zoom_by(self, step: int) -> None:
        now = self.current_zoom()
        if step > 0:
            self.set_zoom(next((z for z in ZOOM_STEPS if z > now * 1.01), ZOOM_STEPS[-1]))
        else:
            self.set_zoom(next((z for z in reversed(ZOOM_STEPS) if z < now * 0.99), ZOOM_STEPS[0]))

    def _render_image(self, scroll: bool = False) -> None:
        pix = getattr(self, "_pixmap", None)
        if pix is None or pix.isNull():
            return
        if self._boxes:
            pix = QPixmap(pix)                        # the saved image stays as it is
            painter = QPainter(pix)
            painter.setPen(QPen(MARK_PEN, 3))
            painter.setBrush(MARK_FILL)
            for x0, y0, x1, y1 in self._boxes:
                painter.drawRect(int(x0) - 4, int(y0) - 3, int(x1 - x0) + 8, int(y1 - y0) + 6)
            painter.end()
        zoom = self.current_zoom()
        ratio = self.devicePixelRatioF() or 1.0         # sharp on Retina screens: scaled in device pixels
        scaled = pix.scaledToWidth(max(1, int(pix.width() * zoom * ratio)), Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self.image.setPixmap(scaled)
        self.zoom_label.setText(f"{zoom:.0%}" + (" (fit width)" if self.zoom is None else ""))
        if scroll and self._boxes:                    # the first mark in view (zoomed in, it can be off-screen)
            x0, y0, x1, y1 = self._boxes[0]
            self.image.adjustSize()
            self.image_scroll.ensureVisible(int((x0 + x1) / 2 * zoom), int((y0 + y1) / 2 * zoom), 120, 80)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.zoom is None:
            self._render_image()

    def _toggle_everywhere(self, on: bool) -> None:
        self.everywhere_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.everywhere_list.setVisible(on and bool(self.everywhere))

    def _set_review_all(self, on: bool) -> None:
        self.review_all = on
        self.review_all_btn.setText("Back to the pared-down table" if on else "Review all")
        self._load()

    def _everywhere_selected(self, item) -> None:
        """A flag on every row: its details; in Review all, its values selected in the table (to change together)."""
        self._cell_html = ""
        self._show_flag(item)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not data or not self.review_all:
            return
        cells = next((c for f, k, _cols, c in self.everywhere if k == data[1]), set())
        self.select_cells(cells)

    def select_cells(self, cells) -> None:
        t = self.table
        model, selection = t.model(), QItemSelection()
        for r in range(t.rowCount()):
            for c in range(t.columnCount()):
                if self._cell_of(r, c) in cells:
                    index = model.index(r, c)
                    selection.select(index, index)
        t.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def selected_cells(self) -> List[Tuple[str, str, str]]:
        """(row, column, value shown) of the selected values that can be changed (not the row ids)."""
        out = []
        for item in self.table.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data[1] not in corr.FIXED_COLUMNS:
                out.append(tuple(data))
        return out

    def _selection_changed(self) -> None:
        n = len(self.selected_cells())
        self.change_btn.setEnabled(n > 0)
        self.change_btn.setText(f"Change {n} selected values…" if n > 1 else "Change selected values…")

    def _table_menu(self, pos) -> None:
        cells = self.selected_cells()
        if not cells:
            return
        menu = QMenu(self)
        menu.addAction(f"Change {len(cells)} selected value(s)…", self.change_selected)
        corrected = [c for c in cells if (c[0], c[1]) in self.corrected]
        if corrected:
            menu.addAction(f"Revert {len(corrected)} corrected value(s) to the extracted value",
                           lambda: self.revert_cells(corrected))
        keys = {key for fid, col, _b in cells for _f, key in self.cell_flags.get((fid, col), [])}
        if keys - self.checked:
            menu.addAction(f"Tick the flags of the selected value(s) ({len(keys - self.checked)})",
                           lambda: self.tick_keys(keys))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def change_selected(self) -> None:
        cells = self.selected_cells()
        if not cells:
            return
        dialog = ChangeValuesDialog(cells, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        problems = self.change_cells(cells, dialog.edit.text(), dialog.note.text().strip())
        if problems:
            QMessageBox.warning(self, "Not a valid value",
                                "Nothing was changed:\n" + "\n".join(f"- {p}" for p in problems[:12]))

    def change_cells(self, cells, text: str, note: str = "") -> List[str]:
        """Give every cell `text` (checked against each column first: one bad column changes nothing). Returns the
        problems."""
        stored, problems = {}, []
        for column in sorted({col for _f, col, _b in cells}):
            value, problem = corr.stored_value(column, text, self.registry)
            if problem:
                problems.append(f"{column}: {problem}")
            stored[column] = value
        if problems:
            return problems
        for full_id, column, before in cells:
            if stored[column] != before:
                corr.correct(self.result.run_dir, full_id, column, before, stored[column], note=note or None)
        self.changed = True
        self._load()
        self.on_changed()
        return []

    def revert_cells(self, cells) -> None:
        for full_id, column, _before in cells:
            corr.revert(self.result.run_dir, full_id, column)
        self.changed = True
        self._load()
        self.on_changed()

    def tick_keys(self, keys) -> None:
        self.checked |= set(keys)
        corr.save_checked(self.result.run_dir, self.checked)
        self.changed = True
        self._load()
        self.on_changed()

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
        n_open = sum(k not in self.checked for _f, k, _c, _cells in self.everywhere)
        self.everywhere_toggle.setText(f"On every row ({len(self.everywhere)}, {n_open} not checked yet)")
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
