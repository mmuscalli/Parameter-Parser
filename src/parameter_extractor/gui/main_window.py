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
    QAbstractItemView, QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
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
from parameter_extractor.pipeline import Extraction, finish, plan_figure

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
               "wet_dry": "Wet-dry cycling", "chemistry": "Solution chemistry",
               "figure_planner": "Figure suggestions", "triage": "Screening"}


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
        self.pubchem_box = QCheckBox("Look up chemical names on PubChem")
        self.pubchem_box.setToolTip("Recognises different names for the same compound (e.g. 2'-CMP and "
                                    "cytidine 2'-monophosphate), so it goes in the same column. Only the "
                                    "species names are sent to PubChem (NIH); results are kept on this "
                                    "computer.")
        form.addRow("", self.pubchem_box)

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
        stored_key = key_store.load_key()
        self._key_was_stored = bool(stored_key)
        if stored_key:
            self.key_edit.setText(stored_key)
            self.remember_key_box.setChecked(True)

    def focus_terms(self) -> list:
        text = self.terms_edit.toPlainText().replace(";", "\n")
        return [t.strip() for t in text.splitlines() if t.strip()]

    def _save_preferences(self) -> None:
        self._settings.setValue("output_dir", self.out_edit.text().strip())
        self._settings.setValue("focus_terms", self.terms_edit.toPlainText())
        self._settings.setValue("use_pubchem", self.pubchem_box.isChecked())
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
                  self.show_key_box, self.terms_edit, self.registry_action):
            w.setEnabled(enabled)
        self._update_run_enabled()

    # ---- results ---------------------------------------------------------------

    def show_result(self, result) -> None:
        self._last_run_dir, self._last_csv = result.run_dir, result.csv_path
        self._fill_rows(result)
        self._fill_flags(result)
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
        if src.source:
            lines.append(f"Where: {src.source}")
        if src.quote and src.quote_verified is False:
            lines.append(f"Model's wording (not found word for word in the paper's text -- its own "
                         f"description, or read from a table image): {src.quote}")
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
                shown = f.quote or (f"(model's wording, not in the paper) {f.unverified_quote}"
                                    if f.unverified_quote else "")
                child = QTreeWidgetItem([f.message, shown, f.source or ""])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                child.setToolTip(0, f.message)
                child.setToolTip(1, shown)
                if not f.quote and f.unverified_quote:
                    child.setForeground(1, QBrush(QColor("gray")))
                group.addChild(child)
            tree.addTopLevelItem(group)
            group.setExpanded(True)

        cited_flags = [f for f in result.paper_flags if f.kind == "cited_data"]
        new_var_flags = [f for f in result.paper_flags if f.kind == "new_variable"]
        derived_flags = [f for f in result.paper_flags if f.kind == "derived_value"]
        repeat_flags = [f for f in result.paper_flags if f.kind == "duplicate_removed"]
        other_paper_flags = [f for f in result.paper_flags
                             if f.kind not in ("new_variable", "cited_data", "derived_value", "duplicate_removed")]
        if cited_flags:
            add_group("Data reproduced from other publications", cited_flags)
        if new_var_flags:
            add_group("New variables not added to the CSV", new_var_flags)
        if derived_flags:
            add_group("Calculated by the app (not stated in the paper)", derived_flags)
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
        if flag.unverified_quote:
            quote += (f"<p><b>Model's wording \u2014 not found word for word in the paper's text</b><br>"
                      f"{html.escape(flag.unverified_quote)}<br><span style='color:gray'>Either the model's own "
                      f"description, or read from a table image whose text layer differs. Check the paper."
                      f"</span></p>")
        if flag.model_note:
            quote += f"<p><b>Model's note</b><br>{html.escape(flag.model_note)}</p>"
        source = f"<p><b>Where</b><br>{html.escape(flag.source)}</p>" if flag.source else ""
        self.flag_details.setHtml(f"<p>{html.escape(flag.message)}</p>{quote}{source}")

    def _fill_summary(self, result) -> None:
        usage_rows = "".join(
            f"<tr><td>{STEP_LABELS.get(u.stage, u.stage)}</td><td>{u.model}</td>"
            f"<td align=right>{u.input_tokens:,}</td><td align=right>{u.output_tokens:,}</td>"
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
              <tr><th>Step</th><th>Model</th><th>Input tokens</th><th>Output tokens</th>
                  <th>Est. cost (USD)</th><th>Time</th></tr>
              {usage_rows}
              <tr><td colspan=2><b>Total</b></td><td align=right><b>{result.input_tokens:,}</b></td>
                  <td align=right><b>{result.output_tokens:,}</b></td>
                  <td align=right><b>{format_usd(result.cost_usd)}</b></td><td></td></tr>
            </table>
            <p style="color:gray">Costs are estimates from Anthropic's list prices as of {PRICES_CHECKED}
            (the API reports tokens, not charges); your invoice is the authority.</p>
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
