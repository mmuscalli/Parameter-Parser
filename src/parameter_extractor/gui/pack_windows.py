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
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame,
                               QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter,
                               QTabWidget, QToolButton,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor import packs
from parameter_extractor.pack_editing import (BUILTIN_STAGES, CALCULATION_NEEDS, CALCULATION_STEP, CALCULATIONS,
                                              PackDraft, Problem, check)
from parameter_extractor.gui.widgets import RowSeparatorDelegate, in_cell, style_rows, fit_to_screen

from parameter_extractor.gui import themes  # noqa: E402
LEVEL_COLORS = {level: themes.MARKS[level] for level in ("error", "warning", "note")}   # follow the theme
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


class _PageTabs(QTabWidget):
    """The data pack editor's pages, chosen from a sidebar grouped by what the user is doing (2026-11-25, Mickey: eleven
    tabs in one row had become hard to read). A QTabWidget with its bar hidden, so code and tests keep using tab names
    (tab_index, setTabEnabled, setTabText); the sidebar (`nav`) and the page heading follow every change."""

    PAGE = Qt.ItemDataRole.UserRole + 1           # a sidebar row's page index (None: a group heading)

    def __init__(self):
        from PySide6.QtWidgets import QListWidget
        super().__init__()
        self.tabBar().hide()
        self.setDocumentMode(True)
        self.nav = QListWidget()
        self.nav.setObjectName("packPages")
        self.nav.setFixedWidth(196)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setStyleSheet("QListWidget#packPages { background: palette(window); outline: 0; }"
                               "QListWidget#packPages::item { padding: 5px 10px; border-radius: 5px; }"
                               "QListWidget#packPages::item:selected { background: palette(highlight); "
                               "color: palette(highlighted-text); }"
                               "QListWidget#packPages::item:hover:!selected { background: palette(alternate-base); }")
        self.title = QLabel()
        font = self.title.font()
        font.setPointSizeF(font.pointSizeF() * 1.35)
        font.setBold(True)
        self.title.setFont(font)
        self.about = _hint("")
        self._about: Dict[int, str] = {}
        # the heading row: the page's title and, for a page that wants it, its own controls beside the title
        # (2026-11-26, Mickey: the Map's view had too little of the window)
        self.header = QWidget()
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        hl.addWidget(self.title)
        self._header_row = hl
        hl.addStretch(1)
        self._extras: Dict[int, QWidget] = {}
        self._compact: set = set()
        self.nav.currentItemChanged.connect(self._picked)
        self.currentChanged.connect(self._follow)

    def add_group(self, heading: str) -> None:
        from PySide6.QtWidgets import QListWidgetItem
        item = QListWidgetItem(heading.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setPointSizeF(font.pointSizeF() * 0.82)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        item.setFont(font)
        item.setForeground(QBrush(themes.MARKS["muted"]))
        item.setSizeHint(QSize(0, 22 if self.nav.count() == 0 else 38))       # space above every group but the first
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.nav.addItem(item)

    def add_page(self, widget: QWidget, name: str, about: str) -> int:
        """A page, scrolling when the window is smaller than it needs (2026-11-26: the tallest page made the window
        taller than a laptop screen); `page(i)` is the page itself."""
        from PySide6.QtWidgets import QListWidgetItem
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        i = self.addTab(scroll, name)
        self._about[i] = about
        item = QListWidgetItem("   " + name)
        item.setData(self.PAGE, i)
        item.setToolTip(about)
        item.setSizeHint(QSize(0, 30))
        self.nav.addItem(item)
        if i == 0:
            self.nav.setCurrentItem(item)
            self._follow(0)
        return i

    def page(self, i: int) -> QWidget:
        holder = self.widget(i)
        return holder.widget() if isinstance(holder, QScrollArea) else holder

    def set_compact(self, i: int, extras: Optional[QWidget] = None) -> None:
        """Page i keeps its heading to one row: its description goes into the title's tooltip and `extras` (its
        controls) sit beside the title, shown only with that page."""
        self._compact.add(i)
        if extras is not None:
            self._header_row.addWidget(extras)
            self._extras[i] = extras
        self._follow(self.currentIndex())

    def _item(self, i: int):
        return next((self.nav.item(r) for r in range(self.nav.count()) if self.nav.item(r).data(self.PAGE) == i), None)

    def _picked(self, item, _previous) -> None:
        if item is not None and item.data(self.PAGE) is not None:
            self.setCurrentIndex(item.data(self.PAGE))

    def _follow(self, i: int) -> None:
        item = self._item(i)
        if item is not None and self.nav.currentItem() is not item:
            self.nav.setCurrentItem(item)
        self.title.setText(self.tabText(i))
        self.about.setText(self._about.get(i, ""))
        compact = i in self._compact
        self.about.setVisible(not compact)
        self.title.setToolTip(self._about.get(i, "") if compact else "")
        for j, extras in self._extras.items():
            extras.setVisible(j == i)

    # the sidebar follows what code does to the (hidden) tabs
    def setTabText(self, i: int, text: str) -> None:
        super().setTabText(i, text)
        item = self._item(i)
        if item is not None:
            item.setText("   " + text)
            problems = text != text.split(" (")[0]          # 'Check (1/2)': the pack has problems
            item.setForeground(QBrush(themes.MARKS["error"]) if problems else QBrush())
        if i == self.currentIndex():
            self.title.setText(text)

    def setTabEnabled(self, i: int, on: bool) -> None:
        super().setTabEnabled(i, on)
        item = self._item(i)
        if item is not None:
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if on else Qt.ItemFlag.NoItemFlags)

    def setTabToolTip(self, i: int, tip: str) -> None:
        super().setTabToolTip(i, tip)
        item = self._item(i)
        if item is not None:
            item.setToolTip(tip or self._about.get(i, ""))


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
        fit_to_screen(self, 620, 420)
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
        self._actions: Dict[str, List[QPushButton]] = {}     # the pack-wide action buttons, by kind (_action)
        self.setWindowTitle(f"Data pack: {self.draft.manifest.get('label', '')}"
                            + ("  (built in, read-only)" if self.read_only else ""))
        fit_to_screen(self, 1700, 1050)            # as much of the screen as it allows (the map uses it)
        layout = QVBoxLayout(self)
        if self.read_only:
            banner = QHBoxLayout()
            banner.addWidget(QLabel("This data pack is part of the app and can't be changed. Copy it to make "
                                    "your own version.", wordWrap=True), 1)
            banner.addWidget(QPushButton("Copy to a new data pack…", clicked=self._copy))
            layout.addLayout(banner)
        self.tabs = _PageTabs()
        # the pages in groups that follow how a pack is put together (2026-11-25, Mickey: readability and workflow --
        # was one row of eleven tabs): see it whole; set it up (name and rows, levels, the modules it links: those
        # decide much of the rest); what's extracted (columns, compounds, steps, rules, formulas); the check
        pages = (
            ("See the pack", (
                ("Map", self._map_tab(), "This data pack as a picture: the steps that read a paper, the kinds of value "
                 "they fill, and the levels those are recorded for. Hover over a step or a kind of value to follow it; "
                 "double-click one to edit it."),
                ("Overview", self._overview_tab(), "What happens to each paper with this data pack: every request to "
                 "the AI model (and where it comes from) and every calculation done on your computer."))),
            ("Set up", (
                ("General", self._general_tab(), "This data pack's name, what its rows are called, its built-in steps "
                 "and calculations."),
                ("Structure", self._structure_tab(), "How this data pack's data is organised: a paper, its groups "
                 "of rows, their rows -- and what each kind of value is recorded for."),
                ("Modules", self._modules_tab(), "The shared modules this data pack links, what each brings, and this "
                 "pack's own settings for them (the modules themselves stay the same in every pack)."))),
            ("What's extracted", (
                ("Columns", self._columns_tab(), "This data pack's columns, by category: what fills each one, and the "
                 "ones every run must answer for."),
                ("Compounds", self._compounds_tab(), "This data pack's compound vocabulary, used by the chemistry step "
                 "(from the Solution chemistry module)."),
                ("Steps", self._stages_tab(), "This data pack's own configurable steps: each is one model request per "
                 "paper it runs for (files in the pack's stages/ folder)."),
                ("Rules", self._rules_tab(), "This data pack's rules for the shared prompts (e.g. planning rows)."),
                ("Formulas", self._formulas_tab(), "This data pack's calculations written as formulas."))),
            ("Review", (
                ("Check", self._check_tab(), "Problems the app finds in this data pack."),)))
        for heading, group in pages:
            self.tabs.add_group(heading)
            for name, widget, about in group:
                self.tabs.add_page(widget, name, about)
        self.tabs.set_compact(self.tab_index("Map"), self.map_bar)      # the map: one heading row, the most view
        # the sidebar comes back on leaving the Map (a double-click on the map opens another page)
        self.tabs.currentChanged.connect(lambda i: self.sidebar_btn.setChecked(False)
                                         if i != self.tab_index("Map") else None)
        self.tabs.currentChanged.connect(lambda _i: self._fit_rows())
        self._follow_step("chemistry", "Compounds")
        self._refresh_module_effects()
        self._refresh_overview()
        self.tabs.currentChanged.connect(lambda i: self._refresh_formula_columns()
                                         if self.tabs.tabText(i) == "Formulas" else None)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.tabs.nav)
        page = QVBoxLayout()
        page.setSpacing(2)
        page.addWidget(self.tabs.header)
        page.addWidget(self.tabs.about)
        page.addSpacing(8)
        page.addWidget(self.tabs, 1)
        body.addLayout(page, 1)
        layout.addLayout(body, 1)
        bottom = QHBoxLayout()            # the page actions are on their pages (2026-11-26, Mickey: a crowded row)
        bottom.addStretch(1)
        bottom.addWidget(QPushButton("Close", clicked=self.reject))
        self.save_btn = QPushButton("Save", clicked=self.save, default=True)
        self.save_btn.setEnabled(not self.read_only)
        bottom.addWidget(self.save_btn)
        layout.addLayout(bottom)
        if self.read_only:
            for tab in range(self.tabs.count() - 1):            # Check stays usable
                self._lock(self.tabs.page(tab))
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
        folder = QHBoxLayout()
        where = _hint(str(self.draft.folder))
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder.addWidget(where, 1)
        folder.addWidget(QPushButton("Open folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.draft.folder)))))
        form.addRow("Folder:", folder)
        v.addLayout(form)

        improve = QGroupBox("Improve this data pack")
        grid = QGridLayout(improve)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(14)
        for r, (kind, what) in enumerate((
                ("suggest", "New sample papers surveyed for what this data pack lacks; you choose what's added."),
                ("remembered", "Columns, synonyms and compound names you accepted while reviewing papers."))):
            button = self._action(kind)
            if button is not None:
                grid.addWidget(button, r, 0)
                grid.addWidget(_hint(what), r, 1)
        v.addWidget(improve)

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
            # the step's name on the box, what it does wrapped under it (2026-11-26: a checkbox's text can't wrap, and
            # these descriptions made the window wider than a laptop screen)
            box = QCheckBox(name, checked=name in self._own_steps)
            box.setProperty("about", about)
            box.setToolTip(about)
            box.toggled.connect(lambda on, n=name, b=box: (self._own_steps.add(n) if on else self._own_steps.discard(n))
                                if b.isEnabled() else None)
            self.builtin_boxes[name] = box
            sv.addWidget(box)
            what = _hint(about)
            what.setContentsMargins(24, 0, 0, 4)
            sv.addWidget(what)
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

    ACTIONS = {
        "suggest": ("Suggest additions from papers…", "_suggest_additions",
                    "Survey a few new sample papers (cheap) and get suggestions for what this research area lacks: "
                    "parameters, steps, categories, rules, compounds. You choose what's added. Saves your edits first."),
        "remembered": ("Remembered from your reviews…", "_open_remembered",
                       "What you've taught the app for this data pack while reviewing papers (accepted columns, "
                       "synonyms, compound names, changes to this pack's columns). Kept apart from the pack, so it "
                       "applies on top of it."),
        "compounds": ("Find compounds / tidy names…", "_find_compounds",
                      "Find the compounds named in this data pack's columns and examples, identify them on PubChem "
                      "(free, no model) and switch the chemistry step on for them -- you review everything before "
                      "it's changed. Saves your edits first."),
    }

    def _action(self, kind: str) -> Optional[QPushButton]:
        """A button for one of the pack-wide actions, placed on the pages it belongs to (2026-11-26, Mickey: they were
        all in the bottom row): suggestions and what you taught the app on General and Overview, finding compounds on
        Columns and Compounds. None where it doesn't apply (no registry: nothing remembered)."""
        if kind == "remembered" and not self.registry_path:
            return None
        text, slot, tip = self.ACTIONS[kind]
        button = QPushButton(text, clicked=getattr(self, slot))
        button.setToolTip(tip)
        if kind != "remembered" and self.read_only:
            button.setEnabled(False)
            button.setToolTip("Copy this data pack first: the app's own can't be changed.")
        if kind == "suggest" and self._config is None:
            button.setEnabled(False)
        self._actions.setdefault(kind, []).append(button)
        if kind == "suggest" and not hasattr(self, "suggest_btn"):
            self.suggest_btn = button
        if kind == "compounds" and not hasattr(self, "compounds_btn"):
            self.compounds_btn = button
        return button

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
        self.category_panel.show_category(self.category_panel.cid)        # as changed there

    # ---- Columns ------------------------------------------------------------------------

    def _columns_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_titled("The dataset's columns, by kind of value", "The dataset's columns, grouped by kind of "
                          "value (variable category) in the order the dataset writes them; click a kind of value for "
                          "its settings. Put the unit at the end of a name "
                          "(temperature_C, pressure_bar, mass_g, yield_pct): values are converted into it. The shared "
                          "columns (paper, authors, DOI, ...) and row identifiers are added automatically. Columns a "
                          "step fills but that aren't listed here are added after these. Double-click a column to "
                          "rename it; drag it to reorder, or onto another kind of value to move it there."))
        row = QHBoxLayout()
        self.column_tree = _ColumnTree()
        self.column_tree.setHeaderLabels(["Column", "Unit", "Filled by", "Must answer"])
        from parameter_extractor.parameter_checks import marked, set_marked
        try:
            self._required = set(marked(packs.Pack(self.draft.folder)))
        except Exception:                            # noqa: BLE001 -- a pack that doesn't load yet: the file's own
            self._required = set(self.draft.manifest.get("check_columns", []) or [])
        if self.draft.manifest.get("check_columns") and not self.read_only:   # 0.6.6 kept them in pack.json
            set_marked(self.draft.manifest.get("id", ""), self._required)
        self.column_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.column_tree.header().setStretchLastSection(True)
        self.column_tree.setColumnWidth(0, 360)
        self.column_tree.setColumnWidth(1, 90)
        self._fill_column_tree(self.draft.columns)
        row.addWidget(self.column_tree, 1)
        side = QVBoxLayout()
        for text, slot in (("Add…", self._add_column), ("Remove", self._remove_column)):
            side.addWidget(QPushButton(text, clicked=slot))
        self.build_values_btn = QPushButton("Build columns…", clicked=lambda: self._build_columns("values"))
        self.build_values_btn.setToolTip("Columns in the app's formats: compounds identified on PubChem, or a value "
                                         "with its unit and the step that asks for it. Saves your edits first.")
        self.build_values_btn.setEnabled(not self.read_only)
        side.addWidget(self.build_values_btn)
        side.addWidget(self._action("compounds"))
        side.addSpacing(16)
        # 'Must answer' (2026-11-25, Mickey): runs with this pack answer for these columns, found or not
        self.require_btn = QPushButton("Must answer", clicked=lambda: self._set_required(True))
        self.require_btn.setToolTip("Mark the selected columns: every run with this data pack has to say whether the "
                                    "paper reports them (reported / not reported / unclear) -- parameter_checks.csv. "
                                    "For a step's values and compound columns. Select several to mark them at once. "
                                    "Kept in your app data (also for the app's own data packs), saved at once.")
        self.unrequire_btn = QPushButton("Not required", clicked=lambda: self._set_required(False))
        for b in (self.require_btn, self.unrequire_btn):
            side.addWidget(b)
        side.addSpacing(16)
        side.addWidget(QPushButton("Add a kind of value…", clicked=self._add_category))
        side.addStretch(1)
        row.addLayout(side)
        # the selected kind of value's settings (2026-11-19: the categories in the Data packs window)
        from parameter_extractor.gui.category_panel import CategoryPanel
        self.category_panel = CategoryPanel(self.draft.manifest, self.structure_page, self._saved_categories,
                                            self.read_only, open_all=self._open_categories)
        self.category_panel.setFixedWidth(420)
        self.category_panel.changed.connect(self._category_renamed)
        self.category_panel.remove_requested.connect(self._remove_category)
        self.column_tree.currentItemChanged.connect(lambda item, _old: self._show_category_of(item))
        row.addWidget(self.category_panel)
        v.addLayout(row, 1)
        return w

    # the Columns tab's kinds of value (variable categories) -------------------------------------------------------

    def _saved_categories(self) -> dict:
        """{id: VariableCategory} of the pack as saved (its modules' and the shared ones included)."""
        from parameter_extractor import variable_categories as vc
        pack = self._saved_pack()
        try:
            return {c.id: c for c in vc.categories(pack)} if pack else {}
        except Exception:                           # noqa: BLE001 -- a pack that can't load: its own only
            return {}

    def _category_header(self, cid: str) -> Optional[QTreeWidgetItem]:
        return next((self.column_tree.topLevelItem(i) for i in range(self.column_tree.topLevelItemCount())
                     if self.column_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == cid), None)

    def _show_category_of(self, item: Optional[QTreeWidgetItem]) -> None:
        group = item.parent() or item if item is not None else None
        key = group.data(0, Qt.ItemDataRole.UserRole) if group is not None else None
        if key and key.startswith("__"):
            self.category_panel.show_category(None, automatic=f"{group.text(0)}: added to every dataset by the "
                                                              "app (they identify the rows and where values come from).")
        else:
            self.category_panel.show_category(key or None)

    def show_category(self, cid: str) -> None:
        """The Columns tab on a kind of value (the Map's double-click)."""
        self.tabs.setCurrentIndex(self.tab_index("Columns"))
        header = self._category_header(cid)
        if header is not None:
            self.column_tree.setCurrentItem(header)
            self.column_tree.scrollToItem(header, QAbstractItemView.ScrollHint.PositionAtTop)

    def _category_renamed(self, cid: str) -> None:
        header = self._category_header(cid)
        own = self.category_panel.own_entry(cid)
        if header is not None and own is not None:
            header.setText(0, own.get("label", cid))

    def _add_category(self) -> None:
        label, ok = QInputDialog.getText(self, "Add a kind of value", "Name of the new kind of value (variable "
                                         "category), e.g. Light source:")
        label = (label or "").strip()
        if not ok or not label:
            return
        self.add_category(label)

    def add_category(self, label: str) -> str:
        """A new kind of value of this pack's own (pack.json, saved with it), recorded for each row; returns its id."""
        import re
        from parameter_extractor import variable_categories as vc
        taken = set(self._saved_categories()) | set(vc.RESERVED_IDS) | \
            {c.get("id") for c in self.draft.manifest.get("variable_categories", [])}
        base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "category"
        base = base if base[0].isalpha() else f"c_{base}"
        cid, n = base, 2
        while cid in taken:
            cid, n = f"{base}_{n}", n + 1
        self.draft.manifest.setdefault("variable_categories", []).append(
            {"id": cid, "label": label, "description": "", "model_assigns": False})
        self.structure_page.add_kind(cid, label)
        header = QTreeWidgetItem([label, "empty", ""])
        header.setData(0, Qt.ItemDataRole.UserRole, cid)
        first = self.column_tree.topLevelItem(0)
        if first is not None:
            header.setFont(0, first.font(0))
            header.setForeground(0, first.foreground(0))
            header.setForeground(1, first.foreground(1))
        header.setSizeHint(0, QSize(0, 40))
        header.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDropEnabled)
        header.setToolTip(0, "No columns yet: drag columns here to put them in this category.")
        at = next((i for i in range(self.column_tree.topLevelItemCount())          # before Other / the added ones
                   if self.column_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) in ("other", "__provenance__")),
                  self.column_tree.topLevelItemCount())
        self.column_tree.insertTopLevelItem(at, header)
        header.setFirstColumnSpanned(True)
        self.column_tree.setCurrentItem(header)
        return cid

    def _remove_category(self, cid: str) -> None:
        """A kind of value of this pack's own removed; its columns go to Other."""
        header = self._category_header(cid)
        n = len(self._column_children(header)) if header is not None else 0
        if n and QMessageBox.question(self, "Remove this kind of value?", f"Its {n} column(s) move to Other. "
                                      "Remove it?") != QMessageBox.StandardButton.Yes:
            return
        self.remove_category(cid)

    def remove_category(self, cid: str) -> None:
        m = self.draft.manifest
        m["variable_categories"] = [c for c in m.get("variable_categories", []) if c.get("id") != cid]
        if not m["variable_categories"]:
            m.pop("variable_categories")
        (m.get("category_columns") or {}).pop(cid, None)
        self.structure_page.remove_kind(cid)
        header = self._category_header(cid)
        if header is not None:
            other = self._category_header("other")
            children = [c for c in header.takeChildren() if not c.data(0, self.SUBHEADER)
                        and not c.data(0, self.MODULE_COLUMN)]
            if other is not None and children:
                other.addChildren(children)
                other.setText(1, f"{len(self._column_children(other))} columns")
            self.column_tree.takeTopLevelItem(self.column_tree.indexOfTopLevelItem(header))
        self.category_panel.show_category(None)

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
        fills = self._column_fills()
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
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | \
                (Qt.ItemFlag.ItemIsDropEnabled if droppable else Qt.ItemFlag.NoItemFlags)
            item.setFlags(flags)
            tree.addTopLevelItem(item)
            item.setExpanded(True)
            return item
        if order is not None:
            for cat in order.display:                    # every category, so columns can be moved into an empty one
                groups[cat.id] = header(cat.id, cat.label, True)
        ordered = order.ordered(columns) if order else list(columns)
        members: Dict[str, List[str]] = {}
        for c in ordered:
            if order is None:
                key, label = "", "Columns"
            else:
                label = order.label_of(c)
                key = {IDENTIFIERS_LABEL: "__row__", PROVENANCE_LABEL: "__provenance__"}.get(label, order.category_of(c))
            if key not in groups:
                groups[key] = header(key, label, not key.startswith("__"))
            members.setdefault(key, []).append(c)
        # the linked modules' columns too, in their kinds of value, read-only (2026-11-19: the Map counted them and
        # the tab didn't show them -- Mineral surfaces '6 columns', none here)
        module_of = self._module_columns()
        step_of = {c: f"this data pack's step '{names[0]}'" for c, names in self.draft.stage_columns().items()
                   if c not in set(columns) and c not in module_of}      # filled by a step, not in the list
        from_modules: Dict[str, List[str]] = {}
        from_steps: Dict[str, List[str]] = {}
        for found, into in ((module_of, from_modules), (step_of, from_steps)):
            for c in found:
                if c in set(columns) or order is None:
                    continue
                key = order.category_of(c)
                if key not in groups:
                    groups[key] = header(key, order.label_of(c), True)
                into.setdefault(key, []).append(c)
        module_of = {**module_of, **step_of}
        # in each kind of value the columns something fills, the modules' columns, then the ones nothing fills
        # automatically (kept for the dataset's layout), set apart and greyed (Mickey, 2026-11-19)
        for key in list(dict.fromkeys(list(members) + list(from_modules) + list(from_steps))):
            cols = members.get(key, [])
            filled = [c for c in cols if fills.get(c)]
            empty = [c for c in cols if not fills.get(c)]
            stepped, modular = from_steps.get(key, []), from_modules.get(key, [])
            parts = [p for p in (filled, stepped, modular, empty) if p]
            if filled and len(parts) > 1:
                self._subheader(groups[key], f"Filled automatically ({len(filled)})")
            for c in filled:
                self._column_item(groups[key], c, unit_for_column(c), fills.get(c))
            for extra, title, where in ((stepped, "Added by this data pack's steps", "the Steps tab"),
                                        (modular, "From linked modules", "the module (Modules tab)")):
                if extra:
                    self._subheader(groups[key], f"{title} ({len(extra)}) -- edited in {where}")
                for c in extra:
                    item = self._column_item(groups[key], c, unit_for_column(c), fills.get(c) or [module_of[c]])
                    item.setData(0, self.MODULE_COLUMN, module_of[c])
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)   # not renamed or moved
                    item.setToolTip(0, f"Filled by {module_of[c]}: change it in {where}.")
            if empty:
                self._subheader(groups[key], f"Not filled automatically ({len(empty)})")
            for c in empty:
                self._column_item(groups[key], c, unit_for_column(c), None)
        for key, item in groups.items():                 # counts; empty categories say so
            n = len(self._column_children(item))
            item.setText(1, f"{n} column{'s' if n != 1 else ''}" if n else "empty")
            if not n:
                item.setToolTip(0, "No columns yet: drag columns here to put them in this category.")
            item.setForeground(1, QBrush(tree.palette().color(QPalette.ColorRole.PlaceholderText)))
        # Row / Provenance blocks first and last, as the dataset writes them
        for key, index in (("__row__", 0), ("__provenance__", tree.topLevelItemCount() - 1)):
            if key in groups:
                tree.insertTopLevelItem(index, tree.takeTopLevelItem(tree.indexOfTopLevelItem(groups[key])))
                groups[key].setExpanded(True)

    SUBHEADER = Qt.ItemDataRole.UserRole + 1       # a 'Filled / Not filled automatically' line among the columns
    MODULE_COLUMN = Qt.ItemDataRole.UserRole + 2   # a linked module's column: shown, not the pack's to save

    def _module_columns(self) -> Dict[str, str]:
        """{column: 'the <label> module'} for the columns the linked modules bring (as this pack's settings name
        them)."""
        out: Dict[str, str] = {}
        try:
            for mod, spec in self.draft.module_specs():
                for c in spec.columns:
                    out.setdefault(c, f"the {mod.label} module")
            for c in self.draft.module_columns():
                out.setdefault(c, "a linked module")
        except Exception:                            # noqa: BLE001 -- a module that can't load: none shown
            return {}
        return out

    def _column_fills(self) -> Dict[str, List[str]]:
        """{column: what fills it} (column_sources.py: steps, built-in steps, the row plan, calculations, ...)."""
        from parameter_extractor import column_sources
        try:
            return column_sources.sources(self.draft)
        except Exception:                            # noqa: BLE001 -- never in the way of editing: the own steps
            return self.draft.stage_columns()

    def _subheader(self, parent: QTreeWidgetItem, text: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, self.SUBHEADER, True)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = QFont(self.column_tree.font())
        font.setItalic(True)
        item.setFont(0, font)
        item.setForeground(0, QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText)))
        parent.addChild(item)
        item.setFirstColumnSpanned(True)
        return item

    def _column_children(self, group: QTreeWidgetItem) -> List[QTreeWidgetItem]:
        """A category's column items (not its subheaders)."""
        return [group.child(j) for j in range(group.childCount()) if not group.child(j).data(0, self.SUBHEADER)]

    def _column_item(self, parent: QTreeWidgetItem, column: str, unit: str, stages) -> QTreeWidgetItem:
        from parameter_extractor.column_sources import NOTHING
        item = QTreeWidgetItem([column, unit or "", ", ".join(stages) if stages else NOTHING])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
                      | Qt.ItemFlag.ItemIsDragEnabled)
        item.setToolTip(0, f"Filled by: {', '.join(stages)}" if stages else
                        "Nothing fills this column automatically: it stays in the dataset's layout, filled only by "
                        "your corrections, a digitized figure or a step's 'other values' answer.")
        if not stages:
            muted = QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText))
            for col in (0, 1):
                item.setForeground(col, muted)
            item.setForeground(2, QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText)))
        parent.addChild(item)
        self._show_required(item)
        return item

    def answerable(self, column: str) -> bool:
        """A column a run can be made to answer for: a step's parameter (the pack's or a module's), a compound column
        (the chemistry step), the row plan's (each sample's time, each set's type) or a paper detail."""
        from parameter_extractor.focused_search import _COMPOUND_COLUMN
        from parameter_extractor.parameter_checks import PAPER_DETAILS, planner_columns
        if _COMPOUND_COLUMN.match(column):
            return True
        if not hasattr(self, "_step_param_columns"):
            cols = set(self.draft.stage_columns()) | set(PAPER_DETAILS)
            try:
                cols |= {c for _m, spec in self.draft.module_specs() for c in spec.columns}
                cols |= set(planner_columns(packs.Pack(self.draft.folder)))
            except Exception:                        # noqa: BLE001 -- a module that can't load: its steps unknown
                pass
            self._step_param_columns = cols
        return column in self._step_param_columns

    def _show_required(self, item: QTreeWidgetItem) -> None:
        """A 'Must answer' column: marked in its own column and highlighted (themes.MARKS['must_answer'])."""
        from parameter_extractor.column_sources import NOTHING
        from parameter_extractor.gui.themes import MARKS
        on = item.text(0).strip() in self._required
        item.setText(3, "must answer" if on else "")
        muted = QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText))
        unfilled = item.text(2) == NOTHING
        for col in range(4):
            item.setBackground(col, QBrush(MARKS["must_answer"]) if on else QBrush())
            # marked: the marks' text colour in every column (readable on the tint in any theme); else as before
            item.setForeground(col, QBrush(MARKS["mark_text"]) if on else (muted if unfilled and col < 3 else QBrush()))

    def _set_required(self, on: bool) -> None:
        """The selected columns (several at once) marked 'Must answer', or not -- saved at once in the user's app
        data (parameter_checks.set_marked), so the app's own packs can be marked too; columns no step or compound
        fills are left as they are and named."""
        from parameter_extractor.parameter_checks import set_marked
        skipped = []
        for item in self.column_tree.selectedItems():
            if item.parent() is None or item.data(0, self.SUBHEADER):
                continue
            column = item.text(0).strip()
            if on and not self.answerable(column):
                skipped.append(column)
                continue
            (self._required.add if on else self._required.discard)(column)
            self._show_required(item)
        set_marked(self.draft.manifest.get("id", ""), self._required)
        if skipped:
            QMessageBox.information(self, "Must answer", "Not marked -- no step asks for these, and they aren't "
                                    "compound columns, so a run has nothing to answer for them:\n\n"
                                    + "\n".join(skipped[:20]))

    def _refresh_column_fills(self) -> None:
        """'Filled by' after the steps changed (in place: the columns move between the parts at the next Save)."""
        from parameter_extractor.column_sources import NOTHING
        fills = self._column_fills()
        muted = QBrush(self.column_tree.palette().color(QPalette.ColorRole.PlaceholderText))
        for i in range(self.column_tree.topLevelItemCount()):
            for item in self._column_children(self.column_tree.topLevelItem(i)):
                stages = fills.get(item.text(0).strip())
                item.setText(2, ", ".join(stages) if stages else NOTHING)
                for col in (0, 1, 2):
                    item.setForeground(col, QBrush() if stages else muted)
                self._show_required(item)            # a marked row keeps the marks' text colour (readable on the tint)

    def _tree_columns(self) -> List[str]:
        """The columns as the tree lists them (category by category)."""
        out = []
        for i in range(self.column_tree.topLevelItemCount()):
            group = self.column_tree.topLevelItem(i)
            out += [c.text(0).strip() for c in self._column_children(group)
                    if c.text(0).strip() and not c.data(0, self.MODULE_COLUMN)]      # a module's: not the pack's
        return out

    def _moved_categories(self) -> Dict[str, str]:
        """column -> category for columns the user put under a different category than they'd go to by default."""
        out = {}
        for i in range(self.column_tree.topLevelItemCount()):
            group = self.column_tree.topLevelItem(i)
            key = group.data(0, Qt.ItemDataRole.UserRole) or ""
            if not key or key.startswith("__"):
                continue
            for child in self._column_children(group):
                if child.data(0, self.MODULE_COLUMN):
                    continue
                col = child.text(0).strip()
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
        return self.tabs.page(self.tab_index(name))

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

    # ---- Structure (levels and the level of each kind of value; branch levels-and-facets) ------------------------

    def _structure_tab(self) -> QWidget:
        from parameter_extractor.gui.structure_page import StructurePage
        try:
            pack = packs.Pack(self.draft.folder)
        except Exception:                           # a pack that can't load as saved: its own categories only
            pack = None
        self.structure_page = StructurePage(self.draft.manifest, pack, self.set_edit, self.sample_edit)
        return self.structure_page

    # ---- Overview (what happens to each paper) and module settings (2026-11-09) ------------------------------------

    def _map_tab(self) -> QWidget:
        """The pack's structure as a picture (structure_canvas.py), as saved -- Save updates it."""
        from parameter_extractor.gui.structure_canvas import StructureCanvas
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)                 # the view gets all of the page (2026-11-26, Mickey)
        # its controls beside the page's title (_PageTabs.set_compact, after the pages are added)
        self.map_bar = QWidget()
        bar = QHBoxLayout(self.map_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        saved_note = _hint("As saved -- Save updates it.")
        saved_note.setWordWrap(False)
        bar.addWidget(saved_note)
        bar.addWidget(HelpButton("Hover over a step or a kind of value to follow it; click it for its details; "
                                 "double-click one to edit it, right-click for every place it's edited. Pinch or "
                                 "Ctrl+scroll to zoom, drag to move; Fit to window shows it whole again."))
        bar.addSpacing(12)
        self.map_canvas = StructureCanvas()
        self.map_canvas.setFrameShape(QFrame.Shape.NoFrame)
        self.map_canvas.actions_for = self._map_actions
        self.sidebar_btn = QPushButton("Hide sidebar", checkable=True)
        self.sidebar_btn.setToolTip("More room for the map: hide the list of pages (show it again here).")
        self.sidebar_btn.toggled.connect(lambda on: (self.tabs.nav.setVisible(not on),
                                                     self.sidebar_btn.setText("Show sidebar" if on else "Hide sidebar")))
        bar.addWidget(self.sidebar_btn)
        bar.addWidget(QPushButton("Fit to window", clicked=lambda: self.map_canvas.fit()))
        export = QPushButton("Export image…", clicked=lambda: self.export_map())
        export.setToolTip("The map as an image for a figure: PNG with a transparent background, or SVG (vector); "
                          "dark text for a white page or light text for a dark slide. Opened nodes are exported "
                          "opened.")
        bar.addWidget(export)
        v.addWidget(self.map_canvas, 1)
        self._refresh_map()
        return w

    def _map_actions(self, target: str) -> list:
        """What the Map offers for a step, a kind of value, a level, the calculations or the paper: [(text, run)],
        the first on a double-click -- the tab where it's edited."""
        from parameter_extractor import modules as module_store
        structure = getattr(self.map_canvas.scene(), "structure", None)
        go = lambda tab: (lambda: self.tabs.setCurrentIndex(self.tab_index(tab)))
        out = []
        if target.startswith("step:") and structure is not None:
            name = target[5:]
            step = next((st for st in structure.steps if st.name == name), None)
            stage_file = next((f for f, spec in self.draft.stages.items() if spec.get("name") == name), None)
            builtin = [self.builtin_list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.builtin_list.count())]
            module = next((mid for mid, mod in module_store.available().items()
                           if step is not None and mod.label == step.source), None)
            if stage_file:
                out.append(("Edit the step (Steps tab)", lambda: self.show_stage(stage_file)))
            elif name in builtin:
                out.append(("Show the step (Steps tab)", lambda: self._view_builtin_from_module(name)))
            if module:
                out.append((f"Open its module, {step.source} (Modules tab)", lambda: self.show_module(module)))
            if name == "structure_planner":
                out.append(("Rules for planning the rows (Rules tab)",
                            lambda: (self.tabs.setCurrentIndex(self.tab_index("Rules")),
                                     self.rules_page.select("structure_planner"))))
            out.append(("Show it in the overview (Overview tab)", go("Overview")))
            for cid in (step.kinds if step else [])[:6]:
                kind = next((k for k in structure.kinds if k.id == cid), None)
                if kind:
                    out.append((f"Its kind of value: {kind.label} (Columns tab)", lambda c=cid: self.show_category(c)))
        elif target.startswith("kind:"):
            cid = target[5:]
            out += [("Edit the kind of value and its columns (Columns tab)", lambda: self.show_category(cid)),
                    ("Where it's recorded and filled in (Structure tab)", go("Structure"))]
        elif target.startswith("level:"):
            out.append(("Edit the levels and their words (Structure tab)", go("Structure")))
        elif target == "calcs":
            out.append(("Choose the calculations (General tab)", go("General")))
        elif target == "paper":
            out.append(("What happens to each paper (Overview tab)", go("Overview")))
        return out

    def show_stage(self, stage_file: str) -> None:
        """The Steps tab on one of the pack's own steps."""
        self.tabs.setCurrentIndex(self.tab_index("Steps"))
        files = list(self.draft.stages)
        if stage_file in files:
            self.stage_list.setCurrentRow(files.index(stage_file))

    def show_module(self, mid: str) -> None:
        """The Modules tab on one module."""
        self.tabs.setCurrentIndex(self.tab_index("Modules"))
        for r in range(self.module_table.rowCount()):
            item = self.module_table.item(r, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == mid:
                self.module_table.setCurrentCell(r, 0)
                return

    MAP_EXPORTS = (("PNG, dark text for light pages (*.png)", "light"),
                   ("PNG, light text for dark slides (*.png)", "dark"),
                   ("SVG vector, dark text for light pages (*.svg)", "light"),
                   ("SVG vector, light text for dark slides (*.svg)", "dark"))

    def export_map(self, path: Optional[Path] = None, look: str = "light") -> Optional[Path]:
        """The Map as an image file (structure_canvas.export_image): PNG with no background, or SVG; `look` 'light'
        (dark text for a white page) or 'dark' (light text for a dark slide) -- chosen in the dialog's file types."""
        from parameter_extractor.gui.structure_canvas import export_image, print_palette
        if path is None:
            name = f"{self.draft.manifest.get('id') or 'data_pack'}_map.png"
            chosen, kind = QFileDialog.getSaveFileName(self, "Export the map", str(Path.home() / name),
                                                       ";;".join(f for f, _l in self.MAP_EXPORTS))
            if not chosen:
                return None
            path = Path(chosen)
            look = dict(self.MAP_EXPORTS).get(kind, "light")
            if kind.startswith("SVG") and path.suffix.lower() != ".svg":
                path = path.with_suffix(".svg")
        if path.suffix.lower() not in (".png", ".svg"):
            path = path.with_suffix(".png")
        try:
            export_image(packs.Pack(self.draft.folder), path, opened=set(self.map_canvas.opened),
                         palette=print_palette(look))
        except Exception as e:                       # noqa: BLE001 -- say why, never crash the editor
            QMessageBox.warning(self, "Not exported", f"The map couldn't be exported: {e}")
            return None
        return path

    def _refresh_map(self) -> None:
        try:
            self.map_canvas.show_pack(packs.Pack(self.draft.folder))
        except Exception:                           # a pack that can't load as saved: the Check tab says why
            self.map_canvas.setScene(None)

    def _overview_tab(self) -> QWidget:
        from PySide6.QtWidgets import QTextBrowser
        w = QWidget()
        v = QVBoxLayout(w)
        actions = QHBoxLayout()
        for kind in ("suggest", "remembered"):
            button = self._action(kind)
            if button is not None:
                actions.addWidget(button)
        actions.addStretch(1)
        v.addLayout(actions)
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
        self.module_table = QTableWidget(0, 3)                  # column 2 (hidden): the order (_regroup_modules)
        self.module_table.setHorizontalHeaderLabels(["Module", "In this data pack", ""])
        self.module_table.setColumnHidden(2, True)
        self.module_table.verticalHeader().setVisible(False)
        head = self.module_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.module_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.module_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        style_rows(self.module_table)
        own = set(self.draft.manifest.get("modules", []))
        for heading in ("In this data pack", "Not linked"):     # the two groups (_regroup_modules)
            r = self.module_table.rowCount()
            self.module_table.insertRow(r)
            item = QTableWidgetItem(heading.upper())
            item.setData(self.MODULE_HEADING, heading)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            font = item.font()
            font.setPointSizeF(font.pointSizeF() * 0.82)
            font.setBold(True)
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
            item.setFont(font)
            item.setForeground(QBrush(themes.MARKS["muted"]))
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
            self.module_table.setItem(r, 0, item)
            for c in (1, 2):
                blank = QTableWidgetItem("")
                blank.setFlags(Qt.ItemFlag.NoItemFlags)
                self.module_table.setItem(r, c, blank)
        for n, (mid, mod) in enumerate(module_store.core().items()):   # part of every data pack: ticked, locked, first
            r = self.module_table.rowCount()
            self.module_table.insertRow(r)
            item = QTableWidgetItem(mod.label)
            item.setData(Qt.ItemDataRole.UserRole, mid)
            item.setData(self.CORE_MODULE, True)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(mod.manifest.description)
            self.module_table.setItem(r, 0, item)
            status = QTableWidgetItem("core: every data pack")
            status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.module_table.setItem(r, 1, status)
            self.module_table.setItem(r, 2, QTableWidgetItem(f"1{n:03d}"))
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
            self.module_table.setItem(r, 2, QTableWidgetItem(""))
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
        self._regroup_modules()
        first = next((r for r in range(self.module_table.rowCount()) if self._module_row_id(r)), -1)
        if first >= 0:
            self.module_table.setCurrentCell(first, 0)
        return w

    CORE_MODULE = Qt.ItemDataRole.UserRole + 5        # a core module's row: part of every pack, not the pack's to link
    MODULE_HEADING = Qt.ItemDataRole.UserRole + 6     # a group heading's row in the module list

    def _module_row_id(self, r: int) -> Optional[str]:
        """The module on row r of the module list (None: a group heading)."""
        item = self.module_table.item(r, 0)
        return None if item is None or item.data(self.MODULE_HEADING) else item.data(Qt.ItemDataRole.UserRole)

    def _regroup_modules(self) -> None:
        """The module list in two groups (2026-11-25, Mickey): the modules in this data pack -- core, linked, brought
        along by another -- then the ones not linked, each group under its heading with space above the second; a
        module moves between them when ticked or unticked."""
        t = self.module_table
        t.blockSignals(True)
        unlinked = 0
        for r in range(t.rowCount()):
            item, order = t.item(r, 0), t.item(r, 2)
            heading = item.data(self.MODULE_HEADING)
            if heading:
                order.setText("0" if heading == "In this data pack" else "3")
            elif item.data(self.CORE_MODULE):
                pass                                          # '1nnn', set when the list was made
            elif item.checkState() == Qt.CheckState.Checked:  # linked, or brought along by a linked module
                order.setText("2" + item.text().lower())
            else:
                order.setText("4" + item.text().lower())
                unlinked += 1
        t.sortItems(2)
        for r in range(t.rowCount()):
            heading = t.item(r, 0).data(self.MODULE_HEADING)
            if heading:
                t.setRowHeight(r, 26 if heading == "In this data pack" else 46)
                t.setRowHidden(r, heading == "Not linked" and not unlinked)
        t.blockSignals(False)

    def _module_status(self, mid: str) -> str:
        from parameter_extractor import modules as module_store
        if mid in module_store.core():
            return "core: every data pack"
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
            if self._module_row_id(r):
                t.item(r, 1).setText(self._module_status(self._module_row_id(r)))
        t.blockSignals(False)

    def _chosen_modules(self) -> list:
        """The modules ticked (the pack's own list; the ones they bring along aren't listed)."""
        t = getattr(self, "module_table", None)
        if t is None:
            return list(self.draft.manifest.get("modules", []))
        out = []
        for r in range(t.rowCount()):
            item = t.item(r, 0)
            if item.checkState() == Qt.CheckState.Checked and item.flags() & Qt.ItemFlag.ItemIsEnabled \
                    and not item.data(self.CORE_MODULE) and self._module_row_id(r):
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
            mid = self._module_row_id(r)
            if mid is None:
                continue
            by = [found[o].label for o in chosen if o in found and mid in found[o].manifest.needs]
            if mid not in chosen and mid in linked and by:
                item.setCheckState(Qt.CheckState.Checked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            elif not self.read_only:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
        t.blockSignals(False)
        self._regroup_modules()
        self._mark_module_changes()
        provided = self._module_steps()
        for name, box in self.builtin_boxes.items():
            box.blockSignals(True)
            if name in provided:
                box.setChecked(True)
                box.setEnabled(False)
                box.setText(f"{name}  (from the {provided[name]} module)")
            else:
                box.setEnabled(not self.read_only)
                box.setChecked(name in self._own_steps)
                box.setText(name)
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
        item = self.module_table.item(row, 0) if row >= 0 and self._module_row_id(row) else None
        mod = module_store.available().get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        page = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        pv = QVBoxLayout(page)
        pv.setContentsMargins(14, 10, 14, 14)
        pv.setSpacing(12)
        core = module_store.core().get(item.data(Qt.ItemDataRole.UserRole)) if item and mod is None else None
        if core is not None:                            # a core module: what it holds, nothing to set
            from parameter_extractor import step_info
            steps = [step_info.DOCS[s]["label"] for s in core.manifest.builtin_stages if s in step_info.DOCS]
            cols = [(e["column"], e.get("description", "")) for e in
                    list(core.manifest.standard_columns) + list(core.manifest.app_columns)]
            pv.addWidget(QLabel(f"<h3>{escape(core.label)}</h3><p>{escape(core.manifest.description)}</p>"
                                f"<p><b>Its request (built-in step):</b> {escape(', '.join(steps))} -- see the Steps "
                                f"tab.</p>" + "".join(f"<p><b>Its calculation:</b> {escape(c)} -- {escape(d)}</p>"
                                                     for c, d in core.manifest.calculations.items())
                                + "<p><b>Its columns</b> (in every dataset; their names are fixed):</p>"
                                + "<table>" + "".join(f"<tr><td><code>{escape(c)}</code></td><td>{escape(d)}</td></tr>"
                                                      for c, d in cols) + "</table>"
                                f"<p class='muted'>A core module is part of every data pack: it can't be unlinked "
                                f"or changed. A pack's own row rules go in its Rules tab.</p>", wordWrap=True))
            pv.addStretch(1)
            self.module_scroll.setWidget(page)
            return
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
        brings = QLabel(pack_modules.brings_html(mod.id), wordWrap=True)
        brings.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box = QGroupBox("What it brings")
        bv = QVBoxLayout(box)
        bv.addWidget(brings)
        from parameter_extractor import step_info
        saved = self._saved_pack()
        steps = [s for s in step_info.STEPS if (s in mod.manifest.builtin_stages or s in (mod.manifest.prompt_rules or {}))
                 and saved is not None and s in saved.manifest.builtin_stages]
        if steps:
            row = QHBoxLayout()
            for s in steps:
                verb = "brings" if s in mod.manifest.builtin_stages else "adds rules to"
                btn = QPushButton(f"View the {step_info.DOCS[s]['label'].split(' (')[0].lower()} step…",
                                  clicked=lambda _c=False, s=s: self._view_builtin_from_module(s))
                btn.setToolTip(f"This module {verb} the built-in step '{s}': see what it reads, records and fills, "
                               f"and its instructions for this data pack (view only).")
                row.addWidget(btn)
            row.addStretch(1)
            bv.addLayout(row)
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

    def _view_builtin_from_module(self, name: str) -> None:
        """A module page's 'View the … step' button: the Steps tab on that built-in step."""
        self.tabs.setCurrentIndex(self.tab_index("Steps"))
        for r in range(self.builtin_list.count()):
            if self.builtin_list.item(r).data(Qt.ItemDataRole.UserRole) == name:
                self.builtin_list.setCurrentRow(r)
                return

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
        self.build_compounds_btn = QPushButton("Add compounds from PubChem…",
                                               clicked=lambda: self._build_columns("compounds"))
        self.build_compounds_btn.setToolTip("Type names or formulas; they're identified (the app's name rules, then "
                                            "PubChem) and get their columns. Saves your edits first.")
        self.build_compounds_btn.setEnabled(not self.read_only)
        row.addWidget(self.build_compounds_btn)
        row.addWidget(QPushButton("Remove", clicked=lambda: [self.compound_table.removeRow(r) for r in sorted(
            {i.row() for i in self.compound_table.selectedIndexes()}, reverse=True)]))
        row.addWidget(self._action("compounds"))
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
        item = self._column_item(group, name, unit_for_column(name), self._column_fills().get(name))
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
            if item.parent() is not None and not item.data(0, self.MODULE_COLUMN):   # a module's: not here
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
        # built-in steps (code: chemistry, analysis, fitting models), view only (Mickey, 2026-11-11: what the chemistry
        # step contains wasn't shown anywhere): step_info.py
        self.builtin_title = _titled("Built-in steps (view only)", "Steps that are part of the app: this data pack or "
                                     "its modules switch them on and add rules to them, but their answer format and "
                                     "instructions can't be edited. Select one to see what it reads, records and fills.")
        left.addWidget(self.builtin_title)
        self.builtin_list = QListWidget()
        self.builtin_list.setWordWrap(True)
        self.builtin_list.currentRowChanged.connect(self._on_builtin_row)
        left.addWidget(self.builtin_list)
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

        from PySide6.QtWidgets import QStackedWidget, QTextBrowser
        self.builtin_view = QTextBrowser()
        self.builtin_view.setOpenExternalLinks(False)
        self.builtin_view.document().setDocumentMargin(14)
        self.stage_stack = QStackedWidget()
        self.stage_stack.addWidget(form_w)
        self.stage_stack.addWidget(self.builtin_view)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_w)
        split.addWidget(self.stage_stack)
        split.setSizes([220, 1080])
        split.splitterMoved.connect(lambda *_: self._fit_rows())
        outer.addWidget(split)
        self._fill_stage_list()
        self._fill_builtin_list()
        return w

    def _saved_pack(self):
        """The pack as saved (built-in step pages describe it; unsaved edits aren't in it yet)."""
        try:
            return packs.Pack(self.draft.folder)
        except Exception:
            return None

    def _fill_builtin_list(self) -> None:
        from parameter_extractor import step_info
        pack = self._saved_pack()
        self.builtin_list.blockSignals(True)
        self.builtin_list.clear()
        for name in (step_info.built_in_steps(pack) if pack else []):
            item = QListWidgetItem(step_info.DOCS[name]["label"])
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(f"Built-in step '{name}': {step_info.DOCS[name]['label']} (view only)")
            self.builtin_list.addItem(item)
        self.builtin_list.blockSignals(False)
        rows = max(1, self.builtin_list.count())          # as tall as its rows: no empty box, no scrolling
        self.builtin_list.setFixedHeight(rows * (self.builtin_list.sizeHintForRow(0) or 22) + 8)
        self.builtin_title.setVisible(self.builtin_list.count() > 0)
        self.builtin_list.setVisible(self.builtin_list.count() > 0)

    def _on_builtin_row(self, row: int) -> None:
        if row < 0:
            return
        self._store_stage()
        self.stage_list.blockSignals(True)
        self.stage_list.clearSelection()
        self.stage_list.setCurrentRow(-1)
        self.stage_list.blockSignals(False)
        self._stage = None
        self.show_builtin_step(self.builtin_list.item(row).data(Qt.ItemDataRole.UserRole))

    def show_builtin_step(self, name: str) -> None:
        """The built-in step's page (step_info.py) in place of the step form."""
        from html import escape
        from parameter_extractor import step_info
        pack = self._saved_pack()
        try:
            page = step_info.as_html(step_info.describe(name, pack))
        except Exception as e:                      # a description is a convenience: never in the way of editing
            page = f"<p>The step's description couldn't be built: {escape(str(e))}</p>"
        page = ("<p style='color:gray'><i>Shown as this data pack is saved: changes you haven't saved yet (modules, "
                "rules, compounds) appear after Save.</i></p>") + page
        self.builtin_view.setHtml(page)
        self.stage_stack.setCurrentIndex(1)

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
        if row >= 0 and hasattr(self, "stage_stack"):     # back from a built-in step's page
            self.stage_stack.setCurrentIndex(0)
            self.builtin_list.blockSignals(True)
            self.builtin_list.setCurrentRow(-1)
            self.builtin_list.blockSignals(False)
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
        """The shared prompts this pack adds rules to, each laid out as the model gets it (gui/rules_page.py)."""
        from parameter_extractor.gui.rules_page import RulesPage
        self.rules_page = RulesPage(self.draft, self.read_only, self._saved_pack,
                                    show_modules=lambda: self.tabs.setCurrentIndex(self.tab_index("Modules")))
        self.rules_table = self.rules_page.rules_table
        return self.rules_page

    def rules_items(self) -> list:
        return self.rules_page.rules_items()

    def set_rules_items(self, items: list) -> None:
        self.rules_page.set_rules_items(items)
        self.rules_page.store()

    def _add_rule(self, text: str = "", edit: bool = True) -> None:
        self.rules_page.add_rule(text, edit)
        self.rules_page.store()

    def _move_rule(self, step: int) -> None:
        self.rules_page.move_rule(step)

    def _store_rules(self) -> None:
        self.rules_page.store()

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
        box = QGroupBox("Columns" if self.read_only else "Columns (click to insert)")
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
        """Into the open Formula cell at its cursor; else at the end of the selected formula. Not on a read-only data
        pack (the list is to look through there)."""
        if self.read_only:
            return
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
        self.structure_page.store(m)
        m["focused_row_plan"] = self.focused_box.isChecked()
        m.pop("check_columns", None)          # the 'Must answer' columns are kept in the user's app data now
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
        self.__dict__.pop("_step_param_columns", None)            # the steps may have changed
        shown = self.category_panel.cid
        self._fill_column_tree(self.draft.columns)      # the kinds of value as saved (names, table order)
        if shown and self._category_header(shown) is not None:
            self.column_tree.setCurrentItem(self._category_header(shown))
        self._refresh_overview()
        self._refresh_map()
        self._fill_builtin_list()           # modules linked or unlinked: their built-in steps
        self.saved.emit(self.draft.manifest.get("id", ""))
        return True

    def _find_compounds(self) -> None:
        from parameter_extractor.gui.pack_assist import CompoundSetupDialog
        if not self.save():
            return
        dlg = CompoundSetupDialog(self.draft.folder, self)
        if dlg.exec():
            self._reopen("Compounds set up", dlg.applied, dlg.problems)

    def _build_columns(self, start: str) -> None:
        from parameter_extractor.gui.variable_builder import VariableBuilderDialog
        if self.read_only or not self.save():
            return
        dlg = VariableBuilderDialog(self.draft.folder, self, start=start)
        if dlg.exec():
            self._reopen("Columns built", dlg.applied, dlg.problems)

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
            elif child in (self.rules_page.show_btn, self.rules_page.modules_btn, self.require_btn,
                           self.unrequire_btn) or (isinstance(child, QPushButton)
                                               and child.text() in ("Fit to window", "Export image…", "Open folder",
                                                                    "Variable categories (all data packs)…")) \
                    or child in self._actions.get("remembered", []):
                continue                       # looking at things: a prompt, the map, other tabs; 'Must answer'
                                               # (kept in the user's app data, not the pack)
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
