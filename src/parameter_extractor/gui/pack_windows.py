"""
The Data Packs menu's windows (Mickey, 2026-11-05: research areas made and edited inside the app).

  NewPackDialog   name, id, description, what a set and a row are called, and what to start from: the template
                  (packs/_template: examples to replace) or a copy of an existing research area -- the way to change
                  one of the app's own. packs.create_pack() makes the folder in the user's packs folder.
  PackEditor      one research area's files as tabs, edited on a copy (pack_editing.PackDraft) and written on Save:
                    General  -- name, description, set / row words, built-in steps, calculations, categories
                    Columns  -- the dataset's columns in order (and a compound vocabulary for the chemistry step)
                    Stages   -- each extraction stage: what it asks, when it runs, its parameters (columns)
                    Rules    -- the pack's rules for the shared prompts (planning rows, figures, ...)
                    Formulas -- calculations without code (formulas.py), with a panel to try one out
                    Check    -- pack_editing.check(): errors, warnings and notes; run again on Save
                  The app's own research areas open read-only, with a button to copy one.
"""
from __future__ import annotations
import copy
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                               QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor import packs
from parameter_extractor.pack_editing import (BUILTIN_STAGES, CALCULATIONS, RULE_PROMPTS, PackDraft, Problem,
                                              check)

LEVEL_COLORS = {"error": QColor(190, 40, 40), "warning": QColor(176, 110, 0), "note": QColor(110, 110, 110)}
UNCERTAINTY_STYLES = [("<column>_err_plus / _err_minus", ["_err_plus", "_err_minus"], "_"),
                      ("<column>err1 / err2 / lim (Exoplanet Archive)", ["err1", "err2", "lim"], "")]
P_COLUMN, P_UNIT, P_KIND, P_DESC, P_CHOICES, P_INTEGER, P_UNCERT = range(7)
P_HEADERS = ["Column", "Unit", "Kind", "Description (the model reads it)", "Allowed words", "Whole no.", "±"]


def suggest_id(label: str) -> str:
    """'Soil carbon cycling' -> 'soil_carbon_cycling' (a usable pack id)."""
    text = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    if text and not text[0].isalpha():
        text = "area_" + text
    return text[:41]


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


def _split(text: str):
    return [w.strip() for w in (text or "").split(",") if w.strip()]


def _hint(text: str) -> QLabel:
    label = QLabel(text, wordWrap=True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


# ---- New research area -------------------------------------------------------------------------

class NewPackDialog(QDialog):
    """Name a new research area and choose what it starts from; `created` is the new pack after Create."""

    def __init__(self, parent=None, source: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("New research area")
        self.resize(620, 420)
        self.created: Optional[packs.Pack] = None
        self._id_edited = False
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("A research area (a data pack) decides the dataset's columns, how a paper's results "
                               "become rows, and what is extracted. It starts as a working copy of the template or "
                               "of an existing area; you then edit it (Data Packs > Edit research area)."))
        form = _form()
        self.label_edit = QLineEdit(placeholderText="e.g. Mineral surface catalysis")
        self.id_edit = QLineEdit(placeholderText="filled in from the name")
        self.id_edit.setToolTip("Lower-case letters, digits and '_'. Fixed once created: remembered variables and "
                                "categories are stored under it.")
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText("What kind of papers, and what one row of the dataset is.")
        self.desc_edit.setFixedHeight(70)
        self.set_edit = QLineEdit("experiment set")
        self.sample_edit = QLineEdit("sample")
        self.source_combo = QComboBox()
        self.source_combo.addItem("The template (example columns, stage and rules to replace)", "")
        for pack_id, pack in sorted(packs.available().items(), key=lambda kv: kv[1].label):
            self.source_combo.addItem(f"A copy of: {pack.label}", pack_id)
        if source:
            self.source_combo.setCurrentIndex(max(self.source_combo.findData(source), 0))
        form.addRow("Name:", self.label_edit)
        form.addRow("ID:", self.id_edit)
        form.addRow("Description:", self.desc_edit)
        form.addRow("A group of rows is called:", self.set_edit)
        form.addRow("One row is called:", self.sample_edit)
        form.addRow("Start from:", self.source_combo)
        layout.addLayout(form)
        self.error = QLabel(wordWrap=True)
        self.error.setStyleSheet(f"color: {LEVEL_COLORS['error'].name()};")
        layout.addWidget(self.error)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_btn = buttons.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.label_edit.textChanged.connect(self._on_label)
        self.id_edit.textEdited.connect(lambda _t: setattr(self, "_id_edited", True))
        self.source_combo.currentIndexChanged.connect(self._on_source)

    def _on_label(self, text: str) -> None:
        if not self._id_edited:
            self.id_edit.setText(suggest_id(text))

    def _on_source(self, _index: int) -> None:
        source = packs.available().get(self.source_combo.currentData() or "")
        if source is not None:                      # a copy keeps the words of what it's copied from
            self.set_edit.setText(source.manifest.units.get("set", "set"))
            self.sample_edit.setText(source.manifest.units.get("sample", "sample"))

    def create(self) -> None:
        source = packs.available().get(self.source_combo.currentData() or "")
        try:
            self.created = packs.create_pack(self.id_edit.text().strip(), self.label_edit.text(),
                                             self.desc_edit.toPlainText(), source=source,
                                             units={"set": self.set_edit.text(), "sample": self.sample_edit.text()})
        except (ValueError, OSError) as e:
            self.error.setText(str(e))
            return
        self.accept()


# ---- Edit a research area ----------------------------------------------------------------------

class PackEditor(QDialog):
    """One research area's files as tabs (see the module docstring). `saved` fires after a save."""
    saved = Signal(str)

    def __init__(self, folder: Path, parent=None, registry_path: Optional[Path] = None):
        super().__init__(parent)
        self.draft = PackDraft.load(folder)
        self.registry_path = registry_path
        self.read_only = self.draft.builtin
        self._stage = None                         # the stage file shown in the Stages tab
        self._rules_shown = None
        self.setWindowTitle(f"Research area: {self.draft.manifest.get('label', '')}"
                            + ("  (built in, read-only)" if self.read_only else ""))
        self.resize(1320, 820)
        layout = QVBoxLayout(self)
        if self.read_only:
            banner = QHBoxLayout()
            banner.addWidget(QLabel("This research area is part of the app and can't be changed. Copy it to make "
                                    "your own version.", wordWrap=True), 1)
            banner.addWidget(QPushButton("Copy to a new research area…", clicked=self._copy))
            layout.addLayout(banner)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._columns_tab(), "Columns")
        self.tabs.addTab(self._stages_tab(), "Stages")
        self.tabs.addTab(self._rules_tab(), "Rules")
        self.tabs.addTab(self._formulas_tab(), "Formulas")
        self.tabs.addTab(self._check_tab(), "Check")
        self.tabs.currentChanged.connect(lambda _i: self._fit_rows())
        layout.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        where = _hint(f"Folder: {self.draft.folder}")
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom.addWidget(where, 1)
        bottom.addWidget(QPushButton("Open folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.draft.folder)))))
        bottom.addWidget(QPushButton("Close", clicked=self.reject))
        self.save_btn = QPushButton("Save", clicked=self.save, default=True)
        self.save_btn.setEnabled(not self.read_only)
        bottom.addWidget(self.save_btn)
        layout.addLayout(bottom)
        if self.read_only:
            for tab in range(self.tabs.count() - 1):            # Check stays usable
                self._lock(self.tabs.widget(tab))
        self.run_check()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_rows()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_rows()

    def _fit_rows(self) -> None:
        """Parameter rows as tall as their wrapped descriptions -- once the layout has settled (the stretched
        description column gets its width after the window is laid out)."""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.p_table.resizeRowsToContents)

    # ---- General ------------------------------------------------------------------------

    def _general_tab(self) -> QWidget:
        m = self.draft.manifest
        w = QWidget()
        v = QVBoxLayout(w)
        form = _form()
        self.label_edit = QLineEdit(m.get("label", ""))
        self.desc_edit = QPlainTextEdit(m.get("description", ""))
        self.desc_edit.setFixedHeight(64)
        units = m.get("units", {})
        self.set_edit = QLineEdit(units.get("set", "set"))
        self.sample_edit = QLineEdit(units.get("sample", "sample"))
        self.row_edit = QLineEdit(units.get("row", ""), placeholderText="row")
        self.row_edit.setToolTip("Optional: what one row is called in messages, if not 'row'.")
        self.focused_box = QCheckBox("Focused searches plan each paper's rows first (more accurate rows, a little "
                                     "more cost)", checked=bool(m.get("focused_row_plan")))
        self.compact_box = QCheckBox("Send the paper text with long runs of spaces collapsed (about 20% cheaper "
                                     "on table-heavy papers)", checked=bool(m.get("compact_text")))
        form.addRow("Name:", self.label_edit)
        form.addRow("ID:", QLabel(m.get("id", "")))
        form.addRow("Description:", self.desc_edit)
        form.addRow("A group of rows is called:", self.set_edit)
        form.addRow("One row is called:", self.sample_edit)
        form.addRow("In messages, a row is:", self.row_edit)
        v.addLayout(form)
        v.addWidget(self.focused_box)
        v.addWidget(self.compact_box)

        steps = QGroupBox("Built-in extraction steps (written in code; most new research areas use none)")
        sv = QVBoxLayout(steps)
        self.builtin_boxes = {}
        for name, about in BUILTIN_STAGES.items():
            box = QCheckBox(f"{name} -- {about}", checked=name in m.get("builtin_stages", []))
            self.builtin_boxes[name] = box
            sv.addWidget(box)
        v.addWidget(steps)

        calcs = QGroupBox("Calculations run on the rows, in this order (drag to reorder; tick to use)")
        cv = QVBoxLayout(calcs)
        self.calc_list = QListWidget()
        self.calc_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        chosen = list(m.get("postprocess", []))
        for name in chosen + [n for n in CALCULATIONS if n not in chosen]:
            about, needs = CALCULATIONS.get(name, ("(unknown calculation)", ""))
            item = QListWidgetItem(f"{name} -- {about}" + (f"  [needs the {needs} step]" if needs else ""))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked)
            self.calc_list.addItem(item)
        cv.addWidget(self.calc_list)
        v.addWidget(calcs, 1)

        cats = QHBoxLayout()
        cats.addWidget(_hint("Variable categories (how suggested variables and columns are grouped) are edited in "
                             "their own window; categories defined by the pack are in pack.json."), 1)
        self.categories_btn = QPushButton("Edit variable categories…", clicked=self._open_categories)
        cats.addWidget(self.categories_btn)
        v.addLayout(cats)
        return w

    def _open_categories(self) -> None:
        from parameter_extractor.gui.categories_dialog import CategoriesDialog
        if self.draft.manifest.get("id") not in packs.available():
            QMessageBox.information(self, "Save first", "Save the research area first: its categories are edited "
                                                        "once the app knows it.")
            return
        dlg = CategoriesDialog(self.registry_path, parent=self)
        dlg.area_combo.setCurrentIndex(max(dlg.area_combo.findData(self.draft.manifest["id"]), 0))
        dlg.exec()

    # ---- Columns ------------------------------------------------------------------------

    def _columns_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_hint("The dataset's columns, in order. Put the unit at the end of a name (temperature_C, "
                          "pressure_bar, mass_g, yield_pct): values are converted into it. The shared columns "
                          "(paper, authors, DOI, ...) and row identifiers are added automatically. Columns a stage "
                          "fills but that aren't listed here are added after these. Double-click to rename; drag to "
                          "reorder."))
        row = QHBoxLayout()
        self.column_list = QListWidget()
        self.column_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for c in self.draft.columns:
            self._add_column_item(c)
        row.addWidget(self.column_list, 1)
        side = QVBoxLayout()
        for text, slot in (("Add…", self._add_column), ("Remove", self._remove_column)):
            side.addWidget(QPushButton(text, clicked=slot))
        side.addStretch(1)
        row.addLayout(side)
        v.addLayout(row, 1)
        self.species_box = QGroupBox("Compound vocabulary (for the chemistry step): one name per line")
        sv = QVBoxLayout(self.species_box)
        self.species_edit = QPlainTextEdit("\n".join(self.draft.species))
        sv.addWidget(self.species_edit)
        self.species_box.setVisible("chemistry" in self.draft.manifest.get("builtin_stages", []))
        self.builtin_boxes["chemistry"].toggled.connect(self.species_box.setVisible)
        v.addWidget(self.species_box)
        self._update_column_tips()
        return w

    def _add_column_item(self, column: str) -> None:
        item = QListWidgetItem(column)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.column_list.addItem(item)

    def _add_column(self) -> None:
        name, ok = QInputDialog.getText(self, "Add a column", "Column name (unit at the end, e.g. mass_g):")
        name = (name or "").strip()
        if ok and name:
            self._add_column_item(name)
            self.column_list.setCurrentRow(self.column_list.count() - 1)

    def _remove_column(self) -> None:
        for item in self.column_list.selectedItems():
            self.column_list.takeItem(self.column_list.row(item))

    def _update_column_tips(self) -> None:
        fills = self.draft.stage_columns()
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            stages = fills.get(item.text())
            item.setToolTip(f"Filled by: {', '.join(stages)}" if stages else "No stage fills this column yet.")

    # ---- Stages -------------------------------------------------------------------------

    def _stages_tab(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(_hint("Each stage is one request to the model, run for every paper (or only papers that "
                             "need it). Several small stages run in parallel."))
        self.stage_list = QListWidget()
        self.stage_list.currentRowChanged.connect(self._on_stage_row)
        left.addWidget(self.stage_list, 1)
        buttons = QHBoxLayout()
        for text, slot in (("New…", self._new_stage), ("Duplicate", self._duplicate_stage),
                           ("Remove", self._remove_stage)):
            buttons.addWidget(QPushButton(text, clicked=slot))
        left.addLayout(buttons)
        left_w = QWidget()
        left_w.setLayout(left)

        form_w = QWidget()                       # the stage's settings (scrolls) over its parameters
        settings_w = QWidget()
        fv = QVBoxLayout(settings_w)
        form = _form()
        self.s_name = QLineEdit()
        self.s_name.setToolTip("Lower-case letters, digits and '_'.")
        self.s_label = QLineEdit()
        self.s_desc = QLineEdit(placeholderText="shown next to the stage's on/off switch")
        self.s_system = QLineEdit()
        self.s_intro = QPlainTextEdit()
        self.s_intro.setFixedHeight(70)
        self.s_per = QComboBox()
        self.s_per.addItem("a row: values can belong to single rows", "sample")
        self.s_per.addItem("a group of rows: values belong to whole sets", "set")
        self.s_always = QCheckBox("every paper")
        self.s_keywords = QLineEdit(placeholderText="words in the paper, comma-separated (e.g. rate constant, half-life)")
        self.s_set_types = QLineEdit(placeholderText="set types, comma-separated (e.g. Time Series)")
        self.s_patterns = QLineEdit(placeholderText="patterns on set labels, comma-separated (e.g. wet-dry)")
        trigger = QWidget()
        tv = QVBoxLayout(trigger)
        tv.setContentsMargins(0, 0, 0, 0)
        for widget in (self.s_always, self.s_keywords, self.s_set_types, self.s_patterns):
            tv.addWidget(widget)
        self.s_images = QCheckBox("send pictures of the paper's tables (more reliable for tables; costs more)")
        self.s_open = QCheckBox("also collect values that have no column (offered in the review)")
        self.s_open_hint = QLineEdit(placeholderText="what else to look for, and what to leave out")
        self.s_uncert = QComboBox()
        for label, _suffixes, _sep in UNCERTAINTY_STYLES:
            self.s_uncert.addItem(label)
        self.s_rules = QPlainTextEdit()
        self.s_rules.setPlaceholderText("Extra instructions, one per line.")
        self.s_rules.setFixedHeight(60)
        form.addRow("Name:", self.s_name)
        form.addRow("Label:", self.s_label)
        form.addRow("Description:", self.s_desc)
        form.addRow("The model's role:", self.s_system)
        form.addRow("Instruction:", self.s_intro)
        form.addRow("Values belong to:", self.s_per)
        form.addRow("Runs for:", trigger)
        form.addRow("Tables:", self.s_images)
        form.addRow("Other values:", self.s_open)
        form.addRow("", self.s_open_hint)
        form.addRow("Uncertainty columns:", self.s_uncert)
        form.addRow("Rules:", self.s_rules)
        fv.addLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings_w)
        params_w = QWidget()
        fv = QVBoxLayout(params_w)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.addWidget(QLabel("Parameters -- the columns this stage fills:"))
        self.p_table = QTableWidget(0, len(P_HEADERS))
        self.p_table.setHorizontalHeaderLabels(P_HEADERS)
        for c, tip in ((P_INTEGER, "A count: written as a whole number ('triplicate' -> 3)."),
                       (P_UNCERT, "Also fill the ± uncertainty columns of this value."),
                       (P_CHOICES, "For text: the only words allowed, comma-separated (others are left out)."),
                       (P_UNIT, "The column's unit (matching the end of its name); values are converted into it.")):
            self.p_table.horizontalHeaderItem(c).setToolTip(tip)
        self.p_table.horizontalHeader().setSectionResizeMode(P_DESC, QHeaderView.ResizeMode.Stretch)
        self.p_table.setWordWrap(True)
        self.p_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        for c, width in ((P_COLUMN, 170), (P_UNIT, 55), (P_KIND, 92), (P_CHOICES, 110), (P_INTEGER, 70),
                         (P_UNCERT, 40)):
            self.p_table.setColumnWidth(c, width)
        # descriptions wrap: row heights follow the description column's width
        self.p_table.horizontalHeader().sectionResized.connect(lambda *_: self._fit_rows())
        fv.addWidget(self.p_table, 1)
        pb = QHBoxLayout()
        for text, slot in (("Add parameter", self._add_parameter), ("Remove", self._remove_parameter),
                           ("Up", lambda: self._move_parameter(-1)), ("Down", lambda: self._move_parameter(1))):
            pb.addWidget(QPushButton(text, clicked=slot))
        pb.addStretch(1)
        fv.addLayout(pb)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.addWidget(scroll)
        vsplit.addWidget(params_w)
        vsplit.setSizes([360, 380])
        vsplit.splitterMoved.connect(lambda *_: self._fit_rows())
        QVBoxLayout(form_w).addWidget(vsplit)
        form_w.layout().setContentsMargins(0, 0, 0, 0)
        self.stage_form = form_w

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_w)
        split.addWidget(form_w)
        split.setSizes([220, 1080])
        split.splitterMoved.connect(lambda *_: self._fit_rows())
        outer.addWidget(split)
        self._fill_stage_list()
        return w

    def _fill_stage_list(self, select: Optional[str] = None) -> None:
        self.stage_list.blockSignals(True)
        self.stage_list.clear()
        for file, spec in self.draft.stages.items():
            item = QListWidgetItem(f"{spec.get('label') or spec.get('name')}  ({spec.get('name', '')})")
            item.setData(Qt.ItemDataRole.UserRole, file)
            self.stage_list.addItem(item)
        self.stage_list.blockSignals(False)
        files = list(self.draft.stages)
        row = files.index(select) if select in files else (0 if files else -1)
        self._stage = None
        self.stage_list.setCurrentRow(row)
        if row < 0:
            self.stage_form.setEnabled(False)
        elif self.stage_list.currentRow() == row:
            self._on_stage_row(row)

    def _on_stage_row(self, row: int) -> None:
        self._store_stage()
        if row < 0 or row >= self.stage_list.count():
            self._stage = None
            self.stage_form.setEnabled(False)
            return
        self._stage = self.stage_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.stage_form.setEnabled(not self.read_only)
        self._load_stage(self.draft.stages[self._stage])

    def _load_stage(self, spec: dict) -> None:
        self.s_name.setText(spec.get("name", ""))
        self.s_label.setText(spec.get("label", ""))
        self.s_desc.setText(spec.get("description", ""))
        self.s_system.setText(spec.get("system_prompt", ""))
        self.s_intro.setPlainText(spec.get("intro", ""))
        self.s_per.setCurrentIndex(max(self.s_per.findData(spec.get("per", "set")), 0))
        t = spec.get("trigger", {})
        self.s_always.setChecked(bool(t.get("always")))
        self.s_keywords.setText(", ".join(t.get("keywords", [])))
        self.s_set_types.setText(", ".join(t.get("set_types", [])))
        self.s_patterns.setText(", ".join(t.get("set_patterns", [])))
        self.s_images.setChecked(bool(spec.get("table_images")))
        self.s_open.setChecked(bool(spec.get("open_ended")))
        self.s_open_hint.setText(spec.get("open_ended_hint", ""))
        suffixes = spec.get("error_suffixes", ["err1", "err2", "lim"])
        self.s_uncert.setCurrentIndex(0 if suffixes == UNCERTAINTY_STYLES[0][1] else 1)
        self.s_rules.setPlainText("\n".join(spec.get("rules", [])))
        self.p_table.setRowCount(0)
        for p in spec.get("parameters", []):
            self._add_parameter(p)
        self._fit_rows()

    def _store_stage(self) -> None:
        """The form back into the draft's spec (keys the form doesn't show are kept)."""
        if self._stage is None or self._stage not in self.draft.stages or self.read_only:
            return
        spec = self.draft.stages[self._stage]
        spec.update(name=self.s_name.text().strip(), label=self.s_label.text().strip(),
                    description=self.s_desc.text().strip(), system_prompt=self.s_system.text().strip(),
                    intro=self.s_intro.toPlainText().strip(), per=self.s_per.currentData(),
                    table_images=self.s_images.isChecked(), open_ended=self.s_open.isChecked(),
                    open_ended_hint=self.s_open_hint.text().strip(),
                    rules=[r.strip() for r in self.s_rules.toPlainText().splitlines() if r.strip()])
        trigger = dict(spec.get("trigger", {}))
        trigger.update(always=self.s_always.isChecked(), keywords=_split(self.s_keywords.text()),
                       set_types=_split(self.s_set_types.text()), set_patterns=_split(self.s_patterns.text()))
        spec["trigger"] = {k: v for k, v in trigger.items() if v}
        _label, suffixes, sep = UNCERTAINTY_STYLES[self.s_uncert.currentIndex()]
        spec["error_suffixes"], spec["suffix_separator"] = list(suffixes), sep
        old = {p.get("column"): p for p in spec.get("parameters", [])}
        params = []
        for r in range(self.p_table.rowCount()):
            column = (self.p_table.item(r, P_COLUMN).text() if self.p_table.item(r, P_COLUMN) else "").strip()
            p = dict(old.get(column, {}))                     # keeps fields the table doesn't show
            p["column"] = column
            p["unit"] = self.p_table.item(r, P_UNIT).text().strip() if self.p_table.item(r, P_UNIT) else ""
            kind = self.p_table.cellWidget(r, P_KIND).currentData()
            if kind == "text":
                p["kind"] = "text"
            else:
                p.pop("kind", None)
            p["description"] = self.p_table.item(r, P_DESC).text().strip() if self.p_table.item(r, P_DESC) else ""
            choices = _split(self.p_table.item(r, P_CHOICES).text() if self.p_table.item(r, P_CHOICES) else "")
            if choices:
                p["choices"] = choices
            else:
                p.pop("choices", None)
            for c, key in ((P_INTEGER, "integer"), (P_UNCERT, "uncertainties")):
                if self.p_table.item(r, c).checkState() == Qt.CheckState.Checked:
                    p[key] = True
                else:
                    p.pop(key, None)
            if not p.get("unit"):
                p.pop("unit", None)
            params.append(p)
        spec["parameters"] = params
        # the list shows the current label and name
        for i in range(self.stage_list.count()):
            if self.stage_list.item(i).data(Qt.ItemDataRole.UserRole) == self._stage:
                self.stage_list.item(i).setText(f"{spec['label'] or spec['name']}  ({spec['name']})")

    def _add_parameter(self, p: Optional[dict] = None) -> None:
        p = p if isinstance(p, dict) else {}
        r = self.p_table.rowCount()
        self.p_table.insertRow(r)
        for c, text in ((P_COLUMN, p.get("column", "")), (P_UNIT, p.get("unit", "")),
                        (P_DESC, p.get("description", "")), (P_CHOICES, ", ".join(p.get("choices") or []))):
            self.p_table.setItem(r, c, QTableWidgetItem(text))
        kind = QComboBox()
        kind.addItem("number", "number")
        kind.addItem("text", "text")
        kind.setCurrentIndex(1 if p.get("kind") == "text" else 0)
        self.p_table.setCellWidget(r, P_KIND, kind)
        for c, key in ((P_INTEGER, "integer"), (P_UNCERT, "uncertainties")):
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if p.get(key) else Qt.CheckState.Unchecked)
            self.p_table.setItem(r, c, item)

    def _remove_parameter(self) -> None:
        rows = sorted({i.row() for i in self.p_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.p_table.removeRow(r)

    def _move_parameter(self, step: int) -> None:
        r = self.p_table.currentRow()
        if r < 0 or not 0 <= r + step < self.p_table.rowCount():
            return
        self._store_stage()
        params = self.draft.stages[self._stage]["parameters"]
        params[r], params[r + step] = params[r + step], params[r]
        self._load_stage(self.draft.stages[self._stage])
        self.p_table.setCurrentCell(r + step, P_COLUMN)

    def _new_stage(self) -> None:
        label, ok = QInputDialog.getText(self, "New stage", "What the stage extracts (e.g. Sample properties):")
        if not ok or not label.strip():
            return
        self._store_stage()
        try:
            file = self.draft.new_stage(suggest_id(label) or "stage", label.strip())
        except ValueError as e:
            QMessageBox.warning(self, "New stage", str(e))
            return
        self._fill_stage_list(select=file)

    def _duplicate_stage(self) -> None:
        if self._stage is None:
            return
        self._store_stage()
        original = self.draft.stages[self._stage]
        name = original["name"] + "_copy"
        n = 2
        while any(s.get("name") == name for s in self.draft.stages.values()):
            name, n = f"{original['name']}_copy{n}", n + 1
        file = self.draft.new_stage(name, original.get("label", "") + " (copy)")
        spec = copy.deepcopy(original)
        spec.update(name=name, label=self.draft.stages[file]["label"],
                    schema_name=self.draft.stages[file]["schema_name"])
        self.draft.stages[file] = spec
        self._fill_stage_list(select=file)

    def _remove_stage(self) -> None:
        if self._stage is None:
            return
        name = self.draft.stages[self._stage].get("name", self._stage)
        if QMessageBox.question(self, "Remove stage", f"Remove the stage '{name}'? (Only on Save.)") \
                != QMessageBox.StandardButton.Yes:
            return
        file, self._stage = self._stage, None
        self.draft.remove_stage(file)
        self._fill_stage_list()

    # ---- Rules --------------------------------------------------------------------------

    def _rules_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_hint("Rules for this research area, added to the app's shared prompts. The most important "
                          "are the row-planning rules: what ONE row is, what makes rows one set, and which results "
                          "must not become rows. A few lines are enough."))
        top = QHBoxLayout()
        self.rules_combo = QComboBox()
        for name, about in RULE_PROMPTS.items():
            self.rules_combo.addItem(f"{name} -- {about}", name)
        top.addWidget(self.rules_combo, 1)
        top.addWidget(QPushButton("Show the shared prompt…", clicked=self._show_prompt))
        v.addLayout(top)
        self.rules_note = _hint("")
        v.addWidget(self.rules_note)
        self.rules_edit = QPlainTextEdit()
        self.rules_edit.setPlaceholderText("- One rule per line, e.g. '- One row per soil sample and depth.'")
        v.addWidget(self.rules_edit, 1)
        self.rules_combo.currentIndexChanged.connect(self._on_rules_prompt)
        self._on_rules_prompt(0)
        return w

    def _store_rules(self) -> None:
        if self._rules_shown is not None and not self.read_only:
            self.draft.rules[self._rules_shown] = self.rules_edit.toPlainText()

    def _on_rules_prompt(self, _index: int) -> None:
        self._store_rules()
        name = self.rules_combo.currentData()
        self._rules_shown = name
        self.rules_edit.setPlainText(self.draft.rules.get(name, ""))
        own = name in self.draft.own_prompts
        self.rules_note.setText(f"This research area has its own whole {name} prompt (prompts/{name}.md): rules "
                                "here are used only if that prompt has a {{PACK_RULES}} slot." if own else "")

    def _show_prompt(self) -> None:
        from parameter_extractor.config import settings
        name = self.rules_combo.currentData()
        path = self.draft.folder / "prompts" / f"{name}.md"
        path = path if path.is_file() else settings.PROMPTS_DIR / f"{name}.md"
        dlg = QDialog(self)
        dlg.setWindowTitle(f"The {name} prompt")
        dlg.resize(820, 640)
        lay = QVBoxLayout(dlg)
        lay.addWidget(_hint("Read-only. {{PACK_RULES}} is where this research area's rules go."))
        text = QPlainTextEdit(path.read_text() if path.is_file() else "(no prompt)")
        text.setReadOnly(True)
        lay.addWidget(text)
        lay.addWidget(QPushButton("Close", clicked=dlg.accept))
        dlg.exec()

    # ---- Formulas -----------------------------------------------------------------------

    def _formulas_tab(self) -> QWidget:
        from parameter_extractor.formulas import FUNCTION_HELP, IF_PRESENT
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_hint("Calculations without code: each formula fills its column on every row where its inputs "
                          "have values, after the review, in this order (a formula can use the columns of the ones "
                          "above it). The column's unit is what its name says; inputs are in their own columns' "
                          "units, so convert in the formula (e.g. temperature_K = temperature_C + 273.15)."))
        self.f_table = QTableWidget(0, 4)
        self.f_table.setHorizontalHeaderLabels(["Column it fills", "Formula", "Description",
                                                "If the paper already gives a value"])
        self.f_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.f_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.f_table.setColumnWidth(0, 200)
        self.f_table.setColumnWidth(3, 250)
        self.f_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._if_present = {"check": "keep the paper's, flag if different", "keep": "keep the paper's",
                            "replace": "use the formula's"}
        assert set(self._if_present) == set(IF_PRESENT)
        for raw in self.draft.manifest.get("formulas", []):
            self._add_formula(raw)
        self.f_table.currentCellChanged.connect(lambda *_: self._show_formula_inputs())
        self.f_table.itemChanged.connect(lambda item: self._show_formula_inputs() if item.column() == 1 else None)
        v.addWidget(self.f_table, 2)
        buttons = QHBoxLayout()
        for text, slot in (("Add formula", lambda: self._add_formula({})), ("Remove", self._remove_formula),
                           ("Up", lambda: self._move_formula(-1)), ("Down", lambda: self._move_formula(1))):
            buttons.addWidget(QPushButton(text, clicked=slot))
        buttons.addStretch(1)
        v.addLayout(buttons)

        below = QHBoxLayout()
        trial = QGroupBox("Try the selected formula")
        tv = QVBoxLayout(trial)
        tv.addWidget(_hint("Enter values for its inputs (as they'd be in their columns)."))
        self.f_inputs = QTableWidget(0, 2)
        self.f_inputs.setHorizontalHeaderLabels(["Input column", "Value"])
        self.f_inputs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.f_inputs.itemChanged.connect(lambda _i: self._try_formula())
        tv.addWidget(self.f_inputs, 1)
        self.f_result = QLabel("Result: --")
        tv.addWidget(self.f_result)
        below.addWidget(trial, 1)
        helpbox = QGroupBox("What a formula can use")
        hv = QVBoxLayout(helpbox)
        from html import escape                      # 'pH < 7' in the help is text, not markup
        rows = "".join(f"<tr><td><code>{escape(a)}</code></td><td>&nbsp;{escape(b)}</td></tr>"
                       for a, b in FUNCTION_HELP)
        hv.addWidget(QLabel("Column names, numbers, + - * / ** ( ), comparisons and <i>and / or / not</i>.<table>"
                            f"{rows}</table>A column with no value makes the result empty (except in first() and the "
                            "pattern totals).", wordWrap=True))
        below.addWidget(helpbox, 1)
        v.addLayout(below, 1)
        return w

    def _add_formula(self, raw: dict) -> None:
        t = self.f_table
        t.blockSignals(True)
        r = t.rowCount()
        t.insertRow(r)
        for c, key in ((0, "column"), (1, "expression"), (2, "description")):
            t.setItem(r, c, QTableWidgetItem(raw.get(key, "")))
        combo = QComboBox()
        for key, label in self._if_present.items():
            combo.addItem(label, key)
        combo.setCurrentIndex(max(combo.findData(raw.get("if_present", "check")), 0))
        t.setCellWidget(r, 3, combo)
        t.blockSignals(False)
        if not raw:
            t.setCurrentCell(r, 0)

    def _remove_formula(self) -> None:
        for r in sorted({i.row() for i in self.f_table.selectedIndexes()}, reverse=True):
            self.f_table.removeRow(r)

    def _move_formula(self, step: int) -> None:
        r = self.f_table.currentRow()
        if r < 0 or not 0 <= r + step < self.f_table.rowCount():
            return
        formulas = self._formulas_from_table()
        formulas[r], formulas[r + step] = formulas[r + step], formulas[r]
        self.f_table.setRowCount(0)
        for raw in formulas:
            self._add_formula(raw)
        self.f_table.setCurrentCell(r + step, 1)

    def _formulas_from_table(self) -> list:
        out = []
        for r in range(self.f_table.rowCount()):
            text = lambda c: (self.f_table.item(r, c).text().strip() if self.f_table.item(r, c) else "")
            raw = {"column": text(0), "expression": text(1), "description": text(2),
                   "if_present": self.f_table.cellWidget(r, 3).currentData()}
            if any((raw["column"], raw["expression"])):
                out.append(raw)
        return out

    def _show_formula_inputs(self) -> None:
        """The selected formula's input columns, ready for trial values."""
        from parameter_extractor.formulas import Formula, FormulaError
        r = self.f_table.currentRow()
        expression = self.f_table.item(r, 1).text() if r >= 0 and self.f_table.item(r, 1) else ""
        try:
            inputs = Formula("x", expression).inputs() if expression.strip() else []
        except FormulaError:
            inputs = []
        old = {self.f_inputs.item(i, 0).text(): (self.f_inputs.item(i, 1).text() if self.f_inputs.item(i, 1) else "")
               for i in range(self.f_inputs.rowCount())}
        self.f_inputs.blockSignals(True)
        self.f_inputs.setRowCount(len(inputs))
        for i, column in enumerate(inputs):
            name = QTableWidgetItem(column)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.f_inputs.setItem(i, 0, name)
            self.f_inputs.setItem(i, 1, QTableWidgetItem(old.get(column, "")))
        self.f_inputs.blockSignals(False)
        self._try_formula()

    def _try_formula(self) -> None:
        from parameter_extractor.formulas import MISSING, FormulaError, evaluate
        r = self.f_table.currentRow()
        expression = self.f_table.item(r, 1).text() if r >= 0 and self.f_table.item(r, 1) else ""
        if not expression.strip():
            self.f_result.setText("Result: --")
            return
        values = {self.f_inputs.item(i, 0).text(): (self.f_inputs.item(i, 1).text() if self.f_inputs.item(i, 1) else "")
                  for i in range(self.f_inputs.rowCount())}
        try:
            value = evaluate(expression, values)
            text = "no value (an input is missing)" if value is MISSING else f"{value:.10g}"
        except FormulaError as e:
            text = f"not a usable formula: {e}"
        except (ZeroDivisionError, ValueError, OverflowError) as e:
            text = "division by zero" if isinstance(e, ZeroDivisionError) else str(e)
        column = self.f_table.item(r, 0).text() if self.f_table.item(r, 0) else ""
        self.f_result.setText(f"Result: {column or 'the column'} = {text}")

    # ---- Check --------------------------------------------------------------------------

    def _check_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        self.check_summary = QLabel()
        top.addWidget(self.check_summary, 1)
        top.addWidget(QPushButton("Check again", clicked=self.run_check))
        v.addLayout(top)
        self.check_table = QTableWidget(0, 3)
        self.check_table.setHorizontalHeaderLabels(["Level", "Where", "What"])
        self.check_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.check_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.check_table.setWordWrap(True)
        self.check_table.verticalHeader().setVisible(False)
        v.addWidget(self.check_table, 1)
        v.addWidget(_hint("Errors: the research area won't work as meant. Warnings: probably not what you want. "
                          "Notes: worth knowing."))
        return w

    def run_check(self) -> list:
        self.collect()
        problems = check(self.draft)
        t = self.check_table
        t.setRowCount(len(problems))
        for r, p in enumerate(problems):
            for c, text in enumerate([p.level.capitalize(), p.where, p.message]):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setForeground(QBrush(LEVEL_COLORS[p.level]))
                t.setItem(r, c, item)
        t.resizeColumnToContents(0)
        t.resizeColumnToContents(1)
        t.resizeRowsToContents()
        counts = {lvl: sum(p.level == lvl for p in problems) for lvl in ("error", "warning", "note")}
        self.check_summary.setText("Nothing to report." if not problems else
                                   f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['note']} note(s)")
        self.tabs.setTabText(self.tabs.count() - 1, f"Check ({counts['error']}/{counts['warning']})"
                             if counts["error"] or counts["warning"] else "Check")
        return problems

    # ---- the whole draft ----------------------------------------------------------------

    def collect(self) -> None:
        """Every tab's widgets into the draft."""
        if self.read_only:
            return
        m = self.draft.manifest
        m["label"] = self.label_edit.text().strip()
        m["description"] = self.desc_edit.toPlainText().strip()
        units = dict(m.get("units", {}))
        units.update(set=self.set_edit.text().strip() or "set", sample=self.sample_edit.text().strip() or "sample")
        if self.row_edit.text().strip():
            units["row"] = self.row_edit.text().strip()
        else:
            units.pop("row", None)
        m["units"] = units
        m["focused_row_plan"] = self.focused_box.isChecked()
        m["compact_text"] = self.compact_box.isChecked()
        m["builtin_stages"] = [n for n, box in self.builtin_boxes.items() if box.isChecked()] + \
            [n for n in m.get("builtin_stages", []) if n not in self.builtin_boxes]      # e.g. old 'methodology'
        m["postprocess"] = [self.calc_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.calc_list.count())
                            if self.calc_list.item(i).checkState() == Qt.CheckState.Checked]
        m["formulas"] = self._formulas_from_table()
        if not m["formulas"] and "_about_formulas" not in m:
            m.pop("formulas", None)
        self.draft.columns = [self.column_list.item(i).text() for i in range(self.column_list.count())]
        self.draft.species = self.species_edit.toPlainText().splitlines()
        self._store_stage()
        self._store_rules()
        self._update_column_tips()

    def save(self) -> bool:
        problems = self.run_check()
        errors = [p for p in problems if p.level == "error"]
        if errors:
            answer = QMessageBox.warning(
                self, "Save with errors?", f"The check found {len(errors)} error(s), e.g.:\n\n{errors[0]}\n\nSave "
                "anyway? The research area may not run until they're fixed.",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(self.tabs.count() - 1)
                return False
        try:
            self.draft.save()
        except (OSError, PermissionError) as e:
            QMessageBox.warning(self, "Not saved", str(e))
            return False
        self.setWindowTitle(f"Research area: {self.draft.manifest.get('label', '')}")
        self.saved.emit(self.draft.manifest.get("id", ""))
        return True

    def _copy(self) -> None:
        dlg = NewPackDialog(self, source=self.draft.manifest.get("id"))
        if dlg.exec() and dlg.created is not None:
            self.saved.emit(dlg.created.id)
            self.accept()
            editor = PackEditor(dlg.created.folder, self.parent(), self.registry_path)
            editor.saved.connect(self.saved.emit)
            editor.exec()

    def _lock(self, widget: QWidget) -> None:
        """Read-only (the app's own research areas): everything can be looked at, nothing changed."""
        for child in widget.findChildren(QWidget):
            if isinstance(child, (QLineEdit, QPlainTextEdit)):
                child.setReadOnly(True)
            elif child is self.rules_combo or (isinstance(child, QPushButton)
                                               and child.text() == "Show the shared prompt…"):
                continue                       # choosing which rules to look at
            elif isinstance(child, (QCheckBox, QComboBox, QPushButton)):
                child.setEnabled(False)
        for lst in widget.findChildren(QListWidget):
            lst.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            lst.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for table in widget.findChildren(QTableWidget):
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)


DELETE_WORD = "DELETE"


class DeleteConfirmDialog(QDialog):
    """The second confirmation of removing a research area: type DELETE, then Remove (Mickey, 2026-11-05)."""

    def __init__(self, pack: packs.Pack, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove research area")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"To remove <b>{pack.label}</b> and its folder for good, type "
                                f"<b>{DELETE_WORD}</b> below.", wordWrap=True))
        self.word_edit = QLineEdit(placeholderText=DELETE_WORD)
        layout.addWidget(self.word_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.remove_btn = buttons.addButton("Remove", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.word_edit.textChanged.connect(self._on_word)
        self.setMinimumWidth(440)

    def _on_word(self, text: str) -> None:
        typed = text == DELETE_WORD
        self.remove_btn.setEnabled(typed)
        self.remove_btn.setDefault(typed)          # Return confirms only once DELETE is typed


def remove_pack(parent) -> Optional[str]:
    """Data Packs > Remove research area: choose one of the user's areas, a warning (Remove / Cancel), then type
    DELETE and confirm. Returns the id removed, or None."""
    pack = choose_pack(parent, "Remove research area", include_builtin=False)
    if pack is None:
        return None
    warning = QMessageBox(QMessageBox.Icon.Warning, "Remove research area",
                          f"Remove the research area '{pack.label}'?", parent=parent)
    warning.setInformativeText(f"Its folder -- columns, stages, rules -- is deleted and can't be restored:\n"
                               f"{pack.folder}\n\nDatasets already written from it are not affected.")
    proceed = warning.addButton("Continue…", QMessageBox.ButtonRole.DestructiveRole)
    warning.addButton(QMessageBox.StandardButton.Cancel)
    warning.exec()
    if warning.clickedButton() is not proceed:
        return None
    if DeleteConfirmDialog(pack, parent).exec() != QDialog.DialogCode.Accepted:
        return None
    try:
        packs.delete_pack(pack.id)
    except (ValueError, PermissionError, OSError) as e:
        QMessageBox.warning(parent, "Not removed", str(e))
        return None
    return pack.id


def choose_pack(parent, title: str, include_builtin: bool = True) -> Optional[packs.Pack]:
    """Ask which research area (the app's own marked as such)."""
    found = sorted(packs.available().values(), key=lambda p: p.label)
    if not include_builtin:
        found = [p for p in found if not PackDraft.load(p.folder).builtin]
    if not found:
        QMessageBox.information(parent, title, "There are no research areas of your own yet: use Data Packs > New "
                                               "research area.")
        return None
    labels = [p.label + ("  (built in)" if PackDraft.load(p.folder).builtin else "") for p in found]
    label, ok = QInputDialog.getItem(parent, title, "Research area:", labels, 0, False)
    return found[labels.index(label)] if ok else None
