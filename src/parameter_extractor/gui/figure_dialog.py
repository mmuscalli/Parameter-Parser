"""
Figure review: after the automatic extraction, step through each figure the
PDF contains and choose Skip or Digitize. Digitized figures come back as
DigitizedFigure objects for pipeline.finish(); skipped ones never reach the
dataset.

Suggestions (pipeline.plan_figure, one API call) are requested only when the
user chooses Digitize, on a background thread, and fill in the editor when
they arrive -- the user can start calibrating meanwhile.
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
        self.index = -1
        self.editor: Optional[DigitizerWidget] = None
        self._plan_request: Optional[int] = None

        self.header = QLabel()
        self.header.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.bg_status = QLabel()
        self.bg_status.setStyleSheet("color: palette(placeholder-text);")
        self.stack = QStackedWidget()

        # page 0: decide
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
        self.digitize_btn = QPushButton("Digitize this figure", clicked=self._start_digitizing, default=True)
        self.skip_btn = QPushButton("Skip", clicked=self._skip)
        self.skip_rest_btn = QPushButton("Skip all remaining figures", clicked=self._skip_rest)
        drow.addWidget(self.digitize_btn)
        drow.addWidget(self.skip_btn)
        drow.addStretch(1)
        drow.addWidget(self.skip_rest_btn)
        dv.addLayout(drow)
        hint = QLabel("Skipped figures are left out of the dataset. Digitized points are added as "
                      "extra rows, marked 'digitized'.")
        hint.setStyleSheet("color: palette(placeholder-text);")
        dv.addWidget(hint)
        self.stack.addWidget(decide)

        # page 1: digitize (editor inserted per figure)
        self.digitize_page = QWidget()
        self.digitize_layout = QVBoxLayout(self.digitize_page)
        self.digitize_layout.setContentsMargins(0, 0, 0, 0)
        brow = QHBoxLayout()
        self.cancel_digitizing_btn = QPushButton("Skip this figure", clicked=self._skip)
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

    # ---- navigation ------------------------------------------------------------

    @property
    def figure(self) -> FigureCandidate:
        return self.figures[self.index]

    def _next(self) -> None:
        self._drop_editor()
        self.index += 1
        if self.index >= len(self.figures):
            self.accept()
            return
        f = self.figure
        self.header.setText(f"{f.figure_id} (page {f.page}) -- figure {self.index + 1} of {len(self.figures)}")
        pix = QPixmap(f.crop_image)
        if pix.width() > 1100:
            pix = pix.scaledToWidth(1100, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pix)
        self.caption.setText(f"Caption (as read from the PDF): {f.caption}")
        self.stack.setCurrentIndex(0)
        self.digitize_btn.setFocus()

    def _skip(self) -> None:
        self.skipped.append(self.figure.figure_id)
        self._next()

    def _skip_rest(self) -> None:
        self.skipped += [f.figure_id for f in self.figures[self.index:]]
        self._drop_editor()
        self.index = len(self.figures)
        self.accept()

    def reject(self) -> None:
        """Closing the window = skip whatever hasn't been decided yet (work already
        saved is kept)."""
        if 0 <= self.index < len(self.figures):
            self.skipped += [f.figure_id for f in self.figures[self.index:]]
        self._drop_editor()
        super().reject()

    # ---- digitizing --------------------------------------------------------------

    def _start_digitizing(self) -> None:
        f = self.figure
        model = DigitizedFigure(figure_id=f.figure_id, number=f.number, page=f.page, caption=f.caption,
                                render_scale=f.render_scale, page_image=f.page_image,
                                figure_bbox=f.figure_bbox)
        self.editor = DigitizerWidget(model, self.columns)
        self.digitize_layout.insertWidget(0, self.editor, 1)
        self.stack.setCurrentIndex(1)
        if self.bridge is not None:
            self.editor.suggestion_label.setText(
                "Getting suggestions for the axes and series from the figure and caption... You can "
                "start calibrating. (If the text extraction is still in its first steps, this waits "
                "for the experiment structure, up to about a minute.)")
            editor = self.editor
            self._plan_request = self.bridge.request(
                f, lambda plan: editor.offer_plan(plan) if editor is self.editor else None,
                lambda msg: editor.show_plan_error(msg) if editor is self.editor else None)

    def _drop_editor(self) -> None:
        if self._plan_request is not None and self.bridge is not None:
            self.bridge.cancel(self._plan_request)
        self._plan_request = None
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
            elif not (panel.x.column or panel.y.column):
                issues.append(f"'{s.label}': neither axis of '{panel.name}' is assigned to a column.")
        if not any(s.points for s in fig.series):
            issues.append("No points have been clicked yet.")
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
        self._next()
