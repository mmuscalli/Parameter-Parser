"""
Focused search window (File -> Focused search across papers…): choose papers (PDFs, and/or arXiv
IDs / DOIs / ADS bibcodes typed or loaded from a CSV list), tick a few parameters of the research
area, optionally give search words (e.g. EXOFAST), and search them all (focused_search.py).

It uses the main window's research area, run options (models, batch, arXiv text, stages) and
Settings (API key, ADS token, output folder) -- one place for each choice. Runs on a background
thread like a full run; results: a table here, and focused_results.csv / papers.csv on disk.
"""
from __future__ import annotations
import threading
import traceback
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor.errors import PipelineError, RunCancelledError
from parameter_extractor.pricing import format_usd

STATUS_TEXT = {"found": "Found", "not found": "Not reported", "not mentioned": "Not mentioned (no API call)",
               "error": "Couldn't search"}


class FocusedWorker(QObject):
    progress = Signal(int, int, str)
    succeeded = Signal(object)          # focused_search.FocusedRun
    failed = Signal(str)
    cancelled = Signal()
    done = Signal()

    def __init__(self, items, columns, config, search_words, whole_paper, whole_tables=True, plan_rows=None):
        super().__init__()
        self.args = (items, columns, config, search_words, whole_paper, whole_tables, plan_rows)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        from parameter_extractor.focused_search import run_focused_search
        from parameter_extractor.gui.error_log import record
        items, columns, config, words, whole, tables, plan = self.args
        try:
            run = run_focused_search(items, columns, config, search_words=words, whole_paper=whole, whole_tables=tables,
                                     plan_rows=plan,
                                     on_progress=self.progress.emit, cancel_event=self._cancel)
        except RunCancelledError:
            self.cancelled.emit()
        except PipelineError as e:
            self.failed.emit(str(e))
        except Exception as e:
            path = record(traceback.format_exc(), None)
            self.failed.emit(f"Unexpected error ({type(e).__name__}): {e}\n\nDetails saved to:\n{path}")
        else:
            self.succeeded.emit(run)
        finally:
            self.done.emit()


class FocusedSearchWindow(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Focused search across papers")
        self.resize(1000, 720)
        self._settings = QSettings()
        self._thread: Optional[QThread] = None
        self._worker: Optional[FocusedWorker] = None
        self._run = None
        self._pack_shown = None

        layout = QVBoxLayout(self)
        intro = QLabel("Search many papers for a few parameters only. Papers whose text never mentions the "
                       "search words are skipped without an API call; the rest get one small call each with "
                       "only the passages around the matches (or the whole paper, if ticked). Uses the main "
                       "window's research area, run options and Settings.", wordWrap=True)
        intro.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(intro)

        top = QSplitter(Qt.Orientation.Horizontal)
        # papers
        from parameter_extractor.gui.paper_list import PaperListPanel
        self.paper_panel = PaperListPanel("Papers")
        self.paper_panel.changed.connect(self._update_ready)
        self.paper_panel.message.connect(lambda m: self.status.setText(m))
        self.papers_list, self.id_edit = self.paper_panel.list, self.paper_panel.id_edit
        papers_box = self.paper_panel
        top.addWidget(papers_box)
        # parameters
        params_box = QGroupBox("Parameters")
        ql = QVBoxLayout(params_box)
        self.filter_edit = QLineEdit(placeholderText="Filter parameters…")
        self.filter_edit.textChanged.connect(self._filter_parameters)
        ql.addWidget(self.filter_edit)
        self.params_tree = QTreeWidget()
        self.params_tree.setHeaderLabels(["Parameter", "Description"])
        self.params_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.params_tree.itemChanged.connect(self._update_ready)
        ql.addWidget(self.params_tree)
        self.area_label = QLabel()
        self.area_label.setStyleSheet("color: palette(placeholder-text);")
        ql.addWidget(self.area_label)
        top.addWidget(params_box)
        top.setSizes([380, 620])
        layout.addWidget(top, stretch=2)

        form = QFormLayout()
        self.words_edit = QLineEdit(placeholderText="Optional, comma-separated, e.g. EXOFAST -- default: words from "
                                                    "the parameters' descriptions")
        self.words_edit.setToolTip("A paper is searched only if its text contains one of these words (case "
                                   "doesn't matter); the passages around them are what the model reads.")
        form.addRow("Search words:", self.words_edit)
        self.tables_box = QCheckBox("Keep whole tables -- a match in or just above a table sends the whole table")
        self.tables_box.setToolTip("Table rows rarely contain the search words (a planet table's rows are names "
                                   "and numbers), so without this most of a table is left out. Measured: about "
                                   "10-45% more tokens than the matching lines alone (~$0.003 a paper on Economy).")
        form.addRow("", self.tables_box)
        self.plan_box = QCheckBox("Rows as in a full extraction -- plan each paper's rows first (more tokens)")
        self.plan_box.setToolTip("Runs the research area's row planner on each paper (the whole paper and images of "
                                 "its tables), then asks for the parameters on those rows: one row per sample, as a "
                                 "full extraction makes them. Roughly doubles the cost of a search. Unticked, the "
                                 "answer names its rows itself (fine for planets; experiment sets can end up as "
                                 "single rows).")
        form.addRow("", self.plan_box)
        self.whole_box = QCheckBox("Whole paper -- send each paper in full (finds more, costs more)")
        self.whole_box.toggled.connect(lambda on: self.tables_box.setEnabled(not on))
        form.addRow("", self.whole_box)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("Search papers", clicked=self._start, default=True)
        self.cancel_btn = QPushButton("Cancel", clicked=self._cancel, enabled=False)
        self.progress = QProgressBar(textVisible=False)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.cancel_btn)
        controls.addWidget(self.progress, stretch=1)
        layout.addLayout(controls)
        self.status = QLabel("Add papers and tick at least one parameter.", wordWrap=True)
        layout.addWidget(self.status)

        # one row per paper (and object), a column per parameter -- as in focused_results.csv
        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Paper", "Object", "Result", "Read from"])
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.results, stretch=2)
        buttons = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open results folder", enabled=False,
                                           clicked=lambda: self._open(self._run.out_dir))
        self.open_csv_btn = QPushButton("Open values CSV", enabled=False,
                                        clicked=lambda: self._open(self._run.results_csv))
        self.retry_btn = QPushButton("Retry failed papers", enabled=False, clicked=self._retry_failed)
        self.retry_btn.setToolTip("Search again only the papers whose result was 'Couldn't search' (e.g. arXiv was "
                                  "busy), with the same parameters. Papers already read come from the cache.")
        buttons.addWidget(self.open_folder_btn)
        buttons.addWidget(self.open_csv_btn)
        buttons.addWidget(self.retry_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.words_edit.setText(self._settings.value("focused/search_words", ""))
        self.whole_box.setChecked(self._settings.value("focused/whole_paper", False, type=bool))
        self.tables_box.setChecked(self._settings.value("focused/whole_tables", True, type=bool))
        self._load_plan_box()

    def _load_plan_box(self) -> None:
        """Per research area, defaulting to the pack's setting (on for prebiotic chemistry)."""
        from parameter_extractor import packs
        pack_id = self.main.pack_combo.currentData() or "prebiotic_chemistry"
        pack = packs.available().get(pack_id)
        default = bool(pack and pack.manifest.focused_row_plan)
        self.plan_box.setChecked(self._settings.value(f"focused/{pack_id}/plan_rows", default, type=bool))

    # ---- parameters -------------------------------------------------------------------------------
    def showEvent(self, event) -> None:
        self._refresh_parameters()
        self._load_plan_box()                  # the research area may have changed
        super().showEvent(event)

    def _refresh_parameters(self) -> None:
        """The research area's parameters (stages switched off in the main window are left out),
        grouped by stage; ticks are remembered per research area."""
        from parameter_extractor import packs
        from parameter_extractor.focused_search import available_parameters
        pack_id = self.main.pack_combo.currentData() or "prebiotic_chemistry"
        pack = packs.available().get(pack_id)
        chosen = set(self._settings.value(f"focused/{pack_id}/columns", []) or [])
        if self._pack_shown == pack_id and self.params_tree.topLevelItemCount():
            chosen |= set(self.checked_columns())
        self._pack_shown = pack_id
        self.params_tree.blockSignals(True)
        self.params_tree.clear()
        groups = {}
        for p in available_parameters(pack, self.main.optional_stage_choices()):
            group = groups.get(p.group)
            if group is None:
                group = groups[p.group] = QTreeWidgetItem([p.group])
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.params_tree.addTopLevelItem(group)
            item = QTreeWidgetItem([p.column, p.description + (f" [{p.unit}]" if p.unit else "")])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if p.column in chosen else Qt.CheckState.Unchecked)
            item.setToolTip(1, p.description)
            item.setData(0, Qt.ItemDataRole.UserRole, p.column)
            group.addChild(item)
        for group in groups.values():
            group.setExpanded(any(group.child(i).checkState(0) == Qt.CheckState.Checked
                                  for i in range(group.childCount())) or len(groups) == 1)
        self.params_tree.resizeColumnToContents(0)
        self.params_tree.blockSignals(False)
        self.area_label.setText(f"Research area: {pack.label if pack else pack_id} (change it in the main window)")
        self._filter_parameters(self.filter_edit.text())
        self._update_ready()

    def _filter_parameters(self, text: str) -> None:
        t = text.strip().lower()
        for i in range(self.params_tree.topLevelItemCount()):
            group = self.params_tree.topLevelItem(i)
            visible = 0
            for j in range(group.childCount()):
                child = group.child(j)
                hide = bool(t) and t not in child.text(0).lower() and t not in child.text(1).lower()
                child.setHidden(hide)
                visible += not hide
            group.setHidden(visible == 0)
            if t and visible:
                group.setExpanded(True)

    def checked_columns(self) -> List[str]:
        out = []
        for i in range(self.params_tree.topLevelItemCount()):
            group = self.params_tree.topLevelItem(i)
            for j in range(group.childCount()):
                if group.child(j).checkState(0) == Qt.CheckState.Checked:
                    out.append(group.child(j).data(0, Qt.ItemDataRole.UserRole))
        return out

    # ---- papers (gui/paper_list.PaperListPanel) ------------------------------------------------------
    def items(self) -> list:
        return self.paper_panel.items()

    def add_items(self, items) -> int:
        return self.paper_panel.add_items(items)

    def _add_typed(self) -> None:
        self.paper_panel.add_typed()

    # ---- running ----------------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None

    def _update_ready(self, *_args) -> None:
        main_ready = bool(self.main.key_edit.text().strip() and self.main.out_edit.text().strip())
        ready = self.papers_list.count() > 0 and bool(self.checked_columns()) and main_ready
        self.run_btn.setEnabled(ready and not self.running)
        if not self.running and not main_ready:
            self.status.setText("Add your Anthropic API key and a results folder in Settings first.")

    def _start(self) -> None:
        columns, items = self.checked_columns(), self.items()
        missing = [str(i) for i in items if isinstance(i, Path) and not i.is_file()]
        if missing:
            QMessageBox.warning(self, "Papers not found", "No PDF at:\n" + "\n".join(missing[:10]))
            return
        pack_id = self.main.pack_combo.currentData() or "prebiotic_chemistry"
        self._settings.setValue(f"focused/{pack_id}/columns", columns)
        self._settings.setValue("focused/search_words", self.words_edit.text())
        self._settings.setValue("focused/whole_paper", self.whole_box.isChecked())
        self._settings.setValue("focused/whole_tables", self.tables_box.isChecked())
        self._settings.setValue(f"focused/{pack_id}/plan_rows", self.plan_box.isChecked())
        words = [w.strip() for w in self.words_edit.text().split(",") if w.strip()]
        self.main._save_preferences()
        config = self.main.current_config()
        self._worker = FocusedWorker(items, columns, config, words, self.whole_box.isChecked(),
                                     self.tables_box.isChecked(), self.plan_box.isChecked())
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(lambda m: (self.status.setText("Search failed."),
                                               QMessageBox.critical(self, "Search failed", m)))
        self._worker.cancelled.connect(lambda: self.status.setText("Cancelled."))
        self._worker.done.connect(self._on_done)
        self.results.setRowCount(0)
        self.retry_btn.setEnabled(False)
        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.run_btn.setEnabled(False)
        self.main._set_inputs_enabled(False)   # its settings are in use; no full run meanwhile
        self.status.setText(f"Searching {len(items)} paper(s) for {', '.join(columns)}…")
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText("Cancelling -- papers already being read finish first…")

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status.setText(f"{done} of {total}: {message}")

    def _on_succeeded(self, run) -> None:
        from parameter_extractor.focused_search import cell_text, result_columns, value_tip, wide_rows
        self._run = run
        columns = result_columns(run.params, run.outcomes)
        rows = wide_rows(run.outcomes)
        from parameter_extractor import packs
        units = packs.current().manifest.units          # the searched pack's set / row words
        headers = ["Paper", units.get("set", "set").capitalize(), units.get("sample", "sample").capitalize(),
                   "Result"] + [
            name + (f" [{p.unit}]" if part == "value" and p.unit else "") for name, p, part in columns] + ["Read from"]
        self.results.clear()
        self.results.setColumnCount(len(headers))
        self.results.setHorizontalHeaderLabels(headers)
        for c, (name, p, part) in enumerate(columns, start=4):
            self.results.horizontalHeaderItem(c).setToolTip(p.description)
        self.results.setRowCount(len(rows))
        for r, row in enumerate(rows):
            o = row.outcome
            result = STATUS_TEXT.get(o.status, o.status)
            fixed = [(o.reference or o.title or o.paper, "\n".join(x for x in (o.reference, o.item, o.title) if x)),
                     (row.set, row.set), (row.obj, row.obj), (result, o.message or result)]
            for c, (text, tip) in enumerate(fixed):
                item = QTableWidgetItem(str(text))
                item.setToolTip(tip)
                self.results.setItem(r, c, item)
            for c, (name, p, part) in enumerate(columns, start=4):
                values = row.cells.get(p.column, [])
                item = QTableWidgetItem(cell_text(values, p, part))
                if values:
                    item.setToolTip(value_tip(values))
                self.results.setItem(r, c, item)
            item = QTableWidgetItem(o.read_from)
            item.setToolTip(o.read_from)
            self.results.setItem(r, len(headers) - 1, item)
        self.results.resizeColumnsToContents()
        for c in range(self.results.columnCount()):
            self.results.setColumnWidth(c, min(self.results.columnWidth(c), 260))
        counts = {}
        for o in run.outcomes:
            counts[STATUS_TEXT.get(o.status, o.status)] = counts.get(STATUS_TEXT.get(o.status, o.status), 0) + 1
        self.status.setText(f"Done: {', '.join(f'{n} {s.lower()}' for s, n in counts.items())}. Estimated cost "
                            f"{format_usd(run.cost_usd)}. Saved to {run.out_dir}")
        self.open_folder_btn.setEnabled(True)
        self.open_csv_btn.setEnabled(True)
        failed = [o for o in run.outcomes if o.status == "error"]
        self.retry_btn.setText(f"Retry failed papers ({len(failed)})" if failed else "Retry failed papers")
        self.retry_btn.setEnabled(bool(failed))

    def _on_done(self) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread, self._worker = None, None
        self.cancel_btn.setEnabled(False)
        self.main._set_inputs_enabled(True)
        self._update_ready()

    def _retry_failed(self) -> None:
        """The paper list becomes the papers that failed (labels kept), and the search runs again."""
        from parameter_extractor.ingestion.arxiv_source import PaperRef
        failed = [o for o in self._run.outcomes if o.status == "error"] if self._run else []
        if not failed:
            return
        self.papers_list.clear()
        self.add_items([Path(o.item) if o.item.lower().endswith(".pdf") else PaperRef(o.item, o.reference)
                        for o in failed])
        self._start()

    @staticmethod
    def _open(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event) -> None:
        if self.running:
            self.hide()                         # keeps searching; reopen from the File menu
            event.ignore()
            return
        super().closeEvent(event)
