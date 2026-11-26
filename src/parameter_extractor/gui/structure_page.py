"""
The data pack editor's Structure tab (branch levels-and-facets, step 2): how this research area's data is organised, in
words and a small picture -- a paper holds its sets ('experiment sets', 'planetary systems'), a set holds its rows
('samples', 'planets') -- and, for every kind of value (the variable categories), what it is recorded for: the paper,
each set, or each row. Changing a kind's level is a dropdown; the level words are the same as on the General tab.

What it changes is how the values are grouped in the nested record (record_tree.py) and the Experiment sets results
tab; the dataset CSV is the same whatever is chosen. The pack's own categories keep their level in their entry
(`level`); a module's or a shared one's level for this pack goes into `category_levels`.
"""
from __future__ import annotations

import html
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from parameter_extractor.gui.widgets import clear_cell_widgets, in_cell as _in_cell

RESERVED = {"figure", "assumed"}
FILL_WIDTH = 330                 # the 'If only some rows give it' column, the same in both tables (they line up)


def _section(title: str, hint: str, help_text: str) -> QWidget:
    """A section's title (with a '?' holding the details) and a one-line hint under it."""
    from parameter_extractor.gui.pack_windows import HelpButton
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 2)
    v.setSpacing(1)
    row = QHBoxLayout()
    label = QLabel(title)
    font = label.font()
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 1.12)
    label.setFont(font)
    row.addWidget(label)
    if help_text:
        row.addWidget(HelpButton(help_text))
    row.addStretch(1)
    v.addLayout(row)
    if hint:
        note = QLabel(hint, wordWrap=True)
        note.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(note)
    return w


class StructurePage(QWidget):
    K_NAME, K_FROM, K_LEVEL, K_FILL = range(4)    # the kinds-of-value table's columns
    V_NAME, V_FILL = range(2)                     # the single values' table

    @staticmethod
    def _table_style(table: QTableWidget, widths: dict) -> None:
        """Name first (stretched), the given fixed widths, the fill column last at FILL_WIDTH; a vertical scroll bar
        always there, so both tables' last columns end at the same place."""
        from parameter_extractor.gui.widgets import style_rows
        table.verticalHeader().setVisible(False)
        style_rows(table)
        head = table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for c in range(1, table.columnCount()):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(c, widths.get(c, FILL_WIDTH))
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

    def __init__(self, manifest: dict, pack=None, set_edit: Optional[QLineEdit] = None,
                 sample_edit: Optional[QLineEdit] = None, parent=None):
        super().__init__(parent)
        self.manifest = manifest
        self._set_edit, self._sample_edit = set_edit, sample_edit
        self._syncing = False
        v = QVBoxLayout(self)
        v.setSpacing(6)
        # laid out in three sections (2026-11-26, Mickey: a block of text and two tables whose 'If only some rows
        # give it' columns didn't line up): the levels, beside their picture; each kind of value; single values. The
        # fill column is the last one of both tables, the same width, so the two line up.
        v.addWidget(_section(
            "Levels", "A paper is divided into groups of rows; each group holds rows -- the rows of the dataset.",
            "Every kind of value is recorded for one of three levels: the paper (the title, the authors), each group "
            "(how its experiments were set up) or each row (what was measured). The words are the same as on the "
            "General tab."))
        levels = QHBoxLayout()
        levels.setSpacing(24)
        names = QFormLayout()
        names.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        units = manifest.get("units", {})
        self.group_word = QLineEdit(units.get("set", "set"))
        self.row_word = QLineEdit(units.get("sample", "sample"))
        names.addRow("One group of rows is called:", self.group_word)
        names.addRow("One row is called:", self.row_word)
        names_box = QVBoxLayout()                     # the two words at the top, whatever the picture's height
        names_box.addLayout(names)
        names_box.addStretch(1)
        levels.addLayout(names_box, 2)
        for mine, theirs in ((self.group_word, set_edit), (self.row_word, sample_edit)):
            mine.textChanged.connect(lambda _t: self._words_changed())
            if theirs is not None:                    # the General tab's same words
                mine.textChanged.connect(lambda t, w=theirs: self._sync(w, t))
                theirs.textChanged.connect(lambda t, w=mine: self._sync(w, t))
        self.picture = QLabel(textFormat=Qt.TextFormat.RichText, wordWrap=True)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignTop)
        levels.addWidget(self.picture, 3)
        v.addLayout(levels)
        v.addSpacing(14)

        v.addWidget(_section(
            "What each kind of value is recorded for",
            "Recorded for: the level it belongs to. If only some rows give it: leave the others empty, or fill them "
            "in from their group or from the whole paper.",
            "A value recorded for a group is stored once when all its rows share it, and per row when they differ; "
            "one recorded for each row always stays with its row. This decides how results are arranged in the "
            "results tab named after your groups and in the nested record (JSON); the dataset table has the same "
            "values whatever you choose.\n\nFilling in: papers often state a method or condition once, for one "
            "experiment. The rows that don't give it get the value the others agree on (marked as assumed, and "
            "listed under Things to check); never filled when the rows that give it disagree."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Kind of value", "Comes from", "Recorded for",
                                              "If only some rows give it"])
        self.table.horizontalHeaderItem(self.K_FILL).setToolTip(
            "Papers often state a method or condition once, for one experiment. Fill in: the rows that don't give it "
            "get the value the others agree on (marked as assumed, and listed under Things to check). Never filled "
            "when the rows that give it disagree.")
        self._table_style(self.table, {self.K_FROM: 230, self.K_LEVEL: 210})
        v.addWidget(self.table, 1)
        v.addSpacing(14)

        # single columns with a setting of their own (a time that differs per row is never filled in)
        v.addWidget(_section(
            "Single values with their own setting",
            "A column that shouldn't follow its kind's setting -- e.g. a duration, which differs from row to row, is "
            "never filled in.", ""))
        self.columns = QTableWidget(0, 2)
        self.columns.setHorizontalHeaderLabels(["Value (column)", "If only some rows give it"])
        self._table_style(self.columns, {})
        self.columns.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.columns.setMaximumHeight(150)
        v.addWidget(self.columns)
        add = QHBoxLayout()
        self.new_column = QLineEdit(placeholderText="a column's name, e.g. stirring_rate_rpm")
        self.new_column.returnPressed.connect(self._add_column)
        self.add_column_btn = QPushButton("Add", clicked=self._add_column)
        self.remove_column_btn = QPushButton("Remove selected", clicked=self._remove_selected)
        add.addWidget(self.new_column, 1)
        add.addWidget(self.add_column_btn)
        add.addSpacing(12)
        add.addWidget(self.remove_column_btn)
        v.addLayout(add)
        self.fill_note = QLabel(wordWrap=True)
        self.fill_note.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.fill_note)
        v.addSpacing(6)
        # advanced: how many levels a paper's record may have (Mickey, 2026-11-18: four by default, an override)
        from parameter_extractor import record_tree
        self.advanced_btn = QToolButton(text="Advanced", checkable=True)
        self.advanced_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_btn.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.advanced = QWidget()
        av = QFormLayout(self.advanced)
        self.level_limit = QSpinBox(minimum=record_tree.MAX_LEVELS, maximum=12)
        self.level_limit.setValue(max(int(manifest.get("level_limit") or 0), record_tree.MAX_LEVELS))
        self.level_limit.setToolTip("A paper's record has the paper, its groups and their rows -- and, where a group "
                                    "holds several separate experiments each sampled over time, a run between them "
                                    f"(four levels). Raise this only for a research area that needs more.")
        av.addRow("Most levels a paper's record may have:", self.level_limit)
        av.addRow(QLabel("<span style='color:gray'>The levels come from each paper's row plan: the paper, its "
                         "groups, a run where a group holds several experiments each sampled over time, and the "
                         "rows.</span>", textFormat=Qt.TextFormat.RichText, wordWrap=True))
        self.advanced.setVisible(False)
        self.advanced_btn.toggled.connect(lambda on: (self.advanced.setVisible(on), self.advanced_btn.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)))
        v.addWidget(self.advanced_btn)
        v.addWidget(self.advanced)
        self._kinds: List[dict] = []
        self._column_fill: Dict[str, str] = {}
        self.fill_changed = False
        self.load(pack)

    # ---- the words ----------------------------------------------------------------------------------------------

    def combo(self, row: int, column: int, table: Optional[QTableWidget] = None) -> Optional[QComboBox]:
        """The dropdown in a cell of the kinds table (or `table`): held centred in its row (widgets.in_cell)."""
        holder = (table or self.table).cellWidget(row, column)
        return holder if isinstance(holder, QComboBox) or holder is None else holder.findChild(QComboBox)

    def _sync(self, widget: QLineEdit, text: str) -> None:
        if self._syncing or widget.text() == text:
            return
        self._syncing = True
        try:
            widget.setText(text)
        finally:
            self._syncing = False

    def _words(self):
        return self.group_word.text().strip() or "set", self.row_word.text().strip() or "sample"

    def _level_choices(self):
        group, row = self._words()
        return [("paper", "the paper"), ("set", f"each {group}"), ("sample", f"each {row}")]

    def _fill_choices(self):
        group, row = self._words()
        return [("none", "leave the others empty"), ("set", f"fill in from its {group} (or figure / table)"),
                ("paper", "fill in across the paper")]

    def _words_changed(self) -> None:
        for r in range(self.table.rowCount()):
            for col, choices in ((self.K_LEVEL, self._level_choices()), (self.K_FILL, self._fill_choices())):
                combo = self.combo(r, col)
                if combo is not None:
                    for i, (_v, text) in enumerate(choices):
                        combo.setItemText(i, text)
        for r in range(self.columns.rowCount()):
            combo = self.combo(r, self.V_FILL, self.columns)
            if combo is not None:
                for i, (_v, text) in enumerate(self._fill_choices()):
                    combo.setItemText(i, text)
        self._draw()

    # ---- the kinds of value ---------------------------------------------------------------------------------------

    def load(self, pack=None) -> None:
        """The pack's categories as saved (its modules' and the shared ones included), each with its level here."""
        from parameter_extractor import variable_categories as vc
        own = {c.get("id"): c for c in self.manifest.get("variable_categories", [])}
        chosen = dict(self.manifest.get("category_levels") or {})
        module_of: Dict[str, str] = {}
        cats = []
        if pack is not None:
            for mod in getattr(pack, "modules", []) or []:
                for c in mod.manifest.variable_categories:
                    module_of.setdefault(c.get("id"), mod.label)
            try:
                cats = [c for c in vc.categories(pack) if c.id not in RESERVED]
            except Exception:                         # noqa: BLE001 -- a pack that can't load: its own only
                cats = []
        if not cats:
            cats = [vc.VariableCategory(**c) for c in own.values()]
        from parameter_extractor.calculators import shared_values
        fills, self._column_fill = {}, {}
        self._patterns = False
        if pack is not None:
            fills, self._column_fill = shared_values.fill_choices(pack)
            legacy = not shared_values.uses_fill_settings(pack.own_manifest)
            self._patterns = legacy and any((pack.manifest.shared_columns or {}).get("patterns") or
                                            (pack.manifest.group_columns or {}).get("patterns") for _ in [0])
        self._kinds = []
        for c in cats:
            if c.id in own:
                origin, default = "this data pack", own[c.id].get("level", "")
            elif c.id in module_of:
                origin, default = f"module: {module_of[c.id]}", c.level
            else:
                origin, default = "every data pack (shared)", c.level
            self._kinds.append({"id": c.id, "label": c.label, "description": c.description, "origin": origin,
                                "own": c.id in own, "default": default or "sample",
                                "level": chosen.get(c.id) or (own[c.id].get("level") if c.id in own else "")
                                or default or "sample",
                                "fill": fills.get(c.id) or "none"})
        self._fill()
        self._fill_columns()

    # ---- one kind of value, from the Columns tab's category panel (gui/category_panel.py) ----------------------------

    def kind(self, cid: str) -> Optional[dict]:
        """A kind of value's entry here (id, label, level, fill, origin, own, ...), or None."""
        return next((k for k in self._kinds if k["id"] == cid), None)

    def level_choices(self):
        return self._level_choices()

    def fill_choices(self):
        return self._fill_choices()

    def fills_by_patterns(self) -> bool:
        """An older pack choosing the values to fill in by name patterns: its fill settings are edited in pack.json."""
        return self._patterns

    def set_kind(self, cid: str, **values) -> None:
        """Change a kind of value's level, fill or label here (the table follows)."""
        k = self.kind(cid)
        if k is None:
            return
        if "fill" in values and values["fill"] != k["fill"]:
            self.fill_changed = True
        k.update({f: v for f, v in values.items() if f in ("level", "fill", "label")})
        self._fill()

    def add_kind(self, cid: str, label: str) -> None:
        """A kind of value the pack has just been given (recorded for each row, not filled in)."""
        if self.kind(cid) is None:
            self._kinds.append({"id": cid, "label": label, "description": "", "origin": "this data pack",
                                "own": True, "default": "sample", "level": "sample", "fill": "none"})
            self._fill()

    def remove_kind(self, cid: str) -> None:
        self._kinds = [k for k in self._kinds if k["id"] != cid]
        self._fill()

    def _fill(self) -> None:
        clear_cell_widgets(self.table)                 # refilled in an open window: the old ones away now
        self.table.setRowCount(len(self._kinds))
        for r, k in enumerate(self._kinds):
            name = QTableWidgetItem(k["label"])
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setToolTip(k["description"] or k["id"])
            self.table.setItem(r, self.K_NAME, name)
            origin = QTableWidgetItem(k["origin"])
            origin.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.K_FROM, origin)
            combo = QComboBox()
            for lv, text in self._level_choices():
                combo.addItem(text, lv)
            combo.setCurrentIndex(max(combo.findData(k["level"]), 0))
            combo.currentIndexChanged.connect(lambda _i, r=r, c=combo: self._moved(r, c.currentData()))
            self.table.setCellWidget(r, self.K_LEVEL, _in_cell(combo))
            fill = QComboBox()
            for f, text in self._fill_choices():
                fill.addItem(text, f)
            fill.setCurrentIndex(max(fill.findData(k["fill"]), 0))
            fill.currentIndexChanged.connect(lambda _i, r=r, c=fill: self._fill_set(r, c.currentData()))
            fill.setEnabled(not self._patterns)
            self.table.setCellWidget(r, self.K_FILL, _in_cell(fill))
        self.fill_note.setText("This data pack chooses the values to fill in by name patterns (pack.json "
                               "shared_columns / group_columns): edit them there." if self._patterns else "")
        self._draw()

    def _fill_set(self, row: int, fill: str) -> None:
        self._kinds[row]["fill"] = fill
        self.fill_changed = True

    def _fill_columns(self) -> None:
        clear_cell_widgets(self.columns)               # refilled in an open window: the old ones away now
        self.columns.setRowCount(len(self._column_fill))
        for r, (column, fill) in enumerate(sorted(self._column_fill.items())):
            name = QTableWidgetItem(column)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.columns.setItem(r, self.V_NAME, name)
            combo = QComboBox()
            for f, text in self._fill_choices():
                combo.addItem(text, f)
            combo.setCurrentIndex(max(combo.findData(fill), 0))
            combo.currentIndexChanged.connect(lambda _i, col=column, c=combo: self._column_set(col, c.currentData()))
            combo.setEnabled(not self._patterns)
            self.columns.setCellWidget(r, self.V_FILL, _in_cell(combo))
        self.remove_column_btn.setEnabled(not self._patterns)

    def _column_set(self, column: str, fill: str) -> None:
        self._column_fill[column] = fill
        self.fill_changed = True

    def _remove_column(self, column: str) -> None:
        self._column_fill.pop(column, None)
        self.fill_changed = True
        self._fill_columns()

    def _remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.columns.selectedIndexes()}, reverse=True):
            item = self.columns.item(r, self.V_NAME)
            if item is not None:
                self._column_fill.pop(item.text(), None)
                self.fill_changed = True
        self._fill_columns()

    def _add_column(self) -> None:
        column = self.new_column.text().strip()
        if not column or self._patterns:
            return
        self._column_fill.setdefault(column, "none")
        self.fill_changed = True
        self.new_column.clear()
        self._fill_columns()

    def _moved(self, row: int, level: str) -> None:
        self._kinds[row]["level"] = level
        self._draw()

    def _draw(self) -> None:
        """The picture: the three levels, nested, each with the kinds of value recorded for it."""
        group, row = self._words()
        at = {lv: [k["label"] for k in self._kinds if k["level"] == lv] for lv in ("paper", "set", "sample")}
        def box(title: str, kinds: List[str], inner: str = "", indent: int = 0) -> str:
            listed = html.escape(", ".join(kinds)) if kinds else "<i>nothing recorded here</i>"
            return (f"<table cellspacing=0 cellpadding=6 width='100%' style='margin-left:{indent}px; "
                    f"border-left: 3px solid gray;'><tr><td><b>{html.escape(title)}</b><br>"
                    f"<span style='color:gray'>{listed}</span>{inner}</td></tr></table>")
        sample = box(f"Each {row} (one row of the dataset)", at["sample"], indent=22)
        group_box = box(f"Each {group}", at["set"], sample, indent=22)
        self.picture.setText(box("The paper", at["paper"], group_box))

    # ---- saving -------------------------------------------------------------------------------------------------

    def store(self, manifest: dict) -> None:
        """The choices into the manifest: a pack's own category keeps its level in its entry; another category's level
        for this pack goes into category_levels when it differs from the category's own."""
        from parameter_extractor import record_tree
        if self.level_limit.value() > record_tree.MAX_LEVELS:
            manifest["level_limit"] = self.level_limit.value()
        else:
            manifest.pop("level_limit", None)
        own = {c.get("id"): c for c in manifest.get("variable_categories", [])}
        levels = {}
        for k in self._kinds:
            if k["id"] in own:
                if k["level"] == "sample":
                    own[k["id"]].pop("level", None)
                else:
                    own[k["id"]]["level"] = k["level"]
            elif k["level"] != k["default"]:
                levels[k["id"]] = k["level"]
        if levels:
            manifest["category_levels"] = levels
        else:
            manifest.pop("category_levels", None)
        if not self.fill_changed or self._patterns:   # an older pack's lists stay as they are until a fill changes
            return
        fills = {}
        for k in self._kinds:
            if k["id"] in own:
                if k["fill"] in ("set", "paper"):
                    own[k["id"]]["fill"] = k["fill"]
                else:
                    own[k["id"]].pop("fill", None)
            elif k["fill"] in ("set", "paper"):
                fills[k["id"]] = k["fill"]
        for key, value in (("category_fill", fills), ("fill_columns", dict(sorted(self._column_fill.items())))):
            if value:
                manifest[key] = value
            else:
                manifest.pop(key, None)
        manifest.pop("shared_columns", None)          # replaced by the settings above
        manifest.pop("group_columns", None)
