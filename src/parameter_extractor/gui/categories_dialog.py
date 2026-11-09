"""
"Variable categories" (Variables menu; Mickey, 2026-11-03): create and edit the categories new variables are
sorted into, per data pack -- Standard (every pack) or one pack's own.

Each category: id, label, description (what the model is told it holds), value format (value_type), max words,
table order (where its block sits in the dataset, lower = further left) and whether the model may put
suggestions in it. The app's own categories can be edited but not renamed (id) or removed -- pack settings and
the stages refer to them by id; editing them changes the model's instructions, so it warns first. The user's
own categories can be removed. Saved in the registry file ("categories"); applied to later runs.
"""
from __future__ import annotations
import copy
import re
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (QAbstractItemView, QStyledItemDelegate, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from parameter_extractor import packs, variable_categories as vc
from parameter_extractor.gui.widgets import RowSeparatorDelegate, in_cell, style_rows
from parameter_extractor.registry import STANDARD, VariableRegistry, areas

FORMATS = {"number": "One number with a unit", "text": "Text", "any": "Number or text"}
FIELDS = ["id", "label", "description", "value_type", "max_words", "table_order", "model_assigns"]
HEADERS = ["ID", "Label", "Description", "Value format", "Max words", "Table order", "Model may assign", "Origin"]
C_ID, C_LABEL, C_DESC, C_FORMAT, C_WORDS, C_ORDER, C_MODEL, C_ORIGIN = range(8)
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
WARNING = ("The app's own categories are part of the instructions the model gets (labels, descriptions, formats) "
           "and decide where columns sit. Changing them can make extraction differ from the app's tested "
           "behaviour. Your own categories are offered to the model too when 'Model may assign' is ticked.")


class CategoriesDialog(QDialog):
    def __init__(self, registry_path: Optional[Path], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Variable categories")
        self.resize(1150, 520)
        self.path = Path(registry_path) if registry_path else None
        self.registry = VariableRegistry(self.path)
        self.edits: Dict[str, dict] = copy.deepcopy(self.registry.local_categories)
        self.packs = packs.available()
        self.builtin_confirmed = False
        self._filling = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Categories sort suggested new variables in the review and place columns in the dataset. Standard "
            "categories apply to every data pack; a data pack's own come first in its review.",
            wordWrap=True))
        warning = QLabel("⚠ " + WARNING, wordWrap=True)
        warning.setStyleSheet("color: #8a5a00;")
        layout.addWidget(warning)
        top = QHBoxLayout()
        top.addWidget(QLabel("Data pack:"))
        self.area_combo = QComboBox()
        for area, label in areas():
            self.area_combo.addItem(label, area)
        self.area_combo.setCurrentIndex(max(self.area_combo.findData(packs.current().id), 0))
        self.area = self.area_combo.currentData()
        self.area_combo.currentIndexChanged.connect(self._on_area)
        top.addWidget(self.area_combo)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(C_DESC, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        style_rows(self.table)                           # spaced rows, faint dividers, descriptions wrap
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)
        self.note = QLabel(wordWrap=True)
        self.note.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self.note)

        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Add category", clicked=self.add_category))
        buttons.addWidget(QPushButton("Remove", clicked=self._remove_selected))
        buttons.addWidget(QPushButton("Reset to default", clicked=self._reset_selected))
        buttons.addStretch(1)
        buttons.addWidget(QPushButton("Cancel", clicked=self.reject))
        self.save_btn = QPushButton("Save", clicked=self._save, default=True)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)
        self._fill()

    # ---- the area's categories ----------------------------------------------------

    def bundled(self, area: str) -> List[vc.VariableCategory]:
        return vc.bundled_shared() if area == STANDARD else vc.bundled_own(self.packs[area])

    def rows(self, area: Optional[str] = None) -> List[dict]:
        """The area's categories as edited so far: [{fields..., 'builtin': bool, 'changed': bool}]."""
        area = area or self.area
        edits = self.edits.get(area, {})
        out = []
        for c in self.bundled(area):
            changed = edits.get("changed", {}).get(c.id, {})
            row = {f: getattr(c, f) for f in FIELDS}
            row["model_assigns"] = c.assignable
            row.update({k: v for k, v in changed.items() if k in FIELDS})
            out.append(dict(row, builtin=True, changed=bool(changed)))
        for c in edits.get("added", []):
            row = {f: c.get(f) for f in FIELDS}
            row["model_assigns"] = c.get("model_assigns", True) is not False
            out.append(dict(row, builtin=False, changed=False))
        return out

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.table.resizeRowsToContents()          # the description column has its real width only now

    def _fill(self) -> None:
        self._filling = True
        try:
            rows = self.rows()
            t = self.table
            t.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, field in ((C_ID, "id"), (C_LABEL, "label"), (C_DESC, "description")):
                    item = QTableWidgetItem(str(row.get(field) or ""))
                    if c == C_ID and row["builtin"]:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setToolTip("The app's own categories keep their id: pack settings refer to it.")
                    if c == C_DESC:
                        item.setToolTip(item.text())
                    t.setItem(r, c, item)
                fmt = QComboBox()
                for key, label in FORMATS.items():
                    fmt.addItem(label, key)
                fmt.setCurrentIndex(max(fmt.findData(row.get("value_type") or "any"), 0))
                fmt.currentIndexChanged.connect(lambda _i, r=r: self._on_widget(r))
                t.setCellWidget(r, C_FORMAT, in_cell(fmt))
                for c, field, top in ((C_WORDS, "max_words", 200), (C_ORDER, "table_order", 10000)):
                    spin = QSpinBox(minimum=0, maximum=top)
                    spin.setValue(int(row.get(field) or 0) if row.get(field) is not None else
                                  (500 if field == "table_order" else 0))
                    if field == "max_words":
                        spin.setSpecialValueText("no limit")
                    spin.valueChanged.connect(lambda _v, r=r: self._on_widget(r))
                    t.setCellWidget(r, c, in_cell(spin))
                box = QCheckBox()
                box.setChecked(bool(row.get("model_assigns")))
                box.toggled.connect(lambda _on, r=r: self._on_widget(r))
                holder = QWidget()
                h = QHBoxLayout(holder)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(box, alignment=Qt.AlignmentFlag.AlignCenter)
                t.setCellWidget(r, C_MODEL, holder)
                origin = QTableWidgetItem("Built-in, changed" if row["changed"] else "Built-in" if row["builtin"]
                                          else "Yours")
                origin.setFlags(origin.flags() & ~Qt.ItemFlag.ItemIsEditable)
                t.setItem(r, C_ORIGIN, origin)
            t.resizeColumnsToContents()
            for c in (C_WORDS, C_ORDER):             # room for 'no limit' beside the arrows
                t.setColumnWidth(c, max(t.columnWidth(c), 110))
            t.setColumnWidth(C_DESC, max(t.columnWidth(C_DESC), 320))
            t.horizontalHeader().setSectionResizeMode(C_DESC, QHeaderView.ResizeMode.Stretch)
            t.resizeRowsToContents()
        finally:
            self._filling = False
        self.note.setText(
            "Shared categories (Metadata, Experimental Methodology, Other) are under Standard."
            if self.area != STANDARD else
            "These apply to every data pack (a data pack can replace one with its own of the same id).")

    def _read_row(self, r: int) -> dict:
        t = self.table
        model = t.cellWidget(r, C_MODEL).findChild(QCheckBox)
        return {"id": t.item(r, C_ID).text().strip(), "label": t.item(r, C_LABEL).text().strip(),
                "description": t.item(r, C_DESC).text().strip(),
                "value_type": t.cellWidget(r, C_FORMAT).findChild(QComboBox).currentData(),
                "max_words": t.cellWidget(r, C_WORDS).findChild(QSpinBox).value(),
                "table_order": t.cellWidget(r, C_ORDER).findChild(QSpinBox).value(),
                "model_assigns": model.isChecked()}

    def _on_item_changed(self, item) -> None:
        if not self._filling:
            self._on_widget(item.row())

    def _on_widget(self, r: int) -> None:
        if self._filling:
            return
        self.set_row(r, self._read_row(r))

    # ---- changes ------------------------------------------------------------------

    def set_row(self, r: int, values: dict) -> bool:
        """Apply the values of row `r` (all fields); asks before the first change to an app category."""
        rows = self.rows()
        if not 0 <= r < len(rows):
            return False
        row = rows[r]
        edits = self.edits.setdefault(self.area, {})
        if row["builtin"]:
            original = next(c for c in self.bundled(self.area) if c.id == row["id"])
            base = {f: getattr(original, f) for f in FIELDS}
            base["model_assigns"] = original.assignable
            diff = {f: values[f] for f in FIELDS[1:] if f in values and values[f] != base[f]}
            if diff != edits.get("changed", {}).get(row["id"], {}):
                if diff and not self.confirm_builtin_change():
                    self._fill()
                    return False
                changed = edits.setdefault("changed", {})
                if diff:
                    changed[row["id"]] = diff
                else:
                    changed.pop(row["id"], None)
        else:
            added = edits.setdefault("added", [])
            i = r - len(self.bundled(self.area))
            added[i] = {f: values.get(f, added[i].get(f)) for f in FIELDS}
        self._tidy(self.area)
        if row["builtin"]:
            self._fill()                    # the Origin column
        return True

    def _tidy(self, area: str) -> None:
        edits = self.edits.get(area, {})
        for k in [k for k, v in edits.items() if not v]:
            del edits[k]
        if not edits:
            self.edits.pop(area, None)

    def confirm_builtin_change(self) -> bool:
        if self.builtin_confirmed:
            return True
        answer = QMessageBox.warning(self, "Change one of the app's categories?", WARNING + "\n\nChange it anyway?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)
        self.builtin_confirmed = answer == QMessageBox.StandardButton.Yes
        return self.builtin_confirmed

    def add_category(self, values: Optional[dict] = None) -> None:
        taken = self.taken_ids(self.area)
        n = 1
        while f"new_category_{n}" in taken:
            n += 1
        row = {"id": f"new_category_{n}", "label": "New category", "description": "", "value_type": "any",
               "max_words": 12, "table_order": 500, "model_assigns": True}
        row.update(values or {})
        self.edits.setdefault(self.area, {}).setdefault("added", []).append(row)
        self._fill()
        self.table.setCurrentCell(self.table.rowCount() - 1, C_ID)

    def remove_row(self, r: int) -> bool:
        rows = self.rows()
        if not 0 <= r < len(rows) or rows[r]["builtin"]:
            return False
        self.edits[self.area]["added"].pop(r - len(self.bundled(self.area)))
        self._tidy(self.area)
        self._fill()
        return True

    def _remove_selected(self) -> None:
        r = self.table.currentRow()
        rows = self.rows()
        if not 0 <= r < len(rows):
            return
        if rows[r]["builtin"]:
            QMessageBox.information(self, "Can't remove", "The app's own categories can't be removed; you can "
                                    "change them, or untick 'Model may assign' so the model stops using it.")
            return
        used = [c for c, info in self.registry.all_columns.items() if info.get("category") == rows[r]["id"]]
        if used and QMessageBox.question(
                self, "Remove category", f"{len(used)} remembered column(s) are in '{rows[r]['label']}' "
                f"({', '.join(used[:5])}{' ...' if len(used) > 5 else ''}). They'll be placed by their names "
                f"instead. Remove it?") != QMessageBox.StandardButton.Yes:
            return
        self.remove_row(r)

    def _reset_selected(self) -> None:
        r = self.table.currentRow()
        rows = self.rows()
        if 0 <= r < len(rows) and rows[r]["builtin"]:
            self.edits.get(self.area, {}).get("changed", {}).pop(rows[r]["id"], None)
            self._tidy(self.area)
            self._fill()

    def _on_area(self, _i: int) -> None:
        self.area = self.area_combo.currentData()
        self._fill()

    # ---- checks and save ----------------------------------------------------------------

    def other_ids(self, area: str) -> set:
        """Ids used outside `area` that a new category in it can't take: the shared ones (for a pack), every
        pack's own (for Standard: it would be replaced there), the review's built-in groups."""
        ids = set(vc.RESERVED_IDS)
        for other in ([p for p in self.packs] if area == STANDARD else [STANDARD]):
            ids |= {r["id"] for r in self.rows(other)}
        return ids

    def taken_ids(self, area: str) -> set:
        return {r["id"] for r in self.rows(area)} | self.other_ids(area)

    def problems(self) -> List[str]:
        out = []
        for area, _label in areas():
            if area != STANDARD and area not in self.packs:
                continue
            rows = self.rows(area)
            ids = [r["id"] for r in rows]
            for r in rows:
                if r["builtin"]:
                    continue
                if not ID_RE.match(r["id"] or ""):
                    out.append(f"'{r['id']}': ids are lower case letters, digits and _ (start with a letter)")
                elif ids.count(r["id"]) > 1 or r["id"] in self.other_ids(area):
                    out.append(f"'{r['id']}' is already used")
                if not r.get("label"):
                    out.append(f"'{r['id']}' has no label")
                if not r.get("description") and r.get("model_assigns"):
                    out.append(f"'{r['id']}' needs a description: the model is told what it holds")
        return out

    def _save(self) -> None:
        bad = self.problems()
        if bad:
            QMessageBox.warning(self, "Check the categories", "\n".join(bad))
            return
        self.save()
        self.accept()

    def save(self) -> None:
        for area, _ in areas():
            self.registry.set_local_categories(area, self.edits.get(area, {}))
        self.registry.save()
        vc.use_local(self.registry.local_categories)
