"""
The plot digitizer: a PlotDigitizer-style editor for one figure.

Left: the rendered page, zoomed to the figure. Trackpad: pinch to zoom,
two-finger scroll to move around; mouse: wheel to zoom; Cmd/Ctrl+scroll zooms
either way; drag in Pan mode. Right: tools.

  1. Set X axis / Set Y axis: click two points on each axis and type their
     values (tick marks far apart give the best accuracy). Log scales and
     slightly rotated scans are handled (digitizing/calibration.py).
  2. Variables: which template column each axis feeds, and a multiplier for
     unit conversion -- pre-filled from the model's suggestions when they
     arrive.
  3. Series: one per data set (legend entry / marker), each with its
     experimental conditions (composition, temperature, pH).
  4. Add points: click each data point of the selected series. Drag a point
     to move it; right-click (or Delete mode) removes one; Ctrl+Z undoes.
     Only the selected series is editable -- other series' points can't be
     grabbed, so new points can go right on top of them -- and "Show only the
     selected series" hides the others in crowded areas. Shift+click always
     adds a point, even on top of one of the same series. Tab / Shift+Tab (with the
     figure or the series list focused) selects the next / previous series.
  5. Optional automation: auto-calibrate (digitizing/auto_axes.py), 'Find similar
     points' from one example (auto_points.py), and 'Find points automatically' --
     bar tops / marker centres sorted into the series (auto_detect.py). 'Clear all
     axis markers' empties every coordinate system's calibration (Ctrl+Z undoes).

Several coordinate systems ("axes") are supported for multi-panel figures or
a second y-axis: each has its own calibration and columns, and each series
is read against one of them.
'Use in every coordinate system' copies the current one's rounding, columns,
log scales or category setting to all the others (one undo step).

Layout (2026-11-08): suggestions (hidden when empty) and the Tool buttons on
top, then three tabs -- Axes (coordinate system, calibration, columns,
rounding, automatic calibration, data reproduced from), Series (list,
conditions, composition, additional options) and Points (series, automatic
point finding, the points table).

The editor works on a schemas.figures.DigitizedFigure; nothing here knows
about rows or files.
"""
from __future__ import annotations
import re
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QCompleter, QFormLayout, QGraphicsEllipseItem,
    QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QDoubleSpinBox, QGridLayout, QSizePolicy, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSplitter, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from parameter_extractor.digitizing.annotate import CALIBRATION_COLOR, SERIES_COLORS
from parameter_extractor.digitizing.auto_figure import (FigureImage, apply_plan as apply_plan_to, calibrate_panel,
                                                        fill_concentrations, find_points, frame_of, panel_sides,
                                                        with_new_column as _with_new_column,
                                                        with_shared as _with_shared)
from parameter_extractor.gui.widgets import ExpandingLineEdit
from parameter_extractor.digitizing.calibration import (
    CalibrationError, is_categorical, pixel_to_y, read_values, snap, try_pixel_to_data)
from parameter_extractor.schemas.figures import (
    AxisCalibration, AxisVariable, CalibrationPoint, DigitizedFigure, DigitizedPanel,
    DigitizedPoint, DigitizedSeries, FigurePlan, SeriesCondition, SpeciesAmount,
)

# (key, button, one-line hint under the tools, full explanation in the button's tooltip)
MODES = [("pan", "Pan", "Drag to move; scroll or pinch to zoom.", "Drag to move around; scroll to zoom."),
         ("x", "X axis", "Click two labelled ticks on the x axis, then type their values (Axes tab).",
          "Click two well-separated points on the x axis (e.g. two labelled ticks), then type their values in the "
          "Axes tab. The dashed guide through the two points should lie on the printed axis."),
         ("y", "Y axis", "Click two labelled ticks on the y axis, then type their values (Axes tab).",
          "Click two well-separated points on the y axis, then type their values in the Axes tab. The dashed guide "
          "through the two points should lie on the printed axis."),
         ("points", "Add points", "Click each point of the selected series. Drag to adjust; right-click removes.",
          "Click each data point of the selected series. Drag to adjust; right-click to remove; Shift+click adds a "
          "point on top of an existing one; Ctrl+Z undoes."),
         ("delete", "Delete", "Click a point of the selected series to remove it.",
          "Click a point of the selected series to remove it."),
         ("errors", "Error bars", "Click the top, then the bottom, of a point's error bar.",
          "Click the top and then the bottom of a point's error bar: the selected series' point nearest in x gets it "
          "(a click above the point sets the upper end, below the lower). Right-click near a point removes its error "
          "bar; Ctrl+Z undoes.")]
NONE_COLUMN = "(none -- not stored)"
# (label, decimals, snap to a whole number within this many pixels)
ROUND_CHOICES = [("exact", None, 0.0), ("whole numbers", 0, 0.0), ("1 decimal", 1, 0.0), ("2 decimals", 2, 0.0),
                 ("3 decimals", 3, 0.0), ("whole ±3 px, else 1 decimal", 1, 3.0),
                 ("whole ±3 px, else 2 decimals", 2, 3.0)]
# 'Use these settings in every coordinate system' (menu entry, what it copies)
COPY_CHOICES = [("Rounding", "rounding"), ("Columns and multipliers", "columns"), ("Log scales", "log"),
                ("Categories (x axis)", "categories"), ("All of these", "all")]


class _NoteLabel(QLabel):
    """A wrapped note that hides itself while it has no text (the suggestions box)."""
    def __init__(self):
        super().__init__("", wordWrap=True)
        self.setVisible(False)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def _section(title: str, help_text: str = "") -> QLabel:
    """A bold sub-heading inside a tab (hover for the longer explanation)."""
    label = QLabel(title)
    label.setStyleSheet("font-weight: 600; margin-top: 6px;")
    if help_text:
        label.setToolTip(help_text)
    return label


def _titled_row(title: str, add, remove, what: str) -> QHBoxLayout:
    """A section heading with small add / remove buttons at its right."""
    row = QHBoxLayout()
    row.addWidget(_section(title))
    row.addStretch(1)
    for text, slot, tip in (("+", add, f"Add a {what}"), ("−", remove, f"Remove the selected {what}")):
        b = QToolButton(text=text, clicked=slot)
        b.setToolTip(tip)
        row.addWidget(b)
    return row


def _expander(title: str):
    """(toggle button, body widget): a section closed until its arrow is clicked."""
    button = QToolButton(text=title, checkable=True, checked=False)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(Qt.ArrowType.RightArrow)
    button.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
    body = QWidget(visible=False)

    def toggle(on: bool) -> None:
        body.setVisible(on)
        button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
    button.toggled.connect(toggle)
    return button, body


FIXED_CONDITION_ROWS = 2     # temperature and pH head the Conditions table


class _ColumnDelegate(QStyledItemDelegate):
    """Column cells: free text with suggestions from the known columns (a name that isn't
    one becomes a new variable, offered in the review)."""
    def __init__(self, columns: List[str], parent=None):
        super().__init__(parent)
        self.columns = columns

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        completer = QCompleter(self.columns, editor)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        editor.setCompleter(completer)
        return editor
HIT_RADIUS_PX = 12   # screen pixels


def _fmt(v: Optional[float]) -> str:
    return "" if v is None else f"{v:.6g}"


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None



class PointItem(QGraphicsEllipseItem):
    """A data point marker: constant on-screen size, draggable."""

    def __init__(self, series_idx: int, point_idx: int, color: QColor, on_moved: Callable,
                 editable: bool = True, snap_to: Optional[Callable] = None):
        super().__init__(-6, -6, 12, 12)
        self.series_idx, self.point_idx, self._on_moved = series_idx, point_idx, on_moved
        self._snap = snap_to             # rounds a dragged point to the axes' precision
        self.editable = editable
        self.setPen(QPen(color, 2.5))
        self.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
        flags = (QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                 | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        if editable:
            flags |= QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)   # clicks pass through
        self.setFlags(flags)
        self.setZValue(10 if editable else 5)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self._snap is not None:
            return self._snap(value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_moved(self.series_idx, self.point_idx, self.pos())
        return super().itemChange(change, value)


class PlotCanvas(QGraphicsView):
    clicked = Signal(float, float, object)     # scene x, scene y, Qt.MouseButton
    hovered = Signal(float, float)
    cycle_series = Signal(int)                 # Tab: +1, Shift+Tab: -1

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.mode = "pan"
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def event(self, event) -> bool:
        """Tab / Shift+Tab select the next / previous series instead of moving the focus."""
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.cycle_series.emit(-1 if event.key() == Qt.Key.Key_Backtab else 1)
            return True
        return super().event(event)

    def set_image(self, path: str) -> None:
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(QPixmap(path))
        self.scene().setSceneRect(self._pixmap_item.boundingRect())

    def zoom_to(self, rect: QRectF) -> None:
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode == "pan"
                         else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if mode == "pan"
                                  else Qt.CursorShape.CrossCursor)

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        if factor > 0 and 0.05 < current * factor < 40:
            self.scale(factor, factor)

    def wheelEvent(self, event) -> None:
        """Mouse wheel zooms. A trackpad's two-finger scroll (it reports pixel
        deltas) pans instead, as elsewhere on macOS; Cmd/Ctrl+scroll zooms either way."""
        zoom_modifier = event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        if not event.pixelDelta().isNull() and not zoom_modifier:
            return super().wheelEvent(event)
        delta = event.angleDelta().y() or event.pixelDelta().y()
        self.zoom_by(1.15 ** (delta / 120))

    def viewportEvent(self, event) -> bool:
        """Trackpad pinch (macOS native zoom gesture)."""
        if (event.type() == QEvent.Type.NativeGesture
                and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture):
            self.zoom_by(1.0 + event.value())
            return True
        return super().viewportEvent(event)

    def mousePressEvent(self, event) -> None:
        self.setFocus()                                 # so Tab reaches the canvas after a click
        if self.mode == "pan" or event.button() == Qt.MouseButton.MiddleButton:
            return super().mousePressEvent(event)
        item = self.itemAt(event.position().toPoint())
        if (isinstance(item, PointItem) and item.editable and self.mode == "points"
                and event.button() == Qt.MouseButton.LeftButton
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            return super().mousePressEvent(event)      # start dragging the point
        pos = self.mapToScene(event.position().toPoint())
        self.clicked.emit(pos.x(), pos.y(), event.button())

    def mouseMoveEvent(self, event) -> None:
        pos = self.mapToScene(event.position().toPoint())
        self.hovered.emit(pos.x(), pos.y())
        super().mouseMoveEvent(event)

    def scene_hit_radius(self) -> float:
        return HIT_RADIUS_PX / max(self.transform().m11(), 1e-6)


class DigitizerWidget(QWidget):
    changed = Signal()

    def __init__(self, figure: DigitizedFigure, template_columns: List[str], parent=None):
        super().__init__(parent)
        self.fig = figure
        self.columns = template_columns
        self.panel_idx = 0
        self.series_idx = -1
        self._undo: List[tuple] = []
        self._pending_plan: Optional[FigurePlan] = None
        self._updating = False

        self.canvas = PlotCanvas()
        self.canvas.set_image(figure.page_image)
        self.canvas.clicked.connect(self._on_canvas_click)
        self.canvas.hovered.connect(self._on_hover)
        self.canvas.cycle_series.connect(self.select_next_series)
        self.hover_label = QLabel(" ")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.canvas, 1)
        lv.addWidget(self.hover_label)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setSpacing(8)
        # suggestions (and warnings like "may duplicate a table") go first, where they're seen; hidden when empty
        self.suggestion_label = _NoteLabel()
        self.suggestion_label.setStyleSheet("background: palette(alternate-base); padding: 6px; border-radius: 4px;")
        self.apply_plan_btn = QPushButton("Apply suggestions", clicked=self._apply_pending_plan,
                                          visible=False)
        rv.addWidget(self.suggestion_label)
        rv.addWidget(self.apply_plan_btn)
        rv.addWidget(self._build_modes())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_axes_box(), "Axes")
        self.tabs.addTab(self._build_series_box(), "Series")
        self.tabs.addTab(self._build_points_box(), "Points")
        self.tabs.addTab(self._build_figure_box(), "Figure")
        rv.addWidget(self.tabs, 1)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(right)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # the tools fit the width
        scroll.setMinimumWidth(460)

        split = self.split = QSplitter()
        split.addWidget(left)
        split.addWidget(scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        self._refresh_panels()
        self._refresh_series_list()
        self.set_mode("x")
        self.redraw()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        total = sum(self.split.sizes())
        if total > 0:                              # the tools take ~40%, at least what they need
            right = max(480, int(total * 0.4))
            self.split.setSizes([max(total - right, 200), right])
        if self.fig.figure_bbox:
            s, (x0, top, x1, bottom) = self.fig.render_scale, self.fig.figure_bbox
            pad = 15
            self.canvas.zoom_to(QRectF((x0 - pad) * s, (top - pad) * s,
                                       (x1 - x0 + 2 * pad) * s, (bottom - top + 2 * pad) * s))

    # ---- layout --------------------------------------------------------------
    # (Mickey, 2026-11-12: less to read at once. Short labels on the controls, the explanations in their tooltips;
    # settings only shown where they apply -- one coordinate system has no 'Read against' or 'Copy to all'; the
    # figure-wide settings and the automatic helpers' switches together on a Figure tab.)

    def _build_modes(self) -> QWidget:
        """The tools, in one row, with a one-line hint for the current one (the full text in its tooltip)."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key, label, short, hint in MODES:
            b = QToolButton(text=label, checkable=True)
            b.setToolTip(hint)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            row.addWidget(b)
        v.addLayout(row)
        self.mode_hint = _muted("")
        self.mode_hint.setWordWrap(True)
        v.addWidget(self.mode_hint)
        v.addSpacing(4)
        return box

    def _build_axes_box(self) -> QWidget:
        """Axes tab: the coordinate system (renamed in its own box), its calibration and its columns."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(6)

        prow = QHBoxLayout()
        self.panel_combo = QComboBox(editable=True)
        self.panel_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.panel_combo.setToolTip("Each panel of the figure, or a second y axis, is its own coordinate system with "
                                    "its own calibration and columns. Type in the box to rename the current one "
                                    "(e.g. the panel letter).")
        self.panel_combo.currentIndexChanged.connect(self._on_panel_selected)
        self.panel_name = self.panel_combo.lineEdit()
        self.panel_name.editingFinished.connect(self._on_panel_name)
        add_panel = QToolButton(text="+", clicked=self._add_panel)
        add_panel.setToolTip("Add a coordinate system: for a second panel or a second y axis.")
        self.copy_settings_btn = QPushButton("Copy to all")
        self.copy_settings_btn.setToolTip("Copy this coordinate system's settings to all the others (e.g. one "
                                          "rounding for every panel of a multi-panel bar chart). Ctrl+Z undoes.")
        menu = QMenu(self.copy_settings_btn)
        for label, what in COPY_CHOICES:
            menu.addAction(label, lambda w=what: self.apply_to_all_panels(w))
        self.copy_settings_btn.setMenu(menu)
        prow.addWidget(QLabel("Coordinate system:"))
        prow.addWidget(self.panel_combo, 1)
        prow.addWidget(add_panel)
        prow.addWidget(self.copy_settings_btn)
        v.addLayout(prow)

        # calibration: the two markers per axis, and how the axis is drawn, as one grid
        v.addWidget(_section("Calibration", "Use the X axis / Y axis tools to place two markers on each axis (two "
                                            "labelled ticks far apart), then type the value printed at each."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for c, text in ((1, "Marker 1"), (2, "Marker 2"), (3, "Axis")):
            grid.addWidget(_muted(text), 0, c)
        self.cal_edits = {}
        for r, axis in enumerate(("x", "y"), start=1):
            grid.addWidget(QLabel(axis.upper()), r, 0)
            for k in (1, 2):
                cell = QHBoxLayout()
                status = QLabel()
                status.setMinimumWidth(30)
                edit = QLineEdit(placeholderText="value")
                edit.setMinimumWidth(60)
                edit.editingFinished.connect(lambda a=axis, kk=k: self._on_cal_value(a, kk))
                self.cal_edits[(axis, k)] = (status, edit)
                cell.addWidget(status)
                cell.addWidget(edit, 1)
                grid.addLayout(cell, r, k)
            kind = QHBoxLayout()
            log = QCheckBox("log")
            log.setToolTip("The axis is drawn on a logarithmic scale (tick values 1, 10, 100, ...).")
            log.toggled.connect(lambda on, a=axis: self._on_log(a, on))
            self.cal_edits[(axis, "log")] = log
            kind.addWidget(log)
            if axis == "x":
                categories = QCheckBox("categories")
                categories.setToolTip("Bars of categories on the x axis: no x calibration; each series' category "
                                      "goes in the X column (e.g. solid_material_name), from its condition for that "
                                      "column or else its name.")
                categories.toggled.connect(self._on_categories)
                self.cal_edits[("x", "categories")] = categories
                kind.addWidget(categories)
            kind.addStretch(1)
            grid.addLayout(kind, r, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        v.addLayout(grid)

        arow = QHBoxLayout()
        arow.addWidget(_muted("Auto-calibrate:"))
        self.auto_axes_btn = QPushButton("This one", clicked=self.auto_calibrate)
        self.auto_axes_btn.setToolTip("Current coordinate system: finds the plot's frame and its tick numbers and "
                                      "places X1/X2 and Y1/Y2 on the outermost numbered ticks. Zoom to the panel "
                                      "first if the figure has several. Check the markers afterwards.")
        self.auto_axes_all_btn = QPushButton("All", clicked=lambda: self.auto_calibrate_all())
        self.auto_axes_all_btn.setToolTip("Every coordinate system that has no markers yet (clear the markers first "
                                          "to redo one).")
        self.clear_axes_btn = QPushButton("Clear markers", clicked=self.clear_axis_markers)
        self.clear_axes_btn.setToolTip("Removes X1/X2 and Y1/Y2 and their values in every coordinate system "
                                       "(Ctrl+Z puts them back). Columns, log scales and points are kept.")
        for b in (self.auto_axes_btn, self.auto_axes_all_btn, self.clear_axes_btn):
            arow.addWidget(b)
        arow.addStretch(1)
        v.addLayout(arow)
        self.auto_status = _NoteLabel()
        self.auto_status.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.auto_status)

        # where the values go: column, unit multiplier and rounding per axis, as one grid
        v.addWidget(_section("Columns", "Which dataset column each axis's values go in. × converts the axis's unit "
                                        "(axis value × multiplier = stored value). Rounding snaps points to that "
                                        "precision when placed or dragged, and rounds the stored values."))
        cgrid = QGridLayout()
        cgrid.setHorizontalSpacing(6)
        cgrid.setVerticalSpacing(2)
        for c, text in ((1, "Column"), (2, "×"), (3, "Rounding")):
            cgrid.addWidget(_muted(text), 0, c)
        self.var_widgets, self.var_hints, self.log_value_boxes = {}, {}, {}
        for i, axis in enumerate(("x", "y")):
            r = 1 + 2 * i
            combo = QComboBox(editable=True)
            combo.addItems([NONE_COLUMN] + self.columns)
            combo.lineEdit().setPlaceholderText("choose a column, or type a new name")
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(14)
            completer = QCompleter(self.columns, combo)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            combo.setCompleter(completer)
            combo.currentTextChanged.connect(lambda _t, a=axis: self._on_variable(a))
            mult = QLineEdit("1")
            mult.setMaximumWidth(50)
            mult.setToolTip("Axis value × multiplier = value stored in the column")
            mult.editingFinished.connect(lambda a=axis: self._on_variable(a))
            rounding = QComboBox()
            rounding.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            rounding.setMinimumContentsLength(7)
            for text, _, _ in ROUND_CHOICES:
                rounding.addItem(text)
            rounding.setToolTip(f"Round {axis} values: points snap to this precision when placed or dragged (e.g. "
                                f"whole numbers for an oligomer length), and the stored values are rounded. "
                                f"'whole ±3 px' snaps to a whole number when the point is within 3 pixels of one.")
            rounding.currentIndexChanged.connect(lambda idx, a=axis: self._on_rounding(a, idx))
            self.cal_edits[(axis, "round")] = rounding
            cgrid.addWidget(QLabel(axis.upper()), r, 0)
            cgrid.addWidget(combo, r, 1)
            cgrid.addWidget(mult, r, 2)
            cgrid.addWidget(rounding, r, 3)
            hint = _NoteLabel()                   # shown only when it has something to say
            hint.setStyleSheet("color: palette(placeholder-text);")
            self.var_hints[axis] = hint
            cgrid.addWidget(hint, r + 1, 1, 1, 3)
            self.var_widgets[axis] = (combo, mult)
        cgrid.setColumnStretch(1, 1)
        v.addLayout(cgrid)

        # rarely needed: axes that plot logarithms
        more_btn, more = _expander("Logarithm axes")
        lrow = QHBoxLayout(more)
        lrow.setContentsMargins(12, 0, 0, 0)
        for axis in ("x", "y"):
            logv = QCheckBox(f"{axis.upper()} values are logarithms")
            logv.setToolTip("The plotted values are logarithms (an axis titled 'Log % yield', 'log [Gly]'): they are "
                            "stored as plotted, in a column of their own ('..._log10_...'), not in the column above. "
                            "Not for an axis that is only drawn on a log scale (use 'log' above for that).")
            logv.toggled.connect(lambda on, a=axis: self._on_log_values(a, on))
            self.log_value_boxes[axis] = logv
            lrow.addWidget(logv)
        lrow.addStretch(1)
        v.addWidget(more_btn)
        v.addWidget(more)
        v.addStretch(1)
        return page

    def _build_series_box(self) -> QWidget:
        """Series tab: the list, and the selected series' axes, notes, conditions and composition."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_section("Series", "Double-click a series to rename it. Tab / Shift+Tab (here or on the "
                                          "figure) selects the next / previous series."))
        head.addStretch(1)
        self.isolate_box = QCheckBox("Show only this one")
        self.isolate_box.setToolTip("Hide the other series' points (useful where points overlap). "
                                    "Only the selected series is ever editable.")
        self.isolate_box.toggled.connect(lambda _on: self.redraw())
        head.addWidget(self.isolate_box)
        for text, slot, tip in (("+", lambda: self.add_series(), "Add a series"),
                                ("−", self._remove_series, "Remove the selected series")):
            b = QToolButton(text=text, clicked=slot)
            b.setToolTip(tip)
            head.addWidget(b)
        v.addLayout(head)
        self.series_list = QListWidget()
        self.series_list.setMaximumHeight(110)
        self.series_list.currentRowChanged.connect(self._on_series_selected)
        self.series_list.itemChanged.connect(self._on_series_renamed)
        self.series_list.installEventFilter(self)
        self.series_list.setToolTip("Double-click to rename. Tab / Shift+Tab (here or on the figure) selects the "
                                    "next / previous series.")
        v.addWidget(self.series_list)

        details = QFormLayout()
        details.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.series_panel_combo = QComboBox()
        self.series_panel_combo.setToolTip("The coordinate system this series' points are read against.")
        self.series_panel_combo.currentIndexChanged.connect(self._on_series_panel)
        self.series_panel_label = QLabel("Read against:")
        details.addRow(self.series_panel_label, self.series_panel_combo)
        self.notes_edit = ExpandingLineEdit("Series notes", hint="Notes about this series; they end up in "
                                                                  "each row's source_notes.")
        self.notes_edit.setPlaceholderText("notes for this series' rows")
        self.notes_edit.editingFinished.connect(self._on_conditions_edited)
        details.addRow("Notes:", self.notes_edit)
        v.addLayout(details)

        self.conditions_table = QTableWidget(0, 2)
        self.conditions_table.setHorizontalHeaderLabels(["Column", "Value (with unit)"])
        self.conditions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conditions_table.verticalHeader().setVisible(False)
        self.conditions_table.setItemDelegateForColumn(0, _ColumnDelegate(self.columns, self))
        self.conditions_table.setMaximumHeight(140)
        self.conditions_table.setToolTip("Temperature and pH, then any other condition (pressure, flow rate, "
                                         "volume, gas, ...). Each goes into its column on every row of this "
                                         "series, converted to the column's unit (e.g. '22.2 MPa' -> 222 in "
                                         "initial_pressure_bar). A column name that doesn't exist yet becomes a "
                                         "new variable for the review.")
        self.conditions_table.itemChanged.connect(self._on_condition_edited)
        v.addLayout(_titled_row("Conditions", self._add_condition_row, self._remove_condition_row,
                                "condition"))
        v.addWidget(self.conditions_table)

        self.species_table = QTableWidget(0, 3)
        self.species_table.setHorizontalHeaderLabels(["Species", "mM", "Source"])
        self.species_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.species_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.species_table.verticalHeader().setVisible(False)
        self.species_table.setMaximumHeight(130)
        self.species_table.setToolTip("The series' starting concentrations (e.g. from the caption: '100 mM "
                                      "glycine'), in mM.")
        self.species_table.itemChanged.connect(self._on_species_edited)
        v.addLayout(_titled_row("Starting composition (mM)", self._add_species_row, self._remove_species_row,
                                "species"))
        v.addWidget(self.species_table)

        # rarely needed settings, out of the way until opened
        self.more_btn, self.more_options = _expander("Additional options")
        more = QFormLayout(self.more_options)
        more.setContentsMargins(12, 0, 0, 0)
        self.series_y_edit = QLineEdit(placeholderText="(the y axis's column)")
        completer = QCompleter(self.columns, self.series_y_edit)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.series_y_edit.setCompleter(completer)
        self.series_y_edit.setToolTip("Only when this series' y values belong in a different column than the "
                                      "axis's -- e.g. an axis 'Gly-Gly and diketopiperazine, mM' shared by two "
                                      "series. Leave empty to use the axis column.")
        self.series_y_edit.editingFinished.connect(self._on_conditions_edited)
        more.addRow("y values go in:", self.series_y_edit)
        v.addWidget(self.more_btn)
        v.addWidget(self.more_options)
        v.addStretch(1)
        return page

    def _build_points_box(self) -> QWidget:
        """Points tab: the selected series' points, and the automatic ways of finding them."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(6)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Series:"))
        self.points_series_combo = QComboBox()
        self.points_series_combo.setToolTip("The series new points go to (Tab / Shift+Tab on the figure).")
        self.points_series_combo.currentIndexChanged.connect(
            lambda i: self.series_list.setCurrentRow(i) if not self._updating and i >= 0 else None)
        srow.addWidget(self.points_series_combo, 1)
        v.addLayout(srow)

        # optional automation: bar tops / marker centres found in the plot, sorted into the series
        v.addWidget(_section("Find points automatically",
                             "Finds the tops of bars, or the centres of filled and open markers (circles, squares, "
                             "triangles, diamonds), in the plot and adds them to the series that have no points yet "
                             "-- by bar order, or by matching each kind of marker to the series' marker description "
                             "('open circles'). Works on clean plots; markers drawn as lines (+, x) and markers on "
                             "lines as thick as themselves are missed. Check every point; Ctrl+Z removes them all. "
                             "Error bars too, if that's on in the Figure tab."))
        prow = QHBoxLayout()
        self.auto_points_btn = QPushButton("This coordinate system", clicked=lambda: self.auto_find_points())
        self.auto_points_btn.setToolTip("Bar tops / marker centres in the current coordinate system's plot (every "
                                        "panel drawn in the same frame, e.g. a second y axis, too).")
        self.auto_points_all_btn = QPushButton("All", clicked=lambda: self.auto_find_points(
            list(range(len(self.fig.panels))), use_view=False))
        self.auto_points_all_btn.setToolTip("The same in every coordinate system.")
        prow.addWidget(self.auto_points_btn)
        prow.addWidget(self.auto_points_all_btn)
        prow.addStretch(1)
        v.addLayout(prow)

        # optional automation: find the other markers that look like one example
        frow = QHBoxLayout()
        self.find_points_btn = QPushButton("Like an example…", clicked=self._start_find_points)
        self.find_points_btn.setToolTip("Then click one marker of this series: markers that look the same are "
                                        "added to it (one undo step). Check them; right-click removes one.")
        self.similarity_spin = QDoubleSpinBox(minimum=0.4, maximum=0.99, singleStep=0.05, decimals=2)
        self.similarity_spin.setValue(QSettings().value("digitizer/similarity", 0.75, type=float))
        self.similarity_spin.setToolTip("How closely a marker must match the example (1 = identical). Lower it "
                                        "to catch markers partly covered by lines or other markers; raise it if "
                                        "other series' markers are picked up.")
        self.similarity_spin.valueChanged.connect(lambda val: QSettings().setValue("digitizer/similarity", val))
        frow.addWidget(self.find_points_btn)
        frow.addWidget(_muted("similarity"))
        frow.addWidget(self.similarity_spin)
        frow.addStretch(1)
        v.addLayout(frow)
        self.points_status = _NoteLabel()
        self.points_status.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.points_status)

        v.addWidget(_section("Points", "The selected series' points, as read off the axes (before the multiplier "
                                       "and rounding to columns)."))
        self.points_table = QTableWidget(0, 2)
        self.points_table.setHorizontalHeaderLabels(["x", "y"])
        self.points_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.points_table.verticalHeader().setVisible(False)
        self.points_table.setMinimumHeight(160)
        v.addWidget(self.points_table, 1)
        return page

    def _build_figure_box(self) -> QWidget:
        """Figure tab: settings for the whole figure, and which automatic helpers run when suggestions arrive."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(6)
        v.addWidget(_section("This figure"))
        self.source_edit = ExpandingLineEdit(
            "Data reproduced from", hint="If the figure reproduces another publication's data, its original "
                                         "reference. The rows will say so, and a warning is added.")
        self.source_edit.setPlaceholderText("leave empty if this paper measured it")
        self.source_edit.setText(self.fig.data_source)
        self.source_edit.editingFinished.connect(
            lambda: setattr(self.fig, "data_source", self.source_edit.text().strip()))
        sform = QFormLayout()
        sform.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        sform.addRow("Data reproduced from:", self.source_edit)
        v.addLayout(sform)
        self.rows_by_x_box = QCheckBox("One row per x value (the series are columns of one experiment)")
        self.rows_by_x_box.setToolTip(
            "For a figure where each x value is its own experiment and the series are the quantities measured in it "
            "(e.g. product yields at each temperature): the points of a coordinate system at the same x become one "
            "row, each series in its own column (set each series' 'y values go in' column). Off: one row per point, "
            "each series its own experiment set.")
        self.rows_by_x_box.setChecked(bool(self.fig.rows_by_x))
        self.rows_by_x_box.toggled.connect(lambda on: setattr(self.fig, "rows_by_x", bool(on)))
        v.addWidget(self.rows_by_x_box)

        v.addWidget(_section("Automatic helpers", "What runs by itself. Remembered for the next figures."))
        self.auto_axes_box = QCheckBox("Calibrate the axes when suggestions arrive")
        self.auto_axes_box.setToolTip("Places the axis markers on the outermost numbered ticks, as 'Auto-calibrate' "
                                      "on the Axes tab. Check them afterwards.")
        self.auto_axes_box.setChecked(QSettings().value("digitizer/auto_axes", False, type=bool))   # off by default
        self.auto_axes_box.toggled.connect(lambda on: QSettings().setValue("digitizer/auto_axes", on))
        self.auto_points_box = QCheckBox("Find the points when suggestions arrive")
        self.auto_points_box.setChecked(QSettings().value("digitizer/auto_points", False, type=bool))  # off
        self.auto_points_box.toggled.connect(lambda on: QSettings().setValue("digitizer/auto_points", on))
        self.auto_points_box.setToolTip("After the suggestions are applied (and the axes calibrated, if that's "
                                        "on): every coordinate system's points, as 'Find points automatically'.")
        self.auto_errors_box = QCheckBox("Find error bars whenever points are found")
        self.auto_errors_box.setChecked(QSettings().value("digitizer/auto_errors", True, type=bool))
        self.auto_errors_box.toggled.connect(lambda on: QSettings().setValue("digitizer/auto_errors", on))
        self.auto_errors_box.setToolTip("Whenever points are found automatically: a thin vertical line from a marker "
                                        "(or a bar's top) ending in a short cap is taken as its error bar. Check "
                                        "them; the 'Error bars' tool sets or corrects one by hand.")
        for box in (self.auto_axes_box, self.auto_points_box, self.auto_errors_box):
            v.addWidget(box)
        v.addStretch(1)
        return page

    def apply_to_all_panels(self, what: str) -> int:
        """Copy the current coordinate system's settings ('rounding', 'log', 'columns', 'categories' or 'all') to
        every other one; points of coordinate systems whose rounding changed snap to it. One undo step."""
        src = self.panel
        parts = {"rounding", "log", "columns", "categories"} if what == "all" else {what}
        saved = [(p.x.model_copy(), p.y.model_copy(), p.x_cal.log, p.y_cal.log) for p in self.fig.panels]
        points = [list(s.points) for s in self.fig.series]
        changed = 0
        for p in self.fig.panels:
            if p is src:
                continue
            for axis in ("x", "y"):
                a, b = getattr(src, axis), getattr(p, axis)
                if "rounding" in parts:
                    b.decimals, b.whole_within_px = a.decimals, a.whole_within_px
                if "columns" in parts:
                    b.column, b.store, b.multiplier = a.column, a.store, a.multiplier
                    b.new_column, b.average = a.new_column, a.average
                    b.log_values, b.log_values_set = a.log_values, a.log_values_set
                if "log" in parts:
                    getattr(p, f"{axis}_cal").log = getattr(src, f"{axis}_cal").log
            if "categories" in parts:
                p.x.categorical = src.x.categorical
            changed += 1
        if "rounding" in parts:                  # already placed points snap to the new precision
            for s in self.fig.series:
                panel = self.fig.panels[min(s.panel, len(self.fig.panels) - 1)]
                if panel is not src:
                    s.points = [pt.model_copy(update={"px": q[0], "py": q[1]})
                                for pt, q in ((pt, snap(panel, pt.px, pt.py)) for pt in s.points)]
        self._undo.append(("panel settings", (saved, points)))
        label = dict((w, l) for l, w in COPY_CHOICES)[what].lower()
        self.auto_status.setText(f"{label[0].upper() + label[1:]} copied from '{src.name}' to {changed} other "
                                 f"coordinate system(s) (Ctrl+Z undoes).")
        self.redraw()
        self.changed.emit()
        return changed

    # ---- modes & canvas interaction -----------------------------------------

    def set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        self.mode_buttons[mode].setChecked(True)
        self.mode_hint.setText(next(short for k, _, short, _h in MODES if k == mode))

    @property
    def panel(self) -> DigitizedPanel:
        return self.fig.panels[self.panel_idx]

    @property
    def series(self) -> Optional[DigitizedSeries]:
        return self.fig.series[self.series_idx] if 0 <= self.series_idx < len(self.fig.series) else None

    def _on_canvas_click(self, x: float, y: float, button) -> None:
        if self.canvas.mode == "example":
            self.set_mode("points")
            if button == Qt.MouseButton.LeftButton:
                self.find_points_like(x, y)
            return
        if self.canvas.mode in ("x", "y") and button == Qt.MouseButton.LeftButton:
            self.place_calibration(self.canvas.mode, x, y)
        elif self.canvas.mode == "points":
            if button == Qt.MouseButton.RightButton:
                self.delete_point_near(x, y)
            elif button == Qt.MouseButton.LeftButton:
                self.add_point(x, y)
        elif self.canvas.mode == "delete" and button == Qt.MouseButton.LeftButton:
            self.delete_point_near(x, y)
        elif self.canvas.mode == "errors":
            if button == Qt.MouseButton.RightButton:
                self.clear_error_bar_near(x, y)
            elif button == Qt.MouseButton.LeftButton:
                self.set_error_end(x, y)

    def _point_nearest_in_x(self, x: float):
        """(series index, point index) of the selected series' point nearest in x, or None."""
        s = self.series
        if s is None or not s.points:
            return None
        pi = min(range(len(s.points)), key=lambda i: abs(s.points[i].px - x))
        return self.series_idx, pi

    def set_error_end(self, x: float, y: float) -> bool:
        """An error bar's end for the selected series' point nearest in x: above the point the upper end,
        below it the lower. One undo step each."""
        found = self._point_nearest_in_x(x)
        if found is None:
            return False
        si, pi = found
        p = self.fig.series[si].points[pi]
        field = "err_hi_py" if y < p.py else "err_lo_py"     # pixel y grows downwards
        self._undo.append(("errors", (si, pi, p.err_hi_py, p.err_lo_py)))
        self.fig.series[si].points[pi] = p.model_copy(update={field: y})
        self.redraw()
        return True

    def clear_error_bar_near(self, x: float, y: float) -> bool:
        found = self._point_nearest_in_x(x)
        if found is None:
            return False
        si, pi = found
        p = self.fig.series[si].points[pi]
        if p.err_hi_py is None and p.err_lo_py is None:
            return False
        self._undo.append(("errors", (si, pi, p.err_hi_py, p.err_lo_py)))
        self.fig.series[si].points[pi] = p.model_copy(update={"err_hi_py": None, "err_lo_py": None})
        self.redraw()
        return True

    def place_calibration(self, axis: str, x: float, y: float) -> None:
        """Place X1/X2 (or Y1/Y2): fills the first empty slot, otherwise moves the
        nearer of the two."""
        cal: AxisCalibration = getattr(self.panel, f"{axis}_cal")
        if cal.p1 is None:
            cal.p1, k = CalibrationPoint(px=x, py=y), 1
        elif cal.p2 is None:
            cal.p2, k = CalibrationPoint(px=x, py=y), 2
        else:
            d1 = (cal.p1.px - x) ** 2 + (cal.p1.py - y) ** 2
            d2 = (cal.p2.px - x) ** 2 + (cal.p2.py - y) ** 2
            k = 1 if d1 <= d2 else 2
            old = cal.p1 if k == 1 else cal.p2
            new = CalibrationPoint(px=x, py=y, value=old.value)
            if k == 1:
                cal.p1 = new
            else:
                cal.p2 = new
        self._refresh_calibration()
        self.redraw()
        edit = self.cal_edits[(axis, k)][1]
        if not edit.text():
            edit.setFocus()

    def add_point(self, x: float, y: float) -> None:
        if self.series is None:
            self.add_series()
        x, y = snap(self.fig.panels[min(self.series.panel, len(self.fig.panels) - 1)], x, y)
        self.series.points.append(DigitizedPoint(px=x, py=y))
        self._undo.append((self.series_idx, len(self.series.points) - 1))
        self.redraw()

    def delete_point_near(self, x: float, y: float) -> bool:
        """Removes the selected series' point nearest the click, if close enough."""
        r2 = self.canvas.scene_hit_radius() ** 2
        best = None
        for si, s in enumerate(self.fig.series):
            if si != self.series_idx:
                continue
            for pi, p in enumerate(s.points):
                d = (p.px - x) ** 2 + (p.py - y) ** 2
                if d <= r2 and (best is None or d < best[0]):
                    best = (d, si, pi)
        if best is None:
            return False
        del self.fig.series[best[1]].points[best[2]]
        self._undo = [(si, pi) for si, pi in self._undo if isinstance(si, str) or (si, pi) != best[1:]]
        self.redraw()
        return True

    def undo(self) -> None:
        while self._undo:
            si, pi = self._undo.pop()
            if si == "panel settings":          # 'Use these settings in every coordinate system'
                saved, points = pi
                for panel, (x, y, xlog, ylog) in zip(self.fig.panels, saved):
                    panel.x, panel.y = x, y
                    panel.x_cal.log, panel.y_cal.log = xlog, ylog
                for series, pts in zip(self.fig.series, points):
                    series.points = pts
                self._refresh_calibration()
                self.redraw()
                return
            if si == "calibrations":            # 'Clear all axis markers': put them back
                for panel, (x_cal, y_cal) in zip(self.fig.panels, pi):
                    panel.x_cal, panel.y_cal = x_cal, y_cal
                self._refresh_calibration()
                self.redraw()
                return
            if si == "errors":                  # an error-bar end set or cleared: the old ends back
                sj, pj, hi, lo = pi
                if sj < len(self.fig.series) and pj < len(self.fig.series[sj].points):
                    pts = self.fig.series[sj].points
                    pts[pj] = pts[pj].model_copy(update={"err_hi_py": hi, "err_lo_py": lo})
                self.redraw()
                return
            if si == "error bars":              # automatic error bars: all go at once
                for sj, pj, hi, lo in pi:
                    if sj < len(self.fig.series) and pj < len(self.fig.series[sj].points):
                        pts = self.fig.series[sj].points
                        pts[pj] = pts[pj].model_copy(update={"err_hi_py": hi, "err_lo_py": lo})
                self.redraw()
                return
            if si == "points":                  # automatic points in several series: all go at once
                for sj, idx in pi:
                    pts = self.fig.series[sj].points if sj < len(self.fig.series) else []
                    for i in sorted(idx, reverse=True):
                        if i < len(pts):
                            del pts[i]
                self.redraw()
                return
            if isinstance(pi, list):            # a batch of found points: all go at once
                pts = self.fig.series[si].points if si < len(self.fig.series) else []
                for i in sorted(pi, reverse=True):
                    if i < len(pts):
                        del pts[i]
                self.redraw()
                return
            if si < len(self.fig.series) and pi < len(self.fig.series[si].points):
                del self.fig.series[si].points[pi]
                self.redraw()
                return

    def _on_point_moved(self, si: int, pi: int, pos: QPointF) -> None:
        if si < len(self.fig.series) and pi < len(self.fig.series[si].points):
            old = self.fig.series[si].points[pi]
            dy = pos.y() - old.py                  # its error bar moves with it
            self.fig.series[si].points[pi] = old.model_copy(update={
                "px": pos.x(), "py": pos.y(),
                "err_hi_py": old.err_hi_py + dy if old.err_hi_py is not None else None,
                "err_lo_py": old.err_lo_py + dy if old.err_lo_py is not None else None})
            self._refresh_points_table()

    def _on_hover(self, x: float, y: float) -> None:
        xy = read_values(self.panel, x, y)
        name = self.panel.name
        if xy and xy[0] is None:
            self.hover_label.setText(f"{name}: y = {xy[1]:.4g} (x: categories)")
            return
        self.hover_label.setText(f"{name}: x = {xy[0]:.4g}, y = {xy[1]:.4g}" if xy
                                 else f"{name}: calibrate both axes to read values")

    # ---- drawing ---------------------------------------------------------------

    def redraw(self) -> None:
        scene = self.canvas.scene()
        for item in list(scene.items()):
            if not isinstance(item, QGraphicsPixmapItem):
                scene.removeItem(item)
        for pi, panel in enumerate(self.fig.panels):
            active = pi == self.panel_idx
            color = QColor(CALIBRATION_COLOR if active else "#8a8a8a")
            for axis, cal in (("X", panel.x_cal), ("Y", panel.y_cal)):
                if active and cal.p1 is not None and cal.p2 is not None:
                    # guide line through the two markers, extended: if it doesn't sit on the
                    # printed axis, a marker is misplaced (values are read along this line)
                    dx, dy = cal.p2.px - cal.p1.px, cal.p2.py - cal.p1.py
                    length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
                    ext = 0.25 * length
                    ux, uy = dx / length, dy / length
                    guide = QGraphicsPathItem()
                    gp = QPainterPath()
                    gp.moveTo(cal.p1.px - ux * ext, cal.p1.py - uy * ext)
                    gp.lineTo(cal.p2.px + ux * ext, cal.p2.py + uy * ext)
                    guide.setPath(gp)
                    pen = QPen(QColor(CALIBRATION_COLOR), 0)          # cosmetic: 1 px at any zoom
                    pen.setStyle(Qt.PenStyle.DashLine)
                    guide.setPen(pen)
                    guide.setOpacity(0.7)
                    guide.setZValue(1)
                    scene.addItem(guide)
                for k, cp in enumerate((cal.p1, cal.p2), start=1):
                    if cp is None:
                        continue
                    path = QPainterPath()
                    path.moveTo(-11, 0); path.lineTo(11, 0)
                    path.moveTo(0, -11); path.lineTo(0, 11)
                    cross = QGraphicsPathItem(path)
                    cross.setPen(QPen(color, 2))
                    cross.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                    cross.setPos(cp.px, cp.py)
                    scene.addItem(cross)
                    text = f"{axis}{k}" + (f"={cp.value:g}" if cp.value is not None else "")
                    if len(self.fig.panels) > 1:
                        text += f" ({panel.name})"
                    label = QGraphicsSimpleTextItem(text)
                    label.setBrush(QBrush(color))
                    label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                    label.setPos(cp.px + 6, cp.py + 4)
                    scene.addItem(label)
        isolate = self.isolate_box.isChecked()
        for si, s in enumerate(self.fig.series):
            selected = si == self.series_idx
            if isolate and not selected:
                continue
            color = QColor(SERIES_COLORS[si % len(SERIES_COLORS)])
            if not selected:
                color.setAlpha(130)
            for pi, p in enumerate(s.points):
                panel = self.fig.panels[min(s.panel, len(self.fig.panels) - 1)]
                if p.err_hi_py is not None or p.err_lo_py is not None:     # the error bar, with caps
                    top = p.err_hi_py if p.err_hi_py is not None else p.py
                    bottom = p.err_lo_py if p.err_lo_py is not None else p.py
                    bar = QPainterPath()
                    bar.moveTo(p.px, top); bar.lineTo(p.px, bottom)
                    for end in (p.err_hi_py, p.err_lo_py):
                        if end is not None:
                            bar.moveTo(p.px - 5, end); bar.lineTo(p.px + 5, end)
                    whisker = QGraphicsPathItem(bar)
                    whisker.setPen(QPen(color, 0))
                    whisker.setZValue(2)
                    scene.addItem(whisker)
                item = PointItem(si, pi, color, self._on_point_moved, editable=selected,
                                 snap_to=lambda pos, pn=panel: QPointF(*snap(pn, pos.x(), pos.y())))
                item.setPos(p.px, p.py)
                scene.addItem(item)
        self._refresh_points_table()
        self._refresh_series_icons()
        self.changed.emit()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.series_list and event.type() == QEvent.Type.KeyPress and \
                event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and not self.series_list.state() == \
                QAbstractItemView.State.EditingState:
            self.select_next_series(-1 if event.key() == Qt.Key.Key_Backtab else 1)
            return True
        return super().eventFilter(obj, event)

    def select_next_series(self, step: int = 1) -> None:
        """The next series down the list (Tab), or up (Shift+Tab); wraps around."""
        n = len(self.fig.series)
        if n == 0:
            return
        row = (self.series_idx + step) % n if self.series_idx >= 0 else (0 if step > 0 else n - 1)
        self.series_list.setCurrentRow(row)          # -> _on_series_selected
        self.mode_hint.setText(f"Series: {self.fig.series[row].label}  (Tab: next, Shift+Tab: previous)")

    # ---- panels (coordinate systems) -------------------------------------------

    def _refresh_panels(self) -> None:
        self._updating = True
        self.panel_combo.clear()
        self.series_panel_combo.clear()
        for p in self.fig.panels:
            self.panel_combo.addItem(p.name)
            self.series_panel_combo.addItem(p.name)
        self.panel_combo.setCurrentIndex(self.panel_idx)
        if self.series:
            self.series_panel_combo.setCurrentIndex(self.series.panel)
        several = len(self.fig.panels) > 1           # only then is there anything to copy to or read against
        self.copy_settings_btn.setVisible(several)
        self.series_panel_combo.setVisible(several)
        self.series_panel_label.setVisible(several)
        self._updating = False
        self._refresh_calibration()

    def _add_panel(self) -> None:
        self.fig.panels.append(DigitizedPanel(name=f"axes {len(self.fig.panels) + 1}"))
        self.panel_idx = len(self.fig.panels) - 1
        self._refresh_panels()
        self.set_mode("x")
        self.redraw()

    def _on_panel_selected(self, idx: int) -> None:
        if self._updating or idx < 0:
            return
        self.panel_idx = idx
        self._refresh_calibration()
        self.redraw()

    def _on_panel_name(self) -> None:
        name = self.panel_name.text().strip()
        if name:
            self.panel.name = name
            self._refresh_panels()

    def _refresh_calibration(self) -> None:
        self._updating = True
        p = self.panel
        self.panel_name.setText(p.name)
        for axis in ("x", "y"):
            cal: AxisCalibration = getattr(p, f"{axis}_cal")
            for k, cp in ((1, cal.p1), (2, cal.p2)):
                status, edit = self.cal_edits[(axis, k)]
                status.setText(f"{axis.upper()}{k} {'✓' if cp else '·'}")
                status.setToolTip("placed" if cp else "not placed yet -- use the Set axis tool")
                edit.setText(_fmt(cp.value) if cp else "")
                edit.setEnabled(cp is not None)
            self.cal_edits[(axis, "log")].setChecked(cal.log)
            var: AxisVariable = getattr(p, axis)
            combo, mult = self.var_widgets[axis]
            combo.setCurrentText(var.column or ("" if var.store else NONE_COLUMN))
            mult.setText(_fmt(var.multiplier))
            from parameter_extractor.ingestion.flatten_to_template import log_base
            self.log_value_boxes[axis].setChecked(bool(log_base(var)))
            self.cal_edits[(axis, "round")].setCurrentIndex(
                next((i for i, (_, d, w) in enumerate(ROUND_CHOICES)
                      if d == var.decimals and w == getattr(var, "whole_within_px", 0.0)), 0))
            self._update_column_hint(axis)
        self.cal_edits[("x", "categories")].setChecked(bool(p.x.categorical))
        self._show_x_calibration()
        self._updating = False

    def _show_x_calibration(self) -> None:
        """A category axis needs no x markers: their boxes say so instead of waiting for values."""
        categorical = bool(self.panel.x.categorical)
        for k in (1, 2):
            status, edit = self.cal_edits[("x", k)]
            edit.setPlaceholderText("not needed" if categorical else "value")
            if categorical:
                edit.setEnabled(False)
        self.cal_edits[("x", "log")].setEnabled(not categorical)

    def _on_log_values(self, axis: str, on: bool) -> None:
        if self._updating:
            return
        getattr(self.panel, axis).log_values_set = bool(on)
        self._update_column_hint(axis)
        self.changed.emit()

    def _update_column_hint(self, axis: str) -> None:
        from parameter_extractor.ingestion.flatten_to_template import log_base, with_log
        var: AxisVariable = getattr(self.panel, axis)
        hint = ""
        base = log_base(var)
        if base and var.column:
            hint = f"Logarithms: stored as plotted in '{with_log(var.column, base)}'. "
        if var.column and var.column not in self.columns:
            hint += "New variable: offered in the review at the end (accept it there)."
        elif not var.column and not (axis == "x" and var.categorical):
            from parameter_extractor.ingestion.figure_rows import axis_column_from_label
            hint = ("Not stored." if not var.store or not var.label else
                    f"No column chosen: offered in the review as "
                    f"'{var.new_column or axis_column_from_label(var.label, var.average)}' -- or choose one.")
        if axis == "x" and var.categorical:
            hint = (hint + " " if hint else "") + "Categories: each series' category goes in this column."
        if hint == "Not stored.":                 # the combo already says '(none -- not stored)'
            hint = ""
        self.var_hints[axis].setText(hint)

    def _on_rounding(self, axis: str, index: int) -> None:
        if self._updating:
            return
        var = getattr(self.panel, axis)
        _, var.decimals, var.whole_within_px = ROUND_CHOICES[index]
        # points already placed in this coordinate system snap too
        for s in self.fig.series:
            if self.fig.panels[min(s.panel, len(self.fig.panels) - 1)] is self.panel:
                s.points = [p.model_copy(update={"px": q[0], "py": q[1]})
                            for p, q in ((p, snap(self.panel, p.px, p.py)) for p in s.points)]
        self.redraw()

    def _on_categories(self, on: bool) -> None:
        if self._updating:
            return
        self.panel.x.categorical = on
        self._refresh_calibration()
        self.redraw()

    def _on_cal_value(self, axis: str, k: int) -> None:
        if self._updating:
            return
        cal: AxisCalibration = getattr(self.panel, f"{axis}_cal")
        cp = cal.p1 if k == 1 else cal.p2
        if cp is not None:
            cp.value = _parse_float(self.cal_edits[(axis, k)][1].text())
            self.redraw()

    def _on_log(self, axis: str, on: bool) -> None:
        if not self._updating:
            getattr(self.panel, f"{axis}_cal").log = on
            self.redraw()

    def _on_variable(self, axis: str) -> None:
        if self._updating:
            return
        combo, mult = self.var_widgets[axis]
        text = combo.currentText().strip()
        var: AxisVariable = getattr(self.panel, axis)
        var.column = None if text in ("", NONE_COLUMN) else text
        var.store = text != NONE_COLUMN          # chosen explicitly: nothing stored for this axis
        m = _parse_float(mult.text())
        var.multiplier = m if m else 1.0
        self._update_column_hint(axis)
        self.changed.emit()

    # ---- series ------------------------------------------------------------------

    def add_series(self, label: Optional[str] = None) -> DigitizedSeries:
        s = DigitizedSeries(label=label or f"Series {len(self.fig.series) + 1}", panel=self.panel_idx)
        self.fig.series.append(s)
        self.series_idx = len(self.fig.series) - 1
        self._refresh_series_list()
        return s

    def _remove_series(self) -> None:
        if self.series is None:
            return
        del self.fig.series[self.series_idx]
        self._undo.clear()
        self.series_idx = min(self.series_idx, len(self.fig.series) - 1)
        self._refresh_series_list()
        self.redraw()

    def _refresh_series_list(self) -> None:
        self._updating = True
        self.series_list.clear()
        for s in self.fig.series:
            item = QListWidgetItem(s.label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.series_list.addItem(item)
        self.series_list.setCurrentRow(self.series_idx)
        self.points_series_combo.clear()
        self.points_series_combo.addItems([s.label for s in self.fig.series])
        self.points_series_combo.setCurrentIndex(self.series_idx)
        self._updating = False
        self._refresh_series_icons()
        self._refresh_series_details()

    def _refresh_series_icons(self) -> None:
        for i in range(self.series_list.count()):
            pix = QPixmap(12, 12)
            pix.fill(QColor(SERIES_COLORS[i % len(SERIES_COLORS)]))
            item = self.series_list.item(i)
            item.setIcon(QIcon(pix))
            n = len(self.fig.series[i].points)
            item.setToolTip(f"{n} point(s), read against '{self.fig.panels[self.fig.series[i].panel].name}'")

    def _on_series_selected(self, row: int) -> None:
        if self._updating:
            return
        self.series_idx = row
        self._updating = True
        self.points_series_combo.setCurrentIndex(row)
        self._updating = False
        if self.series and self.series.panel != self.panel_idx:
            self.panel_idx = self.series.panel
            self._refresh_panels()
        self._refresh_series_details()
        self.redraw()

    def _on_series_renamed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        row = self.series_list.row(item)
        if 0 <= row < len(self.fig.series) and item.text().strip():
            self.fig.series[row].label = item.text().strip()
            self.points_series_combo.setItemText(row, self.fig.series[row].label)

    def _on_series_panel(self, idx: int) -> None:
        if not self._updating and self.series and idx >= 0:
            self.series.panel = idx
            self.panel_idx = idx
            self._refresh_panels()
            self.redraw()

    def _refresh_series_details(self) -> None:
        self._updating = True
        s = self.series
        for w in (self.notes_edit, self.species_table, self.series_panel_combo,
                  self.conditions_table, self.series_y_edit):
            w.setEnabled(s is not None)
        self.notes_edit.setText((s.notes or "") if s else "")
        self.series_y_edit.setText(s.y_column if s else "")
        if s:
            self.series_panel_combo.setCurrentIndex(s.panel)
        self.species_table.setRowCount(0)
        for sp in (s.initial_species if s else []):
            r = self.species_table.rowCount()
            self.species_table.insertRow(r)
            self.species_table.setItem(r, 0, QTableWidgetItem(sp.name))
            self.species_table.setItem(r, 1, QTableWidgetItem(_fmt(sp.concentration_mM)))
            src = QTableWidgetItem(("indirect: " if sp.basis == "indirect" else "") + (sp.source or ""))
            src.setFlags(src.flags() & ~Qt.ItemFlag.ItemIsEditable)
            src.setToolTip(src.text())
            if sp.basis == "indirect":
                src.setForeground(QBrush(QColor("#a0522d")))
            self.species_table.setItem(r, 2, src)
        self.conditions_table.setRowCount(0)
        if s:
            for label, value in (("Temperature (°C)", s.initial_temperature_C), ("pH", s.initial_pH)):
                r = self.conditions_table.rowCount()
                self.conditions_table.insertRow(r)
                name = QTableWidgetItem(label)
                name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name.setToolTip("initial_temperature_C (also sampled_temperature_C)" if r == 0 else "initial_pH")
                self.conditions_table.setItem(r, 0, name)
                self.conditions_table.setItem(r, 1, QTableWidgetItem(_fmt(value)))
        for c in (s.conditions if s else []):
            r = self.conditions_table.rowCount()
            self.conditions_table.insertRow(r)
            self.conditions_table.setItem(r, 0, QTableWidgetItem(c.column))
            value = QTableWidgetItem(c.value)
            if c.source:
                value.setToolTip(f"Stated in: {c.source}")
            self.conditions_table.setItem(r, 1, value)
        self._updating = False
        self._refresh_points_table()

    def _on_conditions_edited(self) -> None:
        if self._updating or self.series is None:
            return
        self.series.notes = self.notes_edit.text().strip() or None
        self.series.y_column = self.series_y_edit.text().strip()

    def _add_condition_row(self) -> None:
        if self.series is None:
            return
        self.series.conditions.append(SeriesCondition(column="", value="", source="added by hand"))
        self._refresh_series_details()
        self.conditions_table.editItem(self.conditions_table.item(self.conditions_table.rowCount() - 1, 0))

    def _remove_condition_row(self) -> None:
        r = self.conditions_table.currentRow() - FIXED_CONDITION_ROWS
        if self.series is not None and 0 <= r < len(self.series.conditions):
            del self.series.conditions[r]
            self._refresh_series_details()

    def _on_condition_edited(self, item: QTableWidgetItem) -> None:
        if self._updating or self.series is None:
            return
        if item.row() < FIXED_CONDITION_ROWS:              # temperature / pH rows
            self._on_fixed_condition_edited(item)
            return
        r = item.row() - FIXED_CONDITION_ROWS
        if r >= len(self.series.conditions):
            return
        column, value = self.conditions_table.item(item.row(), 0), self.conditions_table.item(item.row(), 1)
        old = self.series.conditions[r]
        self.series.conditions[r] = old.model_copy(update=dict(
            column=column.text().strip() if column else "", value=value.text().strip() if value else ""))

    def _on_fixed_condition_edited(self, item: QTableWidgetItem) -> None:
        """Temperature accepts a unit ('353 K', '80 °C'); pH a number. Unreadable -> red, not stored."""
        from parameter_extractor.units import to_column_unit
        text = item.text().strip()
        value, ok = None, True
        if text:
            if item.row() == 0:
                conv = to_column_unit(text, None, "°C")
                value, ok = (conv.value, True) if conv else (None, False)
            else:
                value = _parse_float(text)
                ok = value is not None
        if item.row() == 0:
            self.series.initial_temperature_C = value
        else:
            self.series.initial_pH = value
        self._updating = True
        item.setBackground(QBrush(QColor("#f8d7da")) if not ok else QBrush())
        item.setToolTip("" if ok else "Not a readable value -- not stored.")
        self._updating = False

    def _add_species_row(self) -> None:
        if self.series is None:
            return
        self.series.initial_species.append(SpeciesAmount(name="", concentration_mM=None))
        self._refresh_series_details()
        self.species_table.editItem(self.species_table.item(self.species_table.rowCount() - 1, 0))

    def _remove_species_row(self) -> None:
        r = self.species_table.currentRow()
        if self.series is not None and 0 <= r < len(self.series.initial_species):
            del self.series.initial_species[r]
            self._refresh_series_details()

    def _on_species_edited(self, item: QTableWidgetItem) -> None:
        if self._updating or self.series is None:
            return
        r = item.row()
        if r >= len(self.series.initial_species):
            return
        name_item, conc_item = self.species_table.item(r, 0), self.species_table.item(r, 1)
        old = self.series.initial_species[r]
        conc = _parse_float(conc_item.text()) if conc_item else None
        changed = conc != old.concentration_mM
        self.series.initial_species[r] = old.model_copy(update=dict(
            name=(name_item.text().strip() if name_item else ""), concentration_mM=conc,
            basis="stated" if changed else old.basis, source="entered by hand" if changed else old.source))
        if changed:
            self._refresh_series_details()

    # ---- optional automation ------------------------------------------------------

    @property
    def _image(self) -> FigureImage:
        if getattr(self, "_image_cache", None) is None:
            self._image_cache = FigureImage(self.fig)
        return self._image_cache

    def _gray(self):
        return self._image.gray

    def _rgb(self):
        return self._image.rgb

    def _frames(self):
        return self._image.frames

    _panel_sides = staticmethod(panel_sides)

    def _view_centre(self):
        c = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        return c.x(), c.y()

    def auto_calibrate(self, _checked=False, use_view: bool = True) -> str:
        """Place the current coordinate system's calibration markers automatically."""
        message, _ = calibrate_panel(self.fig, self._image, self.panel_idx,
                                     self._view_centre() if use_view else None)
        self.auto_status.setText(message)
        self._refresh_calibration()
        self.redraw()
        return message

    def auto_calibrate_all(self) -> None:
        """After suggestions arrive: every coordinate system that isn't calibrated yet."""
        current = self.panel_idx
        messages = []
        for i, panel in enumerate(self.fig.panels):
            if panel.x_cal.p1 or panel.x_cal.p2 or panel.y_cal.p1 or panel.y_cal.p2:
                continue                       # the user has started on it: leave it alone
            self.panel_idx = i
            messages.append(self.auto_calibrate(use_view=False))
        self.panel_idx = current
        self._refresh_panels()
        self.auto_status.setText("\n".join(messages))

    def clear_axis_markers(self) -> None:
        """Remove every coordinate system's calibration markers and their values (one undo step)."""
        saved = [(p.x_cal.model_copy(), p.y_cal.model_copy()) for p in self.fig.panels]
        if not any(c.p1 or c.p2 for p in self.fig.panels for c in (p.x_cal, p.y_cal)):
            self.auto_status.setText("No axis markers to clear.")
            return
        for p in self.fig.panels:
            p.x_cal = AxisCalibration(log=p.x_cal.log)
            p.y_cal = AxisCalibration(log=p.y_cal.log)
        self._undo.append(("calibrations", saved))
        self.auto_status.setText(f"Axis markers cleared in {len(self.fig.panels)} coordinate system(s) "
                                 f"(Ctrl+Z puts them back).")
        self._refresh_calibration()
        self.redraw()

    def _frame_of(self, panel_idx: int, use_view: bool):
        return frame_of(self.fig, self._image, panel_idx, self._view_centre() if use_view else None)

    def auto_find_points(self, panels: Optional[List[int]] = None, use_view: bool = True) -> str:
        """Find bar tops / marker centres (and their error bars) in the frames of the given coordinate systems
        (default: the current one) and add them to the series there that have no points yet. One undo step."""
        panels = [self.panel_idx] if panels is None else panels
        result = find_points(self.fig, self._image, panels, self._view_centre() if use_view else None,
                             error_bars=self.auto_errors_box.isChecked())
        if result.added:
            self._undo.append(("points", result.added))
        message = result.message + ("\nCheck every point and error bar -- right-click removes a point, Ctrl+Z "
                                    "removes all that were added." if result.added else "")
        self.points_status.setText(message)
        self.redraw()
        return message

    def _start_find_points(self) -> None:
        if self.series is None:
            self.add_series()
        self.canvas.set_mode("example")
        self.mode_hint.setText(f"Click one marker of '{self.series.label}' -- markers that look the same "
                               f"will be added to it.")

    def find_points_like(self, x: float, y: float) -> int:
        """Add the markers like the one at (x, y) to the selected series; returns how many."""
        from parameter_extractor.digitizing.auto_axes import find_boxes_inside
        from parameter_extractor.digitizing.auto_points import centre_marker, find_similar_points
        gray = self._gray()
        x, y = centre_marker(gray, x, y)
        frame = next((f for f in self._frames() if f.contains(x, y)), None)
        area = (frame.left, frame.top, frame.right, frame.bottom) if frame else self._image.region()
        legends = find_boxes_inside(gray, frame) if frame else []
        existing = [(p.px, p.py) for s in self.fig.series for p in s.points]
        found = find_similar_points(gray, (x, y), area, existing=existing,
                                    threshold=self.similarity_spin.value(), exclude=legends)
        series = self.series
        start = len(series.points)
        series.points += [DigitizedPoint(px=px, py=py) for px, py, _ in found]
        if found:
            self._undo.append((self.series_idx, list(range(start, len(series.points)))))
        self.mode_hint.setText(f"Added {len(found)} point(s) like the example to '{series.label}'. Check them: "
                               f"right-click removes one, Ctrl+Z removes them all. Lower 'similarity' to catch "
                               f"markers partly covered by lines.")
        self.redraw()
        return len(found)

    def _refresh_points_table(self) -> None:
        s = self.series
        pts = s.points if s else []
        panel = self.fig.panels[s.panel] if s else self.panel
        self.points_table.setRowCount(len(pts))
        for i, p in enumerate(pts):
            xy = read_values(panel, p.px, p.py)
            self.points_table.setItem(i, 0, QTableWidgetItem("category" if xy and xy[0] is None
                                                             else f"{xy[0]:.4g}" if xy else "—"))
            text = f"{xy[1]:.4g}" if xy else "—"
            if xy and (p.err_hi_py is not None or p.err_lo_py is not None):     # the error bar, as read
                ends = [read_values(panel, p.px, e) if e is not None else None      # a bar: often the top only
                        for e in (p.err_hi_py, p.err_lo_py)]
                plus = f"+{ends[0][1] - xy[1]:.3g}" if ends[0] else ""
                minus = f"−{xy[1] - ends[1][1]:.3g}" if ends[1] else ""
                text += f" ({'/'.join(x for x in (plus, minus) if x)})"
            self.points_table.setItem(i, 1, QTableWidgetItem(text))

    # ---- suggestions -------------------------------------------------------------

    def _untouched(self) -> bool:
        return not any(s.points for s in self.fig.series) and len(self.fig.series) <= 1

    def offer_plan(self, plan: FigurePlan) -> None:
        """Model suggestions arrived. Applied straight away if the user hasn't
        started on series yet; otherwise offered via the Apply button so their
        work isn't overwritten."""
        self.fig.plan = plan
        notes = []
        if not plan.is_data_plot:
            notes.append("The model doesn't think this is a numeric data plot -- you may want to skip it.")
        if plan.duplicates_tabulated_data:
            notes.append(f"Possibly the same data as a table: {plan.duplicate_note or ''}")
        if getattr(plan, "rows_by_x", False):
            notes.append("Each x value is one experiment and the series are its measured quantities: one row per x "
                         "value, each series in its own column ('One row per x value', Axes tab).")
        if plan.data_source:
            notes.append(f"This figure reproduces another publication's data: {plan.data_source}")
            if not self.fig.data_source:
                self.fig.data_source = plan.data_source
                self.source_edit.setText(plan.data_source)
        if plan.notes:
            notes.append(plan.notes)
        if self._untouched():
            self.apply_plan(plan)
            notes.insert(0, "Suggestions applied (axes columns, series, conditions) -- check and edit as needed.")
            notes += [f"Concentration: {n}" for n in self.fig.plan_notes]
        else:
            self._pending_plan = plan
            self.apply_plan_btn.setVisible(True)
            notes.insert(0, "Suggestions are ready. 'Apply suggestions' fills in axes columns, series names and "
                            "conditions (your calibration and points are kept).")
        self.suggestion_label.setText("\n\n".join(notes))

    def show_plan_error(self, message: str) -> None:
        self.suggestion_label.setText(f"Couldn't get suggestions ({message}). Fill in the axes columns "
                                      f"and series yourself.")

    def _apply_pending_plan(self) -> None:
        if self._pending_plan:
            self.apply_plan(self._pending_plan)
            self.apply_plan_btn.setVisible(False)

    def apply_plan(self, plan: FigurePlan) -> None:
        if not apply_plan_to(self.fig, plan):
            return
        self.rows_by_x_box.setChecked(bool(self.fig.rows_by_x))
        self.panel_idx = 0
        self.series_idx = 0 if self.fig.series else -1
        self._undo.clear()
        self._refresh_panels()
        self._refresh_series_list()
        if self.auto_axes_box.isChecked():
            self.auto_calibrate_all()
        if self.auto_points_box.isChecked():
            self.auto_find_points(list(range(len(self.fig.panels))), use_view=False)
        self.redraw()
