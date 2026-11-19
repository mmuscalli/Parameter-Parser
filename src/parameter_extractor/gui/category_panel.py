"""
The Columns tab's category panel (pack editor; Mickey, 2026-11-19: "integrate the variable categories into the
Data packs window ... merge with the existing Columns tab"): the settings of the kind of value (variable category)
selected in the column tree, beside it.

A category of the pack's own (pack.json "variable_categories") is edited here and saved with the pack: label,
description, value format, max words, table order, whether the model may put values in it. One from a module or
shared by every data pack is shown, not edited here -- it is the same in every pack; the Variable categories window
changes those for all packs. Every category's level and fill setting are this pack's own and editable here (the same
settings as the Structure tab: they are kept there, so both tabs show the same).
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

FORMATS = {"any": "Number or text", "number": "One number with a unit", "text": "Text"}


class CategoryPanel(QWidget):
    """One kind of value's settings. `manifest`: the draft's pack.json (its own categories are changed in it);
    `structure`: the Structure tab's page (levels and fill settings); `saved`: callable -> {id: VariableCategory}
    of the pack as saved (modules' and shared categories)."""

    changed = Signal(str)                  # a category's label changed (the column tree's header follows)
    remove_requested = Signal(str)

    def __init__(self, manifest: dict, structure, saved: Callable[[], dict], read_only: bool = False,
                 open_all: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self.manifest, self.structure, self._saved, self.read_only = manifest, structure, saved, read_only
        self.cid: Optional[str] = None
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 0, 0, 0)
        self.title = QLabel(textFormat=Qt.TextFormat.RichText)
        self.title.setStyleSheet("font-size: 15px; font-weight: bold;")
        v.addWidget(self.title)
        self.origin = QLabel(wordWrap=True)
        self.origin.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.origin)
        self.body = QWidget()
        form = QFormLayout(self.body)
        form.setContentsMargins(0, 6, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.label = QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(76)
        self.description.setToolTip("What the model is told this kind of value holds.")
        self.value_type = QComboBox()
        for key, text in FORMATS.items():
            self.value_type.addItem(text, key)
        self.max_words = QSpinBox(minimum=0, maximum=200, specialValueText="no limit")
        self.table_order = QSpinBox(minimum=0, maximum=10000)
        self.table_order.setToolTip("Where its block of columns sits in the dataset (lower = further left).")
        for spin in (self.max_words, self.table_order):
            spin.setMinimumWidth(120)
        self.model_assigns = QCheckBox("The model may put other values in it")
        self.model_assigns.setToolTip("A step's 'other values' answers may go into this kind of value (it then "
                                      "needs a description: the model is told what it holds).")
        self.level = QComboBox()
        self.fill = QComboBox()
        self.fill.setToolTip("Papers often state a method or condition once, for one experiment. Fill in: the rows "
                             "that don't give it get the value the others agree on (marked as assumed).")
        for text, w in (("Name:", self.label), ("Description:", self.description), ("Value format:", self.value_type),
                        ("Max words:", self.max_words), ("Table order:", self.table_order), ("", self.model_assigns),
                        ("Recorded for:", self.level), ("If only some rows give it:", self.fill)):
            form.addRow(text, w)
        v.addWidget(self.body)
        self.note = QLabel(wordWrap=True)
        self.note.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.note)
        buttons = QHBoxLayout()
        self.remove_btn = QPushButton("Remove this kind of value",
                                      clicked=lambda: self.cid and self.remove_requested.emit(self.cid))
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)
        v.addLayout(buttons)
        v.addStretch(1)
        self.all_btn = QPushButton("Variable categories (all data packs)…")
        self.all_btn.setToolTip("The categories of every data pack in one window: change the shared ones and the "
                                "modules' (for every pack), or the app's own data packs'.")
        if open_all:
            self.all_btn.clicked.connect(open_all)
        v.addWidget(self.all_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.label.editingFinished.connect(self._store)
        self.description.textChanged.connect(self._store)
        for w in (self.value_type, self.level, self.fill):
            w.currentIndexChanged.connect(self._store)
        for w in (self.max_words, self.table_order):
            w.valueChanged.connect(self._store)
        self.model_assigns.toggled.connect(self._store)
        self.show_category(None)

    # ---- showing one ---------------------------------------------------------------------------------------------

    def own_entry(self, cid: Optional[str]) -> Optional[dict]:
        return next((c for c in self.manifest.get("variable_categories", []) if c.get("id") == cid), None)

    def show_category(self, cid: Optional[str], automatic: str = "") -> None:
        """Show `cid`'s settings; None: nothing chosen (`automatic`: what a group of added columns is)."""
        self._loading = True
        try:
            self.cid = cid
            own = self.own_entry(cid)
            saved = self._saved().get(cid) if cid else None
            kind = self.structure.kind(cid) if cid else None
            if cid is None or (own is None and saved is None):
                self.title.setText(automatic and "Added automatically" or "Choose a kind of value")
                self.origin.setText(automatic or "Click a category (or one of its columns) to see its settings "
                                                 "here.")
                self.body.setVisible(False)
                self.remove_btn.setVisible(False)
                self.note.setText("")
                return
            self.body.setVisible(True)
            entry = dict(own) if own is not None else {
                f: getattr(saved, f) for f in ("label", "description", "value_type", "max_words", "table_order")}
            assigns = (own.get("model_assigns") if own.get("model_assigns") is not None else not own.get("sources"))\
                if own is not None else saved.assignable
            self.title.setText(entry.get("label") or cid)
            origin = (kind or {}).get("origin") or ("this data pack" if own is not None else "every data pack")
            self.origin.setText(f"id '{cid}' · from {origin}")
            self.label.setText(entry.get("label", ""))
            self.description.setPlainText(entry.get("description", ""))
            self.value_type.setCurrentIndex(max(self.value_type.findData(entry.get("value_type") or "any"), 0))
            self.max_words.setValue(int(entry.get("max_words") or 0))
            self.table_order.setValue(int(entry.get("table_order") if entry.get("table_order") is not None else 500))
            self.model_assigns.setChecked(bool(assigns))
            for combo, choices, value in ((self.level, self.structure.level_choices(), (kind or {}).get("level")),
                                          (self.fill, self.structure.fill_choices(), (kind or {}).get("fill"))):
                combo.clear()
                for key, text in choices:
                    combo.addItem(text, key)
                combo.setCurrentIndex(max(combo.findData(value), 0))
            editable = own is not None and not self.read_only
            for w in (self.label, self.value_type, self.max_words, self.table_order, self.model_assigns):
                w.setEnabled(editable)
            self.description.setReadOnly(not editable)
            self.level.setEnabled(kind is not None and not self.read_only)
            self.fill.setEnabled(kind is not None and not self.read_only and not self.structure.fills_by_patterns())
            self.remove_btn.setVisible(own is not None)
            self.remove_btn.setEnabled(editable)
            if own is None:
                self.note.setText("Its name, description and format are the same in every data pack that has it: "
                                  "change them in the Variable categories window. Where it's recorded and whether "
                                  "it's filled in are this data pack's own settings.")
            elif self.read_only:
                self.note.setText("")
            else:
                self.note.setText("Saved with the data pack. Where it's recorded and whether it's filled in are also "
                                  "on the Structure tab.")
        finally:
            self._loading = False

    # ---- changes -------------------------------------------------------------------------------------------------

    def _store(self, *_args) -> None:
        if self._loading or self.cid is None or self.read_only:
            return
        own = self.own_entry(self.cid)
        if own is not None:
            label = self.label.text().strip() or own.get("label") or self.cid
            label_changed = label != own.get("label")
            for field, value, default in (("label", label, None),
                                          ("description", self.description.toPlainText().strip(), ""),
                                          ("value_type", self.value_type.currentData(), "any"),
                                          ("max_words", self.max_words.value(), 0),
                                          ("table_order", self.table_order.value(), 500)):
                if value != own.get(field, default):           # only what changed: pack.json keeps its shape
                    own[field] = value
            assigns = own.get("model_assigns") if own.get("model_assigns") is not None else not own.get("sources")
            if self.model_assigns.isChecked() != bool(assigns):
                own["model_assigns"] = self.model_assigns.isChecked()
            if label_changed:
                self.title.setText(label)
                self.structure.set_kind(self.cid, label=label)
                self.changed.emit(self.cid)
        kind = self.structure.kind(self.cid)
        if kind is not None and (kind["level"], kind["fill"]) != (self.level.currentData(), self.fill.currentData()):
            self.structure.set_kind(self.cid, level=self.level.currentData(), fill=self.fill.currentData())
