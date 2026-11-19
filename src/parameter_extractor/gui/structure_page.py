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

RESERVED = {"figure", "assumed"}


class StructurePage(QWidget):
    def __init__(self, manifest: dict, pack=None, set_edit: Optional[QLineEdit] = None,
                 sample_edit: Optional[QLineEdit] = None, parent=None):
        super().__init__(parent)
        self.manifest = manifest
        self._set_edit, self._sample_edit = set_edit, sample_edit
        self._syncing = False
        v = QVBoxLayout(self)
        intro = QLabel(
            "<b>How this research area's data is organised.</b> Each paper is divided into groups of rows, and each "
            "group into rows (the rows of the dataset). Every kind of value is recorded for one of these: the "
            "<i>paper</i> (the title, the authors), each <i>group</i> (how its experiments were set up) or each "
            "<i>row</i> (what was measured). <span style='color:gray'>A value recorded for a group is stored once "
            "when all its rows share it, and per row when they differ; one recorded for each row always stays with "
            "its row. This decides how results are arranged in the results tab named after your groups and in the "
            "nested record (JSON); the dataset table has the same values whatever you choose.</span>", wordWrap=True,
            textFormat=Qt.TextFormat.RichText)
        v.addWidget(intro)
        names = QFormLayout()
        units = manifest.get("units", {})
        self.group_word = QLineEdit(units.get("set", "set"))
        self.row_word = QLineEdit(units.get("sample", "sample"))
        names.addRow("A paper is divided into (one group is called):", self.group_word)
        names.addRow("Each group holds (one row is called):", self.row_word)
        v.addLayout(names)
        for mine, theirs in ((self.group_word, set_edit), (self.row_word, sample_edit)):
            mine.textChanged.connect(lambda _t: self._words_changed())
            if theirs is not None:                    # the General tab's same words
                mine.textChanged.connect(lambda t, w=theirs: self._sync(w, t))
                theirs.textChanged.connect(lambda t, w=mine: self._sync(w, t))
        self.picture = QLabel(textFormat=Qt.TextFormat.RichText, wordWrap=True)
        v.addWidget(self.picture)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Kind of value", "Recorded for", "If only some rows give it",
                                              "Comes from"])
        self.table.horizontalHeaderItem(2).setToolTip(
            "Papers often state a method or condition once, for one experiment. Fill in: the rows that don't give it "
            "get the value the others agree on (marked as assumed, and listed under Things to check). Never filled "
            "when the rows that give it disagree.")
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3):
            head.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)
        # single columns with a setting of their own (a time that differs per row is never filled in)
        v.addWidget(QLabel("<b>Single values with their own setting</b> <span style='color:gray'>(over their kind's; "
                           "e.g. a duration, which differs from row to row, is never filled in)</span>",
                           textFormat=Qt.TextFormat.RichText, wordWrap=True))
        self.columns = QTableWidget(0, 3)
        self.columns.setHorizontalHeaderLabels(["Value (column)", "If only some rows give it", ""])
        self.columns.verticalHeader().setVisible(False)
        ch = self.columns.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.columns.setMaximumHeight(170)
        v.addWidget(self.columns)
        add = QHBoxLayout()
        self.new_column = QLineEdit(placeholderText="a column's name, e.g. stirring_rate_rpm")
        self.add_column_btn = QPushButton("Add", clicked=self._add_column)
        add.addWidget(self.new_column, 1)
        add.addWidget(self.add_column_btn)
        v.addLayout(add)
        self.fill_note = QLabel(wordWrap=True)
        self.fill_note.setStyleSheet("color: gray;")
        v.addWidget(self.fill_note)
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
            for col, choices in ((1, self._level_choices()), (2, self._fill_choices())):
                combo = self.table.cellWidget(r, col)
                if combo is not None:
                    for i, (_v, text) in enumerate(choices):
                        combo.setItemText(i, text)
        for r in range(self.columns.rowCount()):
            combo = self.columns.cellWidget(r, 1)
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
        self.table.setRowCount(len(self._kinds))
        for r, k in enumerate(self._kinds):
            name = QTableWidgetItem(k["label"])
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setToolTip(k["description"] or k["id"])
            self.table.setItem(r, 0, name)
            combo = QComboBox()
            for lv, text in self._level_choices():
                combo.addItem(text, lv)
            combo.setCurrentIndex(max(combo.findData(k["level"]), 0))
            combo.currentIndexChanged.connect(lambda _i, r=r, c=combo: self._moved(r, c.currentData()))
            self.table.setCellWidget(r, 1, combo)
            fill = QComboBox()
            for f, text in self._fill_choices():
                fill.addItem(text, f)
            fill.setCurrentIndex(max(fill.findData(k["fill"]), 0))
            fill.currentIndexChanged.connect(lambda _i, r=r, c=fill: self._fill_set(r, c.currentData()))
            fill.setEnabled(not self._patterns)
            self.table.setCellWidget(r, 2, fill)
            origin = QTableWidgetItem(k["origin"])
            origin.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 3, origin)
        self.fill_note.setText("This data pack chooses the values to fill in by name patterns (pack.json "
                               "shared_columns / group_columns): edit them there." if self._patterns else "")
        self._draw()

    def _fill_set(self, row: int, fill: str) -> None:
        self._kinds[row]["fill"] = fill
        self.fill_changed = True

    def _fill_columns(self) -> None:
        self.columns.setRowCount(len(self._column_fill))
        for r, (column, fill) in enumerate(sorted(self._column_fill.items())):
            name = QTableWidgetItem(column)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.columns.setItem(r, 0, name)
            combo = QComboBox()
            for f, text in self._fill_choices():
                combo.addItem(text, f)
            combo.setCurrentIndex(max(combo.findData(fill), 0))
            combo.currentIndexChanged.connect(lambda _i, col=column, c=combo: self._column_set(col, c.currentData()))
            combo.setEnabled(not self._patterns)
            self.columns.setCellWidget(r, 1, combo)
            remove = QPushButton("Remove", clicked=lambda _c=False, col=column: self._remove_column(col))
            remove.setEnabled(not self._patterns)
            self.columns.setCellWidget(r, 2, remove)

    def _column_set(self, column: str, fill: str) -> None:
        self._column_fill[column] = fill
        self.fill_changed = True

    def _remove_column(self, column: str) -> None:
        self._column_fill.pop(column, None)
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
