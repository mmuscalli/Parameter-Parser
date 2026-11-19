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

Steps and cards show their name (two lines where one isn't enough) and a short line; clicked, one opens in place to
show everything (where a step comes from, when it runs, what it asks; a kind's level, fill setting, origin and the
steps that fill it). In the window (StructureCanvas): hovering a step lights up its lines and the kinds of value it
fills, hovering a kind of value the steps that fill it -- everything else fades; wheel or pinch to zoom, drag to move. Drawn on a QGraphicsScene with
the window's palette (follows the themes). Stage 2: read-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QMenu)

# geometry (scene units = pixels at 100 %)
STEP_W, STEP_GAP = 236, 7
CARD_W, CARD_GAP = 184, 8
LANE_PAD, LANE_TITLE = 12, 30
PAPER_W, CALCS_W = 116, 330
COL_PAPER, COL_STEPS = 0, 156
COL_LANES = COL_STEPS + STEP_W + 150
PER_ROW = 4
LANES_W = PER_ROW * CARD_W + (PER_ROW - 1) * CARD_GAP + 2 * LANE_PAD
NAME_PT, SUB_PT, SMALL_PT = 11.5, 10.0, 9.5
FADED = 0.2

KEY = 0          # item data: the hover target an item belongs to ("step:<name>" / "kind:<id>")
TAGS = 1         # item data: the steps and kinds a line or dot connects (frozenset of keys)
BODY = 2         # item data: a step's or card's outline (outlined in the accent colour while hovered)
PEN = 3          # item data: its own pen, put back after
TARGET = 4       # item data: a part without hovering that can still be opened elsewhere ("level:<id>", "paper")
LANE = 5         # item data: a level's lane and its words (lit while what's hovered has a kind of value in it)


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
    built_in: bool = False      # written in the app's code (its instructions fixed) -- not a configurable step
    own_prompt: bool = False    # an app step following this data pack's own prompt (the row plan's rules)


APP_STEPS = ("structure_planner", "metadata")    # every data pack has them
BUILT_IN = " (built-in step)"


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
            f.source.removeprefix("the ").removesuffix(" module")       # the module's label ('Probe module' too)
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
        own_prompt = f.name in APP_STEPS and source == "pack"
        steps.append(Step(f.name, f.label.removesuffix(BUILT_IN), "app" if f.name in APP_STEPS else source, f.when,
                          f.what, found, makes_rows=f.name == "structure_planner",
                          built_in=f.label.endswith(BUILT_IN), own_prompt=own_prompt))
    # grouped by where they come from: the app's, this pack's, then each module's together (in the order first met)
    first = {}
    for st in steps:
        first.setdefault(st.source, len(first))
    steps.sort(key=lambda st: (0 if st.source == "app" else 1 if st.source == "pack" else 2, first[st.source]))

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
    elided -- the node opened shows it whole)."""
    fm = QFontMetricsF(font)
    out, current = [], ""
    words = text.split()
    for i, word in enumerate(words):
        trial = f"{current} {word}".strip()
        if fm.horizontalAdvance(trial) <= width or not current:
            current = trial
            continue
        if len(out) == lines - 1:                   # the last line: the rest, elided
            current = " ".join([current] + words[i:])
            break
        out.append(current)
        current = word
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
            dashed: bool = False, key: str = "", tags: Optional[Set[str]] = None, body: bool = False
            ) -> QGraphicsPathItem:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        item = QGraphicsPathItem(path)
        item.setBrush(QBrush(fill))
        pen = QPen(line, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        item.setPen(pen)
        if body:
            item.setData(BODY, True)
            item.setData(PEN, pen)
        self._tag(item, key, tags)
        self.scene.addItem(item)
        return item

    def text(self, text: str, x: float, y: float, color: QColor, size: float = 12, bold: bool = False,
             key: str = "") -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(text)
        item.setFont(_font(size, bold))
        item.setBrush(QBrush(color))
        item.setPos(x, y)
        self._tag(item, key, None)
        self.scene.addItem(item)
        return item

    def lines(self, lines: List[str], x: float, y: float, color: QColor, size: float, bold: bool = False,
              key: str = "") -> float:
        """Text lines one under another; returns the y below them."""
        step = QFontMetricsF(_font(size, bold)).height()
        for line in lines:
            self.text(line, x, y, color, size, bold, key)
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
        self._tag(item, "", tags)
        self.scene.addItem(item)

    @staticmethod
    def _tag(item: QGraphicsItem, key: str, tags: Optional[Set[str]]) -> None:
        if key:
            item.setData(KEY, key)
        if tags:
            item.setData(TAGS, frozenset(tags))


STEP_GROUPS = {"app": "The app's steps (every data pack)", "pack": "This data pack's steps",
               "modules": "From linked modules"}
FILL_TEXT = {"set": "fills in per {set}", "paper": "fills in across the paper", "none": ""}
MANY = 99                                        # every line (the header, a lane's note)
OPEN_LINES = 3                                   # an opened node: at most this many lines under its name


def brief(text: str) -> str:
    """The first sentence of a description, without its asides in brackets (the other tabs have it whole)."""
    import re
    first = re.split(r"(?<=[.;])\s+(?=[A-Z])", (text or "").strip(), maxsplit=1)[0].rstrip(".;")
    first = re.sub(r"^Extracts (the )?", "", re.sub(r"\s*\([^)]*\)", "", first).strip())   # what, not 'Extracts ...'
    return first[:1].upper() + first[1:]


def opened_lines(about: str, facts: List[str], font: QFont, width: float) -> List[str]:
    """An opened node's lines: a brief description over its facts (a line each), OPEN_LINES at most."""
    fact_lines = [line for fact in facts for line in wrap(fact, font, width, 2)]
    about = about[:1].upper() + about[1:]
    return (wrap(about, font, width, max(1, OPEN_LINES - len(fact_lines))) if about else []) + fact_lines


def _card_fill(pal: QPalette) -> QColor:
    """Steps' and cards' ground: the base colour in a light theme; in a dark one a shade lighter than the window
    (the base, darker, made a lit card look like a hole among faded ones)."""
    window = pal.color(QPalette.ColorRole.Window)
    if window.lightness() < 128:
        return _mix(window, pal.color(QPalette.ColorRole.Text), 0.07)
    return pal.color(QPalette.ColorRole.Base)


def build_scene(pack, palette: Optional[QPalette] = None, opened: Optional[Set[str]] = None) -> QGraphicsScene:
    """The pack's structure (structure_of) drawn on a new scene; `scene.relations` {key: related keys} for hovering.
    Steps and cards show their name (and a short line); the ones in `opened` (keys) show everything."""
    s = structure_of(pack)
    opened = opened or set()
    pal = palette or QApplication.palette()
    text = pal.color(QPalette.ColorRole.Text)
    window = pal.color(QPalette.ColorRole.Window)
    card = _card_fill(pal)
    muted = _mix(text, window, 0.42)
    line = _mix(text, window, 0.72)
    accent = pal.color(QPalette.ColorRole.Highlight)
    colors = _source_colors(s.steps, pal)
    scene = QGraphicsScene()
    scene.setBackgroundBrush(QBrush(window))
    d = _Drawing(scene)
    units = pack.manifest.units or {}
    set_word = units.get("set", "set")
    width = COL_LANES + LANES_W
    sub_font, sub_h = _font(SUB_PT), QFontMetricsF(_font(SUB_PT)).height()

    # title, what the picture shows, the colours' legend (wrapped to the picture's width)
    y = d.lines([s.title], COL_PAPER, 0, text, 17, True)
    y = d.lines(wrap("How a paper's data is read and organised. Lines: which kinds of value each step fills "
                     "(dashed: only through its 'other values' answers). Hover over a step or a kind of value to "
                     "follow it; click one for its details.", _font(11.5), width, MANY),
                COL_PAPER, y + 4, muted, 11.5) + 6
    x = COL_PAPER
    for src in ["app", "pack"] + [k for k in colors if k not in ("app", "pack")]:
        name = "the app" if src == "app" else "this data pack" if src == "pack" else f"module: {src}"
        w = 18 + QFontMetricsF(_font(10.5)).horizontalAdvance(name) + 18
        if x + w > width and x > COL_PAPER:
            x, y = COL_PAPER, y + 20
        d.box(QRectF(x, y + 3, 11, 11), colors[src], colors[src], radius=3)
        d.text(name, x + 17, y, muted, 10.5)
        x += w
    top = y + 34

    paper_rect = QRectF(COL_PAPER, top, PAPER_W, 84)
    d.box(paper_rect, card, line, 10).setData(TARGET, "paper")
    d.text("The paper", COL_PAPER + 12, top + 10, text, 13, True)
    d.lines(["text · tables", "figures", "(+ supplement)"], COL_PAPER + 12, top + 32, muted, 10.5)

    # steps: the name; opened, where it comes from, when it runs and what it asks
    y = top
    step_out: Dict[str, QPointF] = {}
    name_font = _font(NAME_PT, True)
    name_h = QFontMetricsF(name_font).height()
    tag_font = _font(8.5, True)
    tag_w = QFontMetricsF(tag_font).horizontalAdvance("BUILT-IN") + 10
    group = None
    for st in s.steps:
        key = f"step:{st.name}"
        is_open = key in opened
        here = "app" if st.source == "app" else "pack" if st.source == "pack" else "modules"
        if here != group:                        # a heading where the steps' source changes
            if group is not None:
                y += 10
            group = here
            d.text(STEP_GROUPS[here], COL_STEPS, y, muted, 10.5, True)
            y += 20
        source = ("App, with this data pack's prompt" if st.own_prompt else "App") if st.source == "app" else \
            "Data pack" if st.source == "pack" else f"{st.source} module"
        runs = "Always" if st.when.startswith("every paper") else "Conditional"
        tag = st.built_in and st.source != "app"     # the app's are all written in code: their heading says so
        name = wrap(st.label, name_font, STEP_W - 24 - (tag_w + 6 if tag else 0), 2)
        more = opened_lines(brief(st.what), [f"Runs: {runs} · {source}"], sub_font, STEP_W - 24) if is_open else []
        height = 12 + len(name) * name_h + (len(more) * sub_h + 4 if more else 0)
        rect = QRectF(COL_STEPS, y, STEP_W, height)
        col = colors.get(st.source, text)
        d.box(rect, card, _mix(col, card, 0.35), 8, 1.2, key=key, body=True)
        d.box(QRectF(COL_STEPS, y, 6, height), col, col, 3, key=key)
        if tag:                                  # written in the app's code, not a configurable step
            d.box(QRectF(rect.right() - tag_w - 8, y + 8, tag_w, 15), card, muted, 7.5, 0.8, key=key)
            d.text("BUILT-IN", rect.right() - tag_w - 3, y + 9, muted, 8.5, True, key)
        ty = d.lines(name, COL_STEPS + 15, y + 6, text, NAME_PT, True, key)
        d.lines(more, COL_STEPS + 15, ty + 3, muted, SUB_PT, False, key)
        step_out[st.name] = QPointF(rect.right(), rect.top() + 6 + name_h * min(len(name), 2) / 2)  # opened or not
        d.curve(QPointF(paper_rect.right(), paper_rect.center().y()), QPointF(rect.left(), step_out[st.name].y()),
                line, 1.0, tags={key})
        y += height + STEP_GAP
    if s.calculations:                           # calculations: chips; opened, each with what it does
        key = "calcs"
        y += 6
        d.text("On your computer (no request, free)", COL_STEPS, y, muted, 10.5, True, key)
        y += 20
        x = COL_STEPS
        chip_font = _font(10)
        for label, source, what in s.calculations:
            col = colors.get(source, text)
            w = QFontMetricsF(chip_font).horizontalAdvance(label) + 18
            if key in opened:
                d.box(QRectF(COL_STEPS, y + 4, 7, 7), col, col, 3.5, key=key)
                d.text(label, COL_STEPS + 14, y, text, 10, True, key)
                y = d.lines(wrap(brief(what), sub_font, CALCS_W - 14, 2), COL_STEPS + 14, y + 15, muted, SUB_PT,
                            False, key) + 5
                continue
            if x + w > COL_STEPS + CALCS_W and x > COL_STEPS:
                x, y = COL_STEPS, y + 25
            d.box(QRectF(x, y, w, 20), window, _mix(col, window, 0.35), 10, 1.0, dashed=True, key=key)
            d.text(label, x + 9, y + 3, text, 10, key=key)
            x += w + 5

    # levels as lanes, the kinds of value in them
    y = top
    card_in: Dict[str, QPointF] = {}
    lane_tops: List[float] = []
    lane_kinds: Dict[str, Set[str]] = {}
    ports: Dict[int, Set[str]] = {}

    def fillers(k: Kind) -> Tuple[List[Step], List[Step]]:
        return [st for st in s.steps if k.id in st.kinds], [st for st in s.steps if k.id in st.other_kinds]

    def card_text(k: Kind, lane: str) -> Tuple[List[str], List[str]]:
        """(name lines, detail lines) for a card, opened or not."""
        is_open = f"kind:{k.id}" in opened
        full, other = fillers(k)
        dots = min(len(full or other), 6)
        name = wrap(k.label, name_font, CARD_W - 22 - 9 * dots, 2)
        count = f"{k.columns} column{'s' if k.columns != 1 else ''}" if k.columns else "no columns yet"
        fill = FILL_TEXT.get(k.fill, "").format(set=set_word)
        if not is_open:
            return name, wrap(" · ".join(x for x in (count, fill) if x), sub_font, CARD_W - 18, 2)
        facts = [f"{count[:1].upper()}{count[1:]} · Level: {lane[:1].upper()}{lane[1:]}"]   # the pack's words
        fills = {"set": f"within each {set_word}", "paper": "across the whole paper"}
        if k.fill in fills:
            facts.append(f"Fills in: {fills[k.fill]}")
        return name, opened_lines(brief(k.description), facts, sub_font, CARD_W - 18)

    for i, (lid, label, note) in enumerate(s.levels):
        cards = [k for k in s.kinds if k.level == lid]
        rows = [cards[r:r + PER_ROW] for r in range(0, len(cards), PER_ROW)]
        texts = {k.id: card_text(k, label) for k in cards}
        card_h = {k.id: 14 + len(texts[k.id][0]) * name_h + len(texts[k.id][1]) * sub_h for k in cards}
        row_heights = [max(card_h[k.id] for k in row) for row in rows]
        title = label[:1].upper() + label[1:]
        title_w = QFontMetricsF(_font(13, True)).horizontalAdvance(title)
        note_lines = wrap(note, _font(10.5), LANES_W - 2 * LANE_PAD - title_w - 20, MANY) if note else []
        lane_title = max(LANE_TITLE, 10 + len(note_lines) * QFontMetricsF(_font(10.5)).height() + 6)
        is_run = lid == "run"
        empty = [] if cards else wrap(
            "(nothing recorded here: what its rows hold sits in the lanes above and below)" if not is_run
            else f"(it holds the {units.get('run_row') or units.get('sample', 'sample')}s of one "
                 f"{units.get('run', 'run')}; values they all share sit on it)",
            _font(10.5), LANES_W - 2 * LANE_PAD, MANY)
        height = lane_title + (sum(h + CARD_GAP for h in row_heights) if cards else len(empty) * 16 + 4) + LANE_PAD
        tint = _mix(window, accent, 0.04 + 0.03 * (len(s.levels) - 1 - i))
        before = set(scene.items())
        d.box(QRectF(COL_LANES, y, LANES_W, height), tint, line, 12, 1.0, dashed=is_run).setData(TARGET, f"level:{lid}")
        d.text(title, COL_LANES + LANE_PAD, y + 7, text, 13, True)
        d.lines(note_lines, COL_LANES + LANE_PAD + title_w + 20, y + 10, muted, 10.5)
        d.lines(empty, COL_LANES + LANE_PAD, y + lane_title, muted, 10.5)
        for item in set(scene.items()) - before:
            item.setData(LANE, lid)
        lane_kinds[lid] = {f"kind:{k.id}" for k in cards}
        lane_tops.append(y)
        cy = y + lane_title
        for row, row_h in zip(rows, row_heights):
            for j, k in enumerate(row):
                key = f"kind:{k.id}"
                cx = COL_LANES + LANE_PAD + j * (CARD_W + CARD_GAP)
                # the closed cards of a row alike in height; an opened one as tall as its text
                closed = [card_h[c.id] for c in row if f"kind:{c.id}" not in opened]
                own_h = card_h[k.id] if f"kind:{k.id}" in opened else max(closed)
                rect = QRectF(cx, cy, CARD_W, own_h)
                full, other = fillers(k)
                d.box(rect, card, line, 8, 1.0, key=key, body=True)
                for n, st in enumerate((full or other)[:6]):           # a dot per step: hollow for 'other values'
                    dot = colors.get(st.source, text)
                    d.box(QRectF(cx + CARD_W - 12 - n * 9, cy + 8, 7, 7), dot if full else card, dot, 3.5,
                          tags={key, f"step:{st.name}"})
                name, details = texts[k.id]
                ty = d.lines(name, cx + 9, cy + 6, text, NAME_PT, True, key)
                d.lines(details, cx + 9, ty + 1, muted, SUB_PT, False, key)
                port_y = cy + 6 + name_h / 2                # level with the row's first line: one port a row
                card_in[k.id] = QPointF(COL_LANES, port_y)
                ports.setdefault(round(port_y), set()).add(key)
            cy += row_h + CARD_GAP
        y += height + 10

    # lines and where they come in
    relations: Dict[str, Set[str]] = {}
    for st in s.steps:
        key = f"step:{st.name}"
        start = step_out[st.name]
        col = QColor(colors.get(st.source, text))
        col.setAlpha(170)
        if st.makes_rows:
            for (lid, _label, _note), top_y in list(zip(s.levels, lane_tops))[1:]:
                d.curve(start, QPointF(COL_LANES, top_y + 14), col, 1.6, tags={key})
                relations.setdefault(key, set()).add(f"level:{lid}")
            continue
        faint = QColor(col)
        faint.setAlpha(90)
        for cid, dashed in [(c, False) for c in st.kinds] + [(c, True) for c in st.other_kinds]:
            if cid in card_in:
                d.curve(start, card_in[cid], faint if dashed else col, 1.1 if dashed else 1.5, dashed=dashed,
                        tags={key, f"kind:{cid}"})
                relations.setdefault(key, set()).add(f"kind:{cid}")
                relations.setdefault(f"kind:{cid}", set()).add(key)
    for y_mid, keys in ports.items():
        d.box(QRectF(COL_LANES - 4, y_mid - 4, 8, 8), line, line, 4, tags=set(keys)).setZValue(2)
    scene.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
    scene.relations = relations
    scene.accent = accent
    scene.structure = s
    scene.lane_kinds = lane_kinds
    return scene


class StructureCanvas(QGraphicsView):
    """The structure picture of one data pack: hover a step or a kind of value to follow it (the rest fades), click
    it for its details (again to close); pinch or Ctrl+wheel to zoom, drag to move; fitted to its space until
    zoomed."""

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
        self._pack = None
        self._pressed = None
        self._clicked: Optional[str] = None
        self.opened: Set[str] = set()
        # target -> [(menu text, what it does)]: the first runs on a double-click, all are on the right-click menu
        # (the pack editor sets it: its tabs)
        self.actions_for: Optional[Callable[[str], List[Tuple[str, Callable[[], None]]]]] = None
        if pack is not None:
            self.show_pack(pack)

    def show_pack(self, pack) -> None:
        self._pack = pack
        # what was open stays open over a Save (a step or kind no longer there: nothing)
        self.setScene(build_scene(pack, self.palette(), self.opened))
        self._hovered = None
        self.fit()

    # ---- opening a step or a kind of value -------------------------------------------------------------------------

    def toggle(self, key: str) -> None:
        """Open `key` (show all it says) or close it; the view stays where it is."""
        if self._pack is None:
            return
        self.opened ^= {key}
        centre = self.mapToScene(self.viewport().rect().center())
        transform = self.transform()
        self.setScene(build_scene(self._pack, self.palette(), self.opened))
        self.setTransform(transform)
        self.centerOn(centre)
        self._follow = False                # the picture changed size: keep the zoom until Fit
        hovered, self._hovered = self._hovered, None
        self.highlight(hovered)
        for item in self.scene().items():
            if item.data(KEY) == key and item.data(BODY):
                self.ensureVisible(item.sceneBoundingRect(), 16, 16)
                break

    def mousePressEvent(self, event) -> None:
        self._pressed = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        pos, self._pressed = event.position().toPoint(), self._pressed
        self._clicked = None
        if event.button() == Qt.MouseButton.LeftButton and self._pressed is not None \
                and (pos - self._pressed).manhattanLength() <= 4:
            key = self.key_at(pos)
            if key:
                self.toggle(key)
                self._clicked = key
        self._pressed = None

    # ---- going to where a part is edited (the pack editor's tabs) ---------------------------------------------------

    def target_at(self, pos) -> Optional[str]:
        """What a double-click or right-click at `pos` is about: a step, a kind of value, the calculations, a level
        ("level:<id>") or the paper."""
        for item in self.items(pos):
            key = item.data(KEY) or item.data(TARGET)
            if key:
                return key
        return None

    def mouseDoubleClickEvent(self, event) -> None:
        """The first of the two places the right-click menu offers: the tab where it's edited."""
        target = self.target_at(event.position().toPoint())
        if target and target == self._clicked:
            self.toggle(target)                      # the double-click's first click opened it: as it was
        self._clicked = None
        actions = self.actions_for(target) if target and self.actions_for else []
        if actions:
            actions[0][1]()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        target = self.target_at(event.pos())
        actions = self.actions_for(target) if target and self.actions_for else []
        if not actions:
            return
        menu = QMenu(self)
        for text, run in actions:
            menu.addAction(text, run)
        menu.exec(event.globalPos())

    # ---- following a step or a kind of value ---------------------------------------------------------------------

    def key_at(self, pos) -> Optional[str]:
        for item in self.items(pos):
            key = item.data(KEY)
            if key:
                return key
        return None

    def highlight(self, key: Optional[str]) -> None:
        """Light up `key` (a step or a kind of value), what it connects to and the lines between, and outline it;
        fade the other steps, cards, lines and dots. None: everything as drawn."""
        scene = self.scene()
        if scene is None or key == self._hovered:
            return
        self._hovered = key
        related = ({key} | getattr(scene, "relations", {}).get(key, set())) if key else set()
        accent = getattr(scene, "accent", self.palette().color(QPalette.ColorRole.Highlight))
        lane_kinds = getattr(scene, "lane_kinds", {})
        for item in scene.items():
            own, tags = item.data(KEY), item.data(TAGS)
            if item.data(BODY):
                item.setPen(QPen(accent, 2.2) if key and own == key else item.data(PEN))
            if key is None:
                item.setOpacity(1.0)
            elif own:
                item.setOpacity(1.0 if own in related else FADED)
            elif tags:
                item.setOpacity(1.0 if key in tags else FADED)
            elif item.data(LANE):                   # a level: lit when it holds what's lit (the row plan: every level)
                lane = item.data(LANE)
                lit = f"level:{lane}" in related or related & lane_kinds.get(lane, set())
                item.setOpacity(1.0 if lit else FADED)

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


def render_png(pack, path, palette: Optional[QPalette] = None, scale: float = 2.0,
               opened: Optional[Set[str]] = None) -> None:
    """The picture as an image file (mockups, docs)."""
    from PySide6.QtGui import QImage
    scene = build_scene(pack, palette, opened)
    rect = scene.sceneRect()
    image = QImage(int(rect.width() * scale), int(rect.height() * scale), QImage.Format.Format_ARGB32)
    image.fill(scene.backgroundBrush().color())
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
    painter.end()
    image.save(str(path))
