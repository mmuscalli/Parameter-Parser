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
     adds a point, even on top of one of the same series.

Several coordinate systems ("axes") are supported for multi-panel figures or
a second y-axis: each has its own calibration and columns, and each series
is read against one of them.

The editor works on a schemas.figures.DigitizedFigure; nothing here knows
about rows or files.
"""
from __future__ import annotations
import re
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QCompleter, QFormLayout, QGraphicsEllipseItem,
    QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QDoubleSpinBox, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from parameter_extractor.digitizing.annotate import CALIBRATION_COLOR, SERIES_COLORS
from parameter_extractor.gui.widgets import ExpandingLineEdit
from parameter_extractor.digitizing.calibration import try_pixel_to_data
from parameter_extractor.schemas.figures import (
    AxisCalibration, AxisVariable, CalibrationPoint, DigitizedFigure, DigitizedPanel,
    DigitizedPoint, DigitizedSeries, FigurePlan, SeriesCondition, SpeciesAmount,
)

MODES = [("pan", "Pan / zoom", "Drag to move around; scroll to zoom."),
         ("x", "Set X axis", "Click two well-separated points on the x axis (e.g. two labelled "
                             "ticks), then type their values below. The dashed guide through the two "
                             "points should lie on the printed axis."),
         ("y", "Set Y axis", "Click two well-separated points on the y axis, then type their values below. "
                             "The dashed guide through the two points should lie on the printed axis."),
         ("points", "Add points", "Click each data point of the selected series. Drag to adjust; "
                                  "right-click to remove; Shift+click adds a point on top of an "
                                  "existing one; Ctrl+Z undoes."),
         ("delete", "Delete points", "Click a point of the selected series to remove it.")]
NONE_COLUMN = "(none -- not stored)"
FIXED_CONDITION_ROWS = 2     # temperature and pH head the Conditions table


def fill_concentrations(series: List[DigitizedSeries], found) -> None:
    """Fill each series' species that have no concentration from the plan's list of
    concentrations found in the paper (converted to mM here, never by the model);
    adds the species if the series doesn't list it yet."""
    from parameter_extractor.units import to_column_unit
    for c in found:
        conv = to_column_unit(c.value, None, "mM")
        if conv is None:
            continue
        labels = {l.strip().lower() for l in c.series}
        for s in series:
            base = re.sub(r"\s*\[[^\]]*\]$", "", s.label).strip().lower()   # label without " [marker]"
            if labels and base not in labels and s.label.strip().lower() not in labels:
                continue
            source = f"{'indirect -- ' if c.basis == 'indirect' else ''}{c.source or 'stated in the paper'} " \
                     f"('{c.value}')"
            for i, sp in enumerate(s.initial_species):
                if sp.name.strip().lower() == c.species.strip().lower():
                    if sp.concentration_mM is None:
                        s.initial_species[i] = sp.model_copy(update=dict(
                            concentration_mM=conv.value, basis=c.basis, source=source))
                    break
            else:
                s.initial_species.append(SpeciesAmount(name=c.species, concentration_mM=conv.value,
                                                       basis=c.basis, source=source))


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
                 editable: bool = True):
        super().__init__(-6, -6, 12, 12)
        self.series_idx, self.point_idx, self._on_moved = series_idx, point_idx, on_moved
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
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_moved(self.series_idx, self.point_idx, self.pos())
        return super().itemChange(change, value)


class PlotCanvas(QGraphicsView):
    clicked = Signal(float, float, object)     # scene x, scene y, Qt.MouseButton
    hovered = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.mode = "pan"
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None

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
        self.hover_label = QLabel(" ")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.canvas, 1)
        lv.addWidget(self.hover_label)

        right = QWidget()
        rv = QVBoxLayout(right)
        # suggestions (and warnings like "may duplicate a table") go first, where they're seen
        self.suggestion_label = QLabel("", wordWrap=True)
        self.suggestion_label.setStyleSheet("background: palette(alternate-base); padding: 6px;")
        self.apply_plan_btn = QPushButton("Apply suggestions", clicked=self._apply_pending_plan,
                                          visible=False)
        rv.addWidget(self.suggestion_label)
        rv.addWidget(self.apply_plan_btn)
        rv.addWidget(self._build_modes())
        rv.addWidget(self._build_axes_box())
        rv.addWidget(self._build_series_box(), 1)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(right)
        scroll.setMinimumWidth(400)

        split = QSplitter()
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
        if self.fig.figure_bbox:
            s, (x0, top, x1, bottom) = self.fig.render_scale, self.fig.figure_bbox
            pad = 15
            self.canvas.zoom_to(QRectF((x0 - pad) * s, (top - pad) * s,
                                       (x1 - x0 + 2 * pad) * s, (bottom - top + 2 * pad) * s))

    # ---- layout --------------------------------------------------------------

    def _build_modes(self) -> QWidget:
        box = QGroupBox("Tool")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key, label, _ in MODES:
            b = QToolButton(text=label, checkable=True)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            row.addWidget(b)
        v.addLayout(row)
        self.mode_hint = QLabel(wordWrap=True)
        self.mode_hint.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.mode_hint)
        return box

    def _build_axes_box(self) -> QWidget:
        box = QGroupBox("Axes")
        form = QFormLayout(box)

        self.panel_combo = QComboBox()
        self.panel_combo.currentIndexChanged.connect(self._on_panel_selected)
        add_panel = QPushButton("Add axes", clicked=self._add_panel)
        add_panel.setToolTip("For a second panel or a second y-axis: a separate coordinate system.")
        prow = QWidget()
        ph = QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.addWidget(self.panel_combo, 1)
        ph.addWidget(add_panel)
        form.addRow("Coordinate system:", prow)
        self.panel_name = QLineEdit()
        self.panel_name.editingFinished.connect(self._on_panel_name)
        form.addRow("Name:", self.panel_name)

        self.cal_edits = {}
        for axis in ("x", "y"):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            for k in (1, 2):
                status = QLabel()
                edit = QLineEdit(placeholderText=f"{axis.upper()}{k} value")
                edit.setMaximumWidth(90)
                edit.editingFinished.connect(lambda a=axis, kk=k: self._on_cal_value(a, kk))
                self.cal_edits[(axis, k)] = (status, edit)
                h.addWidget(status)
                h.addWidget(edit)
            log = QCheckBox("log")
            log.toggled.connect(lambda on, a=axis: self._on_log(a, on))
            self.cal_edits[(axis, "log")] = log
            h.addWidget(log)
            h.addStretch(1)
            form.addRow(f"{axis.upper()} axis:", row)

        self.source_edit = ExpandingLineEdit(
            "Data reproduced from", hint="If the figure reproduces another publication's data, its original "
                                         "reference. The rows will say so, and a warning is added.")
        self.source_edit.setPlaceholderText("leave empty if this paper measured it")
        self.source_edit.setText(self.fig.data_source)
        self.source_edit.editingFinished.connect(
            lambda: setattr(self.fig, "data_source", self.source_edit.text().strip()))

        self.var_widgets = {}
        for axis in ("x", "y"):
            combo = QComboBox(editable=True)
            combo.addItems([NONE_COLUMN] + self.columns)
            completer = QCompleter(self.columns, combo)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            combo.setCompleter(completer)
            combo.currentTextChanged.connect(lambda _t, a=axis: self._on_variable(a))
            mult = QLineEdit("1")
            mult.setMaximumWidth(70)
            mult.setToolTip("Axis value x multiplier = value stored in the column")
            mult.editingFinished.connect(lambda a=axis: self._on_variable(a))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(combo, 1)
            h.addWidget(QLabel("x"))
            h.addWidget(mult)
            self.var_widgets[axis] = (combo, mult)
            form.addRow(f"{axis.upper()} column:", row)
        form.addRow("Data reproduced from:", self.source_edit)

        # optional automation: place the calibration markers from the axis numbers
        self.auto_axes_btn = QPushButton("Auto-calibrate this coordinate system", clicked=self.auto_calibrate)
        self.auto_axes_btn.setToolTip("Finds the plot's frame and its tick numbers and places X1/X2 and Y1/Y2 on "
                                      "the outermost numbered ticks. Zoom to the panel first if the figure has "
                                      "several. Check the markers afterwards.")
        self.auto_axes_box = QCheckBox("Calibrate automatically when suggestions arrive")
        self.auto_axes_box.setChecked(QSettings().value("digitizer/auto_axes", False, type=bool))   # off by default
        self.auto_axes_box.toggled.connect(lambda on: QSettings().setValue("digitizer/auto_axes", on))
        self.auto_status = QLabel(wordWrap=True)
        self.auto_status.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(self.auto_axes_btn)
        form.addRow(self.auto_axes_box)
        form.addRow(self.auto_status)
        return box

    def _build_series_box(self) -> QWidget:
        box = QGroupBox("Series")
        v = QVBoxLayout(box)
        self.series_list = QListWidget()
        self.series_list.setMaximumHeight(130)
        self.series_list.currentRowChanged.connect(self._on_series_selected)
        self.series_list.itemChanged.connect(self._on_series_renamed)
        v.addWidget(self.series_list)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Add series", clicked=lambda: self.add_series()))
        row.addWidget(QPushButton("Remove", clicked=self._remove_series))
        row.addStretch(1)
        v.addLayout(row)
        self.isolate_box = QCheckBox("Show only the selected series")
        self.isolate_box.setToolTip("Hide the other series' points (useful where points overlap). "
                                    "Only the selected series is ever editable.")
        self.isolate_box.toggled.connect(lambda _on: self.redraw())
        v.addWidget(self.isolate_box)
        # optional automation: find the other markers that look like one example
        frow = QHBoxLayout()
        self.find_points_btn = QPushButton("Find similar points…", clicked=self._start_find_points)
        self.find_points_btn.setToolTip("Then click one marker of this series: markers that look the same are "
                                        "added to it (one undo step). Check them; right-click removes one.")
        self.similarity_spin = QDoubleSpinBox(minimum=0.4, maximum=0.99, singleStep=0.05, decimals=2)
        self.similarity_spin.setValue(QSettings().value("digitizer/similarity", 0.75, type=float))
        self.similarity_spin.setToolTip("How closely a marker must match the example (1 = identical). Lower it "
                                        "to catch markers partly covered by lines or other markers; raise it if "
                                        "other series' markers are picked up.")
        self.similarity_spin.valueChanged.connect(lambda v: QSettings().setValue("digitizer/similarity", v))
        frow.addWidget(self.find_points_btn)
        frow.addWidget(QLabel("similarity"))
        frow.addWidget(self.similarity_spin)
        frow.addStretch(1)
        v.addLayout(frow)

        details = QFormLayout()
        self.series_panel_combo = QComboBox()
        self.series_panel_combo.currentIndexChanged.connect(self._on_series_panel)
        details.addRow("Read against:", self.series_panel_combo)
        self.notes_edit = ExpandingLineEdit("Series notes", hint="Notes about this series; they end up in "
                                                                  "each row's source_notes.")
        self.notes_edit.editingFinished.connect(self._on_conditions_edited)
        details.addRow("Notes:", self.notes_edit)
        v.addLayout(details)

        v.addWidget(QLabel("Conditions:"))
        self.conditions_table = QTableWidget(0, 2)
        self.conditions_table.setHorizontalHeaderLabels(["Column", "Value as printed (with unit)"])
        self.conditions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conditions_table.setItemDelegateForColumn(0, _ColumnDelegate(self.columns, self))
        self.conditions_table.setMaximumHeight(150)
        self.conditions_table.setToolTip("Temperature and pH, then any other condition (pressure, flow rate, "
                                         "volume, gas, ...). Each goes into its column on every row of this "
                                         "series, converted to the column's unit (e.g. '22.2 MPa' -> 222 in "
                                         "initial_pressure_bar). A column name that doesn't exist yet becomes a "
                                         "new variable for the review.")
        self.conditions_table.itemChanged.connect(self._on_condition_edited)
        v.addWidget(self.conditions_table)
        crow = QHBoxLayout()
        crow.addWidget(QPushButton("Add condition", clicked=self._add_condition_row))
        crow.addWidget(QPushButton("Remove condition", clicked=self._remove_condition_row))
        crow.addStretch(1)
        v.addLayout(crow)

        v.addWidget(QLabel("Initial composition (mM):"))
        self.species_table = QTableWidget(0, 3)
        self.species_table.setHorizontalHeaderLabels(["Species", "mM", "Source"])
        self.species_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.species_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.species_table.setMaximumHeight(140)
        self.species_table.itemChanged.connect(self._on_species_edited)
        v.addWidget(self.species_table)
        srow = QHBoxLayout()
        srow.addWidget(QPushButton("Add species", clicked=self._add_species_row))
        srow.addWidget(QPushButton("Remove species", clicked=self._remove_species_row))
        srow.addStretch(1)
        v.addLayout(srow)

        v.addWidget(QLabel("Points (values as read off the axes):"))
        self.points_table = QTableWidget(0, 2)
        self.points_table.setHorizontalHeaderLabels(["x", "y"])
        self.points_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.points_table, 1)

        # rarely needed settings, out of the way until opened
        self.more_btn = QToolButton(text="Additional options", checkable=True, checked=False)
        self.more_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.more_btn.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
        self.more_options = QWidget(visible=False)
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

        def toggle(on: bool) -> None:
            self.more_options.setVisible(on)
            self.more_btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.more_btn.toggled.connect(toggle)
        v.addWidget(self.more_btn)
        v.addWidget(self.more_options)
        return box

    # ---- modes & canvas interaction -----------------------------------------

    def set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        self.mode_buttons[mode].setChecked(True)
        self.mode_hint.setText(dict((k, h) for k, _, h in MODES)[mode])

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
        self._undo = [(si, pi) for si, pi in self._undo if (si, pi) != best[1:]]
        self.redraw()
        return True

    def undo(self) -> None:
        while self._undo:
            si, pi = self._undo.pop()
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
            self.fig.series[si].points[pi] = DigitizedPoint(px=pos.x(), py=pos.y())
            self._refresh_points_table()

    def _on_hover(self, x: float, y: float) -> None:
        xy = try_pixel_to_data(self.panel, x, y)
        name = self.panel.name
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
                item = PointItem(si, pi, color, self._on_point_moved, editable=selected)
                item.setPos(p.px, p.py)
                scene.addItem(item)
        self._refresh_points_table()
        self._refresh_series_icons()
        self.changed.emit()

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
            combo.setCurrentText(var.column or NONE_COLUMN)
            mult.setText(_fmt(var.multiplier))
        self._updating = False

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
        m = _parse_float(mult.text())
        var.multiplier = m if m else 1.0
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

    def _gray(self):
        if getattr(self, "_gray_cache", None) is None:
            import numpy as np
            from PIL import Image
            self._gray_cache = np.asarray(Image.open(self.fig.page_image).convert("L"))
        return self._gray_cache

    def _figure_region(self):
        g = self._gray()
        if self.fig.figure_bbox:
            s = self.fig.render_scale
            x0, y0, x1, y1 = (v * s for v in self.fig.figure_bbox)
            pad = 30
            return (max(int(x0) - pad, 0), max(int(y0) - pad, 0), min(int(x1) + pad, g.shape[1]),
                    min(int(y1) + pad, g.shape[0]))
        return 0, 0, g.shape[1], g.shape[0]

    def _frames(self):
        if getattr(self, "_frames_cache", None) is None:
            from parameter_extractor.digitizing.auto_axes import find_frames
            self._frames_cache = find_frames(self._gray(), self._figure_region())
        return self._frames_cache

    @staticmethod
    def _panel_sides(name: str):
        """Which frame sides a coordinate system reads from, and its base name: '(a) right
        y-axis' -> ('bottom', 'right', '(a)')."""
        low = name.lower()
        # whole words: "diketopiperazine" contains "top" (a planner panel name, alargov2002)
        y_side = "right" if re.search(r"\bright\b", low) else "left"
        x_side = "top" if re.search(r"\btop\b", low) else "bottom"
        base = re.sub(r"\b(left|right|top|bottom|secondary|primary)\b|\b[xy][- ]?axis\b|\baxis\b", "", low)
        return x_side, y_side, re.sub(r"[\s,;:-]+", " ", base).strip()

    def _view_centre(self):
        c = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        return c.x(), c.y()

    def auto_calibrate(self, _checked=False, use_view: bool = True) -> str:
        """Place the current coordinate system's calibration markers automatically."""
        from parameter_extractor.digitizing.auto_axes import AutoAxisError, calibrate_axis, choose_frame
        panel = self.panel
        x_side, y_side, base = self._panel_sides(panel.name)
        bases = list(dict.fromkeys(self._panel_sides(p.name)[2] for p in self.fig.panels))
        notes = []
        try:
            frame = choose_frame(self._frames(), self._view_centre() if use_view else None, bases.index(base))
        except AutoAxisError as e:
            notes.append(str(e))
        else:
            for axis, side, var in (("x", x_side, panel.x), ("y", y_side, panel.y)):
                try:
                    (ax, ay, av), (bx, by, bv), is_log = calibrate_axis(
                        self._gray(), frame, side, list(var.tick_labels), self.fig.tick_numbers)
                except AutoAxisError as e:
                    notes.append(f"{axis.upper()}: {e}")
                    continue
                cal: AxisCalibration = getattr(panel, f"{axis}_cal")
                setattr(panel, f"{axis}_cal", AxisCalibration(
                    p1=CalibrationPoint(px=float(ax), py=float(ay), value=float(av)),
                    p2=CalibrationPoint(px=float(bx), py=float(by), value=float(bv)), log=cal.log or is_log))
                notes.append(f"{axis.upper()}: {av:g} to {bv:g} placed")
        message = f"{panel.name}: " + "; ".join(notes) + " -- check the markers."
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
        area = (frame.left, frame.top, frame.right, frame.bottom) if frame else self._figure_region()
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
            xy = try_pixel_to_data(panel, p.px, p.py)
            self.points_table.setItem(i, 0, QTableWidgetItem(f"{xy[0]:.4g}" if xy else "—"))
            self.points_table.setItem(i, 1, QTableWidgetItem(f"{xy[1]:.4g}" if xy else "—"))

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
        old_panels, old_series = self.fig.panels, self.fig.series
        panels, series = [], []
        for i, pp in enumerate(plan.panels or []):
            base = old_panels[i] if i < len(old_panels) else DigitizedPanel()
            x_cal = base.x_cal.model_copy(update={"log": pp.x.scale == "log"})
            y_cal = base.y_cal.model_copy(update={"log": pp.y.scale == "log"})
            panels.append(DigitizedPanel(name=pp.name, x_cal=x_cal, y_cal=y_cal, x=pp.x, y=pp.y))
            for ps in pp.series:
                label = ps.label + (f" [{ps.marker}]" if ps.marker and ps.marker not in ps.label else "")
                series.append(DigitizedSeries(
                    label=label, panel=i, initial_species=list(ps.initial_species),
                    initial_temperature_C=ps.initial_temperature_C, initial_pH=ps.initial_pH,
                    conditions=[c.model_copy() for c in ps.conditions], y_column=ps.y_column, notes=ps.notes))
        if not panels:
            return
        fill_concentrations(series, plan.concentrations)
        # keep any points the user already clicked, by position in the list
        for i, s in enumerate(old_series):
            if s.points:
                if i < len(series):
                    series[i].points = s.points
                else:
                    series.append(s.model_copy(update={"panel": min(s.panel, len(panels) - 1)}))
        self.fig.panels, self.fig.series = panels, series
        self.panel_idx = 0
        self.series_idx = 0 if series else -1
        self._undo.clear()
        self._refresh_panels()
        self._refresh_series_list()
        if self.auto_axes_box.isChecked():
            self.auto_calibrate_all()
        self.redraw()
