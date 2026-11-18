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
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

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
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Kind of value", "Recorded for", "Comes from"])
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)
        self._kinds: List[dict] = []
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

    def _words_changed(self) -> None:
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, 1)
            if combo is not None:
                for i, (_lv, text) in enumerate(self._level_choices()):
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
                                or default or "sample"})
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
            origin = QTableWidgetItem(k["origin"])
            origin.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 2, origin)
        self._draw()

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
