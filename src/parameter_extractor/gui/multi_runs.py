"""
The main window's runs over several papers, or for a few parameters (Mickey, 2026-11-08: one search page instead of
the Focused search and Paper queue windows). Controllers, not windows: they report to the main window's status line,
progress bar and Papers list.

- FocusedRun: some parameters unticked -> focused_search.run_focused_search over the papers on a background thread;
  results in the "Search results" tab (one row per paper and object, a column per parameter, as
  focused_results.csv).
- QueueRun: a full extraction of several papers -> paper_queue.PaperQueue: each paper read first so its figures can be
  reviewed while the extraction carries on, then (optionally) each paper's new-variable review, then one combined CSV.
"""
from __future__ import annotations
import threading
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from parameter_extractor.errors import PipelineError, RunCancelledError
from parameter_extractor.pricing import format_usd

FOCUSED_STATUS = {"found": "Found", "not found": "Not reported", "not mentioned": "Not mentioned (no API call)",
                  "error": "Couldn't search"}
QUEUE_STATUS = {"waiting": "Waiting", "reading": "Reading", "extracting": "Extracting", "extracted": "Extracted",
                "finished": "Done", "failed": "Failed", "cancelled": "Cancelled"}


# ---- focused search -------------------------------------------------------------------------------------------

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
                                     plan_rows=plan, on_progress=self.progress.emit, cancel_event=self._cancel)
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


class FocusedRun(QObject):
    finished = Signal()

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.result = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[FocusedWorker] = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, items, columns, config, words, whole_paper, whole_tables, plan_rows) -> None:
        m = self.main
        self._worker = FocusedWorker(items, columns, config, words, whole_paper, whole_tables, plan_rows)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(lambda msg: m.report_failure("Search failed", msg))
        self._worker.cancelled.connect(lambda: m.status.setText("Cancelled."))
        self._worker.done.connect(self._on_done)
        m.progress.setRange(0, max(len(items), 1))
        m.progress.setValue(0)
        m.status.setText(f"Searching {len(items)} paper(s) for {', '.join(columns)}…")
        self._thread.start()

    def cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.main.status.setText("Cancelling -- papers already being read finish first…")

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.main.progress.setRange(0, max(total, 1))
        self.main.progress.setValue(done)
        self.main.status.setText(f"{done} of {total}: {message}")

    def _on_succeeded(self, run) -> None:
        from parameter_extractor import packs
        from parameter_extractor.focused_search import cell_text, result_columns, value_tip, wide_rows
        self.result = run
        m, table = self.main, self.main.search_table
        columns = result_columns(run.params, run.outcomes)
        rows = wide_rows(run.outcomes)
        units = packs.current().manifest.units          # the searched pack's set / row words
        headers = ["Paper", units.get("set", "set").capitalize(), units.get("sample", "sample").capitalize(),
                   "Result"] + [name + (f" [{p.unit}]" if part == "value" and p.unit else "")
                                for name, p, part in columns] + ["Read from"]
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        for c, (name, p, part) in enumerate(columns, start=4):
            table.horizontalHeaderItem(c).setToolTip(p.description)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            o = row.outcome
            result = FOCUSED_STATUS.get(o.status, o.status)
            fixed = [(o.reference or o.title or o.paper, "\n".join(x for x in (o.reference, o.item, o.title) if x)),
                     (row.set, row.set), (row.obj, row.obj), (result, o.message or result)]
            for c, (text, tip) in enumerate(fixed):
                item = QTableWidgetItem(str(text))
                item.setToolTip(tip)
                table.setItem(r, c, item)
            for c, (name, p, part) in enumerate(columns, start=4):
                values = row.cells.get(p.column, [])
                item = QTableWidgetItem(cell_text(values, p, part))
                if values:
                    item.setToolTip(value_tip(values))
                table.setItem(r, c, item)
            item = QTableWidgetItem(o.read_from)
            item.setToolTip(o.read_from)
            table.setItem(r, len(headers) - 1, item)
        table.resizeColumnsToContents()
        for c in range(table.columnCount()):
            table.setColumnWidth(c, min(table.columnWidth(c), 260))
        # each paper's own outcome in the Papers list
        by_item = {}
        for o in run.outcomes:
            by_item.setdefault(o.item, FOCUSED_STATUS.get(o.status, o.status))
        for r, item in enumerate(m.papers.items()):
            m.papers.set_status(r, by_item.get(str(item), ""))
        counts = {}
        for o in run.outcomes:
            key = FOCUSED_STATUS.get(o.status, o.status)
            counts[key] = counts.get(key, 0) + 1
        m.status.setText(f"Done: {', '.join(f'{n} {s.lower()}' for s, n in counts.items())}. Estimated cost "
                         f"{format_usd(run.cost_usd)}. Saved to {run.out_dir}")
        m.show_search_results(run)

    def failed_items(self) -> list:
        from parameter_extractor.ingestion.arxiv_source import PaperRef
        failed = [o for o in self.result.outcomes if o.status == "error"] if self.result else []
        return [Path(o.item) if o.item.lower().endswith(".pdf") else PaperRef(o.item, o.reference) for o in failed]

    def _on_done(self) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread, self._worker = None, None
        self.finished.emit()


# ---- paper queue ------------------------------------------------------------------------------------------------

class _Relay(QObject):
    """Queue events come from worker threads; this hands them to the window's thread."""
    changed = Signal(object)


class QueueRun(QObject):
    finished = Signal()

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.queue = None
        self.summary: Optional[dict] = None
        self._review = None                      # the figure review open now
        self._review_paper = None
        self.skip_remaining_figures = False
        self._finishing = False
        self._review_variables_at_end = True
        self._relay = _Relay()
        self._relay.changed.connect(self._paper_changed)
        self._timer = QTimer(self, interval=700, timeout=self._tick)

    @property
    def running(self) -> bool:
        return self.queue is not None and not self.summary

    def start(self, items, config, review_figures: bool, review_variables: bool) -> None:
        from parameter_extractor.paper_queue import PaperQueue
        m = self.main
        self.summary, self._finishing = None, False
        self.skip_remaining_figures = not review_figures
        self._review_variables_at_end = review_variables
        self.queue = PaperQueue(items, config, on_change=self._relay.changed.emit)
        for paper in self.queue.papers:
            self._paper_changed(paper)
        m.progress.setRange(0, len(self.queue.papers))
        m.progress.setValue(0)
        m.status.setText(f"Reading {len(self.queue.papers)} paper(s)…")
        self.queue.start()
        self._timer.start()

    def cancel(self) -> None:
        if self.queue is not None:
            self.queue.cancel()
            self.main.status.setText("Cancelling -- steps already running finish first…")

    def skip_figures(self) -> None:
        self.skip_remaining_figures = True

    def _row_of(self, paper) -> int:
        """The paper's row in the Papers list (the queue folds supplements into their papers and drops repeats,
        so positions can differ)."""
        rows = {str(item): r for r, item in enumerate(self.main.papers.items())}
        return rows.get(str(paper.item), self.queue.papers.index(paper))

    def _paper_changed(self, paper) -> None:
        if self.queue is None or paper not in self.queue.papers:
            return
        figures = paper.figures
        fig_text = ("" if not figures else f", {len(paper.digitized)}/{len(figures)} figures digitized"
                    if paper.figures_reviewed else f", {len(figures)} figures to review")
        rows = f", {len(paper.result.rows)} rows" if paper.result is not None else ""
        status = QUEUE_STATUS.get(paper.status, paper.status) + rows + fig_text
        self.main.papers.set_status(self._row_of(paper), status, paper.error or paper.step or status)
        done = sum(p.status in ("finished", "failed", "cancelled", "extracted") for p in self.queue.papers)
        self.main.progress.setValue(done)

    def _next_to_review(self):
        for paper in self.queue.papers:
            if paper.extraction is not None and paper.figures and not paper.figures_reviewed \
                    and paper.status not in ("failed", "cancelled"):
                return paper
            if paper.extraction is None and paper.status in ("waiting", "reading"):
                return None          # keep the list's order: wait until this paper has been read
        return None

    def _tick(self) -> None:
        """Every 0.7 s: open the next figure review, or -- when everything is extracted and reviewed -- assemble."""
        if self.queue is None or self._finishing:
            return
        if self._review is None:
            if self.skip_remaining_figures:
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
            self.main.status.setText(f"Figures reviewed so far -- {len(waiting)} paper(s) still being read or "
                                     f"extracted…")

    def _open_review(self, paper) -> None:
        from parameter_extractor.gui import figure_dialog
        from parameter_extractor.pipeline import plan_figure
        extraction = paper.extraction
        bridge = figure_dialog.PlanBridge(lambda fig, ex=extraction: plan_figure(ex, fig), parent=self.main)
        self._review, self._review_paper = figure_dialog.FigureReviewDialog(
            extraction.figures, extraction.vocab["all_columns"], plan_bridge=bridge, parent=self.main,
            auto_digitize=extraction.ctx.config.auto_digitize_figures), paper
        self._review.setWindowTitle(f"Figures -- {paper.label} ({paper.prefix})")
        self._review.finished.connect(self._review_closed)
        self._review.set_background_status("The papers' text extraction runs in the background.")
        self.main.status.setText(f"Review the figures of {paper.label}…")
        self._review.show()

    def _review_closed(self, _result: int) -> None:
        review, paper = self._review, self._review_paper
        self._review = self._review_paper = None
        if paper is not None:
            paper.digitized, paper.skipped = list(review.digitized), list(review.skipped)
            paper.figures_reviewed = True
            self._paper_changed(paper)

    def _review_variables(self, groups, unfound_terms, registry):
        from parameter_extractor.gui import main_window
        dialog = main_window.VariableReviewDialog(groups, unfound_terms, registry, parent=self.main)
        dialog.exec()
        return dialog.decisions()

    def _finish_all(self) -> None:
        """Every paper extracted and reviewed: assemble them one by one, then the combined files."""
        from parameter_extractor.digitizing.annotate import save_digitized
        m = self.main
        self._finishing = True
        self._timer.stop()
        review = self._review_variables if self._review_variables_at_end else None
        for paper in self.queue.papers:
            if paper.status == "extracted":
                m.status.setText(f"Assembling {paper.label}" + (" -- review its new variables…" if review else "…"))
                QApplication.processEvents()
                self.queue.finish_paper(paper, review=review)
            elif paper.digitized and paper.extraction is not None:      # don't lose the clicking
                for fig in paper.digitized:
                    save_digitized(fig, paper.extraction.ctx.run_dir / "figures")
            self._paper_changed(paper)
        self.summary = self.queue.write_combined()
        s = self.summary
        failed = sum(p.status == "failed" for p in self.queue.papers)
        m.status.setText(f"Done: {s['finished']} of {s['papers']} paper(s) assembled, {s['rows']} rows"
                         + (f", {failed} failed (see the Papers list)" if failed else "")
                         + f". Estimated cost ${s['cost_usd']:.2f}. Saved to {self.queue.out_dir}")
        m.progress.setValue(m.progress.maximum())
        self.finished.emit()

    def result_of(self, row: int):
        """The RunResult of the paper in that row of the Papers list (to show it), or None."""
        if self.queue is None:
            return None
        return next((p.result for p in self.queue.papers if self._row_of(p) == row), None)
