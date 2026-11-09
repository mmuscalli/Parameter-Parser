"""
The main window -- one search page (Mickey, 2026-11-08: the Focused search and Paper queue windows folded in).

Layout, top to bottom:
  - the data pack and a line saying what the run will do (mode)
  - three panes: Papers (one or many: PDFs, identifiers, a CSV list; a status per paper), Parameters (the area's
    stages and their parameters, ticked: everything = a full extraction, a stage unticked = without it, single
    parameters unticked = a focused search), Run options (grouped; the options for several papers or for a
    focused search only appear when they apply)
  - (a draggable splitter handle: inputs above, everything below it resizes)
  - Run / Cancel buttons, progress bar and status line
  - results tabs: Rows, Flags, Figures, Tables, Equations, Summary, and Search results for a focused search
Settings (API key, ADS token, results folder, online lookups) are in the Settings menu.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import List, Optional

import html

from PySide6.QtCore import QSettings, Qt, QThread, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QFrame, QMenu, QScrollArea, QSplitter, QToolButton, QWidgetAction,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from parameter_extractor import __version__
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.gui import key_store
from parameter_extractor.digitizing.annotate import save_digitized
from parameter_extractor.errors import PipelineError
from parameter_extractor.gui.figure_dialog import FigureReviewDialog, PlanBridge
from parameter_extractor.gui.variable_review import VariableReviewDialog
from parameter_extractor.gui.worker import PipelineWorker
from parameter_extractor.pricing import PRICES_CHECKED, format_usd
from parameter_extractor.registry import default_arxiv_cache_dir, default_pubchem_cache_path, default_registry_path
from parameter_extractor.pipeline import Extraction, finish, plan_figure, stage_label

DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "Parameter Extractor"
FLAGGED_ROW_COLOR = QColor(255, 243, 205)   # soft amber, readable in light and dark themes
ARCHIVE_ROW_COLOR = QColor(212, 237, 218)   # soft green: the row (fit) the Exoplanet Archive took
ARCHIVE_DIFF_COLOR = QColor(255, 196, 140)  # orange: a value that differs from the archive's
GROUP_TINT = QColor(110, 140, 210, 28)       # every other block of columns (category), faint in either theme
MAX_COLUMN_WIDTH = 260
# Rows tab column order: identify the row, then the measured data, then the
# paper-level details that repeat on every row (DOI, title, ...).
GETTING_STARTED = (
    "<h3>Extracting data from papers</h3>"
    "<p><b>Once:</b> enter your Anthropic API key in <i>Settings</i> (it is kept in the system keychain) and choose "
    "where results are saved.</p>"
    "<ol>"
    "<li><b>Data pack</b> -- what to extract. Pick the pack for your field. To make your own, use <i>New…</i>: start from "
    "a template, copy an existing pack, or let the app draft one from a few sample papers.</li>"
    "<li><b>Papers</b> -- add PDFs (or drop them on the window), type an arXiv ID or DOI, or add a list.</li>"
    "<li><b>What to extract</b> -- everything ticked gives the full dataset. Untick steps or values you don't need: "
    "fewer values means a cheaper, quicker search.</li>"
    "<li><b>Options</b> -- the AI model (cost vs. accuracy) and extras. Hover over any option for an explanation.</li>"
    "<li><b>Run</b> -- press <i>Extract data</i>. You may be asked to choose figures to digitize, and at the end to "
    "review values the pack has no column for yet.</li>"
    "</ol>"
    "<p><b>Results</b> appear in the tabs at the bottom and are saved as CSV files in the results folder. "
    "<i>Things to check</i> lists values worth a second look. Hover over a value in <i>Extracted data</i> to see "
    "where in the paper it came from.</p>"
    "<p><b>Cost</b>: each paper gets a few requests to the AI model -- planning the rows, reading its details, and one "
    "per extraction step the data pack uses. <i>Data Packs › All data packs and modules…</i> lists them for each pack, "
    "and <i>Help › How data packs work…</i> explains steps, modules and calculations.</p>")
START_TEXT = ("Start here: choose a data pack (1), add papers (2), tick what to extract (3), then press Extract data "
              "(5). Results appear below. New to the app? <a href='help'>Getting started</a>")


def _step(number: str, title: str, tip: str) -> QLabel:
    """A numbered step of the workflow ('1  Data pack'), with its explanation on hover."""
    label = QLabel(f"<span style='color: palette(link); font-weight: 700;'>{number}</span>&nbsp;&nbsp;<b>{title}</b>")
    label.setToolTip(tip)
    return label


PRIVACY_NOTE = ("Privacy and cost: each paper's text and table images are sent to Anthropic (or to your own model "
                "server, if set up in Settings) to read the values; usage is billed to your API key.")


STEP_LABELS = {"structure_planner": "Experiment structure", "metadata": "Bibliographic metadata",
               "methodology": "Methodology", "term_search": "Parameters to look for",
               "chemistry": "Solution chemistry",
               "figure_planner": "Figure suggestions", "triage": "Screening",
               "equations": "Equations to LaTeX"}


# (RunConfig.model_profile, label, tooltip) -- costs and accuracy measured 2026-11-03
# (eval/model_comparison_2026-11-03.md; prebiotic, accuracy = share of Standard's reference values)
MODEL_PROFILE_CHOICES = [
    ("standard", "Standard (Claude Sonnet 5.5) -- most accurate",
     "<b>Standard</b> (recommended): Sonnet 5.5 for every step.<br>"
     "Most accurate. Chemistry papers ~$0.15-0.25; long exoplanet papers up to ~$1.50."),
    ("balanced", "Balanced (Sonnet plans, Haiku extracts) -- half price",
     "<b>Balanced</b>: Sonnet 5.5 works out each paper's samples, Haiku 5.5 reads the values.<br>"
     "About half Standard's cost (~$0.07-0.12 per chemistry paper), ~99% of its values. "
     "Read values once. Not recommended for exoplanets (Economy is cheaper there and as accurate)."),
    ("economy", "Economy (Claude Haiku 5.5) -- cheapest",
     "<b>Economy</b>: Haiku 5.5 for every step.<br>"
     "~1-4 cents per paper; ~96% of Standard's values reading once, ~99% reading three times. "
     "Can miss values stated only in the text. Good for screening many papers."),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parameter Extractor")
        self.resize(1300, 900)
        self.setAcceptDrops(True)

        self._settings = QSettings()        # non-secret preferences only (never the key)
        self._thread: Optional[QThread] = None
        self._worker: Optional[PipelineWorker] = None
        self._close_when_done = False
        self._quitting = False
        self._key_was_stored = False
        # one run = background extraction + (optionally) a figure review running alongside it
        self._extraction: Optional[Extraction] = None   # live object, filled in as steps complete
        self._extraction_ok = False
        self._review: Optional[FigureReviewDialog] = None
        self.registry_path = default_registry_path()     # local additions to the variable list
        self._load_category_edits()

        # inputs above, run controls + results below, with a handle between them the user can
        # drag (Mickey, 2026-10-23: the results were squeezed); the inputs scroll when made small
        inputs = QScrollArea()
        inputs.setWidget(self._build_inputs())
        inputs.setWidgetResizable(True)
        inputs.setFrameShape(QFrame.Shape.NoFrame)
        inputs.setMinimumHeight(80)
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addLayout(self._build_run_controls())
        self.tabs = self._build_results()
        lower_layout.addWidget(self.tabs, stretch=1)
        self.main_split = QSplitter(Qt.Orientation.Vertical)
        self.main_split.addWidget(inputs)
        self.main_split.addWidget(lower)
        self.main_split.setChildrenCollapsible(False)
        self.main_split.setHandleWidth(10)
        self.main_split.setStretchFactor(1, 1)             # a taller window grows the results
        self.main_split.setSizes([470, 430])
        # a new key: the one-paper layout's saved position (inputs ~210 px) would squeeze the three panes
        saved = self._settings.value("main_split_v2")
        if saved is not None:
            self.main_split.restoreState(saved)
        self.main_split.splitterMoved.connect(
            lambda *_: self._settings.setValue("main_split_v2", self.main_split.saveState()))
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.main_split)
        self.setCentralWidget(central)

        quit_action = QAction("Quit", self, shortcut=QKeySequence.StandardKey.Quit,
                              triggered=self.close)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.addAction(quit_action)
        file_menu = self.menuBar().addMenu("File")
        self.add_pdfs_action = QAction("Add PDFs…", self, shortcut=QKeySequence.StandardKey.Open,
                                       triggered=self._choose_pdf)
        self.add_list_action = QAction("Add papers from a list (CSV)…", self, triggered=lambda: self.papers.add_list())
        file_menu.addAction(self.add_pdfs_action)
        file_menu.addAction(self.add_list_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)
        # Settings: a menu like Data Packs (Mickey, 2026-11-08), not a button
        settings_menu = self.menuBar().addMenu("Settings")
        self.settings_action = QAction("Settings…", self, shortcut=QKeySequence.StandardKey.Preferences,
                                       triggered=self.open_settings)
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)   # macOS: also in the app menu
        self.settings_menu_action = QAction("API keys, results folder and lookups…", self,
                                            triggered=self.open_settings)
        self.output_action = QAction("Choose the results folder…", self, triggered=self._choose_output_dir)
        self.open_output_action = QAction("Open the results folder", self,
                                          triggered=lambda: self._open(Path(self.out_edit.text().strip()).expanduser()))
        self.lookups_action = QAction("Online lookups (PubChem, NASA Exoplanet Archive)", self, checkable=True)
        self.lookups_action.setToolTip("Names compounds through PubChem and checks exoplanet values against the "
                                       "NASA Exoplanet Archive (no paper text is sent there).")
        for action in (self.settings_menu_action, self.settings_action):
            settings_menu.addAction(action)
        settings_menu.addSeparator()
        for action in (self.output_action, self.open_output_action, self.lookups_action):
            settings_menu.addAction(action)
        settings_menu.setToolTipsVisible(True)
        # one menu for everything about research areas (Mickey, 2026-11-07: the Variables and Data Packs menus
        # overlapped). Two layers: what a pack DEFINES (its window: columns, compounds, analysis methods, stages,
        # rules, formulas) and what YOU taught the app in reviews (accepted columns, synonyms, compound names,
        # changes to pack columns, categories) -- kept apart so they apply on top of any pack.
        packs_menu = self.menuBar().addMenu("Data Packs")
        self.packs_window_action = QAction("All data packs and modules…", self, triggered=self.open_packs_window)
        self.packs_window_action.setToolTip("Every data pack and shared module: what each is made of and what happens "
                                            "to a paper with it; new, copy, edit, check, remove")
        packs_menu.addAction(self.packs_window_action)
        packs_menu.addSeparator()
        self.new_pack_action = QAction("New data pack…", self, triggered=lambda: self.new_pack())
        self.edit_pack_action = QAction("Edit data pack…", self, triggered=lambda: self.edit_pack())
        self.edit_pack_action.setToolTip("What the pack defines: columns, compounds, analysis methods, steps, "
                                         "rules, formulas")
        self.copy_pack_action = QAction("Copy a data pack…", self, triggered=lambda: self.copy_pack())
        self.check_pack_action = QAction("Check data pack…", self, triggered=lambda: self.check_pack())
        self.remove_pack_action = QAction("Remove data pack…", self, triggered=lambda: self.remove_pack())
        self.packs_folder_action = QAction("Open data packs folder", self, triggered=self.open_packs_folder)
        self.registry_action = QAction("Remembered from your reviews…", self, triggered=self.open_registry)
        self.registry_action.setToolTip("Columns you accepted, synonyms, compound names and your changes to pack "
                                        "columns, by data pack")
        self.categories_action = QAction("Variable categories…", self, triggered=self.open_categories)
        packs_menu.setToolTipsVisible(True)
        for action in (self.new_pack_action, self.edit_pack_action, self.copy_pack_action, self.check_pack_action):
            packs_menu.addAction(action)
        packs_menu.addSeparator()
        packs_menu.addAction(self.registry_action)
        packs_menu.addAction(self.categories_action)
        packs_menu.addSeparator()
        packs_menu.addAction(self.remove_pack_action)
        packs_menu.addAction(self.packs_folder_action)
        help_menu = self.menuBar().addMenu("Help")
        self.getting_started_action = QAction("Getting started…", self, triggered=self.show_getting_started)
        help_menu.addAction(self.getting_started_action)
        self.how_packs_action = QAction("How data packs work…", self, triggered=self.show_how_packs_work)
        help_menu.addAction(self.how_packs_action)

        from parameter_extractor.gui.multi_runs import FocusedRun, QueueRun
        self.focused_run = FocusedRun(self)
        self.focused_run.finished.connect(self._multi_done)
        self.queue_run = QueueRun(self)
        self.queue_run.finished.connect(self._multi_done)
        self.lookups_action.setChecked(self.pubchem_box.isChecked())
        self.lookups_action.toggled.connect(self.pubchem_box.setChecked)
        self.pubchem_box.toggled.connect(self.lookups_action.setChecked)

        self._load_preferences()
        self._update_run_enabled()

    # ---- layout ---------------------------------------------------------------

    def _build_inputs(self) -> QWidget:
        """The data pack, then three panes -- Papers, Parameters, Run options -- and the notes below them.
        Set-once things (API key, ADS token, results folder, online lookups) are in Settings
        (gui/settings_dialog.py, the Settings menu); their widgets keep their names here."""
        from parameter_extractor.gui.paper_list import PaperListPanel
        from parameter_extractor.gui.parameter_panel import ParameterPanel
        from parameter_extractor.gui.settings_dialog import SettingsDialog
        self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.closed.connect(self._save_preferences)
        d = self.settings_dialog
        self.key_edit, self.show_key_box, self.remember_key_box = d.key_edit, d.show_key_box, d.remember_key_box
        self.ads_edit, self.remember_ads_box = d.ads_edit, d.remember_ads_box
        self.out_edit, self.pubchem_box = d.out_edit, d.pubchem_box
        for edit in (self.key_edit, self.out_edit):
            edit.textChanged.connect(self._update_run_enabled)
        d.provider_combo.currentIndexChanged.connect(lambda _i: self._refresh_profiles())
        d.local_panel.changed.connect(self._refresh_profiles)
        if d.handoff_box is not None:          # developer builds only
            d.handoff_box.toggled.connect(self._update_run_enabled)
            d.handoff_edit.textChanged.connect(self._update_run_enabled)

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        # the workflow, numbered (Mickey, 2026-11-08: scientists new to the app): 1 data pack, 2 papers, 3 what to
        # extract, 4 options, 5 run -- results below
        head = QHBoxLayout()
        head.addWidget(_step("1", "Data pack",
                             "A data pack decides what is extracted: the dataset's columns, the compounds and "
                             "methods it knows, and the steps that read a paper. Choose the one for your field, or "
                             "make your own (New…)."))
        from parameter_extractor import packs
        self.pack_combo = QComboBox()
        for pack_id, pack in sorted(packs.available().items(), key=lambda kv: kv[1].label):
            self.pack_combo.addItem(pack.label, pack_id)
            self.pack_combo.setItemData(self.pack_combo.count() - 1, pack.manifest.description,
                                        Qt.ItemDataRole.ToolTipRole)
        self.pack_combo.setToolTip("The data pack used for this run: which columns the dataset has and what is read "
                                   "from each paper. Hover over a pack in the list for its description.")
        self.pack_combo.currentIndexChanged.connect(self._on_pack_changed)
        self.pack_combo.setMinimumContentsLength(22)
        head.addWidget(self.pack_combo)
        self.new_pack_btn = QPushButton("New…", clicked=lambda: self.new_pack())
        self.new_pack_btn.setToolTip("Make a data pack for your own field: from a template, a copy of another pack, "
                                     "or drafted automatically from a few sample papers.")
        self.edit_pack_btn = QPushButton("Edit…", clicked=self._edit_current_pack)
        self.edit_pack_btn.setToolTip("Look at or change this data pack: its columns, compounds, steps and rules. "
                                      "The app's own packs can be viewed and copied.")
        self.packs_btn = QPushButton("All data packs…", clicked=self.open_packs_window)
        self.packs_btn.setToolTip("Every data pack and shared module: what each is made of and what happens to a paper "
                                  "with it (every request to the AI model and where it comes from).")
        head.addWidget(self.new_pack_btn)
        head.addWidget(self.edit_pack_btn)
        head.addWidget(self.packs_btn)
        head.addSpacing(12)
        self.pack_description = QLabel()
        self.pack_description.setStyleSheet("color: palette(placeholder-text);")
        self.pack_description.setMinimumWidth(100)
        head.addWidget(self.pack_description, 1)
        v.addLayout(head)
        self.mode_label = QLabel()                    # what the run will do (shown beside the Run button)
        self.mode_label.setStyleSheet("QLabel { font-weight: 600; color: palette(link); }")
        self.mode_label.setToolTip("What pressing the button will do. Everything ticked under 'What to extract': a "
                                   "full extraction (several papers: one after another). A whole step unticked: "
                                   "the extraction skips it. Single values unticked: a quick, cheaper search for just "
                                   "those values (a 'focused search').")

        self.top_split = QSplitter(Qt.Orientation.Horizontal)
        papers_box = QGroupBox("2   Papers")
        papers_box.setToolTip("The papers to read: add PDFs (or drop them on the window), type an arXiv ID or DOI, "
                              "or add a list.")
        pl = QVBoxLayout(papers_box)
        self.papers = PaperListPanel()
        self.papers.changed.connect(self._update_run_enabled)
        self.papers.message.connect(self.status_message)
        self.papers.selected.connect(self._paper_selected)
        self.pdf_edit = self.papers.id_edit            # the typed paper: run directly, or Enter adds it
        self.pdf_edit.textChanged.connect(self._update_run_enabled)
        pl.addWidget(self.papers)
        self.top_split.addWidget(papers_box)

        params_box = QGroupBox("3   What to extract")
        params_box.setToolTip("The data pack's steps and the values each one reads. Everything ticked = the full "
                              "dataset. Untick what you don't need.")
        ql = QVBoxLayout(params_box)
        self.params = ParameterPanel()
        self.params.changed.connect(self._update_run_enabled)
        ql.addWidget(self.params)
        self.top_split.addWidget(params_box)

        options_box = QGroupBox("4   Options")
        options_box.setToolTip("How the papers are read: which AI model (cost vs. accuracy), and what else is done "
                               "and saved.")
        ol = QVBoxLayout(options_box)
        ol.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._build_options())
        ol.addWidget(scroll)
        self.top_split.addWidget(options_box)
        self.top_split.setStretchFactor(0, 3)
        self.top_split.setStretchFactor(1, 4)
        self.top_split.setStretchFactor(2, 3)
        self.top_split.setSizes([330, 430, 330])
        saved = self._settings.value("top_split")
        if saved is not None:
            self.top_split.restoreState(saved)
        self.top_split.splitterMoved.connect(lambda *_: self._settings.setValue("top_split",
                                                                                 self.top_split.saveState()))
        v.addWidget(self.top_split, 1)

        return page

    def show_how_packs_work(self) -> None:
        """Steps, calculations, data packs, modules (the words the windows use) and where model requests come from."""
        from PySide6.QtWidgets import QDialog, QTextBrowser
        from parameter_extractor import pack_overview
        dlg = QDialog(self)
        dlg.setWindowTitle("How data packs work")
        dlg.resize(820, 640)
        v = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.document().setDocumentMargin(18)
        view.setHtml(pack_overview.parts_html("How data packs work")
                     + "<p>To see every request and calculation of a particular data pack, and where each one comes "
                       "from, open <i>Data Packs › All data packs and modules…</i> or the pack's <i>Overview</i> "
                       "tab.</p>")
        v.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        open_btn = QPushButton("All data packs and modules…")
        open_btn.clicked.connect(lambda: (dlg.accept(), self.open_packs_window()))
        row.addWidget(open_btn)
        close = QPushButton("Close", default=True)
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        v.addLayout(row)
        dlg.exec()

    def show_getting_started(self) -> None:
        """The workflow in a few lines (Help menu; also offered on first launch)."""
        box = QMessageBox(self)
        box.setWindowTitle("Getting started")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(GETTING_STARTED)
        box.exec()

    def _edit_current_pack(self) -> None:
        """The editor for the pack chosen above (the menu's Edit… asks which one)."""
        from parameter_extractor import packs
        pack = packs.available().get(self.pack_combo.currentData() or "")
        if pack is not None:
            self._open_pack_editor(pack.folder)

    def _show_pack_description(self) -> None:
        from parameter_extractor import packs
        pack = packs.available().get(self.pack_combo.currentData() or "")
        text = (pack.manifest.description or "") if pack else ""
        first = text.split(". ")[0].rstrip(".") + "." if text else ""
        self.pack_description.setText(first if len(first) < 140 else first[:137] + "…")
        self.pack_description.setToolTip(text)

    @staticmethod
    def _section(title: str) -> QLabel:
        label = QLabel(title)
        label.setStyleSheet("QLabel { font-weight: 600; margin-top: 8px; }")
        return label

    def _build_options(self) -> QWidget:
        """The run options, grouped (Mickey, 2026-11-08: they had outgrown one dropdown). The groups for several
        papers and for a focused search only show when they apply."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 0, 6, 6)
        v.setSpacing(4)

        v.addWidget(self._section("AI model and cost"))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(lambda _i: self._update_run_enabled())
        form.addRow("Model:", self.profile_combo)
        self.passes_combo = QComboBox()
        for n, label in ((1, "Once"), (2, "Twice, keep the majority"), (3, "Three times, keep the majority")):
            self.passes_combo.addItem(label, n)
        self.passes_combo.setToolTip(
            "Read each paper's values more than once and keep the value most readings agree on. Catches values a "
            "single reading misses now and then, at the cost of those readings. Recommended: three times with "
            "Economy, once with Standard or Balanced. Disagreements are listed under Things to check.")
        form.addRow("Read values:", self.passes_combo)
        self._models_form = form
        v.addLayout(form)
        self.batch_box = QCheckBox("Half price, slower (batch mode)")
        self.batch_box.setToolTip("Anthropic answers these requests at half the price, but each step waits in a queue "
                                  "-- usually a few minutes, at most 24 hours -- so a paper takes much longer. The "
                                  "results are the same. Best for papers you don't need right away.")
        self._batch_tip = self.batch_box.toolTip()
        v.addWidget(self.batch_box)

        v.addWidget(self._section("Paper text"))
        self.arxiv_box = QCheckBox("Read the arXiv version when there is one")
        self.arxiv_box.setToolTip("If the paper is on arXiv, read arXiv's text instead of the PDF: cheaper (less text "
                                  "to read) and exact table values. It is the preprint, which can differ from the "
                                  "published paper (noted under Things to check), and its figures can't be "
                                  "digitized. Papers added by arXiv ID or DOI are always read from arXiv.")
        self.si_box = QCheckBox("Also read the supplementary information")
        self.si_box.setChecked(True)
        self.si_box.setToolTip("Put the supplementary PDF in the same folder as the paper, named like the paper plus "
                               "'_SI' (e.g. smith2020.pdf and smith2020_SI.pdf). It is read with the paper; its pages "
                               "are cited as S1, S2, ...")
        v.addWidget(self.arxiv_box)
        v.addWidget(self.si_box)

        self.review_widget = QWidget()            # not used by a focused search: hidden then
        rv = QVBoxLayout(self.review_widget)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        rv.addWidget(self._section("While reading"))
        self.suggest_box = QCheckBox("Suggest values the data pack has no column for")
        self.suggest_box.setChecked(True)
        self.suggest_box.setToolTip("Also note conditions and compounds the dataset has no column for yet (e.g. a "
                                    "stirring rate) and offer them at the end, so you can add them as new columns. "
                                    "Untick for a shorter review at the end.")
        self.auto_figures_box = QCheckBox("Read simple plots automatically")
        self.auto_figures_box.setToolTip(
            "For figures you choose to digitize: a simple bar chart or scatter plot is read without opening the "
            "digitizer (and listed under Things to check, so you can verify it). Other figures open in the digitizer "
            "as usual.")
        rv.addWidget(self.suggest_box)
        rv.addWidget(self.auto_figures_box)

        rv.addWidget(self._section("Saved with the results"))
        self.images_box = QCheckBox("Images of the tables and digitized figures")
        self.images_box.setChecked(True)
        self.images_box.setToolTip("Keep a crop of every table (the Tables tab) and the images of the figures you "
                                   "digitize in the run folder, for checking values and flags against the paper.")
        self.all_figures_box = QCheckBox("Also images of figures not digitized")
        self.all_figures_box.setToolTip("Figures are rendered for the figure review; normally only the ones you "
                                        "digitize are kept. Tick to keep every figure's image.")
        self.images_box.toggled.connect(self.all_figures_box.setEnabled)
        self.equations_box = QCheckBox("Numbered equations as text (LaTeX)")
        self.equations_box.setToolTip("Equations the authors number ('(1)', 'Eq. 2') are always shown in the Equations "
                                      "tab as images. Ticked, they're also written out as LaTeX (about 2 cents for a "
                                      "dozen equations).")
        for box in (self.images_box, self.all_figures_box, self.equations_box):
            rv.addWidget(box)
        v.addWidget(self.review_widget)

        # only with several papers (a full extraction runs them as a queue)
        self.multi_widget = QWidget()
        mv = QVBoxLayout(self.multi_widget)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(4)
        mv.addWidget(self._section("Several papers"))
        self.review_figures_box = QCheckBox("Choose figures to digitize as each paper is read")
        self.review_figures_box.setToolTip("Each paper's figures are offered for digitizing as soon as it has been read, "
                                           "while the others carry on. Unticked, figures are skipped.")
        self.review_variables_box = QCheckBox("Review suggested new columns at the end")
        self.review_variables_box.setToolTip("When every paper is done, each paper's suggested new columns are shown in "
                                             "turn (your choices carry over). Unticked, they stay out of the dataset "
                                             "(listed in each paper's new_variables.json).")
        mv.addWidget(self.review_figures_box)
        mv.addWidget(self.review_variables_box)
        v.insertWidget(0, self.multi_widget)          # the groups that apply to this run come first

        # only for a focused search (single parameters unticked)
        self.focused_widget = QWidget()
        fv = QVBoxLayout(self.focused_widget)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(4)
        fv.addWidget(self._section("Searching for a few values"))
        self.words_edit = QLineEdit(placeholderText="Search words, e.g. EXOFAST (optional)")
        self.words_edit.setToolTip("Only papers containing one of these words are read, and only the passages around "
                                   "them (separate words with commas). Left empty: words from the chosen values' "
                                   "descriptions.")
        self.tables_box = QCheckBox("Keep whole tables")
        self.tables_box.setToolTip("When a search word is in or just above a table, read the whole table -- table rows "
                                   "rarely contain the search words themselves. Costs a little more.")
        self.plan_box = QCheckBox("One row per sample, as in a full extraction")
        self.plan_box.setToolTip("First work out each paper's samples (as a full extraction does), then find the "
                                 "values for each sample. Roughly doubles the cost of a search.")
        self.whole_box = QCheckBox("Read the whole paper (finds more, costs more)")
        self.whole_box.setToolTip("Normally only the passages around the search words are read. Tick to read the whole "
                                  "paper instead.")
        self.whole_box.toggled.connect(lambda on: self.tables_box.setEnabled(not on))
        for x in (self.words_edit, self.tables_box, self.plan_box, self.whole_box):
            fv.addWidget(x)
        v.insertWidget(0, self.focused_widget)
        v.addStretch(1)
        return w

    def option_toggles(self) -> List[QCheckBox]:
        """The on/off run options, in the panel's order."""
        return [self.batch_box, self.arxiv_box, self.si_box, self.suggest_box, self.auto_figures_box,
                self.images_box, self.all_figures_box, self.equations_box]

    def _update_options_summary(self, *_args) -> None:
        """Kept for callers of the old summary line: the mode line says what the run will do now."""
        self._update_mode()

    def run_items(self) -> list:
        """The papers to run: the list, plus a paper typed in the field and not yet added."""
        items = self.papers.items()
        typed = self.paper_item() if self.pdf_edit.text().strip() else None
        if typed is not None and str(typed) not in {str(i) for i in items}:
            items = items + [typed]
        return items

    def _update_mode(self) -> None:
        """The mode line, the Run button's text, and which option groups show: several papers -> a queue
        (multi_widget), single parameters unticked -> a focused search (focused_widget)."""
        n = len(self.run_items())
        focused = self.params.focused
        self.multi_widget.setVisible(n > 1 and not focused)
        self.focused_widget.setVisible(focused)
        self.review_widget.setVisible(not focused)     # figures, new variables, saved images: full extraction only
        self._models_form.setRowVisible(self.passes_combo, not focused)   # a focused search: one call per paper
        if focused:
            k = len(self.params.checked_columns())
            self.mode_label.setText(f"Search for {k} value{'s' if k != 1 else ''} only"
                                    + (f" in {n} papers" if n > 1 else ""))
            self.run_btn.setText(f"Search {n} paper{'s' if n != 1 else ''}" if n else "Search")
        else:
            off = self.params.stages_off()
            narrowed = self.params.scope_summary()
            self.mode_label.setText("Full extraction" + (f" of {n} papers (one after another)" if n > 1 else "")
                                    + (f" -- without {', '.join(off)}" if off else "")
                                    + (f" -- only {narrowed}" if narrowed else ""))
            self.run_btn.setText(f"Extract data from {n} papers" if n > 1 else "Extract data")

    def _refresh_profiles(self) -> None:
        """The Models list: the Claude profiles, or the local profiles set up in Settings > Model provider."""
        local = self.settings_dialog.provider() == "local"
        if getattr(self, "_profiles_local", None) is not None:      # remember the choice of the list being left
            self._settings.setValue("local_model_profile" if self._profiles_local else "model_profile",
                                    self.profile_combo.currentData())
        self._profiles_local = local
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        if local:
            from parameter_extractor import local_models
            profiles = self.settings_dialog.local_panel.settings().profiles
            for name, roles in profiles.items():
                self.profile_combo.addItem(f"{name} (local)", name)
                tip = "<br>".join(f"{label}: {roles.get(role) or '-'}" for role, label in local_models.PROFILE_ROLES)
                self.profile_combo.setItemData(self.profile_combo.count() - 1, f"<b>{name}</b><br>{tip}",
                                               Qt.ItemDataRole.ToolTipRole)
            self.profile_combo.setToolTip("Your local model profiles (Settings > Model provider). Local models "
                                          "aren't validated for this app: check the values against the paper.")
            wanted = self._settings.value("local_model_profile", "")
        else:
            for key, label, tip in MODEL_PROFILE_CHOICES:
                self.profile_combo.addItem(label.split(" -- ")[0], key)       # the details are in the tooltip
                self.profile_combo.setItemData(self.profile_combo.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
            self.profile_combo.setToolTip("Which Claude models read the paper:<br><br>"
                                          + "<br><br>".join(tip for _, _, tip in MODEL_PROFILE_CHOICES)
                                          + "<br><br>Figure-digitizing suggestions and LaTeX conversion (when you "
                                            "ask for them) always use Sonnet 5.5.")
            wanted = self._settings.value("model_profile", "standard")
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(wanted)))
        self.profile_combo.blockSignals(False)
        # batch mode is the Anthropic API's; a local run never uses it
        self.batch_box.setEnabled(not local)
        self.batch_box.setToolTip(self._batch_tip if not local else "Not available with a local model server.")
        self._update_run_enabled()

    def open_settings(self) -> None:
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _build_run_controls(self) -> QVBoxLayout:
        self.run_btn = QPushButton("Extract data", clicked=self._start_run, default=True)
        self.run_btn.setStyleSheet("QPushButton { font-weight: 600; padding: 4px 18px; }")
        self.run_btn.setToolTip("Read the papers and extract the data (step 5). Results appear in the tabs below and "
                                "are saved to the results folder (Settings).")
        self.cancel_btn = QPushButton("Cancel", clicked=self._cancel_run, enabled=False)
        self.skip_figures_btn = QPushButton("Skip figures of the remaining papers", clicked=self._skip_figures)
        self.skip_figures_btn.setHidden(True)
        self.retry_btn = QPushButton("Retry failed papers", clicked=self._retry_failed)
        self.retry_btn.setToolTip("Search again only the papers whose result was 'Couldn't search' (e.g. arXiv was "
                                  "busy), with the same parameters.")
        self.retry_btn.setHidden(True)
        self.progress = QProgressBar(minimum=0, maximum=6, value=0, textVisible=False)
        self.status = QLabel(START_TEXT, wordWrap=True)
        buttons = QHBoxLayout()
        buttons.addWidget(_step("5", "Run", "Press the button: the papers are read and the values extracted. You "
                                            "may be asked to check figures and new variables along the way."))
        for b in (self.run_btn, self.cancel_btn, self.skip_figures_btn, self.retry_btn):
            buttons.addWidget(b)
        buttons.addSpacing(10)
        buttons.addWidget(self.mode_label)
        buttons.addWidget(self.progress, stretch=1)
        # what's missing before a run (API key, results folder): right under the Run button, where it's seen
        self.settings_hint = QLabel(wordWrap=True)
        self.settings_hint.setStyleSheet("QLabel { color: palette(link); font-weight: 600; }")
        self.settings_hint.linkActivated.connect(lambda _: self.open_settings())
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.linkActivated.connect(lambda link: self.show_getting_started() if link == "help" else None)
        self.privacy_note = QLabel(PRIVACY_NOTE, wordWrap=True)
        self.privacy_note.setStyleSheet("color: palette(placeholder-text);")
        col = QVBoxLayout()
        col.addLayout(buttons)
        col.addWidget(self.settings_hint)
        col.addWidget(self.status)
        col.addWidget(self.privacy_note)
        return col

    def status_message(self, text: str) -> None:
        self.status.setText(text)

    def _build_results(self) -> QTabWidget:
        tabs = QTabWidget()

        self.rows_table = QTableWidget()
        from parameter_extractor.gui.widgets import ColumnGroupBand
        self.rows_band = ColumnGroupBand(self.rows_table)         # names each block of columns once
        self.rows_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rows_table.setAlternatingRowColors(True)
        self.rows_legend = QLabel(wordWrap=True)
        self.rows_legend.setHidden(True)
        rows_page = QWidget()
        rows_layout = QVBoxLayout(rows_page)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)
        rows_layout.addWidget(self.rows_band)
        rows_layout.addWidget(self.rows_table, stretch=1)
        rows_layout.addWidget(self.rows_legend)
        tabs.addTab(rows_page, "Extracted data")
        tabs.setTabToolTip(0, "The dataset: one row per sample, one column per value. Hover over a value to see where "
                              "in the paper it came from.")

        self.flags_tree = QTreeWidget()
        self.flags_tree.setHeaderLabels(["Issue", "Quote from the paper", "Where"])
        self.flags_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.flags_tree.currentItemChanged.connect(self._show_flag_details)
        self.flag_details = QTextBrowser(placeholderText="Select a flag to see the full "
                                                         "issue and the supporting quote.")
        flags_split = QSplitter(Qt.Orientation.Vertical)
        flags_split.addWidget(self.flags_tree)
        flags_split.addWidget(self.flag_details)
        flags_split.setSizes([400, 160])
        tabs.addTab(flags_split, "Things to check")
        tabs.setTabToolTip(1, "Values worth a second look (uncertain, calculated, assumed, or disagreeing), and notes "
                              "about the paper -- grouped by kind. Select one for the details and the quote.")

        # captured figures and labelled equations, at a glance (rich text: images + captions)
        self.figures_view = QTextBrowser(placeholderText="Figures found in the paper appear here.")
        self.figures_view.setOpenExternalLinks(False)
        tabs.addTab(self.figures_view, "Figures")
        tabs.setTabToolTip(2, "The paper's figures, and the ones you digitized (values read off the plot).")
        self.tables_view = QTextBrowser(placeholderText="Tables found in the paper appear here.")
        self.tables_view.setOpenExternalLinks(False)
        tabs.addTab(self.tables_view, "Tables")
        tabs.setTabToolTip(3, "The paper's tables as images, to compare the extracted values with.")
        self.equations_view = QTextBrowser(placeholderText="Equations the authors label, e.g. '(1)' or "
                                                           "'Eq. 2', appear here.")
        self.equations_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        tabs.addTab(self.equations_view, "Equations")
        tabs.setTabToolTip(4, "Equations the authors number or name.")

        summary = QWidget()
        s_layout = QVBoxLayout(summary)
        self.summary_text = QTextBrowser()
        self.open_folder_btn = QPushButton("Open results folder", enabled=False,
                                           clicked=lambda: self._open(self._last_run_dir))
        self.open_csv_btn = QPushButton("Open CSV", enabled=False,
                                        clicked=lambda: self._open(self._last_csv))
        s_buttons = QHBoxLayout()
        s_buttons.addWidget(self.open_folder_btn)
        s_buttons.addWidget(self.open_csv_btn)
        s_buttons.addStretch(1)
        s_layout.addWidget(self.summary_text)
        s_layout.addLayout(s_buttons)
        tabs.addTab(summary, "Summary")
        tabs.setTabToolTip(5, "What the run did and cost, and where the files were saved.")

        # a focused search's results: one row per paper and object, a column per parameter (focused_results.csv)
        self.search_table = QTableWidget(0, 4)
        self.search_table.setHorizontalHeaderLabels(["Paper", "Set", "Object", "Result"])
        self.search_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.search_index = tabs.addTab(self.search_table, "Search results")
        tabs.setTabVisible(self.search_index, False)

        tabs.setEnabled(False)
        return tabs

    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for i, widget in enumerate(widgets):
            h.addWidget(widget, stretch=1 if i == 0 else 0)
        return w

    # ---- preferences (QSettings for paths; keychain for the key) -------------

    def _load_preferences(self) -> None:
        self.out_edit.setText(self._settings.value("output_dir", str(DEFAULT_OUTPUT_DIR)))
        self.pubchem_box.setChecked(self._settings.value("use_pubchem", True, type=bool))
        saved_pack = self._settings.value("pack", "prebiotic_chemistry")
        index = self.pack_combo.findData(saved_pack)
        self.pack_combo.setCurrentIndex(index if index >= 0 else self.pack_combo.findData("prebiotic_chemistry"))
        self.params.load(self.pack_combo.currentData(), self.registry_path)           # no change signal if index 0 was kept
        self._show_pack_description()
        self.equations_box.setChecked(self._settings.value("equations_to_latex", False, type=bool))
        from parameter_extractor import local_models
        local = local_models.load()
        local.api_key = key_store.load_key(key_store.LOCAL_ACCOUNT) or ""
        self._local_saved = local.to_dict()            # written back only when changed
        d = self.settings_dialog
        d.local_panel.load(local)
        d.provider_combo.setCurrentIndex(max(0, d.provider_combo.findData(
            self._settings.value("provider", "anthropic"))))
        self._refresh_profiles()
        self.batch_box.setChecked(self._settings.value("batch_mode", False, type=bool))
        self.arxiv_box.setChecked(self._settings.value("prefer_arxiv", False, type=bool))
        self.suggest_box.setChecked(self._settings.value("suggest_new_variables", True, type=bool))
        self.si_box.setChecked(self._settings.value("include_supplements", True, type=bool))
        self.images_box.setChecked(self._settings.value("save_images", True, type=bool))
        self.all_figures_box.setChecked(self._settings.value("save_all_figure_images", False, type=bool))
        self.auto_figures_box.setChecked(self._settings.value("auto_digitize_figures", False, type=bool))
        self.all_figures_box.setEnabled(self.images_box.isChecked())
        self.passes_combo.setCurrentIndex(max(0, self.passes_combo.findData(self._settings.value("passes", 1, type=int))))
        if self.settings_dialog.handoff_box is not None:
            self.settings_dialog.handoff_edit.setText(self._settings.value("dev/handoff_dir", ""))
            self.settings_dialog.handoff_box.setChecked(self._settings.value("dev/handoff", False, type=bool))
        self.review_figures_box.setChecked(self._settings.value("queue/review_figures", True, type=bool))
        self.review_variables_box.setChecked(self._settings.value("queue/review_variables", True, type=bool))
        self.words_edit.setText(self._settings.value("focused/search_words", ""))
        self.whole_box.setChecked(self._settings.value("focused/whole_paper", False, type=bool))
        self.tables_box.setChecked(self._settings.value("focused/whole_tables", True, type=bool))
        self._load_plan_box()
        stored_ads = key_store.load_key(key_store.ADS_ACCOUNT)
        self._ads_was_stored = bool(stored_ads)
        if stored_ads:
            self.ads_edit.setText(stored_ads)
            self.remember_ads_box.setChecked(True)
        self._update_options_summary()
        stored_key = key_store.load_key()
        self._key_was_stored = bool(stored_key)
        if stored_key:
            self.key_edit.setText(stored_key)
            self.remember_key_box.setChecked(True)

    def _on_pack_changed(self, _index: int) -> None:
        """The chosen area's stages and parameters (and its pack active for the windows opened before a run)."""
        from parameter_extractor import packs
        pack_id = self.pack_combo.currentData()
        if pack_id:
            packs.activate(pack_id)
            self.params.load(pack_id, self.registry_path)
            self._load_plan_box()
        self._show_pack_description()

    def _load_plan_box(self) -> None:
        """'Rows as in a full extraction', per data pack, defaulting to the pack's setting."""
        from parameter_extractor import packs
        pack_id = self.pack_combo.currentData() or "prebiotic_chemistry"
        pack = packs.available().get(pack_id)
        default = bool(pack and pack.manifest.focused_row_plan)
        self.plan_box.setChecked(self._settings.value(f"focused/{pack_id}/plan_rows", default, type=bool))

    def optional_stage_choices(self) -> dict:
        """RunConfig.optional_stages: stages unticked in the Parameters panel are 'off'; the rest run as usual."""
        return self.params.optional_stage_choices()

    def focus_terms(self) -> list:
        """'Parameters to look for' left the window (Mickey, 2026-11-08); the backend option stays (CLI --look-for)."""
        return []

    def _save_preferences(self) -> None:
        self._settings.setValue("output_dir", self.out_edit.text().strip())
        self._settings.setValue("queue/review_figures", self.review_figures_box.isChecked())
        self._settings.setValue("queue/review_variables", self.review_variables_box.isChecked())
        self._settings.setValue("focused/search_words", self.words_edit.text())
        self._settings.setValue("focused/whole_paper", self.whole_box.isChecked())
        self._settings.setValue("focused/whole_tables", self.tables_box.isChecked())
        if self.pack_combo.currentData():
            self._settings.setValue(f"focused/{self.pack_combo.currentData()}/plan_rows", self.plan_box.isChecked())
        self._settings.setValue("use_pubchem", self.pubchem_box.isChecked())
        self._settings.setValue("pack", self.pack_combo.currentData())
        self._settings.setValue("equations_to_latex", self.equations_box.isChecked())
        local_run = self.settings_dialog.provider() == "local"
        self._settings.setValue("local_model_profile" if local_run else "model_profile", self.profile_combo.currentData())
        self._settings.setValue("provider", self.settings_dialog.provider())
        from parameter_extractor import local_models
        local = self.settings_dialog.local_panel.settings()
        before = getattr(self, "_local_saved", {}) or {}
        if local.to_dict(with_key=False) != {k: v for k, v in before.items() if k != "api_key"}:
            try:
                local_models.save(local)
            except OSError:
                self.status.setText("Note: couldn't save the local model settings.")
        if local.api_key != before.get("api_key", ""):
            if local.api_key:
                key_store.save_key(local.api_key, key_store.LOCAL_ACCOUNT)
            else:
                key_store.delete_key(key_store.LOCAL_ACCOUNT)
        self._local_saved = local.to_dict()
        self._settings.setValue("batch_mode", self.batch_box.isChecked())
        self._settings.setValue("prefer_arxiv", self.arxiv_box.isChecked())
        self._settings.setValue("suggest_new_variables", self.suggest_box.isChecked())
        self._settings.setValue("include_supplements", self.si_box.isChecked())
        self._settings.setValue("save_images", self.images_box.isChecked())
        self._settings.setValue("save_all_figure_images", self.all_figures_box.isChecked())
        self._settings.setValue("auto_digitize_figures", self.auto_figures_box.isChecked())
        self._settings.setValue("passes", self.passes_combo.currentData() or 1)
        if self.settings_dialog.handoff_box is not None:
            self._settings.setValue("dev/handoff", self.settings_dialog.handoff_box.isChecked())
            self._settings.setValue("dev/handoff_dir", self.settings_dialog.handoff_edit.text().strip())
        # keys: saved when "remember" is ticked; forgotten when it's un-ticked or the field is emptied
        ads = self.ads_edit.text().strip()
        if self.remember_ads_box.isChecked() and ads:
            if not key_store.save_key(ads, key_store.ADS_ACCOUNT):
                self.status.setText("Note: couldn't save the ADS token to the system keychain.")
            self._ads_was_stored = True
        elif self._ads_was_stored:
            key_store.delete_key(key_store.ADS_ACCOUNT)
            self._ads_was_stored = False
        key = self.key_edit.text().strip()
        if self.remember_key_box.isChecked() and key:
            if not key_store.save_key(key):
                self.status.setText("Note: couldn't save the key to the system keychain.")
            self._key_was_stored = True
        elif self._key_was_stored:
            key_store.delete_key()
            self._key_was_stored = False

    # ---- input handling -------------------------------------------------------

    def _choose_pdf(self) -> None:
        self.papers.add_pdfs()

    def _set_pdf(self, path: Path) -> None:
        self.papers.add_items([path])
        self._settings.setValue("last_pdf_dir", str(path.parent))

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save results to", self.out_edit.text())
        if path:
            self.out_edit.setText(path)

    def dragEnterEvent(self, event) -> None:
        if self._dropped_pdfs(event) and not self._busy:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        pdfs = self._dropped_pdfs(event)
        if pdfs:
            self.papers.add_items(pdfs)

    @staticmethod
    def _dropped_pdfs(event) -> List[Path]:
        return [Path(u.toLocalFile()) for u in event.mimeData().urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf")]

    @property
    def _running(self) -> bool:
        """The background extraction is running."""
        return self._thread is not None

    @property
    def _busy(self) -> bool:
        """Something is running: a single paper's extraction and/or its figure review, a run of several papers,
        or a focused search."""
        return self._running or self._review is not None or self.focused_run.running or self.queue_run.running

    def _update_run_enabled(self, *_args) -> None:
        handoff = self.settings_dialog.handoff_dir() is not None      # developer mode: no key needed
        local = self.settings_dialog.provider() == "local"            # a local model server: no key either
        items = self.run_items()
        ready = bool(items and (handoff or local or self.key_edit.text().strip()) and self.out_edit.text().strip())
        if local and not self.profile_combo.currentData():
            ready = False
        if self.params.focused and not self.params.checked_columns():
            ready = False
        self.run_btn.setEnabled(ready and not self._busy)
        missing = [what for what, edit in (("your Anthropic API key", self.key_edit),
                                           ("a folder for the results", self.out_edit))
                   if not edit.text().strip() and not ((handoff or local) and edit is self.key_edit)]
        if local and not self.profile_combo.currentData():
            missing.append("a local model profile")
        self.settings_hint.setText(f"Add {' and '.join(missing)} in <a href='settings'>Settings…</a>"
                                   if missing else "")
        self.settings_hint.setVisible(bool(missing))
        self._update_mode()

    # ---- running ---------------------------------------------------------------
    #
    # A run has two parts that overlap: the extraction on a worker thread
    # (pipeline.extract) and, if the paper has figures, the figure review,
    # opened as soon as the PDF has been read. The dataset is built
    # (pipeline.finish) when BOTH are done, whichever finishes last.

    def current_config(self) -> RunConfig:
        """The run configuration the window's settings and run options describe (also used by the
        focused-search window)."""
        return RunConfig(api_key=self.key_edit.text().strip(),
                         output_dir=Path(self.out_edit.text().strip()).expanduser(),
                         registry_path=self.registry_path, focus_terms=self.focus_terms(),
                         use_pubchem=self.pubchem_box.isChecked(),
                         equations_to_latex=self.equations_box.isChecked(),
                         pack=self.pack_combo.currentData() or "prebiotic_chemistry",
                         online_checks=self.pubchem_box.isChecked(),
                         optional_stages=self.optional_stage_choices(), scopes=self.params.scopes(),
                         model_profile=self.profile_combo.currentData() or "standard",
                         provider=self.settings_dialog.provider(),
                         local=self.settings_dialog.local_panel.settings().to_dict(),
                         batch_mode=self.batch_box.isChecked(),
                         prefer_arxiv=self.arxiv_box.isChecked(), ads_token=self.ads_edit.text().strip(),
                         suggest_new_variables=self.suggest_box.isChecked(),
                         include_supplements=self.si_box.isChecked(),
                         save_images=self.images_box.isChecked(),
                         save_all_figure_images=self.images_box.isChecked() and self.all_figures_box.isChecked(),
                         auto_digitize_figures=self.auto_figures_box.isChecked(),
                         passes=self.passes_combo.currentData() or 1,
                         handoff_dir=self.settings_dialog.handoff_dir(),
                         pubchem_cache_path=default_pubchem_cache_path(), arxiv_cache_dir=default_arxiv_cache_dir())

    def paper_item(self):
        """The paper field: a PDF path, or an arXiv ID / DOI / ADS bibcode (paper_source); None if
        it's neither."""
        from parameter_extractor.ingestion.arxiv_source import identifier_in_cell
        from parameter_extractor.paper_source import is_identifier
        text = self.pdf_edit.text().strip()
        if is_identifier(text):
            return text
        if not text.lower().endswith(".pdf") and (ref := identifier_in_cell(text)):
            return ref                                    # a pasted reference link (Exoplanet Archive, ADS)
        pdf = Path(text).expanduser()
        return pdf if pdf.is_file() else None

    def _start_run(self) -> None:
        """One paper, all parameters: the full extraction with its figure review (below). Several papers: a queue
        (gui/multi_runs.QueueRun). Single parameters unticked: a focused search (gui/multi_runs.FocusedRun)."""
        items = self.run_items()
        if not items:
            QMessageBox.warning(self, "Paper not found",
                                f"There's no PDF at:\n{self.pdf_edit.text().strip()}\n\nand it isn't an arXiv "
                                f"ID, DOI or ADS bibcode either.")
            return
        missing = [str(i) for i in items if isinstance(i, Path) and not i.is_file()]
        if missing:
            QMessageBox.warning(self, "Papers not found", "No PDF at:\n" + "\n".join(missing[:10]))
            return
        self._save_preferences()
        config = self.current_config()
        if self.params.focused or len(items) > 1:
            if self.pdf_edit.text().strip():          # the typed paper joins the list it runs with
                self.papers.add_typed()
            self.papers.clear_statuses()
            self.retry_btn.setHidden(True)
            if self.params.focused:
                words = [w.strip() for w in self.words_edit.text().split(",") if w.strip()]
                self.focused_run.start(items, self.params.checked_columns(), config, words, self.whole_box.isChecked(),
                                       self.tables_box.isChecked(), self.plan_box.isChecked())
            else:
                self.skip_figures_btn.setHidden(not self.review_figures_box.isChecked())
                self.skip_figures_btn.setEnabled(True)
                self.queue_run.start(items, config, self.review_figures_box.isChecked(),
                                     self.review_variables_box.isChecked())
            self._set_inputs_enabled(False)          # after starting: it counts as running now
            self.cancel_btn.setEnabled(True)
            return
        pdf = items[0]

        self._extraction, self._extraction_ok, self._review = None, False, None
        self._worker = PipelineWorker(pdf, config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.figures_found.connect(self._on_figures_found)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.done.connect(self._on_done)

        self._set_inputs_enabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status.setText(f"Starting on {pdf.name if isinstance(pdf, Path) else pdf}…")
        self._thread.start()

    def _multi_done(self) -> None:
        """A run of several papers, or a focused search, has ended."""
        self.cancel_btn.setEnabled(False)
        self.skip_figures_btn.setHidden(True)
        failed = self.focused_run.failed_items() if self.focused_run.result is not None else []
        self.retry_btn.setText(f"Retry failed papers ({len(failed)})")
        self.retry_btn.setHidden(not failed)
        if self.queue_run.summary:
            s = self.queue_run.summary
            self._last_run_dir, self._last_csv = self.queue_run.queue.out_dir, Path(s["csv"]) if "csv" in s else None
            first = next((r for r in range(self.papers.count()) if self.queue_run.result_of(r) is not None), None)
            if first is not None:
                self.papers.table.selectRow(first)        # its results in the tabs; select another paper to switch
        self._set_inputs_enabled(True)

    def _skip_figures(self) -> None:
        self.queue_run.skip_figures()
        self.skip_figures_btn.setEnabled(False)

    def _retry_failed(self) -> None:
        """The paper list becomes the papers the focused search couldn't search (labels kept), and it runs again."""
        failed = self.focused_run.failed_items()
        if failed:
            self.papers.clear()
            self.papers.add_items(failed)
            self._start_run()

    def _paper_selected(self, row: int) -> None:
        """After a run of several papers: the selected paper's results in the tabs."""
        if self._busy:
            return
        result = self.queue_run.result_of(row)
        if result is not None:
            self.show_result(result)
            self.status.setText(f"Showing {self.papers.table.item(row, 0).text()}: {len(result.rows)} rows. "
                                f"All papers: {self.queue_run.queue.out_dir}")

    def show_search_results(self, run) -> None:
        self.tabs.setEnabled(True)
        self.tabs.setTabVisible(self.search_index, True)
        self.tabs.setCurrentIndex(self.search_index)
        self._last_run_dir, self._last_csv = run.out_dir, run.results_csv
        self.open_folder_btn.setEnabled(True)
        self.open_csv_btn.setEnabled(True)

    def report_failure(self, title: str, message: str) -> None:
        self.status.setText(f"{title}.")
        QMessageBox.critical(self, title, message)

    def _cancel_run(self) -> None:
        if self.focused_run.running:
            self.focused_run.cancel()
        elif self.queue_run.running:
            self.queue_run.cancel()
        elif self._worker:
            self._worker.cancel()
            self.status.setText("Cancelling — stopping after the current step finishes…")
        self.cancel_btn.setEnabled(False)

    def _on_progress(self, step: int, total: int, message: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(step - 1)
        self.status.setText(f"Step {step} of {total}: {message}…")
        if self._review is not None:
            self._review.set_background_status(f"Text extraction: step {step} of {total} ({message})")

    def _on_figures_found(self, extraction: Extraction) -> None:
        """The PDF has been read and has figures: start the review now, while the
        extraction carries on in the background."""
        self._extraction = extraction
        if self._quitting:
            return
        bridge = PlanBridge(lambda fig: plan_figure(extraction, fig), parent=self)
        self._review = FigureReviewDialog(extraction.figures, extraction.vocab["all_columns"],
                                          plan_bridge=bridge, parent=self,
                                          auto_digitize=extraction.ctx.config.auto_digitize_figures)
        self._review.finished.connect(self._on_review_closed)
        self._review.set_background_status("Text extraction running in the background…")
        self._review.show()
        self._update_run_enabled()

    def _on_succeeded(self, extraction: Extraction) -> None:
        self._extraction, self._extraction_ok = extraction, True

    def _on_failed(self, message: str) -> None:
        self.status.setText("The run stopped with an error.")
        QMessageBox.critical(self, "Extraction failed", message)

    def _on_cancelled(self) -> None:
        self.status.setText("Run cancelled. Partial outputs were kept in the run folder.")

    def _on_done(self) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread.deleteLater()
        self._worker.deleteLater()
        self._thread = self._worker = None
        self.cancel_btn.setEnabled(False)
        self._maybe_finish()

    def _on_review_closed(self, _result: int) -> None:
        self._maybe_finish()

    def _maybe_finish(self) -> None:
        review_open = self._review is not None and self._review.isVisible()
        if self._running:
            if not review_open and self._review is not None:
                self.status.setText("Figures reviewed — waiting for the text extraction to finish…")
            return
        if review_open:
            if self._extraction_ok and not self._quitting:
                self._review.set_background_status("Text extraction finished. Finish reviewing the "
                                                   "figures to build the dataset.")
                self.status.setText("Text extraction finished — finish reviewing the figures to build "
                                    "the dataset.")
                return
            self._review.reject()     # run failed / cancelled / quitting: closes -> back here
            return

        review, self._review = self._review, None
        digitized = review.digitized if review else []
        skipped = review.skipped if review else []
        extraction = self._extraction
        if self._extraction_ok and not self._quitting:
            self._finish(extraction, digitized, skipped)
        elif digitized and extraction is not None:
            # don't lose the user's clicking: keep the records even though no dataset was built
            for fig in digitized:
                save_digitized(fig, extraction.ctx.run_dir / "figures")
            if not self._quitting:
                QMessageBox.information(
                    self, "Figure work saved",
                    f"The dataset wasn't built, but the {len(digitized)} digitized figure(s) were "
                    f"saved to:\n{extraction.ctx.run_dir / 'figures'}")
        self._extraction, self._extraction_ok = None, False
        self._set_inputs_enabled(True)
        if self._close_when_done:
            self.close()

    def _review_new_variables(self, groups, unfound_terms, registry):
        """Asked by pipeline.finish() before the CSV is written, if anything new was found."""
        self.status.setText("Review the new variables to finish building the dataset…")
        dialog = VariableReviewDialog(groups, unfound_terms, registry, parent=self)
        dialog.exec()
        return dialog.decisions()

    def _finish(self, extraction: Extraction, digitized, skipped) -> None:
        # the worker that reported progress so far is gone; report the last step here
        extraction.ctx.on_progress = lambda e: self._on_progress(e.step, e.total_steps, e.message)
        try:
            result = finish(extraction, digitized, skipped, review=self._review_new_variables)
        except PipelineError as e:
            self._on_failed(str(e))
            return
        self.progress.setValue(self.progress.maximum())
        n_flags = len(result.paper_flags) + sum(len(f) for f in result.row_flags.values())
        n_fig_rows = sum(f["points"] for f in result.figures)
        self.status.setText(f"Done: {len(result.rows)} rows extracted"
                            + (f" ({n_fig_rows} digitized from figures)" if n_fig_rows else "")
                            + f", {n_flags} item(s) flagged for review. Saved to {result.run_dir}")
        self.show_result(result)

    def open_registry(self, area: Optional[str] = None) -> None:
        """View / undo what the variable registry remembered from earlier reviews (`area`: shown filtered)."""
        from parameter_extractor.gui.registry_dialog import RegistryDialog
        RegistryDialog(self.registry_path, parent=self, area=area if isinstance(area, str) else None).exec()
        self._load_category_edits()

    # ---- Data Packs menu ------------------------------------------------------------------

    def new_pack(self, source: Optional[str] = None) -> None:
        from parameter_extractor.gui.pack_windows import NewPackDialog
        dlg = NewPackDialog(self, source=source, config=self.current_config)
        if dlg.exec() and dlg.created is not None:
            if dlg.draft_result is not None:
                r = dlg.draft_result
                surveyed = sum(1 for p in r.papers if p.survey)
                self.status.setText(f"Drafted '{dlg.created.label}' from {surveyed} paper(s) (${r.cost_usd:.3f}): "
                                    f"{sum(len(s.parameters) for s in r.proposal.stages)} parameters in "
                                    f"{len(r.proposal.stages)} step(s)"
                                    + (f"; {r.compound_lines[0]}" if r.compound_lines else "")
                                    + ". Check and edit it in the editor; drafted_from.md in its folder lists where "
                                      "each parameter came from.")
            self.refresh_packs(select=dlg.created.id)
            self._open_pack_editor(dlg.created.folder)

    def copy_pack(self) -> None:
        self.new_pack(source=self.pack_combo.currentData())

    def edit_pack(self, tab=0) -> None:
        from parameter_extractor.gui.pack_windows import choose_pack
        pack = choose_pack(self, "Edit data pack" if not tab else "Check data pack")
        if pack is not None:
            self._open_pack_editor(pack.folder, tab)

    def open_packs_window(self) -> None:
        from parameter_extractor.gui.packs_window import DataPacksWindow
        DataPacksWindow(self).exec()

    def check_pack(self) -> None:
        self.edit_pack(tab="Check")

    def _open_pack_editor(self, folder, tab=0, parent=None) -> None:
        """The editor on a pack folder, opened at a tab (its index or name)."""
        from parameter_extractor.gui.pack_windows import PackEditor
        editor = PackEditor(folder, parent or self, self.registry_path, config=self.current_config)
        editor.saved.connect(lambda pack_id: self.refresh_packs(select=pack_id))
        editor.tabs.setCurrentIndex(editor.tab_index(tab) if isinstance(tab, str) else tab)
        editor.exec()

    def remove_pack(self) -> None:
        """Two confirmations (a warning, then typing DELETE); then the Data pack list is refreshed."""
        from parameter_extractor.gui.pack_windows import remove_pack
        if remove_pack(self):
            self.refresh_packs()

    def open_packs_folder(self) -> None:
        from parameter_extractor import packs
        folder = packs.user_packs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def refresh_packs(self, select: Optional[str] = None) -> None:
        """The Data pack list again (a pack was created or saved), keeping the choice unless `select`."""
        from parameter_extractor import packs
        keep = select or self.pack_combo.currentData()
        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        for pack_id, pack in sorted(packs.available().items(), key=lambda kv: kv[1].label):
            self.pack_combo.addItem(pack.label, pack_id)
            self.pack_combo.setItemData(self.pack_combo.count() - 1, pack.manifest.description,
                                        Qt.ItemDataRole.ToolTipRole)
        index = self.pack_combo.findData(keep)
        if index < 0:                          # the chosen area was removed: back to the default one
            index = self.pack_combo.findData(packs.DEFAULT_PACK)
        self.pack_combo.setCurrentIndex(max(index, 0))
        self.pack_combo.blockSignals(False)
        self._on_pack_changed(self.pack_combo.currentIndex())

    def open_categories(self) -> None:
        """Create / edit the categories of new variables, per data pack."""
        from parameter_extractor.gui.categories_dialog import CategoriesDialog
        CategoriesDialog(self.registry_path, parent=self).exec()
        self._load_category_edits()

    def _load_category_edits(self) -> None:
        """The user's category edits, for the Rows tab's blocks (runs load them again themselves)."""
        from parameter_extractor import variable_categories
        from parameter_extractor.registry import VariableRegistry
        try:
            variable_categories.use_local(VariableRegistry(self.registry_path).local_categories)
        except Exception:                      # a damaged registry file shouldn't stop the window
            variable_categories.use_local({})

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Locked while anything runs (the pack is active during a run; one run at a time)."""
        for w in (self.registry_action, self.categories_action, self.pack_combo, self.new_pack_action,
                  self.new_pack_btn, self.edit_pack_btn, self.packs_btn, self.packs_window_action,
                  self.edit_pack_action, self.copy_pack_action, self.remove_pack_action, self.params,
                  self.profile_combo, self.passes_combo, self.words_edit, self.add_pdfs_action, self.add_list_action,
                  self.output_action, self.lookups_action, *self.option_toggles(), self.review_figures_box,
                  self.review_variables_box, self.tables_box, self.plan_box, self.whole_box):
            w.setEnabled(enabled)
        if enabled:
            self.all_figures_box.setEnabled(self.images_box.isChecked())
            self.tables_box.setEnabled(not self.whole_box.isChecked())
        self.papers.set_locked(not enabled)
        self.settings_dialog.lock(not enabled)
        self._update_run_enabled()

    # ---- results ---------------------------------------------------------------

    def show_result(self, result) -> None:
        self._last_run_dir, self._last_csv = result.run_dir, result.csv_path
        self._fill_rows(result)
        self._fill_flags(result)
        self._fill_figures(result)
        self._fill_tables(result)
        self._fill_equations(result)
        self._fill_summary(result)
        self.open_folder_btn.setEnabled(True)
        self.open_csv_btn.setEnabled(True)
        self.tabs.setEnabled(True)
        n_flags = len(result.paper_flags) + sum(len(f) for f in result.row_flags.values())
        self.tabs.setTabText(1, f"Things to check ({n_flags})")
        self.tabs.setCurrentIndex(1 if n_flags else 0)

    def _fill_rows(self, result) -> None:
        """Shows the CSV exactly as saved, minus columns that are empty in every row."""
        with open(result.csv_path, newline="") as f:
            reader = list(csv.reader(f))
        header, body = reader[0], reader[1:]
        non_empty = [h for i, h in enumerate(header) if any(r[i] for r in body)]
        keep = [header.index(h) for h in non_empty]       # the CSV's order: column_order.py
        from parameter_extractor import packs
        from parameter_extractor.column_order import ColumnOrder
        from parameter_extractor.registry import VariableRegistry
        run_pack = packs.available().get(self.pack_combo.currentData() or "")   # locked during the run
        try:
            order = ColumnOrder(pack=run_pack, registry=VariableRegistry(self.registry_path, pack=run_pack),
                                chosen={a["column"]: a.get("category", "") for a in result.accepted_variables})
        except Exception:                   # the order is a convenience: never in the way of the results
            order = None
        try:                                # columns written under a compound's active name: provenance is kept
            from parameter_extractor.compound_names import CompoundNames      # under the default name
            default_of = CompoundNames(VariableRegistry(self.registry_path, pack=run_pack)).to_default
        except Exception:
            default_of = lambda c: c
        t = self.rows_table
        t.clear()
        t.setColumnCount(len(keep))
        t.setRowCount(len(body))
        # each block of columns (Row, Metadata, Experimental Methodology, ...) named in a band above its
        # columns; alternate blocks lightly tinted
        tinted, groups = set(), []
        for c, i in enumerate(keep):
            label = order.label_of(header[i]) if order else ""
            if not groups or groups[-1][0] != label:
                groups.append([label, c, c])
            groups[-1][2] = c
            item = QTableWidgetItem(header[i])
            item.setData(Qt.ItemDataRole.UserRole, header[i])
            if label:
                item.setToolTip(f"{header[i]} ({label})")
            t.setHorizontalHeaderItem(c, item)
            if (len(groups) - 1) % 2:
                tinted.add(c)
        self.rows_band.set_groups([tuple(g) for g in groups] if order else [])
        id_col = header.index("full_id")
        provenance = {r.full_id: r.provenance for r in result.rows}
        row_word = packs.row_word(run_pack) if run_pack else "row"
        adopted, differing = self._archive_marks(result.run_dir, row_word)
        name_col = header.index("pl_name") if "pl_name" in header else None
        fit_col = header.index("pl_fitlabel") if "pl_fitlabel" in header else None
        n_adopted = n_differ = 0
        for r, row in enumerate(body):
            flags = result.row_flags.get(row[id_col], [])
            prov = provenance.get(row[id_col], {})
            archive_note = adopted.get((row[name_col], row[fit_col] if fit_col is not None else "")) \
                if name_col is not None else None
            n_adopted += archive_note is not None
            cell_notes = differing.get((row[name_col], row[fit_col] if fit_col is not None else ""), {}) \
                if name_col is not None else {}
            for c, i in enumerate(keep):
                item = QTableWidgetItem(row[i])
                if c in tinted:
                    item.setBackground(QBrush(GROUP_TINT))
                tip = self._provenance_tip(prov.get(header[i]) or prov.get(default_of(header[i]))) if row[i] else ""
                if not tip and len(row[i]) > 30:            # no provenance (source_notes ...): the full text
                    tip = row[i]
                if flags:
                    item.setBackground(QBrush(FLAGGED_ROW_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                    tip = "\n".join(f.message for f in flags) + ("\n\n" + tip if tip else "")
                if archive_note is not None and not (flags and c == 0):   # a flagged row keeps amber in its id cell
                    item.setBackground(QBrush(ARCHIVE_ROW_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                if archive_note is not None:
                    tip = archive_note + ("\n\n" + tip if tip else "")
                if header[i] in cell_notes:             # this value differs from the archive's
                    item.setBackground(QBrush(ARCHIVE_DIFF_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                    tip = cell_notes[header[i]] + ("\n\n" + tip if tip else "")
                    n_differ += 1
                if tip:
                    item.setToolTip(tip)
                t.setItem(r, c, item)
        t.resizeColumnsToContents()
        for c in range(t.columnCount()):
            t.setColumnWidth(c, min(t.columnWidth(c), MAX_COLUMN_WIDTH))
        self.rows_legend.setText(
            f"Green rows ({n_adopted}): the {row_word} the NASA Exoplanet Archive took for this paper. Orange cells "
            f"({n_differ}): values that differ from the archive's. Amber: rows with flags (a flagged green row keeps "
            f"amber in its first cell). Hover for details.")
        self.rows_legend.setHidden(not n_adopted)

    @staticmethod
    def _archive_marks(run_dir, row_word: str = "row"):
        """From archive_validation.json (exoplanet runs with online lookups): ({(pl_name, fit label):
        hover note} for the rows the Exoplanet Archive's parameter set for this paper corresponds to --
        compared, and not another fit of the planet than the one it took --, and {same key: {column:
        hover note}} for those rows' values that differ from the archive's)."""
        path = Path(run_dir) / "archive_validation.json" if run_dir else None
        try:
            report = json.loads(path.read_text()) if path and path.is_file() else []
        except (OSError, ValueError):
            return {}, {}
        adopted, differing = {}, {}
        for e in report:
            if e.get("status") != "compared" or e.get("archive_solution"):
                continue                        # another fit than the archive's: differences expected
            key = (e["pl_name"], e.get("solution", ""))
            n = len(e.get("matches", [])) + len(e.get("differs", []))
            default = ("it is also the archive's default parameter set for this planet"
                       if str(e.get("default_flag")) == "1" else
                       "the archive's default parameter set for this planet is from another paper")
            adopted[key] = (f"NASA Exoplanet Archive: this row is the {row_word} the archive took for "
                            f"'{e.get('reference', 'this paper')}' ({len(e.get('matches', []))} of {n} values "
                            f"match); {default}.")
            for d in e.get("differs", []):
                shown = (f"{d['extracted']:.6g}" if isinstance(d["extracted"], (int, float)) else f"'{d['extracted']}'")
                archived = (f"{d['archive']:.6g}" if isinstance(d["archive"], (int, float)) else f"'{d['archive']}'")
                differing.setdefault(key, {})[d["column"]] = (
                    f"Differs from the NASA Exoplanet Archive: extracted {shown}, archive {archived}. Check the "
                    f"paper -- a misread, or the archive took this value from elsewhere.")
        return adopted, differing

    @staticmethod
    def _provenance_tip(src) -> str:
        """Hover text for a cell: where its value came from."""
        if src is None:
            return ""
        lines = [f"From: {src.origin}" + (f" ({src.confidence} confidence)"
                                          if src.confidence in ("high", "medium", "low") else "")]
        if src.source or src.page:
            lines.append("Where: " + ", ".join(x for x in (src.source, f"p. {src.page}" if src.page else "") if x))
        if src.quote and src.quote_check == "table image":
            lines.append(f"Read from the table's image (the model's transcription; the table's text layer "
                         f"differs): {src.quote}")
        elif src.quote and src.quote_check == "not found":
            lines.append(f"Model's wording (not found word for word in the paper's text): {src.quote}")
        elif src.quote:
            lines.append(f"\u201c{src.quote}\u201d")
        return "\n".join(lines)

    def _fill_flags(self, result) -> None:
        tree = self.flags_tree
        tree.clear()
        self.flag_details.clear()

        def add_group(title, flags):
            group = QTreeWidgetItem([f"{title} ({len(flags)})"])
            for f in flags:
                shown = f.quote or (f"(from the table image) {f.table_image_quote}" if f.table_image_quote else
                                    f"(model's wording, not in the paper) {f.unverified_quote}"
                                    if f.unverified_quote else "")
                where = ", ".join(x for x in (f.source or "", f"p. {f.page}" if f.page else "") if x)
                child = QTreeWidgetItem([f.message, shown, where])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                child.setToolTip(0, f.message)
                child.setToolTip(1, shown)
                if not f.quote and (f.unverified_quote or f.table_image_quote):
                    child.setForeground(1, QBrush(QColor("gray")))
                group.addChild(child)
            tree.addTopLevelItem(group)
            group.setExpanded(False)          # collapsed until the user opens a category

        cited_flags = [f for f in result.paper_flags if f.kind == "cited_data"]
        new_var_flags = [f for f in result.paper_flags if f.kind == "new_variable"]
        archive_flags = [f for f in result.paper_flags if f.kind in ("archive_check", "archive_match")]
        derived_flags = [f for f in result.paper_flags if f.kind == "derived_value"]
        repeat_flags = [f for f in result.paper_flags if f.kind == "duplicate_removed"]
        fit_flags = [f for f in result.paper_flags if f.kind in ("fit_model", "multimodal", "other_estimates")]
        identity_flags = [f for f in result.paper_flags if f.kind == "identity_not_quoted"]
        source_flags = [f for f in result.paper_flags if f.kind == "paper_source"]
        scope_flags = [f for f in result.paper_flags if f.kind == "scope"]
        vote_flags = [f for f in result.paper_flags if f.kind == "pass_disagreement"]
        auto_fig_flags = [f for f in result.paper_flags if f.kind == "auto_digitized"]
        analysis_flags = [f for f in result.paper_flags if f.kind == "analysis"]
        other_paper_flags = [f for f in result.paper_flags
                             if f.kind not in ("new_variable", "cited_data", "derived_value", "duplicate_removed",
                                               "archive_check", "archive_match", "fit_model",
                                               "multimodal", "other_estimates", "identity_not_quoted",
                                               "paper_source", "pass_disagreement", "auto_digitized",
                                               "analysis", "scope")]
        if scope_flags:
            add_group("Scope of this run (compounds / instrument families)", scope_flags)
        if source_flags:
            add_group("Where the text came from", source_flags)
        if cited_flags:
            add_group("Data reproduced from other publications", cited_flags)
        if new_var_flags:
            add_group("New variables not added to the CSV", new_var_flags)
        if derived_flags:
            add_group("Calculated by the app (not stated in the paper)", derived_flags)
        if archive_flags:
            add_group("Checked against the NASA Exoplanet Archive", archive_flags)
        if identity_flags:
            add_group("Species identified without being named in the quote", identity_flags)
        if fit_flags:
            add_group("How the values were obtained (fitting models)", fit_flags)
        if analysis_flags:
            add_group("Analysis methods (techniques and instrument settings)", analysis_flags)
        if repeat_flags:
            add_group("Left out as repeats of the solution chemistry", repeat_flags)
        if vote_flags:
            add_group("Passes disagreed (value kept by vote)", vote_flags)
        if auto_fig_flags:
            add_group("Figures digitized automatically (check their points)", auto_fig_flags)
        if other_paper_flags:
            add_group("Whole paper", other_paper_flags)
        for row_id, flags in result.row_flags.items():
            add_group(f"Row {row_id}", flags)
        if not result.paper_flags and not result.row_flags:
            tree.addTopLevelItem(QTreeWidgetItem(["Nothing was flagged."]))
        tree.resizeColumnToContents(2)
        tree.setColumnWidth(1, 320)

    def _show_flag_details(self, item, _previous=None) -> None:
        flag = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if flag is None:
            self.flag_details.clear()
            return
        quote = (f"<p><b>Quote from the paper</b><br><i>\u201c{html.escape(flag.quote)}\u201d</i></p>"
                 if flag.quote else "")
        if flag.table_image_quote:
            quote += (f"<p><b>Read from the table's image</b> (the model's transcription; the table's text "
                      f"layer differs)<br><i>{html.escape(flag.table_image_quote)}</i></p>")
        if flag.unverified_quote:
            quote += (f"<p><b>Model's wording \u2014 not found word for word in the paper's text</b><br>"
                      f"{html.escape(flag.unverified_quote)}<br><span style='color:gray'>The model's own "
                      f"description, not a quote. Check the paper.</span></p>")
        if flag.model_note:
            quote += f"<p><b>Model's note</b><br>{html.escape(flag.model_note)}</p>"
        where = ", ".join(x for x in (flag.source or "", f"page {flag.page}" if flag.page else "") if x)
        source = f"<p><b>Where</b><br>{html.escape(where)}</p>" if where else ""
        self.flag_details.setHtml(f"<p>{html.escape(flag.message)}</p>{quote}{source}")

    @staticmethod
    def _image_html(path: str, max_width: int = 900) -> str:
        """An <img> no wider than max_width (QTextBrowser shows images at full size)."""
        from PySide6.QtGui import QImageReader
        size = QImageReader(path).size()
        width = min(size.width(), max_width) if size.isValid() else max_width
        return f"<img src='{QUrl.fromLocalFile(path).toString()}' width={width}>"

    def _fill_figures(self, result) -> None:
        figures = result.figures
        self.tabs.setTabText(self.tabs.indexOf(self.figures_view), f"Figures ({len(figures)})")
        if not figures:
            self.figures_view.setHtml("<p>No figures were found in this paper.</p>")
            return
        status_text = {"digitized": "digitized", "skipped": "skipped", "not digitized": "not digitized"}
        parts = []
        for f in figures:
            image = f.get("annotated_image") or f.get("image")
            detail = (f" &middot; {f['series']} series, {f['points']} points (clicked points marked)"
                      if f["status"] == "digitized" else "")
            parts.append(
                f"<h3>{html.escape(f['figure_id'])}"
                + (f" <span style='font-weight:normal;color:gray'>(page {f['page']})</span>" if f.get("page") else "")
                + f"</h3><p><b>{status_text.get(f['status'], f['status'])}</b>{detail}</p>"
                + (f"<p>{self._image_html(image)}</p>" if image else
                   f"<p style='color:gray'>({html.escape(f['image_note'])})</p>" if f.get("image_note") else "")
                + (f"<p style='color:gray'>{html.escape(f.get('caption', ''))}</p>" if f.get("caption") else "")
                + "<hr>")
        self.figures_view.setHtml("".join(parts))

    def _fill_tables(self, result) -> None:
        tables = getattr(result, "tables", []) or []
        self.tabs.setTabText(self.tabs.indexOf(self.tables_view), f"Tables ({len(tables)})")
        if not tables:
            self.tables_view.setHtml(
                "<p>No table images. Tables are cropped from the paper's table pages when "
                "&ldquo;Save table and figure images&rdquo; is on (Options); a paper read from arXiv text "
                "has none.</p>")
            return
        parts = ["<p style='color:gray'>Crops of the paper's tables, for checking values and flags "
                 "(&ldquo;Where: Table 2&rdquo; in a cell's hover text). The values themselves were read from "
                 "the full page images.</p>"]
        for t in tables:
            parts.append(f"<h3>{html.escape(t['table_id'])} "
                         f"<span style='font-weight:normal;color:gray'>(page {html.escape(str(t['page_label']))})"
                         f"</span></h3>"
                         + (f"<p>{self._image_html(t['image'])}</p>" if Path(t["image"]).is_file() else "")
                         + (f"<p style='color:gray'>{html.escape(t['caption'])}</p>" if t.get("caption") else "")
                         + "<hr>")
        self.tables_view.setHtml("".join(parts))

    def _fill_equations(self, result) -> None:
        equations = result.equations
        self.tabs.setTabText(self.tabs.indexOf(self.equations_view), f"Equations ({len(equations)})")
        if not equations:
            self.equations_view.setHtml(
                "<p>No labelled equations found. Only equations the authors number or name "
                "(&ldquo;(1)&rdquo;, &ldquo;Eq. 2&rdquo;) are collected; reaction schemes drawn as images "
                "are figures.</p>")
            return
        converted = any(e.latex for e in equations)
        parts = [] if converted else [
            "<p style='color:gray'>Tick &ldquo;Convert labelled equations to LaTeX&rdquo; before a run to "
            "get each one as LaTeX as well (one small API call).</p>"]
        for e in equations:
            parts.append(f"<h3>Equation ({html.escape(e.label)}) "
                         f"<span style='font-weight:normal;color:gray'>page {e.page}</span></h3>"
                         f"<p>{self._image_html(e.image)}</p>")
            if e.latex:
                parts.append(f"<p><b>LaTeX</b> (select to copy):</p><pre>{html.escape(e.latex)}</pre>")
            if e.latex_note:
                parts.append(f"<p style='color:gray'>{html.escape(e.latex_note)}</p>")
            parts.append("<hr>")
        self.equations_view.setHtml("".join(parts))

    def _fill_summary(self, result) -> None:
        usage_rows = "".join(
            f"<tr><td>{STEP_LABELS.get(u.stage) or stage_label(u.stage)}</td>"
            f"<td>{u.model}{' (batch, half price)' if getattr(u, 'batch', False) else ''}</td>"
            f"<td align=right>{u.prompt_tokens:,}</td><td align=right>{u.cache_read_tokens:,}</td>"
            f"<td align=right>{u.output_tokens:,}</td>"
            f"<td align=right>{format_usd(u.cost_usd)}</td><td align=right>{u.elapsed_sec:.0f} s</td></tr>"
            for u in result.usage)
        self.summary_text.setHtml(f"""
            <h3>{result.paper_id}</h3>
            <p><b>{len(result.rows)}</b> rows extracted &middot;
               <b>{len(result.paper_flags)}</b> thing(s) to check &middot;
               <b>{len(result.row_flags)}</b> row(s) marked for checking &middot;
               estimated cost <b>{format_usd(result.cost_usd)}</b></p>
            {self._new_variables_html(result)}
            <p>Results folder: <code>{result.run_dir}</code><br>
               Dataset (CSV): <code>{result.csv_path.name}</code> (one row per sample) &middot;
               <code>{result.observations_path.name if result.observations_path else ""}</code>
               (one value per line, with where each came from)</p>
            {self._figures_html(result)}
            <h4>Cost of each step</h4>
            <p style='color:gray'>Text is measured in tokens (about 3/4 of a word each). "Cached" text was re-read at a
               tenth of the price.</p>
            <table cellspacing=0 cellpadding=4 border=1>
              <tr><th>Step</th><th>Model</th><th>Text read (tokens)</th><th>of which cached</th><th>Text written (tokens)</th>
                  <th>Est. cost (USD)</th><th>Time</th></tr>
              {usage_rows}
              <tr><td colspan=2><b>Total</b></td><td align=right><b>{result.input_tokens:,}</b></td>
                  <td align=right><b>{result.cached_tokens:,}</b></td>
                  <td align=right><b>{result.output_tokens:,}</b></td>
                  <td align=right><b>{format_usd(result.cost_usd)}</b></td><td></td></tr>
            </table>
            <p style="color:gray">Costs are estimates from Anthropic's list prices as of {PRICES_CHECKED}
            (the API reports tokens, not charges); your invoice is the authority. Cached input -- the
            paper, sent once and reused by the later steps -- costs 5-10% of the normal input price.</p>
            <p style="color:gray">Parameter Extractor {__version__}. Every value should be
            checked against the paper; flagged items first.</p>""")

    @staticmethod
    def _new_variables_html(result) -> str:
        parts = []
        cited = [f for f in result.paper_flags if f.kind == "cited_data"]
        if cited:
            n_rows = sum(1 for r in result.rows if r.original_data_reference)
            parts.append(f"<p><b>Note:</b> {n_rows} row(s) in {len(cited)} set(s)/figure(s) are data "
                         f"reproduced from other publications (see <code>original_data_reference</code> "
                         f"and the Things to check tab).</p>")
        if result.accepted_variables:
            items = "".join(f"<li>{html.escape(a['name'])} &rarr; <code>{html.escape(a['column'])}</code> "
                            f"({html.escape(a['how'])})</li>" for a in result.accepted_variables)
            parts.append(f"<h4>Variables beyond the template</h4><ul>{items}</ul>")
        names = sorted({v.name for v in result.new_variables})
        if names:
            parts.append(f"<p>Not added: {html.escape(', '.join(names))} "
                         f"(kept in <code>new_variables.json</code>).</p>")
        if result.unfound_terms:
            parts.append(f"<p>Searched for but not stated in the paper: "
                         f"{html.escape('; '.join(result.unfound_terms))}.</p>")
        return "".join(parts)

    @staticmethod
    def _figures_html(result) -> str:
        if not result.figures:
            return ""
        items = "".join(
            f"<li>{f['figure_id']}: {f['status']}"
            + (f" ({f['series']} series, {f['points']} points)" if f["status"] == "digitized" else "")
            + "</li>" for f in result.figures)
        return f"<h4>Figures</h4><ul>{items}</ul>"

    @staticmethod
    def _open(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---- closing ---------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if not self._busy:
            self._save_preferences()            # keys too: they may have been entered with no run since
            event.accept()
            return
        detail = ("The current step will finish first (this can take up to a minute)."
                  if self._running else "Figures not yet saved will be lost.")
        answer = QMessageBox.question(
            self, "Run in progress",
            f"A paper is still being processed. Stop it and quit without building the dataset?\n\n{detail}")
        if answer == QMessageBox.StandardButton.Yes:
            self._close_when_done = self._quitting = True
            self._cancel_run()
            if self._review is not None and self._review.isVisible():
                self._review.reject()       # -> _maybe_finish(), which closes once all has stopped
        event.ignore()
