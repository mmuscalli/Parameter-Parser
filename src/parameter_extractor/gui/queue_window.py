"""
Paper queue window (File -> Paper queue (full extraction)…): the whole parser over many papers
(paper_queue.py), with the person's part front-loaded and at the end only:

- start: every paper is read in the background, one after another, and its extraction steps run as
  soon as it's read (a few papers at a time);
- figure review FIRST: as each paper is read, its figures open in the usual figure review (choose,
  then digitize), paper after paper, while the extraction continues behind it; "Skip figures of the
  remaining papers" ends the reviewing;
- then nothing is needed until every paper is extracted and reviewed: the papers are assembled one by
  one -- with the new-variable review per paper (remembered choices carry over to the next), or
  without it (new variables stay out of the CSV, in each paper's new_variables.json);
- a combined CSV of every paper's rows, plus each paper's own run folder, inside the queue's folder.

It uses the main window's research area, run options and Settings, like the focused search.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

STATUS_TEXT = {"waiting": "Waiting", "reading": "Reading", "extracting": "Extracting",
               "extracted": "Extracted", "finished": "Done", "failed": "Failed", "cancelled": "Cancelled"}
COLUMNS = ["Paper", "Status", "Figures", "Progress", "Rows", "Folder"]


class _Relay(QObject):
    """Queue events come from worker threads; this hands them to the window's thread."""
    changed = Signal(object)


class QueueWindow(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Paper queue -- full extraction")
        self.resize(1100, 760)
        self._settings = QSettings()
        self.queue = None
        self._review = None                      # the figure review open now
        self._review_paper = None
        self._skip_remaining_figures = False
        self._finishing = False
        self._summary: Optional[dict] = None
        self._relay = _Relay()
        self._relay.changed.connect(self._paper_changed)
        self._timer = QTimer(self, interval=700, timeout=self._tick)

        layout = QVBoxLayout(self)
        intro = QLabel("Run the full parser over many papers. Each paper is read first, so you can review and "
                       "digitize its figures right away while the extraction carries on in the background; "
                       "after that, nothing is needed until the end, when the papers are assembled (with the "
                       "new-variable review, if ticked). Uses the main window's research area, run options and "
                       "Settings.", wordWrap=True)
        intro.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(intro)
        from parameter_extractor.gui.paper_list import PaperListPanel
        split = QSplitter(Qt.Orientation.Vertical)
        self.paper_panel = PaperListPanel("Papers")
        self.paper_panel.changed.connect(self._update_ready)
        self.paper_panel.message.connect(lambda m: self.status.setText(m))
        split.addWidget(self.paper_panel)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        split.addWidget(self.table)
        split.setSizes([260, 380])
        layout.addWidget(split, stretch=1)

        self.figures_box = QCheckBox("Review figures as the papers are read (digitize the ones you want)")
        self.variables_box = QCheckBox("Review new variables at the end (otherwise they stay out of the CSV)")
        for box, key in ((self.figures_box, "queue/review_figures"), (self.variables_box, "queue/review_variables")):
            box.setChecked(self._settings.value(key, True, type=bool))
            layout.addWidget(box)
        controls = QHBoxLayout()
        self.run_btn = QPushButton("Start queue", clicked=self._start, default=True)
        self.cancel_btn = QPushButton("Cancel", clicked=self._cancel, enabled=False)
        self.skip_figures_btn = QPushButton("Skip figures of the remaining papers", enabled=False,
                                            clicked=self._skip_figures)
        self.progress = QProgressBar(textVisible=True)
        for w in (self.run_btn, self.cancel_btn, self.skip_figures_btn):
            controls.addWidget(w)
        controls.addWidget(self.progress, stretch=1)
        layout.addLayout(controls)
        self.status = QLabel("Add papers to begin.", wordWrap=True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open queue folder", enabled=False,
                                           clicked=lambda: self._open(self.queue.out_dir))
        self.open_csv_btn = QPushButton("Open combined CSV", enabled=False,
                                        clicked=lambda: self._open(self._summary["csv"]))
        buttons.addWidget(self.open_folder_btn)
        buttons.addWidget(self.open_csv_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # ---- state ----------------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.queue is not None and not self._summary

    def _update_ready(self, *_args) -> None:
        main_ready = bool(self.main.key_edit.text().strip() and self.main.out_edit.text().strip())
        self.run_btn.setEnabled(self.paper_panel.count() > 0 and main_ready and not self.running)
        if not self.running and not main_ready:
            self.status.setText("Add your Anthropic API key and a results folder in Settings first.")

    def _row_of(self, paper) -> int:
        return self.queue.papers.index(paper)

    def _paper_changed(self, paper) -> None:
        if self.queue is None or paper not in self.queue.papers:
            return
        r = self._row_of(paper)
        figures = paper.figures
        fig_text = ("—" if paper.extraction is not None and not figures else
                    f"{len(paper.digitized)} digitized / {len(figures)}" if paper.figures_reviewed and figures else
                    f"{len(figures)} to review" if figures else "")
        rows = len(paper.result.rows) if paper.result is not None else ""
        folder = (str(paper.result.run_dir) if paper.result is not None else
                  str(paper.extraction.ctx.run_dir) if paper.extraction is not None else "")
        progress = paper.error or paper.step
        for c, text in enumerate([paper.label, STATUS_TEXT.get(paper.status, paper.status), fig_text, progress,
                                  str(rows), folder]):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            self.table.setItem(r, c, item)
        done = sum(p.status in ("finished", "failed", "cancelled") or p.status == "extracted"
                   for p in self.queue.papers)
        self.progress.setValue(done)

    # ---- running --------------------------------------------------------------------------------
    def _start(self) -> None:
        from parameter_extractor.paper_queue import PaperQueue
        items = self.paper_panel.items()
        missing = [str(i) for i in items if isinstance(i, Path) and not i.is_file()]
        if missing:
            QMessageBox.warning(self, "Papers not found", "No PDF at:\n" + "\n".join(missing[:10]))
            return
        self._settings.setValue("queue/review_figures", self.figures_box.isChecked())
        self._settings.setValue("queue/review_variables", self.variables_box.isChecked())
        self.main._save_preferences()
        self._summary, self._finishing = None, False
        self._skip_remaining_figures = not self.figures_box.isChecked()
        self.queue = PaperQueue(items, self.main.current_config(), on_change=self._relay.changed.emit)
        self.table.setRowCount(len(self.queue.papers))
        for paper in self.queue.papers:
            self._paper_changed(paper)
        self.progress.setRange(0, len(self.queue.papers))
        self.progress.setValue(0)
        self.paper_panel.set_locked(True)
        for w in (self.figures_box, self.variables_box, self.run_btn, self.open_folder_btn, self.open_csv_btn):
            w.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.skip_figures_btn.setEnabled(not self._skip_remaining_figures)
        self.main._set_inputs_enabled(False)          # its settings are in use
        self.status.setText(f"Reading {len(self.queue.papers)} paper(s)…")
        self.queue.start()
        self._timer.start()

    def _cancel(self) -> None:
        if self.queue is not None:
            self.queue.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText("Cancelling -- steps already running finish first…")

    def _skip_figures(self) -> None:
        self._skip_remaining_figures = True
        self.skip_figures_btn.setEnabled(False)

    def _next_to_review(self):
        for paper in self.queue.papers:
            if paper.extraction is not None and paper.figures and not paper.figures_reviewed \
                    and paper.status not in ("failed", "cancelled"):
                return paper
            if paper.extraction is None and paper.status in ("waiting", "reading"):
                return None          # keep the list's order: wait until this paper has been read
        return None

    def _tick(self) -> None:
        """Every 0.7 s: open the next figure review, or -- when everything is extracted and reviewed --
        assemble the papers."""
        if self.queue is None or self._finishing:
            return
        if self._review is None:
            if self._skip_remaining_figures:
                for paper in self.queue.papers:
                    if paper.extraction is not None and not paper.figures_reviewed:
                        paper.skipped = [f.figure_id for f in paper.figures]
                        paper.figures_reviewed = True
                        self._paper_changed(paper)
            paper = self._next_to_review()
            if paper is not None:
                self._open_review(paper)
                return
        waiting = [p for p in self.queue.papers if not p.extracted.is_set()]
        if self._review is None and self.queue.all_extracted and not waiting:
            if any(p.extraction is not None and p.figures and not p.figures_reviewed
                   and p.status not in ("failed", "cancelled") for p in self.queue.papers):
                return
            self._finish_all()
        elif self._review is None:
            n = len(waiting)
            self.status.setText(f"Figures reviewed so far -- {n} paper(s) still being read or extracted…")

    def _open_review(self, paper) -> None:
        from parameter_extractor.gui.figure_dialog import FigureReviewDialog, PlanBridge
        from parameter_extractor.pipeline import plan_figure
        extraction = paper.extraction
        bridge = PlanBridge(lambda fig, ex=extraction: plan_figure(ex, fig), parent=self)
        self._review, self._review_paper = FigureReviewDialog(extraction.figures, extraction.vocab["all_columns"],
                                                              plan_bridge=bridge, parent=self), paper
        self._review.setWindowTitle(f"Figures -- {paper.label} ({paper.prefix})")
        self._review.finished.connect(self._review_closed)
        self._review.set_background_status("The papers' text extraction runs in the background.")
        self.status.setText(f"Review the figures of {paper.label}…")
        self._review.show()

    def _review_closed(self, _result: int) -> None:
        review, paper = self._review, self._review_paper
        self._review = self._review_paper = None
        if paper is not None:
            paper.digitized, paper.skipped = list(review.digitized), list(review.skipped)
            paper.figures_reviewed = True
            self._paper_changed(paper)

    def _review_variables(self, groups, unfound_terms, registry):
        from parameter_extractor.gui.variable_review import VariableReviewDialog
        dialog = VariableReviewDialog(groups, unfound_terms, registry, parent=self)
        dialog.exec()
        return dialog.decisions()

    def _finish_all(self) -> None:
        """Every paper extracted and reviewed: assemble them one by one, then the combined files."""
        from parameter_extractor.digitizing.annotate import save_digitized
        self._finishing = True
        self._timer.stop()
        self.skip_figures_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        review = self._review_variables if self.variables_box.isChecked() else None
        for paper in self.queue.papers:
            if paper.status == "extracted":
                self.status.setText(f"Assembling {paper.label}"
                                    + (" -- review its new variables…" if review else "…"))
                QApplication.processEvents()
                self.queue.finish_paper(paper, review=review)
            elif paper.digitized and paper.extraction is not None:      # don't lose the clicking
                for fig in paper.digitized:
                    save_digitized(fig, paper.extraction.ctx.run_dir / "figures")
            self._paper_changed(paper)
        self._summary = self.queue.write_combined()
        s = self._summary
        failed = sum(p.status == "failed" for p in self.queue.papers)
        self.status.setText(f"Done: {s['finished']} of {s['papers']} paper(s) assembled, {s['rows']} rows"
                            + (f", {failed} failed (see the table)" if failed else "")
                            + f". Estimated cost ${s['cost_usd']:.2f}. Saved to {self.queue.out_dir}")
        self.open_folder_btn.setEnabled(True)
        self.open_csv_btn.setEnabled("csv" in s)
        self.paper_panel.set_locked(False)
        for w in (self.figures_box, self.variables_box):
            w.setEnabled(True)
        self.main._set_inputs_enabled(True)
        self._update_ready()

    @staticmethod
    def _open(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event) -> None:
        if self.running:
            self.hide()                         # keeps running; reopen from the File menu
            event.ignore()
            return
        super().closeEvent(event)
