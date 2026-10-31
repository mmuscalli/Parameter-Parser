"""
Figure review, in two passes (Mickey, 2026-10-15):

  1. choose: each figure the PDF contains is shown in turn -- Skip or Digitize;
  2. digitize: then the chosen figures open in the digitizer, one after another.

Digitized figures come back as DigitizedFigure objects for pipeline.finish();
skipped ones never reach the dataset.

Suggestions (pipeline.plan_figure, one API call) are requested only for
figures the user chooses to digitize -- as soon as they're chosen, on a
background thread, so they're usually ready by the time that figure's editor
opens. Until they arrive the user can start calibrating.
"""
from __future__ import annotations
import threading
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from parameter_extractor.digitizing.calibration import try_pixel_to_data
from parameter_extractor.schemas.figures import DigitizedFigure, FigureCandidate, FigurePlan
from parameter_extractor.gui.digitizer import DigitizerWidget

# plan_requester(figure, on_success(plan), on_error(message)) -- called on the GUI
# thread; must deliver the callbacks on the GUI thread too (see PlanBridge).
PlanRequester = Callable[[FigureCandidate, Callable[[FigurePlan], None], Callable[[str], None]], None]



def _where(f) -> str:
    """'page 4', or 'supplementary information, page S8'."""
    return f"supplementary information, page {f.page_label}" if f.supplement else f"page {f.page}"

class PlanBridge(QObject):
    """Runs plan requests on Python threads and hands results back to the GUI
    thread via a queued signal. Owned by the main window, so a result that
    arrives after its dialog has closed has somewhere safe to land."""
    _done = Signal(int, object, str)

    def __init__(self, plan_fn: Callable[[FigureCandidate], FigurePlan], parent=None):
        super().__init__(parent)
        self._plan_fn = plan_fn
        self._callbacks: Dict[int, tuple] = {}
        self._next = 0
        self._done.connect(self._deliver)

    def request(self, figure: FigureCandidate, on_success, on_error) -> int:
        self._next += 1
        rid = self._next
        self._callbacks[rid] = (on_success, on_error)

        def work():
            try:
                self._done.emit(rid, self._plan_fn(figure), "")
            except Exception as e:  # PipelineError messages are user-readable already
                self._done.emit(rid, None, str(e) or type(e).__name__)
        threading.Thread(target=work, daemon=True).start()
        return rid

    def cancel(self, rid: int) -> None:
        self._callbacks.pop(rid, None)

    def _deliver(self, rid: int, plan, error: str) -> None:
        callbacks = self._callbacks.pop(rid, None)
        if callbacks:
            (callbacks[0](plan) if plan is not None else callbacks[1](error))


class FigureReviewDialog(QDialog):
    def __init__(self, figures: List[FigureCandidate], template_columns: List[str],
                 plan_bridge: Optional[PlanBridge] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Figures")
        self.resize(1400, 900)
        self.figures = figures
        self.columns = template_columns
        self.bridge = plan_bridge
        self.digitized: List[DigitizedFigure] = []
        self.skipped: List[str] = []
        self.chosen: List[FigureCandidate] = []      # to digitize, in the order chosen
        self.index = -1                              # pass 1: figure being decided
        self.digitize_index = -1                     # pass 2: position in `chosen`
        self.editor: Optional[DigitizerWidget] = None
        self._plans: Dict[str, tuple] = {}           # figure_id -> ("plan", plan) / ("error", message)
        self._plan_requests: Dict[str, int] = {}

        self.header = QLabel()
        self.header.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.bg_status = QLabel()
        self.bg_status.setStyleSheet("color: palette(placeholder-text);")
        self.stack = QStackedWidget()

        # page 0: choose
        decide = QWidget()
        dv = QVBoxLayout(decide)
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        dv.addWidget(scroll, 1)
        self.caption = QLabel(wordWrap=True)
        self.caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dv.addWidget(self.caption)
        drow = QHBoxLayout()
        self.digitize_btn = QPushButton("Digitize this figure", clicked=self._choose, default=True)
        self.skip_btn = QPushButton("Skip", clicked=self._skip)
        self.skip_rest_btn = QPushButton("Skip all remaining figures", clicked=self._skip_rest)
        # a supplement can hold dozens of figures (pulletikurti2022_SI: 90, mostly NMR spectra)
        self.skip_si_btn = QPushButton("Skip the supplement's figures", clicked=self._skip_supplement)
        self.skip_si_btn.setVisible(any(f.supplement for f in figures))
        drow.addWidget(self.digitize_btn)
        drow.addWidget(self.skip_btn)
        drow.addStretch(1)
        drow.addWidget(self.skip_si_btn)
        drow.addWidget(self.skip_rest_btn)
        dv.addLayout(drow)
        self.choose_hint = QLabel()
        self.choose_hint.setStyleSheet("color: palette(placeholder-text);")
        dv.addWidget(self.choose_hint)
        self.stack.addWidget(decide)

        # page 1: digitize (editor inserted per figure)
        self.digitize_page = QWidget()
        self.digitize_layout = QVBoxLayout(self.digitize_page)
        self.digitize_layout.setContentsMargins(0, 0, 0, 0)
        brow = QHBoxLayout()
        self.cancel_digitizing_btn = QPushButton("Skip this figure", clicked=self._skip_digitizing)
        self.save_btn = QPushButton("Save figure data and continue", clicked=self._save)
        brow.addWidget(self.cancel_digitizing_btn)
        brow.addStretch(1)
        brow.addWidget(self.save_btn)
        self.digitize_layout.addLayout(brow)     # the editor is inserted above this per figure
        self.stack.addWidget(self.digitize_page)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.header, 1)
        top.addWidget(self.bg_status)
        layout.addLayout(top)
        layout.addWidget(self.stack, 1)
        self._next()

    def set_background_status(self, text: str) -> None:
        """Shows how the text extraction running alongside this review is doing."""
        self.bg_status.setText(text)

    # ---- pass 1: choose ----------------------------------------------------------

    @property
    def figure(self) -> FigureCandidate:
        """The figure on screen: being decided (pass 1) or digitized (pass 2)."""
        if self.digitize_index >= 0:
            return self.chosen[self.digitize_index]
        return self.figures[self.index]

    def _next(self) -> None:
        self.index += 1
        if self.index >= len(self.figures):
            self._next_to_digitize()
            return
        f = self.figure
        if f.supplement and f.figure_id in self.skipped:       # 'Skip the supplement's figures'
            self._next()
            return
        self.skip_si_btn.setVisible(any(g.supplement for g in self.figures[self.index:]))
        self.header.setText(f"{f.figure_id} ({_where(f)}) -- figure {self.index + 1} of {len(self.figures)}: "
                            f"digitize or skip?")
        pix = QPixmap(f.crop_image)
        if pix.width() > 1100:
            pix = pix.scaledToWidth(1100, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pix)
        self.caption.setText(f"Caption (as read from the PDF): {f.caption}")
        chosen = ", ".join(c.figure_id for c in self.chosen)
        self.choose_hint.setText(
            "Choose for every figure first; the ones you pick to digitize then open one after another"
            + (f" (so far: {chosen})." if chosen else ".")
            + " Skipped figures are left out of the dataset; digitized points are added as extra rows, "
              "marked 'digitized'.")
        self.stack.setCurrentIndex(0)
        self.digitize_btn.setFocus()

    def _choose(self) -> None:
        f = self.figure
        self.chosen.append(f)
        self._request_plan(f)              # prefetch: usually ready by the time the editor opens
        self._next()

    def _skip(self) -> None:
        self.skipped.append(self.figure.figure_id)
        self._next()

    def _skip_supplement(self) -> None:
        """Skip every figure of the supplementary information still to be decided."""
        self.skipped += [f.figure_id for f in self.figures[self.index:] if f.supplement]
        self.index -= 1
        self._next()

    def _skip_rest(self) -> None:
        self.skipped += [f.figure_id for f in self.figures[self.index:]]
        self.index = len(self.figures) - 1
        self._next()

    # ---- pass 2: digitize the chosen figures ---------------------------------------

    def _next_to_digitize(self) -> None:
        self._drop_editor()
        self.digitize_index += 1
        if self.digitize_index >= len(self.chosen):
            self.accept()
            return
        f = self.figure
        self.header.setText(f"Digitizing {f.figure_id} ({_where(f)}) -- {self.digitize_index + 1} of "
                            f"{len(self.chosen)} chosen")
        self._start_digitizing()

    def _skip_digitizing(self) -> None:
        self.skipped.append(self.figure.figure_id)
        self._next_to_digitize()

    def reject(self) -> None:
        """Closing the window = skip whatever hasn't been decided or digitized yet
        (figures already saved are kept)."""
        if self.digitize_index < 0:
            self.skipped += [f.figure_id for f in self.figures[max(self.index, 0):]]
            self.skipped += [c.figure_id for c in self.chosen]
        else:
            self.skipped += [c.figure_id for c in self.chosen[self.digitize_index:]]
        self._drop_editor()
        for rid in self._plan_requests.values():
            if self.bridge is not None:
                self.bridge.cancel(rid)
        super().reject()

    def _request_plan(self, f: FigureCandidate) -> None:
        if self.bridge is None or f.figure_id in self._plan_requests:
            return

        def done(kind, value, fid=f.figure_id):
            self._plans[fid] = (kind, value)
            self._plan_requests.pop(fid, None)
            if self.editor is not None and self.editor.fig.figure_id == fid:
                self._apply_plan(fid)
        self._plan_requests[f.figure_id] = self.bridge.request(
            f, lambda plan: done("plan", plan), lambda msg: done("error", msg))

    def _apply_plan(self, figure_id: str) -> None:
        kind, value = self._plans[figure_id]
        (self.editor.offer_plan(value) if kind == "plan" else self.editor.show_plan_error(value))

    def _start_digitizing(self) -> None:
        f = self.figure
        model = DigitizedFigure(figure_id=f.figure_id, number=f.number, page=f.page, caption=f.caption,
                                render_scale=f.render_scale, page_image=f.page_image,
                                figure_bbox=f.figure_bbox, tick_numbers=list(f.tick_numbers),
                                supplement=f.supplement, page_label=f.page_label, prefix=f.prefix)
        self.editor = DigitizerWidget(model, self.columns)
        self.digitize_layout.insertWidget(0, self.editor, 1)
        self.stack.setCurrentIndex(1)
        if f.figure_id in self._plans:
            self._apply_plan(f.figure_id)
        elif self.bridge is not None:
            self._request_plan(f)
            self.editor.suggestion_label.setText(
                "Getting suggestions for the axes and series from the figure and caption... You can "
                "start calibrating. (If the text extraction is still in its first steps, this waits "
                "for the experiment structure, up to about a minute.)")

    def _drop_editor(self) -> None:
        if self.editor is not None:
            self.digitize_layout.removeWidget(self.editor)
            self.editor.deleteLater()
            self.editor = None

    def problems(self) -> List[str]:
        """What would stop the clicked points from becoming rows."""
        fig = self.editor.fig
        issues = []
        for s in fig.series:
            if not s.points:
                continue
            panel = fig.panels[s.panel]
            if try_pixel_to_data(panel, s.points[0].px, s.points[0].py) is None:
                issues.append(f"'{s.label}': its axes ('{panel.name}') aren't fully calibrated.")
            elif not (panel.x.column or panel.y.column or s.y_column):
                issues.append(f"'{s.label}': neither axis of '{panel.name}' is assigned to a column.")
        if not any(s.points for s in fig.series):
            issues.append("No points have been clicked yet.")
        from parameter_extractor.ingestion.figure_rows import convert_condition
        for s in fig.series:
            for c in s.conditions:
                _, _, problem = convert_condition(c)
                if problem and s.points:
                    issues.append(f"'{s.label}': condition {c.column or '(no column)'} -- {problem}.")
        return issues

    def _save(self, confirm: bool = True) -> None:
        issues = self.problems()
        if issues and confirm:
            answer = QMessageBox.question(
                self, "Save anyway?",
                "Some of this figure's data can't be used yet:\n\n- " + "\n- ".join(issues)
                + "\n\nThose series will be left out of the dataset. Save anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.digitized.append(self.editor.fig)
        self._next_to_digitize()
