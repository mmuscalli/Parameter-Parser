"""
The main window: choose a PDF, enter an API key, run, review the results.

Layout, top to bottom:
  - inputs: paper PDF, API key (optionally remembered in the system
    keychain), output folder, and a notice that the paper is sent to Anthropic
  - Extract / Cancel buttons, progress bar and status line
  - results tabs: Rows (the CSV, flagged rows highlighted), Flags (with the
    supporting quote and source for each), Summary (tokens, files)
"""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Optional

import html

from PySide6.QtCore import QSettings, Qt, QThread, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter,
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
from parameter_extractor.registry import default_pubchem_cache_path, default_registry_path
from parameter_extractor.pipeline import Extraction, finish, plan_figure, stage_label

DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "Parameter Extractor"
FLAGGED_ROW_COLOR = QColor(255, 243, 205)   # soft amber, readable in light and dark themes
MAX_COLUMN_WIDTH = 260
# Rows tab column order: identify the row, then the measured data, then the
# paper-level details that repeat on every row (DOI, title, ...).
LEADING_COLUMNS = ["full_id", "set_type", "duration_hr", "initial_temperature_C",
                   "sampled_temperature_C", "sampled_2peptide_Gly_%yield",
                   "sampled_3peptide_Gly_%yield", "extraction_confidence"]
TRAILING_COLUMNS = ["set_id", "sample_id", "entry_number", "experiment_type", "solution_type",
                    "vessel_material", "solvent_name", "analysis_method", "headspace_gas_name",
                    "paper_DOI", "paper_title", *[f"author{i}" for i in range(1, 8)], "year_published",
                    "journal_published", "source_notes"]
PRIVACY_NOTE = ("The paper's text, and images of its table pages, are sent to Anthropic's API "
                "to extract the data. API usage is billed to the key you enter.")


STEP_LABELS = {"structure_planner": "Experiment structure", "metadata": "Bibliographic metadata",
               "methodology": "Methodology", "term_search": "Parameters to look for",
               "chemistry": "Solution chemistry",
               "figure_planner": "Figure suggestions", "triage": "Screening",
               "equations": "Equations to LaTeX"}


# (RunConfig.model_profile, label, tooltip) -- costs measured 2026-10-22 (CLAUDE.md)
MODEL_PROFILE_CHOICES = [
    ("standard", "Standard (Claude Sonnet 5.5) -- most accurate",
     "<b>Standard</b>: Claude Sonnet 5.5 plans the rows and does every extraction step (only the "
     "bibliographic details from page 1 use Claude Haiku 5.5).<br>Most complete and accurate. "
     "Measured: about $0.40-$0.90 for a typical paper, ~$2 for a 40-page paper with large tables."),
    ("economy", "Economy (Claude Haiku 5.5) -- cheapest",
     "<b>Economy</b>: Claude Haiku 5.5 for every step.<br>Roughly 20x cheaper on typical papers (a few cents), "
     "about 4x on very long ones. On simple papers it matched Standard closely; on complex ones it "
     "missed more -- e.g. a second fit of a planet, values for each mode of a bimodal result, "
     "alternative estimates. Good for screening many papers; check flagged values."),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parameter Extractor")
        self.resize(1100, 760)
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

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_inputs())
        layout.addLayout(self._build_run_controls())
        self.tabs = self._build_results()
        layout.addWidget(self.tabs, stretch=1)
        self.setCentralWidget(central)

        quit_action = QAction("Quit", self, shortcut=QKeySequence.StandardKey.Quit,
                              triggered=self.close)
        self.addAction(quit_action)
        variables_menu = self.menuBar().addMenu("Variables")
        self.registry_action = QAction("Remembered variables…", self, triggered=self.open_registry)
        variables_menu.addAction(self.registry_action)

        self._load_preferences()
        self._update_run_enabled()

    # ---- layout ---------------------------------------------------------------

    def _build_inputs(self) -> QWidget:
        box = QGroupBox("Paper and settings")
        form = QFormLayout(box)

        self.pdf_edit = QLineEdit(placeholderText="Choose a PDF, or drop one onto this window")
        self.pdf_edit.textChanged.connect(self._update_run_enabled)
        pdf_btn = QPushButton("Choose…", clicked=self._choose_pdf)
        form.addRow("Paper (PDF):", self._row(self.pdf_edit, pdf_btn))

        self.key_edit = QLineEdit(placeholderText="sk-ant-…", echoMode=QLineEdit.EchoMode.Password)
        self.key_edit.textChanged.connect(self._update_run_enabled)
        self.show_key_box = QCheckBox("Show")
        self.show_key_box.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.remember_key_box = QCheckBox("Remember on this computer (system keychain)")
        form.addRow("Anthropic API key:", self._row(self.key_edit, self.show_key_box))
        form.addRow("", self.remember_key_box)

        self.out_edit = QLineEdit()
        self.out_edit.textChanged.connect(self._update_run_enabled)
        out_btn = QPushButton("Choose…", clicked=self._choose_output_dir)
        form.addRow("Save results to:", self._row(self.out_edit, out_btn))

        self.terms_edit = QPlainTextEdit()
        self.terms_edit.setPlaceholderText("Optional: parameters you especially want found, one per line "
                                           "(e.g. extraction solvent volume, flowthrough recirculation time)")
        self.terms_edit.setFixedHeight(54)
        self.terms_edit.setToolTip("Each term gets an explicit answer from a targeted search -- its value, "
                                   "or 'not stated in the paper'. One extra API call when used.")
        form.addRow("Parameters to look for:", self.terms_edit)
        from parameter_extractor import packs
        self.pack_combo = QComboBox()
        for pack_id, pack in sorted(packs.available().items(), key=lambda kv: kv[1].label):
            self.pack_combo.addItem(pack.label, pack_id)
            self.pack_combo.setItemData(self.pack_combo.count() - 1, pack.manifest.description,
                                        Qt.ItemDataRole.ToolTipRole)
        self.pack_combo.setToolTip("The research area: which dataset columns, vocabulary, prompts and "
                                   "extraction stages are used (domain packs).")
        self.pack_combo.currentIndexChanged.connect(self._on_pack_changed)
        form.addRow("Research area:", self.pack_combo)
        # the area's switchable extraction stages (stages/optional.toggleable_stages), rebuilt on change
        self.stages_widget = QWidget()
        self.stages_layout = QVBoxLayout(self.stages_widget)
        self.stages_layout.setContentsMargins(0, 0, 0, 0)
        self.stages_layout.setSpacing(2)
        self.stage_boxes: dict = {}
        form.addRow("Extraction stages:", self.stages_widget)
        self.profile_combo = QComboBox()
        for key, label, tip in MODEL_PROFILE_CHOICES:
            self.profile_combo.addItem(label, key)
            self.profile_combo.setItemData(self.profile_combo.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.profile_combo.setToolTip("Which Claude models read the paper:<br><br>"
                                      + "<br><br>".join(tip for _, _, tip in MODEL_PROFILE_CHOICES)
                                      + "<br><br>Figure-digitizing suggestions and LaTeX conversion (when you ask "
                                        "for them) always use Sonnet 5.5.")
        form.addRow("Models:", self.profile_combo)
        self.batch_box = QCheckBox("Batch mode -- half price, slower")
        self.batch_box.setToolTip("Sends every request through Anthropic's Message Batches API at half the price. "
                                  "Each step then waits in Anthropic's batch queue: usually a few minutes, at "
                                  "most 24 hours, so a paper can take much longer. Results are the same. Best for "
                                  "papers you don't need right away.")
        form.addRow("", self.batch_box)
        self._inputs_form = form
        self.pubchem_box = QCheckBox("Use online lookups (PubChem names, NASA Exoplanet Archive check)")
        self.pubchem_box.setToolTip("PubChem: recognises different names for the same compound (e.g. 2'-CMP and "
                                    "cytidine 2'-monophosphate). Exoplanet Archive: compares exoplanet values with "
                                    "the archive's parameter set for the same paper. Only species or planet names "
                                    "are sent; results are kept on this computer.")
        form.addRow("", self.pubchem_box)
        self.equations_box = QCheckBox("Convert labelled equations to LaTeX")
        self.equations_box.setToolTip("Equations the authors number or name ('(1)', 'Eq. 2') are always found and "
                                      "shown in the Equations tab. Ticked, they're also transcribed to LaTeX: "
                                      "one small API call (about 2 cents for a dozen equations).")
        form.addRow("", self.equations_box)

        note = QLabel(PRIVACY_NOTE, wordWrap=True)
        note.setStyleSheet("color: palette(placeholder-text);")
        form.addRow("", note)
        return box

    def _build_run_controls(self) -> QVBoxLayout:
        self.run_btn = QPushButton("Extract data", clicked=self._start_run, default=True)
        self.cancel_btn = QPushButton("Cancel", clicked=self._cancel_run, enabled=False)
        self.progress = QProgressBar(minimum=0, maximum=6, value=0, textVisible=False)
        self.status = QLabel("Choose a paper and enter an API key to begin.")

        buttons = QHBoxLayout()
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.progress, stretch=1)
        col = QVBoxLayout()
        col.addLayout(buttons)
        col.addWidget(self.status)
        return col

    def _build_results(self) -> QTabWidget:
        tabs = QTabWidget()

        self.rows_table = QTableWidget()
        self.rows_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rows_table.setAlternatingRowColors(True)
        tabs.addTab(self.rows_table, "Rows")

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
        tabs.addTab(flags_split, "Flags")

        # captured figures and labelled equations, at a glance (rich text: images + captions)
        self.figures_view = QTextBrowser(placeholderText="Figures found in the paper appear here.")
        self.figures_view.setOpenExternalLinks(False)
        tabs.addTab(self.figures_view, "Figures")
        self.equations_view = QTextBrowser(placeholderText="Equations the authors label, e.g. '(1)' or "
                                                           "'Eq. 2', appear here.")
        self.equations_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        tabs.addTab(self.equations_view, "Equations")

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
        self.terms_edit.setPlainText(self._settings.value("focus_terms", ""))
        self.pubchem_box.setChecked(self._settings.value("use_pubchem", True, type=bool))
        saved_pack = self._settings.value("pack", "prebiotic_chemistry")
        index = self.pack_combo.findData(saved_pack)
        self.pack_combo.setCurrentIndex(index if index >= 0 else self.pack_combo.findData("prebiotic_chemistry"))
        self._rebuild_stage_boxes(self.pack_combo.currentData())     # no change signal if index 0 was kept
        self.equations_box.setChecked(self._settings.value("equations_to_latex", False, type=bool))
        index = self.profile_combo.findData(self._settings.value("model_profile", "standard"))
        self.profile_combo.setCurrentIndex(max(index, 0))
        self.batch_box.setChecked(self._settings.value("batch_mode", False, type=bool))
        stored_key = key_store.load_key()
        self._key_was_stored = bool(stored_key)
        if stored_key:
            self.key_edit.setText(stored_key)
            self.remember_key_box.setChecked(True)

    def _on_pack_changed(self, _index: int) -> None:
        """Windows opened before a run (Remembered variables) show the chosen area's columns."""
        from parameter_extractor import packs
        pack_id = self.pack_combo.currentData()
        if pack_id:
            packs.activate(pack_id)
            self._rebuild_stage_boxes(pack_id)

    def _rebuild_stage_boxes(self, pack_id: str) -> None:
        """One checkbox per switchable stage of the chosen research area; each area remembers
        its own choices (QSettings stages/<pack>/<stage>). Unticked = the stage is skipped."""
        from parameter_extractor import packs
        from parameter_extractor.stages.optional import toggleable_stages
        for box in self.stage_boxes.values():
            self.stages_layout.removeWidget(box)
            box.hide()                     # deleteLater waits for the event loop; don't leave it drawn
            box.setParent(None)
            box.deleteLater()
        self.stage_boxes = {}
        pack = packs.available().get(pack_id)
        toggles = toggleable_stages(pack) if pack else []
        for t in toggles:
            box = QCheckBox(t.label + (" (when the paper calls for it)" if t.conditional else ""))
            box.setToolTip(t.description)
            box.setChecked(self._settings.value(f"stages/{pack_id}/{t.name}", True, type=bool))
            box.toggled.connect(lambda on, key=f"stages/{pack_id}/{t.name}": self._settings.setValue(key, on))
            self.stages_layout.addWidget(box)
            self.stage_boxes[t.name] = box
        self._inputs_form.setRowVisible(self.stages_widget, bool(toggles))

    def optional_stage_choices(self) -> dict:
        """RunConfig.optional_stages: unticked stages are 'off'; ticked ones run as usual."""
        return {name: "auto" if box.isChecked() else "off" for name, box in self.stage_boxes.items()}

    def focus_terms(self) -> list:
        text = self.terms_edit.toPlainText().replace(";", "\n")
        return [t.strip() for t in text.splitlines() if t.strip()]

    def _save_preferences(self) -> None:
        self._settings.setValue("output_dir", self.out_edit.text().strip())
        self._settings.setValue("focus_terms", self.terms_edit.toPlainText())
        self._settings.setValue("use_pubchem", self.pubchem_box.isChecked())
        self._settings.setValue("pack", self.pack_combo.currentData())
        self._settings.setValue("equations_to_latex", self.equations_box.isChecked())
        self._settings.setValue("model_profile", self.profile_combo.currentData())
        self._settings.setValue("batch_mode", self.batch_box.isChecked())
        key = self.key_edit.text().strip()
        if self.remember_key_box.isChecked():
            if not key_store.save_key(key):
                self.status.setText("Note: couldn't save the key to the system keychain.")
            self._key_was_stored = True
        elif self._key_was_stored:  # the user un-ticked "remember": forget it
            key_store.delete_key()
            self._key_was_stored = False

    # ---- input handling -------------------------------------------------------

    def _choose_pdf(self) -> None:
        start = self._settings.value("last_pdf_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Choose a paper", start, "PDF files (*.pdf)")
        if path:
            self._set_pdf(Path(path))

    def _set_pdf(self, path: Path) -> None:
        self.pdf_edit.setText(str(path))
        self._settings.setValue("last_pdf_dir", str(path.parent))

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save results to", self.out_edit.text())
        if path:
            self.out_edit.setText(path)

    def dragEnterEvent(self, event) -> None:
        if self._dropped_pdf(event) and not self._running:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        pdf = self._dropped_pdf(event)
        if pdf:
            self._set_pdf(pdf)

    @staticmethod
    def _dropped_pdf(event) -> Optional[Path]:
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                return Path(url.toLocalFile())
        return None

    @property
    def _running(self) -> bool:
        """The background extraction is running."""
        return self._thread is not None

    @property
    def _busy(self) -> bool:
        """A run is in progress: extracting, and/or the figure review is open."""
        return self._running or self._review is not None

    def _update_run_enabled(self) -> None:
        ready = bool(self.pdf_edit.text().strip() and self.key_edit.text().strip()
                     and self.out_edit.text().strip())
        self.run_btn.setEnabled(ready and not self._busy)

    # ---- running ---------------------------------------------------------------
    #
    # A run has two parts that overlap: the extraction on a worker thread
    # (pipeline.extract) and, if the paper has figures, the figure review,
    # opened as soon as the PDF has been read. The dataset is built
    # (pipeline.finish) when BOTH are done, whichever finishes last.

    def _start_run(self) -> None:
        pdf = Path(self.pdf_edit.text().strip())
        if not pdf.is_file():
            QMessageBox.warning(self, "Paper not found", f"There's no file at:\n{pdf}")
            return
        out_dir = Path(self.out_edit.text().strip()).expanduser()
        self._save_preferences()

        config = RunConfig(api_key=self.key_edit.text().strip(), output_dir=out_dir,
                           registry_path=self.registry_path, focus_terms=self.focus_terms(),
                           use_pubchem=self.pubchem_box.isChecked(),
                           equations_to_latex=self.equations_box.isChecked(),
                           pack=self.pack_combo.currentData() or "prebiotic_chemistry",
                           online_checks=self.pubchem_box.isChecked(),
                           optional_stages=self.optional_stage_choices(),
                           model_profile=self.profile_combo.currentData() or "standard",
                           batch_mode=self.batch_box.isChecked(),
                           pubchem_cache_path=default_pubchem_cache_path())
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
        self.status.setText(f"Starting on {pdf.name}…")
        self._thread.start()

    def _cancel_run(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText("Cancelling — stopping after the current step finishes…")

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
                                          plan_bridge=bridge, parent=self)
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

    def open_registry(self) -> None:
        """View / undo what the variable registry remembered from earlier reviews."""
        from parameter_extractor.gui.registry_dialog import RegistryDialog
        RegistryDialog(self.registry_path, parent=self).exec()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (self.pdf_edit, self.key_edit, self.out_edit, self.remember_key_box,
                  self.show_key_box, self.terms_edit, self.registry_action, self.pack_combo,
                  self.stages_widget, self.pubchem_box, self.equations_box, self.profile_combo,
                  self.batch_box):   # the pack is active during a run
            w.setEnabled(enabled)
        self._update_run_enabled()

    # ---- results ---------------------------------------------------------------

    def show_result(self, result) -> None:
        self._last_run_dir, self._last_csv = result.run_dir, result.csv_path
        self._fill_rows(result)
        self._fill_flags(result)
        self._fill_figures(result)
        self._fill_equations(result)
        self._fill_summary(result)
        self.open_folder_btn.setEnabled(True)
        self.open_csv_btn.setEnabled(True)
        self.tabs.setEnabled(True)
        n_flags = len(result.paper_flags) + sum(len(f) for f in result.row_flags.values())
        self.tabs.setTabText(1, f"Flags ({n_flags})")
        self.tabs.setCurrentIndex(1 if n_flags else 0)

    def _fill_rows(self, result) -> None:
        """Shows the CSV exactly as saved, minus columns that are empty in every row."""
        with open(result.csv_path, newline="") as f:
            reader = list(csv.reader(f))
        header, body = reader[0], reader[1:]
        non_empty = [h for i, h in enumerate(header) if any(r[i] for r in body)]
        lead = [h for h in LEADING_COLUMNS if h in non_empty]
        trail = [h for h in TRAILING_COLUMNS if h in non_empty]
        middle = [h for h in non_empty if h not in lead and h not in trail]  # species columns
        keep = [header.index(h) for h in lead + middle + trail]
        t = self.rows_table
        t.clear()
        t.setColumnCount(len(keep))
        t.setRowCount(len(body))
        t.setHorizontalHeaderLabels([header[i] for i in keep])
        id_col = header.index("full_id")
        provenance = {r.full_id: r.provenance for r in result.rows}
        for r, row in enumerate(body):
            flags = result.row_flags.get(row[id_col], [])
            prov = provenance.get(row[id_col], {})
            for c, i in enumerate(keep):
                item = QTableWidgetItem(row[i])
                tip = self._provenance_tip(prov.get(header[i])) if row[i] else ""
                if flags:
                    item.setBackground(QBrush(FLAGGED_ROW_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                    tip = "\n".join(f.message for f in flags) + ("\n\n" + tip if tip else "")
                if tip:
                    item.setToolTip(tip)
                t.setItem(r, c, item)
        t.resizeColumnsToContents()
        for c in range(t.columnCount()):
            t.setColumnWidth(c, min(t.columnWidth(c), MAX_COLUMN_WIDTH))

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
        other_paper_flags = [f for f in result.paper_flags
                             if f.kind not in ("new_variable", "cited_data", "derived_value", "duplicate_removed",
                                               "archive_check", "archive_match", "fit_model",
                                               "multimodal", "other_estimates")]
        if cited_flags:
            add_group("Data reproduced from other publications", cited_flags)
        if new_var_flags:
            add_group("New variables not added to the CSV", new_var_flags)
        if derived_flags:
            add_group("Calculated by the app (not stated in the paper)", derived_flags)
        if archive_flags:
            add_group("Checked against the NASA Exoplanet Archive", archive_flags)
        if fit_flags:
            add_group("How the values were obtained (fitting models)", fit_flags)
        if repeat_flags:
            add_group("Left out as repeats of the solution chemistry", repeat_flags)
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
                + (f"<p>{self._image_html(image)}</p>" if image else "")
                + (f"<p style='color:gray'>{html.escape(f.get('caption', ''))}</p>" if f.get("caption") else "")
                + "<hr>")
        self.figures_view.setHtml("".join(parts))

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
               <b>{len(result.paper_flags)}</b> paper-level flag(s) &middot;
               <b>{len(result.row_flags)}</b> row(s) flagged &middot;
               estimated cost <b>{format_usd(result.cost_usd)}</b></p>
            {self._new_variables_html(result)}
            <p>Results folder: <code>{result.run_dir}</code><br>
               CSV: <code>{result.csv_path.name}</code> (template layout) &middot;
               <code>{result.observations_path.name if result.observations_path else ""}</code>
               (one value per line, with where each came from)</p>
            {self._figures_html(result)}
            <h4>API usage</h4>
            <table cellspacing=0 cellpadding=4 border=1>
              <tr><th>Step</th><th>Model</th><th>Input tokens</th><th>of which cached</th><th>Output tokens</th>
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
                         f"and the Flags tab).</p>")
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
            self._settings.setValue("output_dir", self.out_edit.text().strip())
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
