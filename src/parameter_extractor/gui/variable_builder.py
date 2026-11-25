"""
Build columns… (pack editor, Columns and Compounds tabs; Mickey, 2026-11-24): columns in the app's own formats
from what the app already has -- variable_builder.py does the work.

- Compounds: type names or formulas (one per line), Identify (the app's name rules, then PubChem), tick the roles,
  phase and measures; the compounds (with their PubChem identities) and their columns go into the data pack.
- Other values: a name, number or text, a quantity and its unit, the kind of value it is and, optionally, the
  pack's step that asks the model for it; the column name follows the app's conventions.

The dialog edits the pack's files itself (pack_editing.PackDraft) and saves them; the editor, saved first, opens
again on the new files (the opener reopens it: no window opens the next one from its own handlers).
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from parameter_extractor import variable_builder as vb
from parameter_extractor.gui.widgets import style_rows

C_USE, C_TYPED, C_NAME, C_TITLE, C_CID, C_HOW = range(6)
NO_STEP = "__column_only__"


class VariableBuilderDialog(QDialog):
    def __init__(self, folder: Path, parent=None, start: str = "compounds"):
        super().__init__(parent)
        from parameter_extractor.pack_editing import PackDraft
        self.folder = Path(folder)
        self.draft = PackDraft.load(self.folder)
        self.applied: List[str] = []
        self.problems: list = []
        self._matches: List[vb.CompoundMatch] = []
        self._values: List[dict] = []
        self.setWindowTitle("Build columns")
        self.resize(900, 640)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._compounds_page(), "Compounds")
        self.tabs.addTab(self._values_page(), "Other values")
        self.tabs.setCurrentIndex(0 if start == "compounds" else 1)
        v.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox()
        self.add_btn = buttons.addButton("Add to the data pack", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self._refresh_preview()

    # ---- compounds ------------------------------------------------------------------------------------------------
    def _compounds_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Type the compounds' names or formulas, one per line (e.g. glycine, NaCl, mgcl2, "
                           "diglycine). <b>Identify</b> matches them with the app's name rules and PubChem; each gets "
                           "one column per role and measure you tick, in the app's compound format "
                           "(<i>role_name_phase_measure</i>), and values for them are written directly.",
                           wordWrap=True))
        self.names_edit = QPlainTextEdit()
        self.names_edit.setPlaceholderText("glycine\nNaCl\nMgCl2\nGly-Gly")
        self.names_edit.setFixedHeight(90)
        v.addWidget(self.names_edit)
        row = QHBoxLayout()
        self.pubchem_box = QCheckBox("Look them up on PubChem (needs the internet)")
        self.pubchem_box.setChecked(QSettings().value("use_pubchem", True, type=bool))
        row.addWidget(self.pubchem_box)
        row.addStretch(1)
        row.addWidget(QPushButton("Identify", clicked=self._identify))
        v.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Add", "Typed", "Name in the columns", "PubChem title", "CID",
                                              "How it was identified"])
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(C_HOW, QHeaderView.ResizeMode.Stretch)
        for c, width in ((C_USE, 40), (C_TYPED, 150), (C_NAME, 170), (C_TITLE, 220), (C_CID, 80)):
            self.table.setColumnWidth(c, width)
        style_rows(self.table)
        self.table.setWordWrap(False)                     # one line a compound; the full text in the tooltip
        self.table.setMinimumHeight(170)
        self.table.itemChanged.connect(lambda _i: self._refresh_preview())
        v.addWidget(self.table, 1)
        opts = QHBoxLayout()
        roles = QGroupBox("Roles")
        rl = QVBoxLayout(roles)
        self.role_boxes = {}
        for role, text in vb.ROLES.items():
            box = QCheckBox(text)
            box.setChecked(role in ("initial", "sampled"))
            box.toggled.connect(lambda _on: self._refresh_preview())
            rl.addWidget(box)
            self.role_boxes[role] = box
        opts.addWidget(roles)
        measures = QGroupBox("Measures")
        ml = QVBoxLayout(measures)
        self.measure_boxes = {}
        for measure, text in vb.MEASURES.items():
            box = QCheckBox(text)
            box.setChecked(measure in ("mM", "%yield"))
            box.toggled.connect(lambda _on: self._refresh_preview())
            ml.addWidget(box)
            self.measure_boxes[measure] = box
        opts.addWidget(measures)
        right = QVBoxLayout()
        form = QFormLayout()
        self.phase_combo = QComboBox()
        for code, text in vb.PHASES.items():
            self.phase_combo.addItem(text, code)
        self.phase_combo.currentIndexChanged.connect(lambda _i: self._refresh_preview())
        form.addRow("Phase:", self.phase_combo)
        right.addLayout(form)
        self.compound_preview = QPlainTextEdit(readOnly=True)      # the new columns, one a line (scrolls)
        right.addWidget(self.compound_preview, 1)
        opts.addLayout(right, 1)
        v.addLayout(opts)
        return w

    def _identify(self) -> None:
        texts = [t for t in self.names_edit.toPlainText().splitlines() if t.strip()]
        if not texts:
            return
        client = None
        if self.pubchem_box.isChecked():
            from parameter_extractor.pubchem import PubChem
            from parameter_extractor.registry import default_pubchem_cache_path
            client = PubChem(default_pubchem_cache_path())
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            found = vb.identify(texts, client, self.draft.compounds)
            if client is not None:
                try:
                    client.save()
                except Exception:
                    pass
        finally:
            QGuiApplication.restoreOverrideCursor()
        known = {m.entered.lower() for m in self._matches}
        self._matches += [m for m in found if m.entered.lower() not in known]
        self._fill_table()

    def _fill_table(self) -> None:
        t = self.table
        t.blockSignals(True)
        t.setRowCount(0)
        for m in self._matches:
            r = t.rowCount()
            t.insertRow(r)
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            identified = bool(m.cid) or not m.how.startswith("not identified")
            use.setCheckState(Qt.CheckState.Checked if identified else Qt.CheckState.Unchecked)
            t.setItem(r, C_USE, use)
            for c, text, editable in ((C_TYPED, m.entered, False), (C_NAME, m.name, True), (C_TITLE, m.title, False),
                                      (C_CID, str(m.cid or ""), False),
                                      (C_HOW, m.how + ("; already in this data pack" if m.known else ""), False)):
                item = QTableWidgetItem(text)
                if not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(", ".join(m.synonyms[:20]) if c == C_TITLE and m.synonyms else text)
                t.setItem(r, c, item)
        t.blockSignals(False)
        self._refresh_preview()

    def chosen_compounds(self) -> List[vb.CompoundMatch]:
        out = []
        for r, m in enumerate(self._matches):
            if self.table.item(r, C_USE).checkState() != Qt.CheckState.Checked:
                continue
            name = self.table.item(r, C_NAME).text().strip()
            if name:
                out.append(vb.CompoundMatch(m.entered, name, m.cid, m.title, m.synonyms, m.how, m.known))
        return out

    def compound_columns(self) -> List[str]:
        roles = [r for r, b in self.role_boxes.items() if b.isChecked()]
        measures = [m for m, b in self.measure_boxes.items() if b.isChecked()]
        have = set(self.draft.columns)
        cols = [c for m in self.chosen_compounds()
                for c in vb.compound_columns(m.name, roles, self.phase_combo.currentData(), measures)]
        return [c for c in dict.fromkeys(cols) if c not in have]

    # ---- other values ---------------------------------------------------------------------------------------------
    def _values_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("A value that isn't a compound: name it in words, say whether it is a number or text and in "
                           "which unit. The column name follows the app's conventions (the unit at the end, the "
                           "app's own column where it has one). Ask for it in one of this data pack's steps to have "
                           "the model look for it -- a focused search can then search for it too.", wordWrap=True))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.v_name = QLineEdit(placeholderText="e.g. stirring rate, catalyst loading, light source")
        self.v_kind = QComboBox()
        self.v_kind.addItem("number", "number")
        self.v_kind.addItem("text", "text")
        self.v_quantity = QComboBox()
        self.v_quantity.addItem("(no unit)", "")
        self._units = vb.units_by_quantity()
        for q in self._units:
            self.v_quantity.addItem(q.replace("_", " "), q)
        self.v_unit = QComboBox()
        self.v_desc = QLineEdit(placeholderText="what the model should look for (shown to it)")
        self.v_uncert = QCheckBox("with its uncertainties (± columns)")
        self.v_category = QComboBox()
        self._fill_categories()
        self.v_step = QComboBox()
        self.v_step.addItem("(no step: a column only)", NO_STEP)
        for file, spec in self.draft.stages.items():
            self.v_step.addItem(spec.get("label") or spec.get("name") or file, file)
        if self.v_step.count() > 1:
            self.v_step.setCurrentIndex(1)
        form.addRow("Name:", self.v_name)
        form.addRow("Number or text:", self.v_kind)
        form.addRow("Quantity:", self.v_quantity)
        form.addRow("Unit:", self.v_unit)
        form.addRow("Description:", self.v_desc)
        form.addRow("", self.v_uncert)
        form.addRow("Kind of value:", self.v_category)
        form.addRow("Asked for in step:", self.v_step)
        v.addLayout(form)
        self.v_preview = QLabel(wordWrap=True)
        v.addWidget(self.v_preview)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Add to the list", clicked=self._add_value))
        row.addWidget(QPushButton("Remove", clicked=self._remove_value))
        row.addStretch(1)
        v.addLayout(row)
        self.value_list = QListWidget()
        v.addWidget(self.value_list, 1)
        for widget in (self.v_name, self.v_desc):
            widget.textChanged.connect(lambda _t: self._refresh_value())
        for combo in (self.v_kind, self.v_unit, self.v_category, self.v_step):
            combo.currentIndexChanged.connect(lambda _i: self._refresh_value())
        self.v_quantity.currentIndexChanged.connect(self._fill_units)
        self._fill_units()
        return w

    def _fill_categories(self) -> None:
        from parameter_extractor import packs, variable_categories
        try:
            cats = variable_categories.categories(packs.Pack(self.folder))
        except Exception:
            cats = []
        for c in sorted(cats, key=lambda c: c.table_order):
            if not c.sources:                         # categories the app fills itself (compounds) aren't offered
                self.v_category.addItem(c.label, c.id)
        index = self.v_category.findData("methodology")
        self.v_category.setCurrentIndex(max(index, 0))

    def _fill_units(self) -> None:
        self.v_unit.blockSignals(True)
        self.v_unit.clear()
        for u in self._units.get(self.v_quantity.currentData() or "", []):
            self.v_unit.addItem(u, u)
        self.v_unit.blockSignals(False)
        self._refresh_value()

    def _built_value(self):
        name = self.v_name.text().strip()
        if not name:
            return None
        kind = self.v_kind.currentData()
        unit = "" if kind == "text" else (self.v_unit.currentData() or "")
        system = self.draft.manifest.get("unit_system", "lab")
        return vb.value_column(name, unit, kind, self.v_desc.text().strip(), system)

    def _refresh_value(self) -> None:
        built = self._built_value()
        if built is None:
            self.v_preview.setText("")
            return
        problem = vb.valid_column(built.column)
        taken = built.column in set(self.draft.columns) | {
            p.get("column") for s in self.draft.stages.values() for p in s.get("parameters", [])}
        self.v_preview.setText(f"Column: <b>{built.column}</b>" + (f" [{built.unit}]" if built.unit else "")
                               + (f" -- {built.note}" if built.note else "")
                               + (f" -- can't be used: {problem}" if problem else "")
                               + (" -- this data pack already has it" if taken else ""))

    def _add_value(self) -> None:
        built = self._built_value()
        if built is None or vb.valid_column(built.column):
            return
        entry = {"value": built, "uncertainties": self.v_uncert.isChecked(),
                 "category": self.v_category.currentData(), "step": self.v_step.currentData()}
        self._values = [x for x in self._values if x["value"].column != built.column] + [entry]
        self.value_list.clear()
        for x in self._values:
            where = "a column only" if x["step"] == NO_STEP else f"asked in {self.v_step.itemText(self.v_step.findData(x['step']))}"
            self.value_list.addItem(f"{x['value'].column}" + (f" [{x['value'].unit}]" if x["value"].unit else "")
                                    + f" -- {where}")
        self.v_name.clear()
        self.v_desc.clear()
        self._refresh_preview()

    def _remove_value(self) -> None:
        r = self.value_list.currentRow()
        if 0 <= r < len(self._values):
            del self._values[r]
            self.value_list.takeItem(r)
        self._refresh_preview()

    # ---- both -----------------------------------------------------------------------------------------------------
    def _refresh_preview(self) -> None:
        cols = self.compound_columns() if hasattr(self, "table") else []
        if hasattr(self, "compound_preview"):
            self.compound_preview.setPlainText(
                (f"{len(cols)} new column(s):\n" + "\n".join(cols)) if cols else
                "No new columns yet: identify compounds and tick a role and a measure.")
        if hasattr(self, "add_btn"):
            self.add_btn.setEnabled(bool(cols or self._values or self.chosen_compounds()))

    def _apply(self) -> None:
        compounds, columns = self.chosen_compounds(), self.compound_columns()
        if not (compounds or columns or self._values):
            return
        self.applied = apply_to_draft(self.draft, compounds, columns, self._values)
        try:
            self.draft.save()
        except Exception as e:
            QMessageBox.warning(self, "Not saved", f"The data pack couldn't be saved: {e}")
            return
        from parameter_extractor.pack_editing import check
        self.problems = check(self.draft)
        self.accept()


def apply_to_draft(draft, compounds, columns, values) -> List[str]:
    """The built compounds (vocabulary + PubChem identities), their columns and the other values into a PackDraft
    (not saved). Returns what was done, for the editor's message."""
    done = []
    existing = draft.compounds
    names = {c["name"] for c in existing}
    new = [m for m in compounds if m.name not in names]
    if new:
        draft.compounds = existing + [{"name": m.name, "cid": m.cid} for m in new]
        species = draft.cids_file.setdefault("species", {})
        for m in new:
            if m.cid and m.name in species:
                species[m.name].update({"title": m.title, "synonyms": list(m.synonyms)})
        done.append(f"{len(new)} compound(s) added: " + ", ".join(m.name for m in new[:12]))
    if columns:
        draft.columns = list(draft.columns) + [c for c in columns if c not in set(draft.columns)]
        done.append(f"{len(columns)} compound column(s) added")
    for x in values:
        built, step = x["value"], x["step"]
        if step != NO_STEP and step in draft.stages:
            params = draft.stages[step].setdefault("parameters", [])
            if all(p.get("column") != built.column for p in params):
                params.append(vb.parameter_entry(built, x["uncertainties"]))
            done.append(f"{built.column}: asked for in the step {draft.stages[step].get('label') or step}")
        elif built.column not in draft.columns:
            draft.columns = list(draft.columns) + [built.column]
            done.append(f"{built.column}: a column")
        if x.get("category"):
            cc = draft.manifest.setdefault("category_columns", {}).setdefault(x["category"], {})
            cc.setdefault("columns", [])
            if built.column not in cc["columns"]:
                cc["columns"].append(built.column)
    return done
