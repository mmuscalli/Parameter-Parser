"""
The Data Packs menu's windows (Mickey, 2026-11-05: data packs made and edited inside the app).

  NewPackDialog   name, id, description, what a set and a row are called, and what to start from: the template
                  (packs/_template: examples to replace) or a copy of an existing data pack -- the way to change
                  one of the app's own. packs.create_pack() makes the folder in the user's packs folder.
  PackEditor      one data pack's files as tabs, edited on a copy (pack_editing.PackDraft) and written on Save:
                    General  -- name, description, set / row words, built-in steps, calculations, categories
                    Columns  -- the dataset's columns in order (and a compound vocabulary for the chemistry step)
                    Stages   -- each extraction stage: what it asks, when it runs, its parameters (columns)
                    Rules    -- the pack's rules for the shared prompts (planning rows, figures, ...)
                    Formulas -- calculations without code (formulas.py), with a panel to try one out
                    Check    -- pack_editing.check(): errors, warnings and notes; run again on Save
                  The app's own data packs open read-only, with a button to copy one.
"""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtCore import QSize
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter,
                               QTabWidget, QToolButton,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor import packs
from parameter_extractor.pack_editing import (BUILTIN_STAGES, CALCULATION_NEEDS, CALCULATION_STEP, CALCULATIONS, RULE_PROMPTS,
                                              PackDraft, Problem, check, items_to_rules, rules_to_items)
from parameter_extractor.gui.widgets import RowSeparatorDelegate, in_cell, style_rows

RULES_ROW_GAP = 13      # rules are long texts: more room between them and the lines (Mickey, 2026-11-06)
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


class HelpButton(QToolButton):
    """A small '?' that shows its explanation on hover and on click (Mickey, 2026-11-05: the editor's long
    explanations moved behind these)."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.help_text = text
        self.setText("?")
        self.setToolTip(text)
        self.setAutoRaise(True)
        self.setFixedSize(22, 22)
        self.setStyleSheet("QToolButton { border: 1px solid palette(mid); border-radius: 11px; font-weight: bold; }")
        self.clicked.connect(self._show)

    def _show(self) -> None:
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.help_text, self)


def _titled(title: str, help_text: str) -> QWidget:
    """A section title with a '?' beside it holding the explanation."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    label = QLabel(f"<b>{title}</b>")
    h.addWidget(label)
    h.addWidget(HelpButton(help_text))
    h.addStretch(1)
    return w


def _disclosure(title: str, box: QWidget = None, bold: bool = True):
    """A collapsible section, closed at first: an arrow button and the widget it shows or hides."""
    box = box or QWidget()
    btn = QToolButton(text=title, checkable=True)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    btn.setArrowType(Qt.ArrowType.RightArrow)
    btn.setStyleSheet("QToolButton { border: none; %s}" % ("font-weight: bold; " if bold else ""))
    box.setVisible(False)

    def toggle(shown: bool) -> None:
        box.setVisible(shown)
        btn.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
    btn.toggled.connect(toggle)
    return btn, box


def _hint(text: str) -> QLabel:
    label = QLabel(text, wordWrap=True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


# ---- New research area -------------------------------------------------------------------------

class _ColumnTree(QTreeWidget):
    """The Columns tab's tree: categories hold columns; a column dropped on a column lands next to it, in that
    column's category (never inside it)."""

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setRootIsDecorated(True)
        self.setIndentation(18)
        self.setAlternatingRowColors(False)
        self.invisibleRootItem().setFlags(Qt.ItemFlag.ItemIsEnabled)      # nothing dropped outside a category

    def dropEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        if target is not None and target.parent() is not None and \
                self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.OnItem:
            event.ignore()                           # onto a column: not as its child
            return
        super().dropEvent(event)
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setExpanded(True)


DRAFT = "__draft__"            # source_combo: drafted from sample papers (pack_drafting.py)
DRAFT_HELP = ("The app reads a few typical papers of the field -- a cheap survey of what each reports (Claude Haiku, a "
              "few cents a paper), then one request (Claude Sonnet) that designs the data pack: columns with "
              "units, categories, extraction steps and rules for the rows. Nothing is extracted yet. The result opens "
              "in the editor to fine-tune; drafted_from.md in its folder lists each parameter with the papers that "
              "reported it. 3-5 papers that differ from each other work best. Uses the models set in Settings (a "
              "local model server, if chosen there).")


class _DraftSignals(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)              # DraftResult or an Exception


class NewPackDialog(QDialog):
    """Name a new data pack and choose what it starts from; `created` is the new pack after Create.
    `config`: a callable giving the run configuration (API key, models) -- needed to draft from sample papers;
    without it that choice isn't offered."""

    def __init__(self, parent=None, source: Optional[str] = None, config=None):
        super().__init__(parent)
        self.setWindowTitle("New data pack")
        self.resize(620, 420)
        self.created: Optional[packs.Pack] = None
        self.draft_result = None
        self._config = config
        self._cancel = None
        self._id_edited = False
        layout = QVBoxLayout(self)
        layout.addWidget(_titled("A new data pack", "A data pack decides the dataset's columns, how a paper's results "
                               "become rows, and what is extracted. It starts as a working copy of the template or "
                               "of an existing area; you then edit it (Data Packs > Edit data pack)."))
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
        self.source_combo.addItem("The template (example columns, step and rules to replace)", "")
        if config is not None:
            self.source_combo.addItem("A draft made from sample papers (uses the API)", DRAFT)
            self.source_combo.setItemData(1, DRAFT_HELP, Qt.ItemDataRole.ToolTipRole)
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
        # drafting from sample papers: the papers, progress, what it costs
        from parameter_extractor.gui.paper_list import PaperListPanel
        self.draft_box = QWidget(visible=False)
        dv = QVBoxLayout(self.draft_box)
        dv.setContentsMargins(0, 0, 0, 0)
        note = QLabel(DRAFT_HELP, wordWrap=True)
        note.setStyleSheet("color: palette(placeholder-text);")
        dv.addWidget(note)
        self.papers = PaperListPanel()
        self.papers.setMinimumHeight(170)
        self.papers.message.connect(lambda m: self.error.setText(m))
        dv.addWidget(self.papers)
        options = QGroupBox("Options")
        of = QFormLayout(options)
        of.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.passes_combo = QComboBox()
        for n, text in ((1, "1 pass (cheapest)"), (2, "2 passes, merged (recommended)"), (3, "3 passes, merged")):
            self.passes_combo.addItem(text, n)
        self.passes_combo.setToolTip("How many times each paper is surveyed (Claude Haiku, about a cent or two a pass "
                                     "per paper). Every pass misses something different; the variables and compounds "
                                     "of all passes are merged.")
        self.tidy_box = QCheckBox("Name columns by the app's conventions (initial_pH, initial_temperature_C, ...)")
        self.tidy_box.setToolTip("Local, no cost: drafted names for quantities the app already has a convention for "
                                 "are changed to it (pH -> initial_pH / sampled_pH, reaction temperature -> "
                                 "initial_temperature_C, wet-dry cycles -> cycle_number, a sample's reaction time -> "
                                 "the row column duration_hr, ...). Listed in drafted_from.md.")
        self.compounds_box = QCheckBox("Find compounds in the drafted columns and set up the chemistry step "
                                       "(local + PubChem, no extra model cost)")
        self.compounds_box.setToolTip("For chemistry papers: substances named in the drafted columns and the papers' "
                                      "examples become compounds of the chemistry step (one column per compound, "
                                      "PubChem identities). Can also be done later in the editor (Find compounds…).")
        from PySide6.QtCore import QSettings
        self.compounds_box.setChecked(QSettings().value("draft/find_compounds", False, type=bool))
        self.compounds_box.toggled.connect(lambda on: QSettings().setValue("draft/find_compounds", on))
        self.tidy_box.setChecked(QSettings().value("draft/tidy_names", True, type=bool))
        self.tidy_box.toggled.connect(lambda on: QSettings().setValue("draft/tidy_names", on))
        self.passes_combo.setCurrentIndex(max(0, self.passes_combo.findData(
            QSettings().value("draft/survey_passes", 2, type=int))))
        self.passes_combo.currentIndexChanged.connect(
            lambda _i: QSettings().setValue("draft/survey_passes", self.passes_combo.currentData()))
        of.addRow("Survey passes:", self.passes_combo)
        of.addRow(self.tidy_box)
        of.addRow(self.compounds_box)
        dv.addWidget(options)
        self.draft_progress = QProgressBar(visible=False, textVisible=False)
        self.draft_status = QLabel(wordWrap=True)
        dv.addWidget(self.draft_progress)
        dv.addWidget(self.draft_status)
        layout.addWidget(self.draft_box, 1)
        self.error = QLabel(wordWrap=True)
        self.error.setStyleSheet(f"color: {LEVEL_COLORS['error'].name()};")
        layout.addWidget(self.error)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_btn = buttons.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.create)
        buttons.rejected.connect(self._cancel_or_close)
        layout.addWidget(buttons)
        self.label_edit.textChanged.connect(self._on_label)
        self.id_edit.textEdited.connect(lambda _t: setattr(self, "_id_edited", True))
        self.source_combo.currentIndexChanged.connect(self._on_source)

    def _on_label(self, text: str) -> None:
        if not self._id_edited:
            self.id_edit.setText(suggest_id(text))

    def _on_source(self, _index: int) -> None:
        drafting = self.source_combo.currentData() == DRAFT
        self.draft_box.setVisible(drafting)
        self.create_btn.setText("Draft from these papers" if drafting else "Create")
        if drafting:                                # room for the papers and options (no overlap on macOS)
            self.setMinimumSize(self.layout().minimumSize())
            self.resize(max(self.width(), 760), max(self.height(), 820, self.layout().sizeHint().height()))
        else:
            self.setMinimumSize(0, 0)
        source = packs.available().get(self.source_combo.currentData() or "")
        if source is not None:                      # a copy keeps the words of what it's copied from
            self.set_edit.setText(source.manifest.units.get("set", "set"))
            self.sample_edit.setText(source.manifest.units.get("sample", "sample"))

    def create(self) -> None:
        if self.source_combo.currentData() == DRAFT:
            self._start_draft()
            return
        source = packs.available().get(self.source_combo.currentData() or "")
        try:
            self.created = packs.create_pack(self.id_edit.text().strip(), self.label_edit.text(),
                                             self.desc_edit.toPlainText(), source=source,
                                             units={"set": self.set_edit.text(), "sample": self.sample_edit.text()})
        except (ValueError, OSError) as e:
            self.error.setText(str(e))
            return
        self.accept()


    # ---- drafting from sample papers ------------------------------------------------------------
    def _start_draft(self) -> None:
        import threading
        from parameter_extractor import pack_drafting
        label, pack_id = self.label_edit.text(), self.id_edit.text().strip()
        try:
            pack_drafting.check_new_id(pack_id, label)
        except ValueError as e:
            self.error.setText(str(e))
            return
        items = self.papers.items()
        if not items:
            self.error.setText("Add a few sample papers (PDFs, or arXiv IDs / DOIs).")
            return
        config = self._config()
        if config.needs_api_key and not config.api_key:
            self.error.setText("Drafting reads the papers with the API: add your Anthropic API key in Settings first "
                               "(or choose a local model server there).")
            return
        self.error.setText("")
        self._cancel = threading.Event()
        self._signals = _DraftSignals()
        self._signals.progress.connect(self._draft_progress)
        self._signals.done.connect(self._draft_done)
        self._set_drafting(True)
        description = self.desc_edit.toPlainText()
        compounds, tidy, passes = self.compounds_box.isChecked(), self.tidy_box.isChecked(), self.passes_combo.currentData()

        def work():
            try:
                from parameter_extractor.pubchem import PubChem
                from parameter_extractor.registry import default_pubchem_cache_path
                pubchem = PubChem(config.pubchem_cache_path or default_pubchem_cache_path()) \
                    if config.use_pubchem else None
                # compounds are set up whenever the draft links the chemistry step; the box asks for it anyway
                result = pack_drafting.draft_pack(items, pack_id, label, description, config,
                                                  on_progress=self._signals.progress.emit, cancel_event=self._cancel,
                                                  passes=passes, tidy=tidy, compounds=True if compounds else None,
                                                  pubchem=pubchem)
                if pubchem is not None:
                    pubchem.save()
            except BaseException as e:           # shown in the dialog
                result = e
            self._signals.done.emit(result)
        self._thread = threading.Thread(target=work, daemon=True, name="pack-draft")
        self._thread.start()

    def _set_drafting(self, on: bool) -> None:
        for w in (self.label_edit, self.id_edit, self.desc_edit, self.set_edit, self.sample_edit, self.source_combo,
                  self.create_btn, self.compounds_box, self.tidy_box, self.passes_combo):
            w.setEnabled(not on)
        self.papers.set_locked(on)
        self.draft_progress.setVisible(on)
        self.draft_progress.setRange(0, 0)

    def _draft_progress(self, done: int, total: int, message: str) -> None:
        self.draft_progress.setRange(0, max(total, 1))
        self.draft_progress.setValue(done)
        self.draft_status.setText(message)

    def _draft_done(self, result) -> None:
        self._set_drafting(False)
        self._cancel = None
        if isinstance(result, BaseException):
            from parameter_extractor.errors import RunCancelledError
            self.error.setText("Drafting cancelled." if isinstance(result, RunCancelledError) else str(result))
            return
        self.draft_result = result
        self.created = result.pack
        self.accept()

    def _cancel_or_close(self) -> None:
        if self._cancel is not None:             # a draft is running: stop it (the dialog stays open)
            self._cancel.set()
            self.draft_status.setText("Cancelling after the current request…")
            return
        self.reject()


# ---- Edit a research area ----------------------------------------------------------------------

class PackEditor(QDialog):
    """One data pack's files as tabs (see the module docstring). `saved` fires after a save."""
    saved = Signal(str)

    def __init__(self, folder: Path, parent=None, registry_path: Optional[Path] = None, config=None):
        super().__init__(parent)
        self.draft = PackDraft.load(folder)
        self.registry_path = registry_path
        self._config = config                    # callable -> RunConfig (suggestions from papers use the API)
        self.read_only = self.draft.builtin
        # a pack to open in a new editor once this one has closed (after a helper rewrote the files, or a copy was
        # made): the opener does it -- a window never runs the next one from inside its own handlers (2026-11-09:
        # nested modal windows left the main window without input)
        self.next_folder: Optional[Path] = None
        self._stage = None                         # the stage file shown in the Stages tab
        self._rules_shown = None
        self.setWindowTitle(f"Data pack: {self.draft.manifest.get('label', '')}"
                            + ("  (built in, read-only)" if self.read_only else ""))
        self.resize(1320, 820)
        layout = QVBoxLayout(self)
        if self.read_only:
            banner = QHBoxLayout()
            banner.addWidget(QLabel("This data pack is part of the app and can't be changed. Copy it to make "
                                    "your own version.", wordWrap=True), 1)
            banner.addWidget(QPushButton("Copy to a new data pack…", clicked=self._copy))
            layout.addLayout(banner)
        self.tabs = QTabWidget()
        # the order says how a pack is put together (2026-11-09): what happens to a paper; the pack's own parts;
        # the shared modules it links and this pack's settings for them; the check
        tabs = (("Overview", self._overview_tab(), "What happens to each paper with this data pack: every request to "
                 "the AI model (and where it comes from) and every calculation done on your computer."),
                ("General", self._general_tab(), "This data pack's name, row words, built-in steps and calculations."),
                ("Columns", self._columns_tab(), "This data pack's columns, by category."),
                ("Steps", self._stages_tab(), "This data pack's own configurable steps: each is one model request per "
                 "paper it runs for (files in the pack's stages/ folder)."),
                ("Rules", self._rules_tab(), "This data pack's rules for the shared prompts (e.g. planning rows)."),
                ("Formulas", self._formulas_tab(), "This data pack's calculations written as formulas."),
                ("Compounds", self._compounds_tab(), "This data pack's compound vocabulary, used by the chemistry step "
                 "(from the Solution chemistry module)."),
                ("Modules", self._modules_tab(), "The shared modules this data pack links, what each brings, and this "
                 "pack's own settings for them (the modules themselves stay the same in every pack)."),
                ("Check", self._check_tab(), "Problems the app finds in this data pack."))
        for name, widget, tip in tabs:
            self.tabs.setTabToolTip(self.tabs.addTab(widget, name), tip)
        self.tabs.currentChanged.connect(lambda _i: self._fit_rows())
        self._follow_step("chemistry", "Compounds")
        self._refresh_module_effects()
        self._refresh_overview()
        self.tabs.currentChanged.connect(lambda i: self._refresh_formula_columns()
                                         if self.tabs.tabText(i) == "Formulas" else None)
        layout.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        where = _hint(f"Folder: {self.draft.folder}")
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom.addWidget(where, 1)
        bottom.addWidget(QPushButton("Open folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.draft.folder)))))
        if self.registry_path:
            remembered = QPushButton("Remembered from your reviews…", clicked=self._open_remembered)
            remembered.setToolTip("What you've taught the app for this data pack while reviewing papers (accepted "
                                  "columns, synonyms, compound names, changes to this pack's columns). Kept apart "
                                  "from the pack, so it applies on top of it.")
            bottom.addWidget(remembered)
        self.compounds_btn = QPushButton("Find compounds / tidy names…", clicked=self._find_compounds)
        self.compounds_btn.setToolTip("Find the compounds named in this data pack's columns and examples, identify "
                                      "them on PubChem (free, no model) and switch the chemistry step on for them -- "
                                      "you review everything before it's changed. Saves your edits first.")
        self.suggest_btn = QPushButton("Suggest additions from papers…", clicked=self._suggest_additions)
        self.suggest_btn.setToolTip("Survey a few new sample papers (cheap) and get suggestions for what this research "
                                    "area lacks: parameters, steps, categories, rules, compounds. You choose what's "
                                    "added. Saves your edits first.")
        for b in (self.compounds_btn, self.suggest_btn):
            b.setEnabled(not self.read_only)
            bottom.addWidget(b)
        if self.read_only:
            for b in (self.compounds_btn, self.suggest_btn):
                b.setToolTip("Copy this data pack first: the app's own can't be changed.")
        if config is None:
            self.suggest_btn.setEnabled(False)
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
        v.addLayout(form)

        rows_box = QGroupBox("Row options")          # what the area's rows and their groups are called (2026-11-06)
        rf = _form()
        rf.addRow("A group of rows is called:", self.set_edit)
        rf.addRow("One row is called:", self.sample_edit)
        rf.addRow("In messages, a row is:", self.row_edit)
        rows_box.setLayout(rf)
        v.addWidget(rows_box)

        self.optimization_btn, self.optimization_box = _disclosure("Optimization and Focused Search")
        ov = QVBoxLayout(self.optimization_box)
        ov.setContentsMargins(18, 0, 0, 0)
        ov.addWidget(self.focused_box)
        ov.addWidget(self.compact_box)
        v.addWidget(self.optimization_btn)
        v.addWidget(self.optimization_box)
        v.addSpacing(14)                               # room before the steps (Mickey: the area felt crowded)

        steps = QGroupBox("Built-in extraction steps (written in code; most new data packs use none)")
        sv = QVBoxLayout(steps)
        self.builtin_boxes = {}
        self._own_steps = set(m.get("builtin_stages", []))
        for name, about in BUILTIN_STAGES.items():
            box = QCheckBox(f"{name} -- {about}", checked=name in self._own_steps)
            box.setProperty("about", about)
            box.toggled.connect(lambda on, n=name, b=box: (self._own_steps.add(n) if on else self._own_steps.discard(n))
                                if b.isEnabled() else None)
            self.builtin_boxes[name] = box
            sv.addWidget(box)
        v.addWidget(steps)

        calcs = QGroupBox("Calculations run on the rows, in this order (tick to use; Move up / down to reorder)")
        cv = QVBoxLayout(calcs)
        self.calc_table = self._calc_table()           # those that suit the area's built-in steps, and any ticked
        row = QHBoxLayout()
        row.addWidget(self.calc_table, 1)
        moves = QVBoxLayout()
        self.calc_up_btn = QPushButton("Move up", clicked=lambda: self._move_calc(-1))
        self.calc_down_btn = QPushButton("Move down", clicked=lambda: self._move_calc(1))
        moves.addWidget(self.calc_up_btn)
        moves.addWidget(self.calc_down_btn)
        moves.addStretch(1)
        row.addLayout(moves)
        self.calc_row = QWidget()
        self.calc_row.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.calc_row, 1)
        self.no_calcs_note = _hint("None of the calculations was written for this data pack's built-in steps "
                                   "(most new areas use none). Formulas (their own tab) cover calculations within a "
                                   "row; the app's other calculations are below.")
        cv.addWidget(self.no_calcs_note)
        self.other_calcs_btn, self.other_calc_table = _disclosure("", self._calc_table(), bold=False)
        self.other_calc_table.itemChanged.connect(self._on_other_calc)
        cv.addWidget(self.other_calcs_btn)
        cv.addWidget(self.other_calc_table, 1)
        v.addWidget(calcs)
        v.addStretch(1)                              # the box only as tall as what it shows
        self._fill_calculations(list(m.get("postprocess", [])))
        for box in self.builtin_boxes.values():
            box.toggled.connect(lambda _on: self._fill_calculations(self._chosen_calculations()))

        cats = QHBoxLayout()
        cats.addWidget(_titled("Variable categories", "Variable categories (how suggested variables and columns are grouped) are edited in "
                             "their own window; categories defined by the pack are in pack.json."), 1)
        self.categories_btn = QPushButton("Edit variable categories…", clicked=self._open_categories)
        cats.addWidget(self.categories_btn)
        v.addLayout(cats)
        return w

    # the calculations tables (spaced rows like the categories window, 2026-11-06) -------------------------------

    CALC_HEADERS = ("Calculator", "Description", "Requirements", "Written for")

    def _calc_table(self) -> QTableWidget:
        t = QTableWidget(0, len(self.CALC_HEADERS))
        t.setHorizontalHeaderLabels(list(self.CALC_HEADERS))
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = t.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        t.setMinimumHeight(200)
        style_rows(t)
        return t

    def _add_calc_row(self, table: QTableWidget, name: str, checked: bool) -> None:
        about, _ = CALCULATIONS.get(name, ("(unknown calculation)", ""))
        step = CALCULATION_STEP.get(name, "")
        r = table.rowCount()
        table.insertRow(r)
        item = QTableWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, name)
        flags = item.flags() & ~Qt.ItemFlag.ItemIsEditable
        from_module = self._module_calcs().get(name)
        if from_module:                        # the module brings it: shown ticked, not the pack's to untick
            flags &= ~(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            step = f"the {from_module} module"
        elif not getattr(self, "_calcs_locked", False):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        else:
            flags &= ~Qt.ItemFlag.ItemIsUserCheckable
        item.setFlags(flags)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        table.setItem(r, 0, item)
        for c, text in ((1, about), (2, CALCULATION_NEEDS.get(name, "")),
                        (3, step if from_module else f"the {step} step" if step else "any data pack")):
            cell = QTableWidgetItem(text)
            cell.setToolTip(text)
            table.setItem(r, c, cell)

    @staticmethod
    def _calc_names(table: QTableWidget, ticked_only: bool = False) -> list:
        return [table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(table.rowCount())
                if not ticked_only or table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def _chosen_calculations(self) -> list:
        """Ticked calculations, in the main table's order (then any ticked below) -- the pack's own: the ones its
        modules bring aren't written into it."""
        provided = self._module_calcs()
        return [n for n in self._calc_names(self.calc_table, True) + self._calc_names(self.other_calc_table, True)
                if n not in provided]

    def _fill_calculations(self, chosen: list) -> None:
        """Main table: the ticked ones (in order), then the unticked ones written for the area's built-in steps;
        'Other calculations': everything else."""
        steps = {n for n, box in self.builtin_boxes.items() if box.isChecked()}
        chosen = list(self._module_calcs()) + [n for n in chosen if n not in self._module_calcs()]
        main = chosen + [n for n in CALCULATIONS if n not in chosen and CALCULATION_STEP.get(n) in steps]
        other = [n for n in CALCULATIONS if n not in main]
        for table, names, ticked in ((self.calc_table, main, set(chosen)), (self.other_calc_table, other, set())):
            table.blockSignals(True)
            table.setRowCount(0)
            for name in names:
                self._add_calc_row(table, name, name in ticked)
            table.blockSignals(False)
            table.resizeRowsToContents()
        self.calc_row.setVisible(bool(main))
        self.no_calcs_note.setVisible(not main)
        self.other_calcs_btn.setText(f"Other calculations ({len(other)}) -- written for other built-in steps")
        self.other_calcs_btn.setVisible(bool(other))
        if not other:
            self.other_calc_table.setVisible(False)
        else:
            self.other_calc_table.setVisible(self.other_calcs_btn.isChecked())

    def _move_calc(self, step: int) -> None:
        t = self.calc_table
        r = t.currentRow()
        if r < 0 or not 0 <= r + step < t.rowCount():
            return
        names = self._calc_names(t)
        ticked = set(self._calc_names(t, True))
        names[r], names[r + step] = names[r + step], names[r]
        t.blockSignals(True)
        t.setRowCount(0)
        for name in names:
            self._add_calc_row(t, name, name in ticked)
        t.blockSignals(False)
        t.resizeRowsToContents()
        t.setCurrentCell(r + step, 0)

    def _on_other_calc(self, item: QTableWidgetItem) -> None:
        """Ticking one of the other calculations moves it into the main table (at the end of the ticked ones)."""
        if item.column() == 0 and item.checkState() == Qt.CheckState.Checked:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._fill_calculations(self._chosen_calculations()))

    def _open_remembered(self) -> None:
        from parameter_extractor.gui.registry_dialog import RegistryDialog
        RegistryDialog(self.registry_path, parent=self, area=self.draft.manifest.get("id")).exec()

    def _open_categories(self) -> None:
        from parameter_extractor.gui.categories_dialog import CategoriesDialog
        if self.draft.manifest.get("id") not in packs.available():
            QMessageBox.information(self, "Save first", "Save the data pack first: its categories are edited "
                                                        "once the app knows it.")
            return
        dlg = CategoriesDialog(self.registry_path, parent=self)
        dlg.area_combo.setCurrentIndex(max(dlg.area_combo.findData(self.draft.manifest["id"]), 0))
        dlg.exec()

    # ---- Columns ------------------------------------------------------------------------

    def _columns_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_titled("The dataset's columns, by category", "The dataset's columns, grouped by variable "
                          "category in the order the dataset writes them. Put the unit at the end of a name "
                          "(temperature_C, pressure_bar, mass_g, yield_pct): values are converted into it. The shared "
                          "columns (paper, authors, DOI, ...) and row identifiers are added automatically. Columns a "
                          "step fills but that aren't listed here are added after these. Double-click a column to "
                          "rename it; drag it to reorder, or onto another category to move it there."))
        row = QHBoxLayout()
        self.column_tree = _ColumnTree()
        self.column_tree.setHeaderLabels(["Column", "Unit", "Filled by"])
        self.column_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.column_tree.header().setStretchLastSection(True)
        self.column_tree.setColumnWidth(0, 360)
        self.column_tree.setColumnWidth(1, 90)
        self._fill_column_tree(self.draft.columns)
        row.addWidget(self.column_tree, 1)
        side = QVBoxLayout()
        for text, slot in (("Add…", self._add_column), ("Remove", self._remove_column)):
            side.addWidget(QPushButton(text, clicked=slot))
        side.addStretch(1)
        row.addLayout(side)
        v.addLayout(row, 1)
        return w

    # the Columns tab: one header per variable category, its columns below (2026-11-08)
    def _fill_column_tree(self, columns: List[str]) -> None:
        from parameter_extractor.column_order import ColumnOrder, IDENTIFIERS_LABEL, PROVENANCE_LABEL
        from parameter_extractor.ingestion.observations import unit_for_column
        try:
            order = ColumnOrder(pack=packs.Pack(self.draft.folder))
        except Exception:                            # a pack that doesn't load yet: one block
            order = None
        self._column_order = order
        self._home_category = {c: order.category_of(c) for c in columns} if order else {}
        tree = self.column_tree
        tree.clear()
        groups: Dict[str, QTreeWidgetItem] = {}
        fills = self.draft.stage_columns()
        header_font = QFont(tree.font())
        header_font.setBold(True)
        header_font.setPointSizeF(header_font.pointSizeF() + 1)

        def header(key: str, label: str, droppable: bool) -> QTreeWidgetItem:
            item = QTreeWidgetItem([label, "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setFont(0, header_font)
            item.setForeground(0, QBrush(tree.palette().color(QPalette.ColorRole.Link)))
            item.setSizeHint(0, QSize(0, 40))              # the space above each category
            item.setFirstColumnSpanned(True)
            flags = Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsDropEnabled if droppable else Qt.ItemFlag.NoItemFlags)
            item.setFlags(flags)
            tree.addTopLevelItem(item)
            item.setExpanded(True)
            return item
        if order is not None:
            for cat in order.display:                    # every category, so columns can be moved into an empty one
                groups[cat.id] = header(cat.id, cat.label, True)
        ordered = order.ordered(columns) if order else list(columns)
        for c in ordered:
            if order is None:
                key, label = "", "Columns"
            else:
                label = order.label_of(c)
                key = {IDENTIFIERS_LABEL: "__row__", PROVENANCE_LABEL: "__provenance__"}.get(label, order.category_of(c))
            if key not in groups:
                groups[key] = header(key, label, not key.startswith("__"))
            self._column_item(groups[key], c, unit_for_column(c), fills.get(c))
        for key, item in groups.items():                 # counts; empty categories say so
            n = item.childCount()
            item.setText(1, f"{n} column{'s' if n != 1 else ''}" if n else "empty")
            if not n:
                item.setToolTip(0, "No columns yet: drag columns here to put them in this category.")
            item.setForeground(1, QBrush(tree.palette().color(QPalette.ColorRole.PlaceholderText)))
        # Row / Provenance blocks first and last, as the dataset writes them
        for key, index in (("__row__", 0), ("__provenance__", tree.topLevelItemCount() - 1)):
            if key in groups:
                tree.insertTopLevelItem(index, tree.takeTopLevelItem(tree.indexOfTopLevelItem(groups[key])))
                groups[key].setExpanded(True)

    def _column_item(self, parent: QTreeWidgetItem, column: str, unit: str, stages) -> QTreeWidgetItem:
        item = QTreeWidgetItem([column, unit or "", ", ".join(stages) if stages else ""])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
                      | Qt.ItemFlag.ItemIsDragEnabled)
        item.setToolTip(0, f"Filled by: {', '.join(stages)}" if stages else "No step fills this column yet.")
        if not stages:
            item.setForeground(2, QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText)))
            item.setText(2, "not filled by a step")
        parent.addChild(item)
        return item

    def _refresh_column_fills(self) -> None:
        """'Filled by' after the stages changed."""
        fills = self.draft.stage_columns()
        muted = QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText))
        for i in range(self.column_tree.topLevelItemCount()):
            group = self.column_tree.topLevelItem(i)
            for j in range(group.childCount()):
                item = group.child(j)
                stages = fills.get(item.text(0).strip())
                item.setText(2, ", ".join(stages) if stages else "not filled by a step")
                item.setForeground(2, QBrush() if stages else muted)
                item.setToolTip(0, f"Filled by: {', '.join(stages)}" if stages else "No step fills this column yet.")

    def _tree_columns(self) -> List[str]:
        """The columns as the tree lists them (category by category)."""
        out = []
        for i in range(self.column_tree.topLevelItemCount()):
            group = self.column_tree.topLevelItem(i)
            out += [group.child(j).text(0).strip() for j in range(group.childCount()) if group.child(j).text(0).strip()]
        return out

    def _moved_categories(self) -> Dict[str, str]:
        """column -> category for columns the user put under a different category than they'd go to by default."""
        out = {}
        for i in range(self.column_tree.topLevelItemCount()):
            group = self.column_tree.topLevelItem(i)
            key = group.data(0, Qt.ItemDataRole.UserRole) or ""
            if not key or key.startswith("__"):
                continue
            for j in range(group.childCount()):
                col = group.child(j).text(0).strip()
                home = self._home_category.get(col)
                if col and (home is None and self._column_order is not None
                            and self._column_order.category_of(col) != key or home is not None and home != key):
                    out[col] = key
        return out

    def _store_column_categories(self) -> None:
        """Moved columns become explicit entries of their new category (pack.json category_columns)."""
        moved = self._moved_categories()
        if not moved:
            return
        cc = self.draft.manifest.setdefault("category_columns", {})
        for entry in cc.values():
            entry["columns"] = [c for c in entry.get("columns", []) if c not in moved]
        for col, cat in moved.items():
            cc.setdefault(cat, {"columns": []}).setdefault("columns", []).append(col)

    # ---- tabs that follow a built-in step ------------------------------------------------------

    def tab(self, name: str) -> QWidget:
        """A tab by its title (tests and code use names: the tabs' positions change)."""
        return self.tabs.widget(self.tab_index(name))

    def tab_index(self, name: str) -> int:
        """The tab titled `name`, also when its title carries a count ('Check (1/2)' when the pack has problems)."""
        return next(i for i in range(self.tabs.count())
                    if self.tabs.tabText(i) == name or self.tabs.tabText(i).startswith(name + " ("))

    def _follow_step(self, step: str, tab: str) -> None:
        """A tab only a built-in step uses is enabled when the step is used -- ticked on the General tab, or brought by
        a module (the chemistry step: the Solution chemistry module)."""
        box = self.builtin_boxes.get(step)
        i = self.tab_index(tab)
        update = lambda _on=None: (
            self.tabs.setTabEnabled(i, bool(box and box.isChecked())),
            self.tabs.setTabToolTip(i, "" if box and box.isChecked() else
                                    f"Used by the '{step}' step: link the module that brings it (Modules tab) or "
                                    f"tick it on the General tab."))
        update()
        if box:
            box.toggled.connect(update)

    # ---- Overview (what happens to each paper) and module settings (2026-11-09) ------------------------------------

    def _overview_tab(self) -> QWidget:
        from PySide6.QtWidgets import QTextBrowser
        w = QWidget()
        v = QVBoxLayout(w)
        self.overview = QTextBrowser()
        self.overview.setOpenExternalLinks(False)
        self.overview.document().setDocumentMargin(18)
        v.addWidget(self.overview, 1)
        return w

    def _refresh_overview(self) -> None:
        """The paper's way through the pack as SAVED (Save updates it), after the parts it's made of."""
        from parameter_extractor import pack_overview
        try:
            flow = pack_overview.as_html(pack_overview.paper_flow(packs.Pack(self.draft.folder)))
        except Exception as e:                      # a pack the app can't load: the Check tab says why
            flow = f"<p>The data pack can't be loaded as saved ({e}); see the Check tab.</p>"
        self.overview.setHtml(pack_overview.parts_html() + "<h2>What happens to each paper</h2>"
                              "<p class='muted'>As saved -- Save updates this page.</p>" + flow)

    # ---- Modules (shared parts the pack links in: parameter_extractor/modules/) ----------------------------

    def _modules_tab(self) -> QWidget:
        """Every module: tick to link; the selected one's description, what it brings, this pack's settings for it
        (module_settings_tab.ModuleSettingsEditor) and -- Analysis methods -- its vocabulary (2026-11-09: one tab)."""
        from PySide6.QtWidgets import QScrollArea, QSplitter
        from parameter_extractor import modules as module_store
        from parameter_extractor.gui.module_settings_tab import ModuleSettingsEditor
        self.module_settings_tab = ModuleSettingsEditor(self.draft.manifest.get("module_settings"),
                                                        read_only=self.read_only, on_change=self._mark_module_changes)
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_titled("Modules this data pack uses", "Modules are shared parts -- steps, calculations, "
                            "columns, rules, a vocabulary -- that several data packs link. They're linked, not "
                            "copied: an improvement to a module reaches every pack that uses it, and there's only ever "
                            "one version. Tick a module to link it, untick to unlink. For a linked module you can "
                            "change how it works IN THIS DATA PACK (switch its parts off, store a value in another "
                            "unit, change trigger words, add rules); only your changes are kept, the rest follows the "
                            "module. Saved with Save."))
        self.module_table = QTableWidget(0, 2)
        self.module_table.setHorizontalHeaderLabels(["Module", "In this data pack"])
        self.module_table.verticalHeader().setVisible(False)
        head = self.module_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.module_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.module_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        style_rows(self.module_table)
        own = set(self.draft.manifest.get("modules", []))
        for mid, mod in module_store.available().items():
            r = self.module_table.rowCount()
            self.module_table.insertRow(r)
            item = QTableWidgetItem(mod.label)
            item.setData(Qt.ItemDataRole.UserRole, mid)
            item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(Qt.CheckState.Checked if mid in own else Qt.CheckState.Unchecked)
            if self.read_only:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            item.setToolTip(mod.manifest.description)
            self.module_table.setItem(r, 0, item)
            linked = QTableWidgetItem("")
            linked.setFlags(linked.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.module_table.setItem(r, 1, linked)
        self.module_table.setColumnWidth(1, 190)
        self.module_table.itemChanged.connect(lambda it: self._refresh_module_effects() if it.column() == 0 else None)
        self.module_table.currentCellChanged.connect(lambda r, _c, pr, _pc: self._show_module(r) if r != pr else None)
        # the analysis vocabulary: built once, placed on the Analysis methods module's page
        self.vocab_box = QGroupBox("Techniques and instrument settings (the module's vocabulary)")
        bv = QVBoxLayout(self.vocab_box)
        bv.addWidget(self._analysis_tab())
        self.vocab_box.setMinimumHeight(560)
        self.module_scroll = QScrollArea()
        self.module_scroll.setWidgetResizable(True)
        # the page follows the pane's width (wrapped text, tables scroll inside) -- no sideways scrolling
        self.module_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        from PySide6.QtWidgets import QSizePolicy
        self.vocab_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.module_table)
        split.addWidget(self.module_scroll)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([360, 1000])
        split.setChildrenCollapsible(False)
        v.addWidget(split, 1)
        if self.module_table.rowCount():
            self.module_table.setCurrentCell(0, 0)
        return w

    def _module_status(self, mid: str) -> str:
        from parameter_extractor import modules as module_store
        found, chosen = module_store.available(), set(self._chosen_modules())
        if mid in chosen:
            return "linked" + (" • changed" if self.module_settings_tab.changed(mid) else "")
        by = [found[o].label for o in chosen if o in found and mid in found[o].manifest.needs]
        if by and mid in {m.id for m in self._linked_modules()}:
            return "brought along by " + ", ".join(by) + (" • changed" if self.module_settings_tab.changed(mid) else "")
        return ""

    def _mark_module_changes(self) -> None:
        t = getattr(self, "module_table", None)
        if t is None:
            return
        t.blockSignals(True)
        for r in range(t.rowCount()):
            t.item(r, 1).setText(self._module_status(t.item(r, 0).data(Qt.ItemDataRole.UserRole)))
        t.blockSignals(False)

    def _chosen_modules(self) -> list:
        """The modules ticked (the pack's own list; the ones they bring along aren't listed)."""
        t = getattr(self, "module_table", None)
        if t is None:
            return list(self.draft.manifest.get("modules", []))
        out = []
        for r in range(t.rowCount()):
            item = t.item(r, 0)
            if item.checkState() == Qt.CheckState.Checked and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _linked_modules(self) -> list:
        from parameter_extractor import modules as module_store
        return module_store.resolve(self._chosen_modules())

    def _module_steps(self) -> dict:
        """{built-in step: module label} for the steps the linked modules bring."""
        return {s: m.label for m in self._linked_modules() for s in m.manifest.builtin_stages}

    def _module_calcs(self) -> dict:
        if getattr(self, "module_table", None) is None:
            return {}
        return {c: m.label for m in self._linked_modules() for c in m.manifest.postprocess}

    def _refresh_module_effects(self) -> None:
        """After a module was ticked or unticked: the 'Linked' column (incl. modules brought along), the built-in
        steps it brings (ticked, greyed), the calculations, the tabs that follow a step."""
        t = self.module_table
        linked = {m.id for m in self._linked_modules()}
        chosen = set(self._chosen_modules())
        from parameter_extractor import modules as module_store
        found = module_store.available()
        t.blockSignals(True)
        for r in range(t.rowCount()):
            item = t.item(r, 0)
            mid = item.data(Qt.ItemDataRole.UserRole)
            by = [found[o].label for o in chosen if o in found and mid in found[o].manifest.needs]
            if mid not in chosen and mid in linked and by:
                item.setCheckState(Qt.CheckState.Checked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            elif not self.read_only:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
        t.blockSignals(False)
        self._mark_module_changes()
        provided = self._module_steps()
        for name, box in self.builtin_boxes.items():
            box.blockSignals(True)
            if name in provided:
                box.setChecked(True)
                box.setEnabled(False)
                box.setText(f"{name} -- {box.property('about')}  (from the {provided[name]} module)")
            else:
                box.setEnabled(not self.read_only)
                box.setChecked(name in self._own_steps)
                box.setText(f"{name} -- {box.property('about')}")
            box.blockSignals(False)
            box.toggled.emit(box.isChecked())          # the tabs that follow a step
        self._fill_calculations(self._chosen_calculations())
        self._fill_vocab()
        self._show_module(t.currentRow())
        from parameter_extractor.stages.optional import StageSpec
        brought = []
        for mod in self._linked_modules():
            for f in mod.stage_files():
                try:
                    brought.append(f"{StageSpec.model_validate_json(f.read_text()).label} ({mod.label} module)")
                except ValueError:
                    pass
        self.module_stages_note.setText("Also run, from linked modules (adjust them on the Modules tab): " + "; ".join(brought)
                                        if brought else "")
        self.module_stages_note.setVisible(bool(brought))

    def _show_module(self, row: int) -> None:
        """The selected module's page: what it is and brings, this pack's settings for it when linked, and the
        Analysis methods module's vocabulary."""
        from html import escape
        from parameter_extractor import modules as module_store, pack_modules
        self.module_settings_tab.release()
        self.vocab_box.setParent(None)                 # kept across pages (built once)
        item = self.module_table.item(row, 0) if row >= 0 else None
        mod = module_store.available().get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        page = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        pv = QVBoxLayout(page)
        pv.setContentsMargins(14, 10, 14, 14)
        pv.setSpacing(12)
        if mod is None:
            self.module_scroll.setWidget(page)
            return
        linked = mod.id in {m.id for m in self._linked_modules()}
        head = QHBoxLayout()
        status = self._module_status(mod.id) or "not linked"
        title = QLabel(f"<span style='font-size:15pt; font-weight:600'>{escape(mod.label)}</span>"
                       f"&nbsp;&nbsp;<span style='color:gray'>{escape(status)}</span>")
        head.addWidget(title, 1)
        if linked:
            reset = QPushButton("Reset to the module's defaults", clicked=lambda: self._reset_module(mod.id))
            reset.setEnabled(not self.read_only)
            reset.setToolTip("Forget this data pack's changes to the module.")
            head.addWidget(reset)
        pv.addLayout(head)
        about = QLabel(escape(mod.manifest.description), wordWrap=True)
        pv.addWidget(about)
        brings = QLabel("<table cellpadding='3' cellspacing='0'>" + "".join(
            f"<tr><td valign='top'>•</td><td>{escape(l)}</td></tr>" for l in pack_modules.describe(mod.id))
            + "</table>", wordWrap=True)
        brings.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box = QGroupBox("What it brings")
        QVBoxLayout(box).addWidget(brings)
        pv.addWidget(box)
        if linked:
            pv.addWidget(_titled(f"Settings for this data pack", "Changes here apply to this data pack only; the "
                                 "module stays the same in every other pack. Anything you leave alone follows the "
                                 "module, including its future improvements."))
            pv.addWidget(self.module_settings_tab.build(mod))
        else:
            pv.addWidget(_hint("Tick the module on the left to link it; its settings for this data pack then appear "
                               "here."))
        if mod.file("analysis_vocab.json"):
            pv.addWidget(self.vocab_box)
            self._fill_vocab()
        pv.addStretch(1)
        self.module_scroll.setWidget(page)

    def _reset_module(self, mid: str) -> None:
        self.module_settings_tab.reset(mid)
        self._mark_module_changes()
        self._show_module(self.module_table.currentRow())

    # ---- Compounds (the chemistry step's compound vocabulary) ------------------------------------

    C_NAME, C_CID, C_TITLE, C_SYN = range(4)

    def _compounds_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_titled("Compound vocabulary (this data pack's; used by the chemistry step)", "The compounds this data pack knows -- the "
                            "pack's own list, used by the chemistry step (the Solution chemistry module): the step "
                            "asks the model to use these names, and their columns (<role>_<name>_<phase>_<measure>) "
                            "are known without a review. A PubChem CID identifies the compound, so the paper's other "
                            "names for it (from PubChem) are matched to it. New compounds found in papers are "
                            "reviewed; the ones you accept are remembered for you (Remembered from reviews), not "
                            "added here."))
        filt = QLineEdit(placeholderText="Filter compounds", clearButtonEnabled=True)
        v.addWidget(filt)
        self.compound_table = QTableWidget(0, 4)
        self.compound_table.setHorizontalHeaderLabels(["Name (as used in columns)", "PubChem CID", "PubChem title",
                                                       "PubChem synonyms"])
        self.compound_table.verticalHeader().setVisible(False)
        head = self.compound_table.horizontalHeader()
        head.setSectionResizeMode(self.C_NAME, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(self.C_CID, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(self.C_TITLE, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(self.C_SYN, QHeaderView.ResizeMode.Stretch)
        self.compound_table.setColumnWidth(self.C_TITLE, 260)
        style_rows(self.compound_table)
        for c in self.draft.compounds:
            self._add_compound_row(c)
        filt.textChanged.connect(lambda t: [self.compound_table.setRowHidden(
            r, bool(t) and t.lower() not in self.compound_table.item(r, self.C_NAME).text().lower())
            for r in range(self.compound_table.rowCount())])
        v.addWidget(self.compound_table, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Add compound…", clicked=self._add_compound))
        row.addWidget(QPushButton("Remove", clicked=lambda: [self.compound_table.removeRow(r) for r in sorted(
            {i.row() for i in self.compound_table.selectedIndexes()}, reverse=True)]))
        self.lookup_btn = QPushButton("Look up missing CIDs on PubChem", clicked=self._lookup_cids)
        self.lookup_btn.setToolTip("Asks PubChem for each compound without a CID (needs the internet). Check the "
                                   "titles it finds: a first hit can be the wrong compound.")
        row.addWidget(self.lookup_btn)
        row.addStretch(1)
        self.compound_count = _hint("")
        row.addWidget(self.compound_count)
        v.addLayout(row)
        self._count_compounds()
        return w

    def _add_compound_row(self, c: dict) -> None:
        t = self.compound_table
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, self.C_NAME, QTableWidgetItem(c.get("name", "")))
        t.setItem(r, self.C_CID, QTableWidgetItem(str(c.get("cid") or "")))
        for col, text in ((self.C_TITLE, c.get("title", "")), (self.C_SYN, ", ".join(c.get("synonyms", [])[:12]))):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(", ".join(c.get("synonyms", [])) if col == self.C_SYN else text)
            t.setItem(r, col, item)

    def _add_compound(self) -> None:
        name, ok = QInputDialog.getText(self, "Add a compound", "Name as it should appear in column names "
                                                              "(e.g. Gly-Gly, NaCl, ImpA):")
        if ok and name.strip():
            self._add_compound_row({"name": name.strip()})
            self.compound_table.scrollToBottom()
            self._count_compounds()

    def _compounds_from_table(self) -> List[dict]:
        t, out = self.compound_table, []
        for r in range(t.rowCount()):
            name = t.item(r, self.C_NAME).text().strip() if t.item(r, self.C_NAME) else ""
            cid = (t.item(r, self.C_CID).text() if t.item(r, self.C_CID) else "").strip()
            if name:
                out.append({"name": name, "cid": int(cid) if cid.isdigit() else 0})
        return out

    def _count_compounds(self) -> None:
        rows = self._compounds_from_table()
        self.compound_count.setText(f"{len(rows)} compounds, {sum(1 for r in rows if r['cid'])} with a PubChem CID")

    def _lookup_cids(self) -> None:
        from parameter_extractor.pubchem import PubChem
        from parameter_extractor.registry import default_pubchem_cache_path
        client, found, failed = PubChem(default_pubchem_cache_path()), 0, 0
        t = self.compound_table
        for r in range(t.rowCount()):
            if t.item(r, self.C_CID).text().strip():
                continue
            try:
                hit = client.lookup(t.item(r, self.C_NAME).text())
            except Exception:
                hit, failed = None, failed + 1
            if hit:
                t.item(r, self.C_CID).setText(str(hit.cid))
                t.item(r, self.C_TITLE).setText(hit.title)
                found += 1
        try:
            client.save()
        except Exception:
            pass
        self._count_compounds()
        QMessageBox.information(self, "PubChem", f"Found {found} CID(s)." + (
            f" {failed} lookup(s) failed (no internet?)." if failed else "") + " Check the titles before saving.")

    # ---- Analysis methods (the analysis step's vocabulary) ---------------------------------------

    def _analysis_tab(self) -> QWidget:
        from PySide6.QtWidgets import QStackedWidget
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_titled("Analytical techniques and their instrument settings", "What the analysis step records: "
                            "each technique a paper used and its settings, in columns analysis_<technique>_<setting>"
                            "[_<unit>] (e.g. analysis_RP-HPLC_flow-rate_mL_min). Settings are grouped in instrument "
                            "families; a technique has the settings of its families plus the 'general' ones. "
                            "Everything listed here is written to the dataset directly; other techniques and "
                            "settings a paper reports are offered in the review. Aliases are other wordings papers "
                            "use -- the app matches them, so the model's prompt only lists the names."))
        self.analysis_stack = QStackedWidget()
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.addWidget(_hint("No vocabulary: link the Analysis methods module (its techniques and settings are shared by "
                           "every data pack that uses it)."))
        ev.addStretch(1)
        self.analysis_stack.addWidget(empty)
        self.analysis_stack.addWidget(self._analysis_editor())
        v.addWidget(self.analysis_stack, 1)
        self._fill_vocab()
        return w

    def _analysis_editor(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Vertical)
        top = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Instrument families</b>"))
        self.family_list = QListWidget()
        self.family_list.currentRowChanged.connect(self._show_family)
        lv.addWidget(self.family_list, 1)
        fam_btns = QHBoxLayout()
        fam_btns.addWidget(QPushButton("Add family…", clicked=self._add_family))
        fam_btns.addWidget(QPushButton("Remove", clicked=self._remove_family))
        lv.addLayout(fam_btns)
        top.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.family_title = QLabel("<b>Settings</b>")
        rv.addWidget(self.family_title)
        self.setting_table = QTableWidget(0, 4)
        self.setting_table.setHorizontalHeaderLabels(["Setting (column part)", "Unit", "Description", "Aliases"])
        self.setting_table.verticalHeader().setVisible(False)
        head = self.setting_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.setting_table.setColumnWidth(0, 200)
        style_rows(self.setting_table)
        rv.addWidget(self.setting_table, 1)
        set_btns = QHBoxLayout()
        set_btns.addWidget(QPushButton("Add setting", clicked=lambda: self._add_setting_row({}, edit=True)))
        set_btns.addWidget(QPushButton("Remove", clicked=lambda: self._remove_rows(self.setting_table)))
        set_btns.addWidget(QPushButton("Up", clicked=lambda: self._move_setting(-1)))
        set_btns.addWidget(QPushButton("Down", clicked=lambda: self._move_setting(1)))
        set_btns.addStretch(1)
        rv.addLayout(set_btns)
        top.addWidget(right)
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 3)
        top.setSizes([380, 1000])
        split.addWidget(top)
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        head_row = QHBoxLayout()
        head_row.addWidget(_titled("Techniques", "One row per technique: its name (the column part, e.g. RP-HPLC), "
                                   "its instrument families (comma-separated ids from the list above), what it is, "
                                   "and other names papers use for it (comma-separated)."), 1)
        self.tech_filter = QLineEdit(placeholderText="Filter techniques", clearButtonEnabled=True)
        self.tech_filter.textChanged.connect(self._filter_techniques)
        head_row.addWidget(self.tech_filter)
        bv.addLayout(head_row)
        self.tech_table = QTableWidget(0, 4)
        self.tech_table.setHorizontalHeaderLabels(["Technique (column part)", "Families", "Description", "Aliases"])
        self.tech_table.verticalHeader().setVisible(False)
        th = self.tech_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tech_table.setColumnWidth(0, 170)
        self.tech_table.setColumnWidth(1, 230)
        style_rows(self.tech_table)
        bv.addWidget(self.tech_table, 1)
        tech_btns = QHBoxLayout()
        tech_btns.addWidget(QPushButton("Add technique", clicked=lambda: self._add_technique_row({}, edit=True)))
        tech_btns.addWidget(QPushButton("Remove", clicked=lambda: self._remove_rows(self.tech_table)))
        tech_btns.addStretch(1)
        self.vocab_count = _hint("")
        tech_btns.addWidget(self.vocab_count)
        bv.addLayout(tech_btns)
        split.addWidget(bottom)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([500, 500])
        v.addWidget(split, 1)
        self._family_shown = None
        return w

    # unit choices: text, whole number, then the units the app converts to
    @staticmethod
    def _unit_choices() -> List[Tuple[str, str]]:
        from parameter_extractor.analysis_vocab import UNIT_TOKENS
        return [("text", ""), ("whole number", "#")] + [(u, u) for u in UNIT_TOKENS]

    def _vocab(self) -> Optional[dict]:
        """The vocabulary shown: the pack's own file (editable; it overrides the module's), else the linked Analysis
        methods module's (read-only here)."""
        if self.draft.analysis_vocab is not None:
            return self.draft.analysis_vocab
        mod = next((m for m in self._linked_modules() if m.file("analysis_vocab.json")), None) \
            if getattr(self, "module_table", None) is not None else None
        if mod is None:
            return None
        if getattr(self, "_module_vocab", (None,))[0] != mod.folder:
            self._module_vocab = (mod.folder, json.loads(mod.file("analysis_vocab.json").read_text()))
        return self._module_vocab[1]

    def _vocab_editable(self) -> bool:
        return self.draft.analysis_vocab is not None and not self.read_only

    def _fill_vocab(self) -> None:
        vocab = self._vocab()
        self.analysis_stack.setCurrentIndex(0 if vocab is None else 1)
        if vocab is None:
            return
        editable = self._vocab_editable()
        for table in (self.tech_table, self.setting_table):
            table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
                                  if editable else QAbstractItemView.EditTrigger.NoEditTriggers)
        for b in self.analysis_stack.widget(1).findChildren(QPushButton):
            b.setVisible(editable)                   # a module's vocabulary is only shown here
        self._family_shown = None
        self.family_list.blockSignals(True)
        self.family_list.clear()
        for fid, fam in vocab.get("families", {}).items():
            item = QListWidgetItem(f"{fid}  --  {fam.get('label', '')}" if fam.get("label") else fid)
            item.setData(Qt.ItemDataRole.UserRole, fid)
            item.setToolTip(f"{fid}: {fam.get('label', '')} ({len(fam.get('settings', []))} settings)")
            self.family_list.addItem(item)
        self.family_list.blockSignals(False)
        self.tech_table.setRowCount(0)
        for t in vocab.get("techniques", []):
            self._add_technique_row(t)
        if self.family_list.count():
            self.family_list.setCurrentRow(0)
            self._show_family(0)
        self._count_vocab()

    def _count_vocab(self) -> None:
        vocab = self._vocab() or {}
        n = sum(len(f.get("settings", [])) for f in vocab.get("families", {}).values())
        self.vocab_count.setText(f"{self.tech_table.rowCount()} techniques, {len(vocab.get('families', {}))} "
                                 f"families, {n} settings")

    def _add_setting_row(self, st: dict, edit: bool = False) -> None:
        t = self.setting_table
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, 0, QTableWidgetItem(st.get("name", "")))
        combo = QComboBox()
        for label, data in self._unit_choices():
            combo.addItem(label, data)
        unit = "#" if st.get("integer") else st.get("unit", "")
        i = combo.findData(unit)
        if i < 0:                                  # a unit the app doesn't convert to: kept, shown as it is
            combo.addItem(unit, unit)
            i = combo.count() - 1
        combo.setCurrentIndex(i)
        t.setCellWidget(r, 1, in_cell(combo))
        t.setItem(r, 2, QTableWidgetItem(st.get("description", "")))
        t.setItem(r, 3, QTableWidgetItem(", ".join(st.get("aliases", []))))
        if edit:
            t.setCurrentCell(r, 0)
            t.editItem(t.item(r, 0))

    def _settings_from_table(self) -> List[dict]:
        t, out = self.setting_table, []
        for r in range(t.rowCount()):
            name = t.item(r, 0).text().strip() if t.item(r, 0) else ""
            if not name:
                continue
            unit = t.cellWidget(r, 1).findChild(QComboBox).currentData()
            entry = {"name": name, "unit": "" if unit == "#" else unit,
                     "description": t.item(r, 2).text().strip() if t.item(r, 2) else "",
                     "aliases": _split(t.item(r, 3).text() if t.item(r, 3) else "")}
            if unit == "#":
                entry = {"name": name, "unit": "", "integer": True, **{k: entry[k] for k in ("description", "aliases")}}
            out.append(entry)
        return out

    def _store_family(self) -> None:
        if self.draft.analysis_vocab is None or self._family_shown is None:
            return
        fam = self.draft.analysis_vocab["families"].get(self._family_shown)
        if fam is not None:
            fam["settings"] = self._settings_from_table()

    def _show_family(self, row: int) -> None:
        self._store_family()
        item = self.family_list.item(row) if row >= 0 else None
        self._family_shown = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.setting_table.setRowCount(0)
        if self._family_shown is None:
            return
        fam = self._vocab()["families"][self._family_shown]
        self.family_title.setText(f"<b>Settings of {self._family_shown}</b>  ({fam.get('label', '')})")
        for st in fam.get("settings", []):
            self._add_setting_row(st)
        self._count_vocab()

    def _add_family(self) -> None:
        fid, ok = QInputDialog.getText(self, "Add an instrument family", "Family id (lower case, e.g. "
                                                                          "'circular_dichroism'):")
        fid = (fid or "").strip().lower().replace(" ", "_")
        if not ok or not fid:
            return
        if fid in self.draft.analysis_vocab["families"]:
            QMessageBox.information(self, "Add family", f"There is already a family '{fid}'.")
            return
        label, _ = QInputDialog.getText(self, "Add an instrument family", "What it covers (shown next to the id):")
        self._store_family()
        self.draft.analysis_vocab["families"][fid] = {"label": label.strip(), "settings": []}
        self._fill_vocab()
        self.family_list.setCurrentRow(self.family_list.count() - 1)

    def _remove_family(self) -> None:
        item = self.family_list.currentItem()
        if not item:
            return
        fid = item.data(Qt.ItemDataRole.UserRole)
        users = [self.tech_table.item(r, 0).text() for r in range(self.tech_table.rowCount())
                 if fid in _split(self.tech_table.item(r, 1).text() if self.tech_table.item(r, 1) else "")]
        if users and QMessageBox.question(self, "Remove family", f"{len(users)} technique(s) use '{fid}' (e.g. "
                                          f"{users[0]}). Remove it anyway?") != QMessageBox.StandardButton.Yes:
            return
        self.draft.analysis_vocab["techniques"] = self._techniques_from_table()
        self.draft.analysis_vocab["families"].pop(fid, None)
        self._family_shown = None
        self._fill_vocab()

    def _move_setting(self, step: int) -> None:
        t = self.setting_table
        r = t.currentRow()
        if r < 0 or not 0 <= r + step < t.rowCount():
            return
        rows = self._settings_from_table()
        rows[r], rows[r + step] = rows[r + step], rows[r]
        t.setRowCount(0)
        for st in rows:
            self._add_setting_row(st)
        t.setCurrentCell(r + step, 0)

    @staticmethod
    def _remove_rows(t: QTableWidget) -> None:
        for r in sorted({i.row() for i in t.selectedIndexes()} | ({t.currentRow()} if t.currentRow() >= 0 else set()),
                        reverse=True):
            t.removeRow(r)

    def _add_technique_row(self, tech: dict, edit: bool = False) -> None:
        t = self.tech_table
        r = t.rowCount()
        t.insertRow(r)
        for c, text in enumerate((tech.get("name", ""), ", ".join(tech.get("families", [])),
                                  tech.get("description", ""), ", ".join(tech.get("aliases", [])))):
            t.setItem(r, c, QTableWidgetItem(text))
        if edit:
            self.tech_filter.clear()
            t.setCurrentCell(r, 0)
            t.editItem(t.item(r, 0))

    def _techniques_from_table(self) -> List[dict]:
        t, out = self.tech_table, []
        for r in range(t.rowCount()):
            cell = lambda c: t.item(r, c).text().strip() if t.item(r, c) else ""
            if cell(0):
                out.append({"name": cell(0), "families": _split(cell(1)), "description": cell(2),
                            "aliases": _split(cell(3))})
        return out

    def _filter_techniques(self, text: str) -> None:
        text = text.lower()
        for r in range(self.tech_table.rowCount()):
            row_text = " ".join(self.tech_table.item(r, c).text() for c in range(4) if self.tech_table.item(r, c))
            self.tech_table.setRowHidden(r, bool(text) and text not in row_text.lower())

    def add_column_named(self, name: str) -> None:
        """A new column, in the selected category (or the one of the selected column; else Other / the last)."""
        from parameter_extractor.ingestion.observations import unit_for_column
        tree = self.column_tree
        current = tree.currentItem()
        group = (current if current is not None and current.parent() is None else
                 current.parent() if current is not None else None)
        if group is None or (group.data(0, Qt.ItemDataRole.UserRole) or "").startswith("__"):
            group = next((tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                          if tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == "other"),
                         tree.topLevelItem(max(0, tree.topLevelItemCount() - 1)))
        if group is None:
            return
        item = self._column_item(group, name, unit_for_column(name), self.draft.stage_columns().get(name))
        group.setExpanded(True)
        tree.setCurrentItem(item)
        tree.scrollToItem(item)

    def _add_column(self) -> None:
        name, ok = QInputDialog.getText(self, "Add a column", "Column name (unit at the end, e.g. mass_g):")
        name = (name or "").strip()
        if ok and name:
            self.add_column_named(name)

    def _remove_column(self) -> None:
        for item in self.column_tree.selectedItems():
            if item.parent() is not None:
                item.parent().removeChild(item)

    # ---- Stages -------------------------------------------------------------------------

    def _stages_tab(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(_titled("Configurable steps", "Each configurable step is one request to the AI model for every paper it runs for (every paper, or only papers that call for it -- trigger words, kinds of experiments). Several steps run in parallel. These are this data pack's own; steps from its modules are listed below and adjusted in the Module settings tab."))
        self.stage_list = QListWidget()
        self.stage_list.currentRowChanged.connect(self._on_stage_row)
        left.addWidget(self.stage_list, 1)
        self.module_stages_note = _hint("")          # stages the linked modules bring (shown, not edited here)
        left.addWidget(self.module_stages_note)
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
        self.s_desc = QLineEdit(placeholderText="shown next to the step's on/off switch")
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
        # Basics: what the stage is and when it runs; Advanced (collapsed): how it asks (Mickey, 2026-11-05)
        fv.addWidget(QLabel("<b>Basics</b>"))
        form.addRow("Name:", self.s_name)
        form.addRow("Label:", self.s_label)
        form.addRow("Description:", self.s_desc)
        form.addRow("Instruction:", self.s_intro)
        form.addRow("Values belong to:", self.s_per)
        form.addRow("Runs for:", trigger)
        fv.addLayout(form)
        self.advanced_btn = QToolButton(text="Advanced", checkable=True)
        self.advanced_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_btn.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        fv.addWidget(self.advanced_btn)
        self.advanced_box = QWidget()
        advanced = _form()
        advanced.setContentsMargins(0, 0, 0, 0)
        self.advanced_box.setLayout(advanced)
        advanced.addRow("The model's role:", self.s_system)
        advanced.addRow("Tables:", self.s_images)
        advanced.addRow("Other values:", self.s_open)
        advanced.addRow("", self.s_open_hint)
        advanced.addRow("Uncertainty columns:", self.s_uncert)
        advanced.addRow("Rules:", self.s_rules)
        self.advanced_box.setVisible(False)
        self.advanced_btn.toggled.connect(self._toggle_advanced)
        fv.addWidget(self.advanced_box)
        fv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings_w)
        self.stage_scroll = scroll
        params_w = QWidget()
        fv = QVBoxLayout(params_w)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.addWidget(QLabel("Parameters -- the columns this step fills:"))
        self.p_table = QTableWidget(0, len(P_HEADERS))
        self.p_table.setHorizontalHeaderLabels(P_HEADERS)
        for c, tip in ((P_INTEGER, "A count: written as a whole number ('triplicate' -> 3)."),
                       (P_UNCERT, "Also fill the ± uncertainty columns of this value."),
                       (P_CHOICES, "For text: the only words allowed, comma-separated (others are left out)."),
                       (P_UNIT, "The column's unit (matching the end of its name); values are converted into it.")):
            self.p_table.horizontalHeaderItem(c).setToolTip(tip)
        self.p_table.horizontalHeader().setSectionResizeMode(P_DESC, QHeaderView.ResizeMode.Stretch)
        style_rows(self.p_table)                       # spaced rows like the categories window
        for c, width in ((P_COLUMN, 170), (P_UNIT, 55), (P_KIND, 92), (P_CHOICES, 110), (P_INTEGER, 70),
                         (P_UNCERT, 40)):
            self.p_table.setColumnWidth(c, width)

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

    def _toggle_advanced(self, shown: bool) -> None:
        self.advanced_box.setVisible(shown)
        self.advanced_btn.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
        if shown:                                    # bring the opened section into view
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.stage_scroll.ensureWidgetVisible(self.advanced_box))

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
        for edit in (self.s_name, self.s_label, self.s_desc, self.s_system, self.s_open_hint, self.s_keywords,
                     self.s_set_types, self.s_patterns):
            edit.setCursorPosition(0)                # long texts show their start
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
            kind = self.p_table.cellWidget(r, P_KIND).findChild(QComboBox).currentData()
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
        self.p_table.setCellWidget(r, P_KIND, in_cell(kind))
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
        label, ok = QInputDialog.getText(self, "New step", "What the step extracts (e.g. Sample properties):")
        if not ok or not label.strip():
            return
        self._store_stage()
        try:
            file = self.draft.new_stage(suggest_id(label) or "stage", label.strip())
        except ValueError as e:
            QMessageBox.warning(self, "New step", str(e))
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
        if QMessageBox.question(self, "Remove step", f"Remove the step '{name}'? (Only on Save.)") \
                != QMessageBox.StandardButton.Yes:
            return
        file, self._stage = self._stage, None
        self.draft.remove_stage(file)
        self._fill_stage_list()

    # ---- Rules --------------------------------------------------------------------------

    def _rules_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_titled("Rules for the shared prompts", "Rules for this data pack, added to the app's shared prompts. The most important "
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
        # one row per rule (the file's '- ' lines; pack_editing.rules_to_items / items_to_rules convert)
        self.rules_table = QTableWidget(0, 1)
        self.rules_table.setHorizontalHeaderLabels(["Rule (double-click to edit)"])
        self.rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        style_rows(self.rules_table, RowSeparatorDelegate(self.rules_table, gap=RULES_ROW_GAP))
        v.addWidget(self.rules_table, 1)
        buttons = QHBoxLayout()
        for text, slot in (("Add rule", self._add_rule), ("Remove", self._remove_rule),
                           ("Up", lambda: self._move_rule(-1)), ("Down", lambda: self._move_rule(1))):
            buttons.addWidget(QPushButton(text, clicked=slot))
        buttons.addStretch(1)
        v.addLayout(buttons)
        self.rules_combo.currentIndexChanged.connect(self._on_rules_prompt)
        self._on_rules_prompt(0)
        return w

    def rules_items(self) -> list:
        return [self.rules_table.item(r, 0).text() for r in range(self.rules_table.rowCount())
                if self.rules_table.item(r, 0) and self.rules_table.item(r, 0).text().strip()]

    def set_rules_items(self, items: list) -> None:
        self.rules_table.setRowCount(0)
        for text in items:
            self._add_rule(text, edit=False)

    def _add_rule(self, text: str = "", edit: bool = True) -> None:
        r = self.rules_table.rowCount()
        self.rules_table.insertRow(r)
        self.rules_table.setItem(r, 0, QTableWidgetItem(text if isinstance(text, str) else ""))
        if edit:
            self.rules_table.setCurrentCell(r, 0)
            self.rules_table.editItem(self.rules_table.item(r, 0))

    def _remove_rule(self) -> None:
        for r in sorted({i.row() for i in self.rules_table.selectedIndexes()}, reverse=True):
            self.rules_table.removeRow(r)

    def _move_rule(self, step: int) -> None:
        r = self.rules_table.currentRow()
        if r < 0 or not 0 <= r + step < self.rules_table.rowCount():
            return
        items = [self.rules_table.item(i, 0).text() if self.rules_table.item(i, 0) else ""
                 for i in range(self.rules_table.rowCount())]
        items[r], items[r + step] = items[r + step], items[r]
        self.set_rules_items(items)
        self.rules_table.setCurrentCell(r + step, 0)

    def _store_rules(self) -> None:
        if self._rules_shown is not None and not self.read_only:
            self.draft.rules[self._rules_shown] = items_to_rules(self.rules_items())

    def _on_rules_prompt(self, _index: int) -> None:
        self._store_rules()
        name = self.rules_combo.currentData()
        self._rules_shown = name
        self.set_rules_items(rules_to_items(self.draft.rules.get(name, "")))
        own = name in self.draft.own_prompts
        self.rules_note.setText(f"This data pack has its own whole {name} prompt (prompts/{name}.md): rules "
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
        lay.addWidget(_hint("Read-only. {{PACK_RULES}} is where this data pack's rules go."))
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
        v.addWidget(_titled("Formulas, run in this order", "Calculations without code: each formula fills its column on every row where its inputs "
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
        self._formula_editor = None
        style_rows(self.f_table, FormulaDelegate(self, self.f_table))
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
        trial.setMaximumWidth(330)                       # a few inputs: it needn't be wide
        tv = QVBoxLayout(trial)
        tv.addWidget(_hint("Values for its inputs, as they'd be in their columns:"))
        self.f_inputs = QTableWidget(0, 2)
        self.f_inputs.setHorizontalHeaderLabels(["Input column", "Value"])
        self.f_inputs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.f_inputs.setColumnWidth(1, 90)
        style_rows(self.f_inputs)
        self.f_inputs.itemChanged.connect(lambda _i: self._try_formula())
        tv.addWidget(self.f_inputs, 1)
        self.f_result = QLabel("Result: --", wordWrap=True)
        tv.addWidget(self.f_result)
        below.addWidget(trial)
        below.addWidget(self._formula_columns())
        below.addWidget(self._formula_reference(FUNCTION_HELP), 1)
        v.addLayout(below, 1)
        return w

    def _formula_columns(self) -> QWidget:
        """Every column of the data pack; a click types the name into the formula being written."""
        box = QGroupBox("Columns (click to insert)")
        box.setMaximumWidth(330)                         # names, not prose: the reference beside it gets the room
        v = QVBoxLayout(box)
        self.f_column_filter = QLineEdit(placeholderText="filter", clearButtonEnabled=True)
        self.f_column_filter.textChanged.connect(self._filter_formula_columns)
        v.addWidget(self.f_column_filter)
        self.f_columns = QListWidget()
        self.f_columns.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # the formula cell keeps the focus (and its cursor)
        self.f_columns.itemClicked.connect(lambda item: self.insert_formula_column(item.text()))
        self.f_columns.setToolTip("Click a column to put it in the formula at the cursor (names with - % ( ) go in "
                                  "backticks automatically).")
        v.addWidget(self.f_columns, 1)
        self._refresh_formula_columns()
        return box

    def _refresh_formula_columns(self) -> None:
        """The columns as the tabs have them now (the Columns / Stages tabs may have changed them)."""
        if not hasattr(self, "f_columns"):
            return
        if not self.read_only and hasattr(self, "column_tree"):
            self.draft.columns = self._tree_columns()
            self._store_stage()
        names = list(dict.fromkeys(self.draft.all_columns()
                                   + [f["column"] for f in self._formulas_from_table() if f["column"]]))
        self.f_columns.clear()
        self.f_columns.addItems(names)
        self._filter_formula_columns(self.f_column_filter.text())

    def _filter_formula_columns(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.f_columns.count()):
            item = self.f_columns.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def insert_formula_column(self, column: str) -> None:
        """Into the open Formula cell at its cursor; else at the end of the selected formula."""
        token = column if column.isidentifier() else f"`{column}`"
        editor = self._formula_editor
        if editor is not None:
            editor.insert(token)
            editor.setFocus()
            return
        r = self.f_table.currentRow()
        if r < 0:
            if self.f_table.rowCount() == 0:
                self._add_formula({})
            r = max(self.f_table.currentRow(), 0)
        item = self.f_table.item(r, 1)
        text = item.text() if item else ""
        joined = text + ("" if not text or text.endswith((" ", "(")) else " ") + token
        if item is None:
            self.f_table.setItem(r, 1, QTableWidgetItem(joined))
        else:
            item.setText(joined)
        self.f_table.setCurrentCell(r, 1)
        self._show_formula_inputs()

    @staticmethod
    def _formula_reference(entries) -> QWidget:
        """What a formula can use: what to write in one aligned column, what it does in the next."""
        from PySide6.QtGui import QFontDatabase
        box = QGroupBox("What a formula can use")
        outer = QVBoxLayout(box)
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(3)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSizeF(QLabel().font().pointSizeF())        # the same size as the descriptions
        for r, (code, what) in enumerate(entries):
            left = QLabel(code)
            left.setFont(mono)
            left.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(left, r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(QLabel(what), r, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(grid_w)
        outer.addWidget(scroll, 1)
        outer.addWidget(_hint("A column with no value leaves the result empty (first() and the pattern totals skip "
                              "it)."))
        return box

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
        t.setCellWidget(r, 3, in_cell(combo))
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
                   "if_present": self.f_table.cellWidget(r, 3).findChild(QComboBox).currentData()}
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
        top.addWidget(self.check_summary)
        top.addWidget(HelpButton("Errors: the data pack won't work as meant. Warnings: probably not what you "
                                 "want. Notes: worth knowing. The check runs again when you save; errors ask before "
                                 "saving."))
        top.addStretch(1)
        top.addWidget(QPushButton("Check again", clicked=self.run_check))
        v.addLayout(top)
        self.check_table = QTableWidget(0, 3)
        self.check_table.setHorizontalHeaderLabels(["Level", "Where", "What"])
        self.check_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.check_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        style_rows(self.check_table)
        self.check_table.verticalHeader().setVisible(False)
        v.addWidget(self.check_table, 1)
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
        provided = self._module_steps()
        m["builtin_stages"] = [n for n in self.builtin_boxes if n in self._own_steps and n not in provided] + \
            [n for n in m.get("builtin_stages", []) if n not in self.builtin_boxes]      # e.g. old 'methodology'
        m["postprocess"] = self._chosen_calculations()
        m["modules"] = self._chosen_modules()
        if not m["modules"]:
            m.pop("modules", None)
        m["module_settings"] = self.module_settings_tab.values([x.id for x in self._linked_modules()])
        if not m["module_settings"]:
            m.pop("module_settings", None)
        m["formulas"] = self._formulas_from_table()
        if not m["formulas"] and "_about_formulas" not in m:
            m.pop("formulas", None)
        self.draft.columns = self._tree_columns()
        self._store_column_categories()
        self.draft.compounds = self._compounds_from_table()
        self._store_family()
        if self.draft.analysis_vocab is not None:
            self.draft.analysis_vocab["techniques"] = self._techniques_from_table()
        self._store_stage()
        self._store_rules()
        self._refresh_column_fills()

    def save(self) -> bool:
        problems = self.run_check()
        errors = [p for p in problems if p.level == "error"]
        if errors:
            answer = QMessageBox.warning(
                self, "Save with errors?", f"The check found {len(errors)} error(s), e.g.:\n\n{errors[0]}\n\nSave "
                "anyway? The data pack may not run until they're fixed.",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(self.tabs.count() - 1)
                return False
        try:
            self.draft.save()
        except (OSError, PermissionError) as e:
            QMessageBox.warning(self, "Not saved", str(e))
            return False
        self.setWindowTitle(f"Data pack: {self.draft.manifest.get('label', '')}")
        self._refresh_overview()
        self.saved.emit(self.draft.manifest.get("id", ""))
        return True

    def _find_compounds(self) -> None:
        from parameter_extractor.gui.pack_assist import CompoundSetupDialog
        if not self.save():
            return
        dlg = CompoundSetupDialog(self.draft.folder, self)
        if dlg.exec():
            self._reopen("Compounds set up", dlg.applied, dlg.problems)

    def _suggest_additions(self) -> None:
        from parameter_extractor.gui.pack_assist import AdditionsDialog
        if self._config is None or not self.save():
            return
        dlg = AdditionsDialog(self.draft.folder, self._config, self)
        if dlg.exec():
            self._reopen("Suggestions applied", dlg.applied, dlg.problems)

    def _reopen(self, title: str, done: list, problems: list) -> None:
        """After a helper changed the pack's files: tell what was done, then the editor again on the new files."""
        errors_ = [p for p in problems if p.level == "error"]
        QMessageBox.information(self, title, "\n".join(f"• {d}" for d in done[:30]) + (
            f"\n\nThe check found {len(errors_)} error(s) -- see the Check tab." if errors_ else ""))
        self.saved.emit(self.draft.manifest.get("id", ""))
        self.next_folder = self.draft.folder
        self.accept()

    def _copy(self) -> None:
        dlg = NewPackDialog(self, source=self.draft.manifest.get("id"), config=self._config)
        if dlg.exec() and dlg.created is not None:
            self.saved.emit(dlg.created.id)
            self.next_folder = dlg.created.folder
            self.accept()

    def help_buttons(self) -> list:
        """The '?' buttons holding the editor's explanations."""
        return self.findChildren(HelpButton)

    def _lock(self, widget: QWidget) -> None:
        """Read-only (the app's own data packs): everything can be looked at, nothing changed."""
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
        self._calcs_locked = True                  # the calculation ticks too
        if hasattr(self, "calc_table"):
            self._fill_calculations(self._chosen_calculations())


DELETE_WORD = "DELETE"


class DeleteConfirmDialog(QDialog):
    """The second confirmation of removing a data pack: type DELETE, then Remove (Mickey, 2026-11-05)."""

    def __init__(self, pack: packs.Pack, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove data pack")
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


def remove_pack(parent, pack: Optional[packs.Pack] = None) -> Optional[str]:
    """Data Packs > Remove data pack: choose one of the user's areas (unless given), a warning (Remove / Cancel), then
    type DELETE and confirm. Returns the id removed, or None."""
    pack = pack or choose_pack(parent, "Remove data pack", include_builtin=False)
    if pack is None:
        return None
    warning = QMessageBox(QMessageBox.Icon.Warning, "Remove data pack",
                          f"Remove the data pack '{pack.label}'?", parent=parent)
    warning.setInformativeText(f"Its folder -- columns, steps, rules -- is deleted and can't be restored:\n"
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


class FormulaDelegate(RowSeparatorDelegate):
    """Spaced rows for the formulas table; remembers the open editor of a Formula cell, so a click on a column name
    (the columns list, which never takes the focus) types it in at the cursor."""

    def __init__(self, editor_window: "PackEditor", table: QTableWidget):
        super().__init__(table)
        self.window = editor_window

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if index.column() == 1 and isinstance(editor, QLineEdit):
            self.window._formula_editor = editor
            editor.destroyed.connect(lambda *_: setattr(self.window, "_formula_editor", None))
        return editor


def choose_pack(parent, title: str, include_builtin: bool = True) -> Optional[packs.Pack]:
    """Ask which data pack (the app's own marked as such)."""
    found = sorted(packs.available().values(), key=lambda p: p.label)
    if not include_builtin:
        found = [p for p in found if not PackDraft.load(p.folder).builtin]
    if not found:
        QMessageBox.information(parent, title, "There are no data packs of your own yet: use Data Packs > New "
                                               "data pack.")
        return None
    labels = [p.label + ("  (built in)" if PackDraft.load(p.folder).builtin else "") for p in found]
    label, ok = QInputDialog.getItem(parent, title, "Data pack:", labels, 0, False)
    return found[labels.index(label)] if ok else None
