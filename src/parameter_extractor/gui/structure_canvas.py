"""
A data pack's structure as one picture (branch levels-and-facets; Mickey, 2026-11-19: "a node-editor style gui for
displaying / editing how data packs (levels, facets, etc.) are structured" -- stage 1, a static view from the pack's
real data, to judge the layout before any editing).

Left to right: the paper; the steps that read it (one model request each per paper -- the app's, the pack's own and
its modules', coloured by where they come from), with the calculations done on this computer below them; then the
pack's levels as lanes, top (the paper) to bottom (the dataset's row), each holding the kinds of value recorded for it
(the variable categories, at their level) with their fill setting. A line runs from each step to the kinds of value
its columns belong to; the row plan's to the lanes themselves (it makes the sets and rows).

Drawn on a QGraphicsScene with the window's palette (follows the themes); `build_scene(pack)` makes it, StructureCanvas
shows it (zoom with the wheel or a pinch, drag to pan).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView)

# geometry (scene units = pixels at 100 %)
STEP_W, STEP_H, STEP_GAP = 250, 50, 12
CARD_W, CARD_H, CARD_GAP = 205, 60, 10
LANE_PAD, LANE_TITLE = 14, 30
COL_PAPER, COL_STEPS, COL_LANES = 0, 230, 620
LANES_W = 4 * CARD_W + 3 * CARD_GAP + 2 * LANE_PAD


@dataclass
class Step:
    name: str
    label: str
    source: str                 # "app", "pack" or a module's label
    when: str
    kinds: List[str] = field(default_factory=list)       # category ids its columns belong to
    makes_rows: bool = False


@dataclass
class Kind:
    id: str
    label: str
    level: str                  # level id
    fill: str                   # "set", "paper" or "none"
    origin: str                 # "this data pack", "module: …", "every data pack"
    columns: int = 0


@dataclass
class Structure:
    title: str
    levels: List[Tuple[str, str, str]]      # (id, label, note)
    steps: List[Step]
    calculations: List[Tuple[str, str]]     # (label, source)
    kinds: List[Kind]


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


# ---- the pack's data ----------------------------------------------------------------------------------------------

# columns that stand for what a built-in step writes (their categories are what it fills)
_BUILT_IN_COLUMNS = {
    "metadata": ["paper_title", "author_list", "paper_DOI"],
    "chemistry": ["initial_Gly_aq_mM", "stock_Gly_aq_mM", "sampled_Gly_aq_%yield", "calculated_Gly_aq_mM"],
    "analysis": ["analysis_RP-HPLC_column", "analysis_RP-HPLC_flow-rate_mL_min"],
    "fit_models": ["pl_fitlabel", "st_fitlabel", "pl_fitmethod"],
}


def structure_of(pack) -> Structure:
    """What the canvas draws, from a packs.Pack as saved."""
    from parameter_extractor import pack_overview, record_tree, variable_categories as vc
    from parameter_extractor.calculators.shared_values import fill_choices
    from parameter_extractor.column_order import ColumnOrder
    from parameter_extractor.registry import standard_columns
    from parameter_extractor.stages.optional import load_specs
    order = ColumnOrder(pack=pack)
    specs = load_specs(pack)
    facets = record_tree.Facets(order, record_tree.levels(pack, runs=True))
    units = pack.manifest.units or {}

    # levels: the paper, its groups, a run where a paper names several experiments in a group, the rows
    levels = []
    for lv in record_tree.levels(pack, runs=True):
        note = ""
        if lv.id == record_tree.RUN:
            note = (f"only when {_a(units['run'])} has several {units['run_row']}s" if units.get("run_row") else
                    f"only when {_a(units.get('set', 'set'))} holds several experiments, each sampled more than once")
        elif lv.id == "paper":
            note = "one per paper"
        name = lv.label if not lv.alone else f"{lv.alone} / {lv.label}"
        levels.append((lv.id, name, note))

    # kinds of value at their level, with their fill setting and where they come from
    cats, cols = fill_choices(pack)
    own = {c.get("id") for c in pack.own_manifest.variable_categories}
    module_of = {c.get("id"): m.label for m in getattr(pack, "modules", []) for c in m.manifest.variable_categories}
    known = set(pack.template_columns) | set(standard_columns(pack)) | {c for s in specs.values() for c in s.columns}
    per_cat: Dict[str, int] = {}
    for c in known:
        per_cat[order.category_of(c)] = per_cat.get(order.category_of(c), 0) + 1
    kinds = []
    for c in vc.categories(pack):
        if c.id in ("figure", "assumed"):
            continue
        level = facets.levels[facets.caps.get(c.id, facets.row)].id
        origin = "this data pack" if c.id in own else f"module: {module_of[c.id]}" if c.id in module_of \
            else "every data pack"
        kinds.append(Kind(c.id, c.label, level, cats.get(c.id) or "none", origin, per_cat.get(c.id, 0)))

    # steps (one request per paper) and calculations (local), from the pack's overview
    steps, calcs = [], []
    for f in pack_overview.paper_flow(pack):
        source = "app" if f.source.startswith("the app") or f.source.lower().startswith("app") else \
            "pack" if "data pack" in f.source.lower() or f.source == pack_overview.PACK else \
            f.source.replace("the ", "", 1).replace(" module", "")
        if f.kind == "local":
            calcs.append((f.label, source))
            continue
        if f.kind == "optional":
            continue
        if f.name in specs:
            columns = specs[f.name].columns
        else:
            columns = _BUILT_IN_COLUMNS.get(f.name, [])
        found = []
        for column in columns:
            cid = order.category_of(column)
            if cid and cid not in found:
                found.append(cid)
        steps.append(Step(f.name, f.label, source, f.when, found, makes_rows=f.name == "structure_planner"))
    return Structure(pack.manifest.label, levels, steps, calcs, kinds)


# ---- drawing ------------------------------------------------------------------------------------------------------

def _palette(widget=None) -> QPalette:
    return widget.palette() if widget is not None else QApplication.palette()


def _source_colors(steps: List[Step], pal: QPalette) -> Dict[str, QColor]:
    """The app's steps in the text colour, the pack's in the highlight colour, each module its own hue."""
    dark = pal.color(QPalette.ColorRole.Window).lightness() < 128
    out = {"app": QColor(pal.color(QPalette.ColorRole.Text)), "pack": QColor(pal.color(QPalette.ColorRole.Highlight))}
    hues = [28, 145, 280, 330, 190, 60, 0, 250]
    i = 0
    for s in steps:
        if s.source not in out:
            out[s.source] = QColor.fromHsl(hues[i % len(hues)], 150, 165 if dark else 95)
            i += 1
    return out


def _box(scene, rect: QRectF, fill: QColor, line: QColor, radius: float = 8, width: float = 1.0,
         dashed: bool = False) -> QGraphicsPathItem:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    item = QGraphicsPathItem(path)
    item.setBrush(QBrush(fill))
    pen = QPen(line, width)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    item.setPen(pen)
    scene.addItem(item)
    return item


def _text(scene, text: str, x: float, y: float, color: QColor, size: float = 12, bold: bool = False,
          width: Optional[float] = None) -> QGraphicsSimpleTextItem:
    font = QFont()
    font.setPointSizeF(size)
    font.setBold(bold)
    if width is not None:
        text = QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, width)
    item = QGraphicsSimpleTextItem(text)
    item.setFont(font)
    item.setBrush(QBrush(color))
    item.setPos(x, y)
    scene.addItem(item)
    return item


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() * (1 - t) + b.red() * t), int(a.green() * (1 - t) + b.green() * t),
                  int(a.blue() * (1 - t) + b.blue() * t))


def _curve(scene, start: QPointF, end: QPointF, color: QColor, width: float = 1.4) -> None:
    path = QPainterPath(start)
    dx = max(40.0, (end.x() - start.x()) * 0.5)
    path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
    item = QGraphicsPathItem(path)
    item.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    item.setZValue(-1)                      # behind the lanes and cards: lines end at a lane's edge
    scene.addItem(item)


FILL_TEXT = {"set": "fills in within its {set}", "paper": "fills in across the paper", "none": ""}


def build_scene(pack, palette: Optional[QPalette] = None) -> QGraphicsScene:
    """The pack's structure (structure_of) drawn on a new scene."""
    s = structure_of(pack)
    pal = palette or _palette()
    text = pal.color(QPalette.ColorRole.Text)
    base = pal.color(QPalette.ColorRole.Base)
    window = pal.color(QPalette.ColorRole.Window)
    muted = _mix(text, window, 0.45)
    line = _mix(text, window, 0.72)
    colors = _source_colors(s.steps, pal)
    scene = QGraphicsScene()
    scene.setBackgroundBrush(QBrush(window))
    units = pack.manifest.units or {}
    set_word = units.get("set", "set")

    _text(scene, s.title, COL_PAPER, -86, text, 17, True)
    _text(scene, "How a paper's data is read and organised. Lines: which kinds of value each step fills.",
          COL_PAPER, -58, muted, 11.5)
    # legend: where the steps come from
    x = COL_PAPER
    for src in ["app", "pack"] + [k for k in colors if k not in ("app", "pack")]:
        name = "the app" if src == "app" else "this data pack" if src == "pack" else f"module: {src}"
        _box(scene, QRectF(x, -30, 12, 12), colors[src], colors[src], radius=3)
        label = _text(scene, name, x + 18, -33, muted, 10.5)
        x += 18 + label.boundingRect().width() + 18

    # the paper
    paper_rect = QRectF(COL_PAPER, 0, 170, 96)
    _box(scene, paper_rect, base, line, 10)
    _text(scene, "The paper", COL_PAPER + 14, 12, text, 13, True)
    _text(scene, "text · tables · figures", COL_PAPER + 14, 36, muted, 11)
    _text(scene, "(+ supplement)", COL_PAPER + 14, 56, muted, 10.5)

    # steps
    y = 0
    step_anchor: Dict[str, Tuple[QPointF, QPointF]] = {}
    for st in s.steps:
        rect = QRectF(COL_STEPS, y, STEP_W, STEP_H)
        col = colors.get(st.source, text)
        _box(scene, rect, base, _mix(col, base, 0.35), 8, 1.2)
        _box(scene, QRectF(COL_STEPS, y, 6, STEP_H), col, col, 3)                  # its source's colour
        _text(scene, st.label, COL_STEPS + 16, y + 7, text, 12, True, width=STEP_W - 26)
        _text(scene, f"for {st.when}", COL_STEPS + 16, y + 28, muted, 10.5, width=STEP_W - 26)
        step_anchor[st.name] = (QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        _curve(scene, QPointF(paper_rect.right(), paper_rect.center().y()), step_anchor[st.name][0], line, 1.0)
        y += STEP_H + STEP_GAP
    # calculations on this computer
    if s.calculations:
        y += 8
        _text(scene, "On your computer (no request, free)", COL_STEPS, y, muted, 11, True)
        y += 22
        x = COL_STEPS
        chip_font = QFont()
        chip_font.setPointSizeF(10.5)
        for label, source in s.calculations:              # chips, wrapped in the steps' column
            col = colors.get(source, text)
            w = QFontMetricsF(chip_font).horizontalAdvance(label) + 20
            if x + w > COL_STEPS + STEP_W + 120 and x > COL_STEPS:
                x, y = COL_STEPS, y + 28
            _box(scene, QRectF(x, y, w, 22), window, _mix(col, window, 0.35), 11, 1.0, dashed=True)
            _text(scene, label, x + 10, y + 3, text, 10.5)
            x += w + 6
        y += 30
    steps_bottom = y

    # levels as lanes, the kinds of value in them
    y = 0
    card_anchor: Dict[str, QPointF] = {}
    lane_tops: List[float] = []
    per_row = 4
    for i, (lid, label, note) in enumerate(s.levels):
        cards = [k for k in s.kinds if k.level == lid]
        rows = max(1, (len(cards) + per_row - 1) // per_row) if cards else 0
        height = LANE_TITLE + (rows * (CARD_H + CARD_GAP) if rows else 22) + LANE_PAD
        tint = _mix(window, pal.color(QPalette.ColorRole.Highlight), 0.04 + 0.03 * (len(s.levels) - 1 - i))
        is_run = lid == "run"
        _box(scene, QRectF(COL_LANES, y, LANES_W, height), tint, line, 12, 1.0, dashed=is_run)
        _text(scene, label[:1].upper() + label[1:], COL_LANES + LANE_PAD, y + 7, text, 13, True)
        if note:
            _text(scene, note, COL_LANES + LANE_PAD + 230, y + 9, muted, 10.5, LANES_W - 260)
        lane_tops.append(y)
        for j, k in enumerate(cards):
            cx = COL_LANES + LANE_PAD + (j % per_row) * (CARD_W + CARD_GAP)
            cy = y + LANE_TITLE + (j // per_row) * (CARD_H + CARD_GAP)
            rect = QRectF(cx, cy, CARD_W, CARD_H)
            _box(scene, rect, base, line, 8, 1.0)
            fillers = [st for st in s.steps if k.id in st.kinds]
            for d, st in enumerate(fillers[:6]):           # a dot per step that fills it, in its colour
                dot = colors.get(st.source, text)
                _box(scene, QRectF(cx + CARD_W - 12 - d * 10, cy + 8, 7, 7), dot, dot, 3.5)
            _text(scene, k.label, cx + 10, cy + 6, text, 11.5, True, width=CARD_W - 24 - 10 * min(len(fillers), 6))
            fill = FILL_TEXT.get(k.fill, "").format(set=set_word)
            count = f"{k.columns} column{'s' if k.columns != 1 else ''}" if k.columns else ""
            sub = " · ".join(x for x in (count, fill) if x)
            _text(scene, sub or k.origin, cx + 10, cy + 26, muted, 10, width=CARD_W - 20)
            if sub:
                _text(scene, k.origin, cx + 10, cy + 41, muted, 9.5, width=CARD_W - 20)
            card_anchor[k.id] = QPointF(COL_LANES, rect.center().y())     # the lane's edge, level with its row
        if not cards:
            rows = units.get("run_row") or units.get("sample", "sample")
            run = units.get("run", "run")
            _text(scene, "(nothing recorded here: what its rows hold sits in the lanes above and below)" if not is_run
                  else f"(it holds the {rows}s of one {run}; values they all share sit on it)",
                  COL_LANES + LANE_PAD, y + LANE_TITLE, muted, 10.5)
        y += height + 12

    # lines: each step to the kinds of value it fills; the row plan to the lanes
    for st in s.steps:
        start = step_anchor[st.name][1]
        col = QColor(colors.get(st.source, text))
        col.setAlpha(150)
        if st.makes_rows:
            for top in lane_tops[1:]:
                _curve(scene, start, QPointF(COL_LANES, top + 14), col, 1.6)
            continue
        for cid in st.kinds:
            if cid in card_anchor:
                _curve(scene, start, card_anchor[cid], col, 1.4)
    for point in {(p.x(), p.y()) for p in card_anchor.values()}:     # where the lines come in
        _box(scene, QRectF(point[0] - 4, point[1] - 4, 8, 8), line, line, 4).setZValue(2)
    scene.setSceneRect(scene.itemsBoundingRect().adjusted(-24, -24, 24, 24))
    return scene


class StructureCanvas(QGraphicsView):
    """The structure picture of one data pack; wheel or pinch to zoom, drag to move."""

    def __init__(self, pack=None, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        if pack is not None:
            self.show_pack(pack)

    def show_pack(self, pack) -> None:
        self.setScene(build_scene(pack, self.palette()))

    def wheelEvent(self, event) -> None:
        factor = 1.0015 ** event.angleDelta().y()
        self.scale(factor, factor)


def render_png(pack, path, palette: Optional[QPalette] = None, scale: float = 2.0) -> None:
    """The picture as an image file (mockups, docs)."""
    from PySide6.QtGui import QImage
    scene = build_scene(pack, palette)
    rect = scene.sceneRect()
    image = QImage(int(rect.width() * scale), int(rect.height() * scale), QImage.Format.Format_ARGB32)
    image.fill(scene.backgroundBrush().color())
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()
    image.save(str(path))
