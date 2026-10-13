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
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from parameter_extractor import __version__
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.gui import key_store
from parameter_extractor.gui.worker import PipelineWorker

DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "Parameter Extractor"
FLAGGED_ROW_COLOR = QColor(255, 243, 205)   # soft amber, readable in light and dark themes
MAX_COLUMN_WIDTH = 260
# Rows tab column order: identify the row, then the measured data, then the
# paper-level details that repeat on every row (DOI, title, ...).
LEADING_COLUMNS = ["full_id", "set_type", "duration_hr", "initial_temperature_C",
                   "sampled_temperature_C", "sampled_2peptide_Gly_pct_yield",
                   "sampled_3peptide_Gly_pct_yield", "extraction_confidence"]
TRAILING_COLUMNS = ["set_id", "sample_id", "entry_number", "experiment_type", "solution_type",
                    "vessel_material", "solvent_name", "analysis_method", "headspace_gas",
                    "paper_doi", "paper_title", "authors", "year_published",
                    "journal_published", "source_notes"]
PRIVACY_NOTE = ("The paper's text, and images of its table pages, are sent to Anthropic's API "
                "to extract the data. API usage is billed to the key you enter.")


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
        self._key_was_stored = False

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
        stored_key = key_store.load_key()
        self._key_was_stored = bool(stored_key)
        if stored_key:
            self.key_edit.setText(stored_key)
            self.remember_key_box.setChecked(True)

    def _save_preferences(self) -> None:
        self._settings.setValue("output_dir", self.out_edit.text().strip())
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
        return self._thread is not None

    def _update_run_enabled(self) -> None:
        ready = bool(self.pdf_edit.text().strip() and self.key_edit.text().strip()
                     and self.out_edit.text().strip())
        self.run_btn.setEnabled(ready and not self._running)

    # ---- running ---------------------------------------------------------------

    def _start_run(self) -> None:
        pdf = Path(self.pdf_edit.text().strip())
        if not pdf.is_file():
            QMessageBox.warning(self, "Paper not found", f"There's no file at:\n{pdf}")
            return
        out_dir = Path(self.out_edit.text().strip()).expanduser()
        self._save_preferences()

        config = RunConfig(api_key=self.key_edit.text().strip(), output_dir=out_dir)
        self._worker = PipelineWorker(pdf, config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
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

    def _on_succeeded(self, result) -> None:
        self.progress.setValue(self.progress.maximum())
        n_flags = len(result.paper_flags) + sum(len(f) for f in result.row_flags.values())
        self.status.setText(f"Done: {len(result.rows)} rows extracted, {n_flags} item(s) "
                            f"flagged for review. Saved to {result.run_dir}")
        self.show_result(result)

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
        self._set_inputs_enabled(True)
        if self._close_when_done:
            self.close()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (self.pdf_edit, self.key_edit, self.out_edit, self.remember_key_box,
                  self.show_key_box):
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
        for r, row in enumerate(body):
            flags = result.row_flags.get(row[id_col], [])
            for c, i in enumerate(keep):
                item = QTableWidgetItem(row[i])
                if flags:
                    item.setBackground(QBrush(FLAGGED_ROW_COLOR))
                    item.setForeground(QBrush(Qt.GlobalColor.black))
                    item.setToolTip("\n".join(f.message for f in flags))
                t.setItem(r, c, item)
        t.resizeColumnsToContents()
        for c in range(t.columnCount()):
            t.setColumnWidth(c, min(t.columnWidth(c), MAX_COLUMN_WIDTH))

    def _fill_flags(self, result) -> None:
        tree = self.flags_tree
        tree.clear()
        self.flag_details.clear()

        def add_group(title, flags):
            group = QTreeWidgetItem([f"{title} ({len(flags)})"])
            for f in flags:
                child = QTreeWidgetItem([f.message, f.quote or "", f.source or ""])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                child.setToolTip(0, f.message)
                child.setToolTip(1, f.quote or "")
                group.addChild(child)
            tree.addTopLevelItem(group)
            group.setExpanded(True)

        if result.paper_flags:
            add_group("Whole paper", result.paper_flags)
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
        source = f"<p><b>Where</b><br>{html.escape(flag.source)}</p>" if flag.source else ""
        self.flag_details.setHtml(f"<p>{html.escape(flag.message)}</p>{quote}{source}")

    def _fill_summary(self, result) -> None:
        usage_rows = "".join(
            f"<tr><td>{u.stage}</td><td>{u.model}</td><td align=right>{u.input_tokens:,}</td>"
            f"<td align=right>{u.output_tokens:,}</td><td align=right>{u.elapsed_sec:.0f} s</td></tr>"
            for u in result.usage)
        self.summary_text.setHtml(f"""
            <h3>{result.paper_id}</h3>
            <p><b>{len(result.rows)}</b> rows extracted &middot;
               <b>{len(result.paper_flags)}</b> paper-level flag(s) &middot;
               <b>{len(result.row_flags)}</b> row(s) flagged</p>
            <p>Results folder: <code>{result.run_dir}</code><br>
               CSV: <code>{result.csv_path.name}</code></p>
            <h4>API usage</h4>
            <table cellspacing=0 cellpadding=4 border=1>
              <tr><th>Step</th><th>Model</th><th>Input tokens</th><th>Output tokens</th><th>Time</th></tr>
              {usage_rows}
              <tr><td colspan=2><b>Total</b></td><td align=right><b>{result.input_tokens:,}</b></td>
                  <td align=right><b>{result.output_tokens:,}</b></td><td></td></tr>
            </table>
            <p style="color:gray">Parameter Extractor {__version__}. Every value should be
            checked against the paper; flagged items first.</p>""")

    @staticmethod
    def _open(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---- closing ---------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if not self._running:
            self._settings.setValue("output_dir", self.out_edit.text().strip())
            event.accept()
            return
        answer = QMessageBox.question(
            self, "Extraction in progress",
            "A paper is still being processed. Stop it and quit?\n\n"
            "The current step will finish first (this can take up to a minute).")
        if answer == QMessageBox.StandardButton.Yes:
            self._close_when_done = True
            self._cancel_run()
        event.ignore()
