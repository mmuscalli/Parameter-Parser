"""
A data pack's structure as one picture (branch levels-and-facets; Mickey, 2026-11-19: "a node-editor style gui for
displaying / editing how data packs (levels, facets, etc.) are structured").

Left to right: the paper; the steps that read it (one model request each per paper -- the app's, the pack's own and
its modules', coloured by where they come from), with the calculations done on this computer below them; then the
pack's levels as lanes, top (the paper) to bottom (the dataset's row), each holding the kinds of value recorded for it
(the variable categories, at their level) with their fill setting. A line runs from each step to the kinds of value
its columns belong to (ending at the lane's edge, level with the card; a dot per step on the card); a faint dashed
line from the steps whose 'other values' answers may go into a kind no step's columns fill (hollow dots); the row
plan's lines go to the lanes themselves (it makes the sets and rows).

Every name is shown whole (two lines where one isn't enough; the full text and details in a tooltip). In the window
(StructureCanvas): hovering a step lights up its lines and the kinds of value it fills, hovering a kind of value the
steps that fill it -- everything else fades; wheel or pinch to zoom, drag to move. Drawn on a QGraphicsScene with
the window's palette (follows the themes). Stage 2: read-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView)

# geometry (scene units = pixels at 100 %)
STEP_W, STEP_GAP = 290, 12
CARD_W, CARD_GAP = 236, 10
LANE_PAD, LANE_TITLE = 14, 30
COL_PAPER, COL_STEPS, COL_LANES = 0, 230, 680
PER_ROW = 4
LANES_W = PER_ROW * CARD_W + (PER_ROW - 1) * CARD_GAP + 2 * LANE_PAD
NAME_PT, SUB_PT, SMALL_PT = 11.5, 10.0, 9.5
FADED = 0.16

KEY = 0          # item data: the hover target an item belongs to ("step:<name>" / "kind:<id>")
TAGS = 1         # item data: the steps and kinds a line or dot connects (frozenset of keys)


@dataclass
class Step:
    name: str
    label: str
    source: str                 # "app", "pack" or a module's label
    when: str
    what: str = ""
    kinds: List[str] = field(default_factory=list)       # category ids its columns belong to
    other_kinds: List[str] = field(default_factory=list)  # kinds only its 'other values' answers may fill
    makes_rows: bool = False


@dataclass
class Kind:
    id: str
    label: str
    level: str                  # level id
    fill: str                   # "set", "paper" or "none"
    origin: str                 # "this data pack", "module: …", "every data pack"
    columns: int = 0
    description: str = ""


@dataclass
class Structure:
    title: str
    levels: List[Tuple[str, str, str]]           # (id, label, note)
    steps: List[Step]
    calculations: List[Tuple[str, str, str]]     # (label, source, what)
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

    levels = []
    for lv in record_tree.levels(pack, runs=True):
        note = ""
        if lv.id == record_tree.RUN:
            note = (f"only when {_a(units['run'])} has several {units['run_row']}s" if units.get("run_row") else
                    f"only when {_a(units.get('set', 'set'))} holds several experiments, each sampled more than once")
        elif lv.id == "paper":
            note = "one per paper"
        levels.append((lv.id, lv.label if not lv.alone else f"{lv.alone} / {lv.label}", note))

    cats, _cols = fill_choices(pack)
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
        kinds.append(Kind(c.id, c.label, level, cats.get(c.id) or "none", origin, per_cat.get(c.id, 0),
                          c.description))

    steps, calcs = [], []
    for f in pack_overview.paper_flow(pack):
        source = "app" if f.source.startswith(pack_overview.APP) else \
            "pack" if f.source.startswith(pack_overview.PACK) else \
            f.source.replace("the ", "", 1).replace(" module", "")
        if f.kind == "local":
            calcs.append((f.label, source, f.what))
            continue
        if f.kind == "optional":
            continue
        columns = specs[f.name].columns if f.name in specs else _BUILT_IN_COLUMNS.get(f.name, [])
        found = []
        for column in columns:
            cid = order.category_of(column)
            if cid and cid not in found:
                found.append(cid)
        steps.append(Step(f.name, f.label, source, f.when, f.what, found, makes_rows=f.name == "structure_planner"))

    # kinds of value only 'other values' answers fill: from every step that asks for other values
    filled = {k for st in steps for k in st.kinds}
    assignable = {c.id for c in vc.assignable(pack)}
    open_steps = [st for st in steps if st.name in specs and specs[st.name].open_ended]
    for k in kinds:
        if k.id not in filled and k.id in assignable:
            for st in open_steps:
                st.other_kinds.append(k.id)
    return Structure(pack.manifest.label, levels, steps, calcs, kinds)


# ---- drawing ------------------------------------------------------------------------------------------------------

def _font(size: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


def wrap(text: str, font: QFont, width: float, lines: int = 2) -> List[str]:
    """`text` in at most `lines` lines of `width` (by words; a word too long, and anything past the last line,
    elided -- the tooltip has it whole)."""
    fm = QFontMetricsF(font)
    out, current = [], ""
    words = text.split()
    for i, word in enumerate(words):
        trial = f"{current} {word}".strip()
        if fm.horizontalAdvance(trial) <= width or not current:
            current = trial
            continue
        out.append(current)
        current = word
        if len(out) == lines - 1:
            current = " ".join(words[i:])
            break
    out.append(current)
    return [fm.elidedText(line, Qt.TextElideMode.ElideRight, width) for line in out[:lines]]


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


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() * (1 - t) + b.red() * t), int(a.green() * (1 - t) + b.green() * t),
                  int(a.blue() * (1 - t) + b.blue() * t))


class _Drawing:
    """Adds items to a scene, tagging the ones hovering concerns."""

    def __init__(self, scene: QGraphicsScene):
        self.scene = scene

    def box(self, rect: QRectF, fill: QColor, line: QColor, radius: float = 8, width: float = 1.0,
            dashed: bool = False, key: str = "", tags: Optional[Set[str]] = None, tip: str = "") -> QGraphicsPathItem:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        item = QGraphicsPathItem(path)
        item.setBrush(QBrush(fill))
        pen = QPen(line, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        item.setPen(pen)
        self._tag(item, key, tags, tip)
        self.scene.addItem(item)
        return item

    def text(self, text: str, x: float, y: float, color: QColor, size: float = 12, bold: bool = False,
             key: str = "", tip: str = "") -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(text)
        item.setFont(_font(size, bold))
        item.setBrush(QBrush(color))
        item.setPos(x, y)
        self._tag(item, key, None, tip)
        self.scene.addItem(item)
        return item

    def lines(self, lines: List[str], x: float, y: float, color: QColor, size: float, bold: bool = False,
              key: str = "", tip: str = "") -> float:
        """Text lines one under another; returns the y below them."""
        step = QFontMetricsF(_font(size, bold)).height()
        for line in lines:
            self.text(line, x, y, color, size, bold, key, tip)
            y += step
        return y

    def curve(self, start: QPointF, end: QPointF, color: QColor, width: float = 1.4, dashed: bool = False,
              tags: Optional[Set[str]] = None) -> None:
        path = QPainterPath(start)
        dx = max(40.0, (end.x() - start.x()) * 0.5)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        item = QGraphicsPathItem(path)
        item.setPen(QPen(color, width, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine,
                         Qt.PenCapStyle.RoundCap))
        item.setZValue(-1)                      # behind the lanes and cards: lines end at a lane's edge
        self._tag(item, "", tags, "")
        self.scene.addItem(item)

    @staticmethod
    def _tag(item: QGraphicsItem, key: str, tags: Optional[Set[str]], tip: str) -> None:
        if key:
            item.setData(KEY, key)
        if tags:
            item.setData(TAGS, frozenset(tags))
        if tip:
            item.setToolTip(tip)


FILL_TEXT = {"set": "fills in within its {set}", "paper": "fills in across the paper", "none": ""}


def build_scene(pack, palette: Optional[QPalette] = None) -> QGraphicsScene:
    """The pack's structure (structure_of) drawn on a new scene; `scene.relations` {key: related keys} for hovering."""
    s = structure_of(pack)
    pal = palette or QApplication.palette()
    text = pal.color(QPalette.ColorRole.Text)
    base = pal.color(QPalette.ColorRole.Base)
    window = pal.color(QPalette.ColorRole.Window)
    muted = _mix(text, window, 0.45)
    line = _mix(text, window, 0.72)
    colors = _source_colors(s.steps, pal)
    scene = QGraphicsScene()
    scene.setBackgroundBrush(QBrush(window))
    d = _Drawing(scene)
    units = pack.manifest.units or {}
    set_word = units.get("set", "set")

    d.text(s.title, COL_PAPER, -86, text, 17, True)
    d.text("How a paper's data is read and organised. Lines: which kinds of value each step fills (dashed: only "
           "through its 'other values' answers). Hover over a step or a kind of value to follow it.",
           COL_PAPER, -58, muted, 11.5)
    x = COL_PAPER
    for src in ["app", "pack"] + [k for k in colors if k not in ("app", "pack")]:
        name = "the app" if src == "app" else "this data pack" if src == "pack" else f"module: {src}"
        d.box(QRectF(x, -30, 12, 12), colors[src], colors[src], radius=3)
        label = d.text(name, x + 18, -33, muted, 10.5)
        x += 18 + label.boundingRect().width() + 18

    paper_rect = QRectF(COL_PAPER, 0, 170, 96)
    d.box(paper_rect, base, line, 10)
    d.text("The paper", COL_PAPER + 14, 12, text, 13, True)
    d.text("text · tables · figures", COL_PAPER + 14, 36, muted, 11)
    d.text("(+ supplement)", COL_PAPER + 14, 56, muted, 10.5)

    # steps
    y = 0
    step_out: Dict[str, QPointF] = {}
    name_font, sub_font = _font(12, True), _font(SUB_PT)
    for st in s.steps:
        key = f"step:{st.name}"
        source = "the app" if st.source == "app" else "this data pack" if st.source == "pack" \
            else f"the {st.source} module"
        tip = f"{st.label}\nFrom {source}; runs for {st.when}." + (f"\n{st.what}" if st.what else "")
        name = wrap(st.label, name_font, STEP_W - 26)
        when = wrap(f"for {st.when}", sub_font, STEP_W - 26)
        height = 12 + len(name) * QFontMetricsF(name_font).height() + len(when) * QFontMetricsF(sub_font).height()
        rect = QRectF(COL_STEPS, y, STEP_W, height)
        col = colors.get(st.source, text)
        d.box(rect, base, _mix(col, base, 0.35), 8, 1.2, key=key, tip=tip)
        d.box(QRectF(COL_STEPS, y, 6, height), col, col, 3, key=key, tip=tip)
        ty = d.lines(name, COL_STEPS + 16, y + 6, text, 12, True, key, tip)
        d.lines(when, COL_STEPS + 16, ty, muted, SUB_PT, False, key, tip)
        step_out[st.name] = QPointF(rect.right(), rect.center().y())
        d.curve(QPointF(paper_rect.right(), paper_rect.center().y()), QPointF(rect.left(), rect.center().y()),
                line, 1.0, tags={key})
        y += height + STEP_GAP
    if s.calculations:
        y += 8
        d.text("On your computer (no request, free)", COL_STEPS, y, muted, 11, True)
        y += 22
        x = COL_STEPS
        chip_font = _font(10.5)
        for label, source, what in s.calculations:
            col = colors.get(source, text)
            w = QFontMetricsF(chip_font).horizontalAdvance(label) + 20
            if x + w > COL_STEPS + STEP_W + 120 and x > COL_STEPS:
                x, y = COL_STEPS, y + 28
            tip = f"{label} -- on your computer" + (f": {what}" if what else "")
            d.box(QRectF(x, y, w, 22), window, _mix(col, window, 0.35), 11, 1.0, dashed=True, tip=tip)
            d.text(label, x + 10, y + 3, text, 10.5, tip=tip)
            x += w + 6

    # levels as lanes, the kinds of value in them
    y = 0
    card_in: Dict[str, QPointF] = {}
    lane_tops: List[float] = []
    ports: Dict[int, Set[str]] = {}
    card_font = _font(NAME_PT, True)
    line_h = QFontMetricsF(card_font).height()

    def name_width(k: Kind) -> float:
        dots = sum(1 for st in s.steps if k.id in st.kinds) or sum(1 for st in s.steps if k.id in st.other_kinds)
        return CARD_W - 22 - 10 * min(dots, 6)
    for i, (lid, label, note) in enumerate(s.levels):
        cards = [k for k in s.kinds if k.level == lid]
        rows = [cards[r:r + PER_ROW] for r in range(0, len(cards), PER_ROW)]
        sub_font = _font(SUB_PT)
        sub_h = QFontMetricsF(sub_font).height()

        def details(k: Kind) -> List[str]:
            fill = FILL_TEXT.get(k.fill, "").format(set=set_word)
            count = f"{k.columns} column{'s' if k.columns != 1 else ''}" if k.columns else ""
            return wrap(" · ".join(x for x in (count, fill) if x), sub_font, CARD_W - 20) \
                if (count or fill) else []
        row_heights = [12 + max(len(wrap(k.label, card_font, name_width(k))) * line_h + len(details(k)) * sub_h
                                for k in row) + SMALL_PT + 8 for row in rows]
        height = LANE_TITLE + (sum(h + CARD_GAP for h in row_heights) if cards else 22) + LANE_PAD
        tint = _mix(window, pal.color(QPalette.ColorRole.Highlight), 0.04 + 0.03 * (len(s.levels) - 1 - i))
        is_run = lid == "run"
        d.box(QRectF(COL_LANES, y, LANES_W, height), tint, line, 12, 1.0, dashed=is_run)
        d.text(label[:1].upper() + label[1:], COL_LANES + LANE_PAD, y + 7, text, 13, True)
        if note:
            d.text(note, COL_LANES + LANE_PAD + 240, y + 9, muted, 10.5)
        lane_tops.append(y)
        cy = y + LANE_TITLE
        for row, row_h in zip(rows, row_heights):
            for j, k in enumerate(row):
                key = f"kind:{k.id}"
                cx = COL_LANES + LANE_PAD + j * (CARD_W + CARD_GAP)
                rect = QRectF(cx, cy, CARD_W, row_h)
                fill = FILL_TEXT.get(k.fill, "").format(set=set_word)
                count = f"{k.columns} column{'s' if k.columns != 1 else ''}" if k.columns else ""
                fillers = [st for st in s.steps if k.id in st.kinds]
                others = [st for st in s.steps if k.id in st.other_kinds]
                tip = "\n".join(x for x in (
                    k.label, k.description, f"Recorded for: {label}" + (f"; {fill}" if fill else ""), count,
                    f"From {k.origin}",
                    f"Filled by: {', '.join(st.label for st in fillers)}" if fillers else "",
                    f"Only through the 'other values' answers of: {', '.join(st.label for st in others)}"
                    if others else "") if x)
                d.box(rect, base, line, 8, 1.0, key=key, tip=tip)
                for n, st in enumerate((fillers or others)[:6]):        # a dot per step: hollow for 'other values'
                    dot = colors.get(st.source, text)
                    d.box(QRectF(cx + CARD_W - 12 - n * 10, cy + 8, 7, 7), dot if fillers else base, dot, 3.5,
                          tags={key, f"step:{st.name}"})
                ty = d.lines(wrap(k.label, card_font, name_width(k)), cx + 10, cy + 6, text, NAME_PT, True, key, tip)
                ty = d.lines(details(k), cx + 10, ty + 1, muted, SUB_PT, False, key, tip)
                d.text(QFontMetricsF(_font(SMALL_PT)).elidedText(k.origin, Qt.TextElideMode.ElideRight, CARD_W - 20),
                       cx + 10, ty, muted, SMALL_PT, key=key, tip=tip)
                card_in[k.id] = QPointF(COL_LANES, rect.center().y())
                ports.setdefault(round(rect.center().y()), set()).add(key)
            cy += row_h + CARD_GAP
        if not cards:
            rows_word = units.get("run_row") or units.get("sample", "sample")
            d.text("(nothing recorded here: what its rows hold sits in the lanes above and below)" if not is_run
                   else f"(it holds the {rows_word}s of one {units.get('run', 'run')}; values they all share sit "
                        f"on it)", COL_LANES + LANE_PAD, y + LANE_TITLE, muted, 10.5)
        y += height + 12

    # lines and where they come in
    relations: Dict[str, Set[str]] = {}
    for st in s.steps:
        key = f"step:{st.name}"
        start = step_out[st.name]
        col = QColor(colors.get(st.source, text))
        col.setAlpha(160)
        if st.makes_rows:
            for top in lane_tops[1:]:
                d.curve(start, QPointF(COL_LANES, top + 14), col, 1.6, tags={key})
            continue
        faint = QColor(col)
        faint.setAlpha(80)
        for cid, dashed in [(c, False) for c in st.kinds] + [(c, True) for c in st.other_kinds]:
            if cid in card_in:
                d.curve(start, card_in[cid], faint if dashed else col, 1.1 if dashed else 1.4, dashed=dashed,
                        tags={key, f"kind:{cid}"})
                relations.setdefault(key, set()).add(f"kind:{cid}")
                relations.setdefault(f"kind:{cid}", set()).add(key)
    for y_mid, keys in ports.items():
        d.box(QRectF(COL_LANES - 4, y_mid - 4, 8, 8), line, line, 4, tags=set(keys)).setZValue(2)
    scene.setSceneRect(scene.itemsBoundingRect().adjusted(-24, -24, 24, 24))
    scene.relations = relations
    return scene


class StructureCanvas(QGraphicsView):
    """The structure picture of one data pack: hover a step or a kind of value to follow it (the rest fades);
    pinch or Ctrl+wheel to zoom, drag to move; fitted to its space until zoomed."""

    def __init__(self, pack=None, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self._hovered: Optional[str] = None
        self._follow = True            # fitted to the window as it resizes, until zoomed
        if pack is not None:
            self.show_pack(pack)

    def show_pack(self, pack) -> None:
        self.setScene(build_scene(pack, self.palette()))
        self._hovered = None
        self.fit()

    # ---- following a step or a kind of value ---------------------------------------------------------------------

    def key_at(self, pos) -> Optional[str]:
        for item in self.items(pos):
            key = item.data(KEY)
            if key:
                return key
        return None

    def highlight(self, key: Optional[str]) -> None:
        """Light up `key` (a step or a kind of value), what it connects to and the lines between; fade the other
        steps, cards, lines and dots. None: everything as drawn."""
        scene = self.scene()
        if scene is None or key == self._hovered:
            return
        self._hovered = key
        related = ({key} | getattr(scene, "relations", {}).get(key, set())) if key else set()
        for item in scene.items():
            own, tags = item.data(KEY), item.data(TAGS)
            if key is None:
                item.setOpacity(1.0)
            elif own:
                item.setOpacity(1.0 if own in related else FADED)
            elif tags:
                item.setOpacity(1.0 if key in tags else FADED)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if not event.buttons():
            self.highlight(self.key_at(event.position().toPoint()))

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.highlight(None)

    # ---- zoom ------------------------------------------------------------------------------------------------------

    def zoom(self, factor: float) -> None:
        self._follow = False
        self.scale(factor, factor)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.zoom(1.0015 ** event.angleDelta().y())
        else:
            super().wheelEvent(event)                 # scroll; a trackpad pinch comes as a gesture

    def viewportEvent(self, event) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None:
                self.zoom(pinch.scaleFactor())
                return True
        if event.type() == QEvent.Type.NativeGesture and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom(1.0 + event.value())
            return True
        return super().viewportEvent(event)

    def fit(self) -> None:
        self._follow = True
        if self.scene() is not None and self.viewport().width() > 50:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._follow:
            self.fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._follow:
            self.fit()


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
