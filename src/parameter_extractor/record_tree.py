"""
A paper's data as a tree of levels and facets (branch levels-and-facets, step 1; Mickey, 2026-11-18: "structuring our
rows or experiments in a more object-oriented format ... as long as the formatting is known, we could still crunch each
paper's object down into a flat .csv").

LEVELS are what contains what: Paper > Set > Sample by default, named by the data pack ('planetary system' >
'planet'); a pack may declare its own (`levels` in pack.json; at most MAX_LEVELS unless the pack's `level_limit` says
more). The deepest level is the dataset's row.

FACETS are the kinds of values -- the pack's variable categories (metadata, methodology, conditions, starting species,
products, ...) plus the row block ('row': what a set varies) and provenance. Each has a LEVEL: the highest level its
values may sit at (metadata at the paper, methods and conditions at the set, measured products at the row; a category
without one stays on the rows). A value sits as high as it can within that: at a node when every row under it has the
same value with the same provenance (source, quote, page, confidence...), otherwise lower down. So nothing is lost or
merged: flattening -- each row with what its ancestors hold -- gives back exactly the observations the tree was built
from (ingestion/observations.py, the run's canonical record), and from them the same dataset CSV.

This step changes nothing the model is asked and nothing in the CSVs: the tree is built from what a run already
produces, and written beside them as <paper>_record.json (a queue: combined_record.json), the nested form JSON-based
data platforms take.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from parameter_extractor.ingestion.observations import Observation

FORMAT = "parameter-extractor/record"
FORMAT_VERSION = 1
MAX_LEVELS = 4                      # the default limit; a pack's `level_limit` raises it (an advanced pack setting)
ROW_FACET, PROVENANCE_FACET = "row", "provenance"
# an observation's fields besides its row and column: what must match for a value to be shared by rows
PAYLOAD = ("value", "unit", "origin", "source", "page", "quote", "quote_in_paper", "confidence")


@dataclass
class Level:
    id: str
    label: str


def check_levels(levels: List[dict], limit: int = 0) -> List[str]:
    """Problems with a pack's declared levels (pack_editing.check): ids and labels, unique ids, at least two levels
    (the paper and the rows), at most `limit` (MAX_LEVELS when 0)."""
    limit = limit or MAX_LEVELS
    problems = []
    ids = [str(lv.get("id", "")).strip() for lv in levels]
    if len(levels) < 2:
        problems.append("levels: at least two (the paper and the rows)")
    if len(levels) > limit:
        problems.append(f"levels: {len(levels)} declared, at most {limit} (raise the pack's level_limit for more)")
    if any(not i for i in ids) or any(not str(lv.get("label", "")).strip() for lv in levels):
        problems.append("levels: every level needs an id and a label")
    if len(set(ids)) != len(ids):
        problems.append("levels: two levels with the same id")
    return problems


def levels(pack=None) -> List[Level]:
    """The pack's levels, top (the paper) to bottom (the dataset's row): declared in pack.json, else the paper and
    the pack's two words for a set and a sample (`units`)."""
    from parameter_extractor import packs
    manifest = (pack or packs.current()).manifest
    declared = getattr(manifest, "levels", None) or []
    if declared:
        return [Level(str(lv["id"]), str(lv["label"])) for lv in declared]
    units = manifest.units or {}
    return [Level("paper", "paper"), Level("set", units.get("set", "set")),
            Level("sample", units.get("sample", "sample"))]


class Facets:
    """Which facet a column belongs to, and the highest level its values may sit at (an index into the levels)."""

    def __init__(self, order, level_list: List[Level]):
        from parameter_extractor.column_order import (IDENTIFIERS, IDENTIFIERS_LABEL, PROVENANCE,
                                                      PROVENANCE_LABEL)
        from parameter_extractor.ingestion.flatten_to_template import OPTIONAL_PROVENANCE_COLUMNS
        self.order = order
        self.levels = level_list
        self.row = len(level_list) - 1
        index = {lv.id: i for i, lv in enumerate(level_list)}
        self._identifiers = set(IDENTIFIERS)
        self._provenance = set(PROVENANCE) | set(OPTIONAL_PROVENANCE_COLUMNS)
        self.labels = {ROW_FACET: IDENTIFIERS_LABEL, PROVENANCE_FACET: PROVENANCE_LABEL}
        # what a set varies belongs to the set; provenance (source notes, confidence) to each row
        self.caps = {ROW_FACET: min(1, self.row), PROVENANCE_FACET: self.row}
        chosen = dict(getattr(order.pack.manifest, "category_levels", None) or {})     # the pack's choices win
        for c in order.categories:
            self.labels[c.id] = c.label
            self.caps[c.id] = index.get(chosen.get(c.id) or getattr(c, "level", "") or "", self.row)

    def of(self, column: str) -> str:
        if column in self._identifiers:
            return ROW_FACET
        if column in self._provenance:
            return PROVENANCE_FACET
        return self.order.category_of(column)

    def cap(self, column: str) -> int:
        return self.caps.get(self.of(column), self.row)

    def described(self) -> List[dict]:
        """[{id, label, level}] for the JSON's header, in the dataset's column order."""
        out = [{"id": ROW_FACET, "label": self.labels[ROW_FACET], "level": self.levels[self.caps[ROW_FACET]].id}]
        for c in self.order.display:
            out.append({"id": c.id, "label": c.label, "level": self.levels[self.caps.get(c.id, self.row)].id})
        out.append({"id": PROVENANCE_FACET, "label": self.labels[PROVENANCE_FACET], "level": self.levels[self.row].id})
        return out


class KnownFacets:
    """The facets as a written record names them (its header and where each column sits), for writing a changed tree
    back without the data pack (corrections.py); a column it doesn't know goes under 'other'."""

    def __init__(self, level_list: List[Level], of: Dict[str, str], order: List[str],
                 facet_levels: Optional[Dict[str, str]] = None):
        self.levels, self._of, self._order = level_list, of, order
        index = {lv.id: i for i, lv in enumerate(level_list)}
        self.row = len(level_list) - 1
        self._caps = {f: index.get(lv, self.row) for f, lv in (facet_levels or {}).items()}

    def of(self, column: str) -> str:
        return self._of.get(column, "other")

    def cap(self, column: str) -> int:
        return self._caps.get(self.of(column), self.row)

    def described(self) -> List[dict]:
        return [{"id": f} for f in self._order]


@dataclass
class Node:
    level: int
    id: str
    label: str = ""
    values: Dict[str, dict] = field(default_factory=dict)       # column -> payload (PAYLOAD fields)
    children: List["Node"] = field(default_factory=list)
    # rows only: the row's ids and the order its values were in (the flat files' order; not part of the JSON)
    set_id: str = ""
    sample_id: str = ""
    entry_number: int = 0
    columns: List[str] = field(default_factory=list)


def _payload(o: Observation) -> dict:
    return {k: getattr(o, k) for k in PAYLOAD}


def build(observations: Iterable[Observation], facets: Facets,
          labels: Optional[Dict[str, str]] = None) -> Node:
    """The paper's tree from its observations: one node per set (by set_id) and per row (by full_id), in the order
    the rows come; then every value moved as high as its facet allows and its rows agree. `labels`: {set_id or
    full_id: label} (the row plan's set and sample labels, where known)."""
    labels = labels or {}
    rows: Dict[str, Node] = {}
    sets: Dict[str, Node] = {}
    paper = Node(level=0, id="")
    row_level = facets.row
    for o in observations:
        row = rows.get(o.full_id)
        if row is None:
            parent = paper
            if row_level >= 2:                       # paper > set > ... > row: the set level from set_id
                parent = sets.get(o.set_id)
                if parent is None:
                    parent = sets[o.set_id] = Node(level=1, id=o.set_id, label=labels.get(o.set_id, ""))
                    paper.children.append(parent)
            row = rows[o.full_id] = Node(level=row_level, id=o.full_id, label=labels.get(o.full_id, ""),
                                         set_id=o.set_id, sample_id=o.sample_id, entry_number=o.entry_number)
            parent.children.append(row)
        row.values[o.column] = _payload(o)
        row.columns.append(o.column)
    paper.id = _common_prefix([r.id for r in rows.values()])
    _lift(paper, facets)
    return paper


def _common_prefix(ids: List[str]) -> str:
    """The paper's prefix in its row ids ('001' of '001004002'), when every row has the same one."""
    heads = {i[:3] for i in ids if len(i) >= 3}
    return heads.pop() if len(heads) == 1 else ""


def _same(a: dict, b: dict) -> bool:
    return all(type(a[k]) is type(b[k]) and a[k] == b[k] for k in PAYLOAD)


def share(paper: Node, facets) -> None:
    """Values every row under a node now agrees on move up again (after corrections changed rows one by one)."""
    _lift(paper, facets)


def _lift(node: Node, facets) -> None:
    """Bottom-up: a column every child holds, with the same value and provenance, moves up to this node -- if its
    facet may sit this high."""
    if not node.children:
        return
    for child in node.children:
        _lift(child, facets)
    first = node.children[0]
    for column in list(first.values):
        if facets.cap(column) > node.level:
            continue
        payload = first.values[column]
        if all(column in c.values and _same(c.values[column], payload) for c in node.children[1:]):
            node.values[column] = payload
            for c in node.children:
                del c.values[column]


def _rows(node: Node, inherited: Dict[str, dict]):
    here = {**inherited, **node.values}
    if not node.children:
        yield node, here
    for child in node.children:
        yield from _rows(child, here)


def flatten(paper: Node, column_order=None) -> List[Observation]:
    """Every row with what its ancestors hold, as observations -- in each row's own order (a tree built here), or
    `column_order` (a ColumnOrder: a tree read from JSON, which keeps no order within a row)."""
    out = []
    for row, values in _rows(paper, {}):
        columns = row.columns or (column_order.ordered(values) if column_order is not None else list(values))
        for column in columns:
            out.append(Observation(full_id=row.id, set_id=row.set_id, sample_id=row.sample_id,
                                   entry_number=row.entry_number, column=column, **values[column]))
    return out


# ---- the JSON ---------------------------------------------------------------------------------------------------------

def _compact(payload: dict) -> dict:
    """A value with only the provenance it has ({'value': 2.5, 'unit': 'mM', 'source': 'Table 1', ...})."""
    return {k: v for k, v in payload.items() if k == "value" or v not in ("", None)}


def _expand(compact: dict) -> dict:
    out = {k: "" for k in PAYLOAD}
    out["confidence"] = None
    out.update(compact)
    return out


def node_json(node: Node, facets) -> dict:
    lv = facets.levels[node.level]
    out = {"level": lv.id, "id": node.id}
    if node.label:
        out["label"] = node.label
    if not node.children:
        if node.level < 2:                           # no set level above it: the row keeps its set's id
            out["set_id"] = node.set_id
        out["sample_id"], out["entry_number"] = node.sample_id, node.entry_number
    grouped: Dict[str, dict] = {}
    for column, payload in node.values.items():
        grouped.setdefault(facets.of(column), {})[column] = _compact(payload)
    order = [f["id"] for f in facets.described()]
    out["facets"] = {f: grouped[f] for f in sorted(grouped, key=lambda f: order.index(f) if f in order else 10**6)}
    if node.children:
        out["children"] = [node_json(c, facets) for c in node.children]
    return out


def to_json(paper: Node, facets: Facets, about: Optional[dict] = None) -> dict:
    """The nested record: its format, the levels and facets it uses, then the paper with its sets and rows."""
    return {"format": FORMAT, "format_version": FORMAT_VERSION, **(about or {}),
            "levels": [{"id": lv.id, "label": lv.label} for lv in facets.levels],
            "facets": facets.described(),
            "paper": node_json(paper, facets)}


def from_json(data: dict) -> Node:
    """The tree back from its JSON (no order within a row: flatten it with a ColumnOrder)."""
    level_ids = [lv["id"] for lv in data["levels"]]

    def node(d: dict, set_id: str) -> Node:
        level = level_ids.index(d["level"])
        set_id = d["id"] if level == 1 and d.get("children") else set_id
        n = Node(level=level, id=d["id"], label=d.get("label", ""), set_id=d.get("set_id", set_id),
                 sample_id=d.get("sample_id", ""), entry_number=d.get("entry_number", 0))
        for _facet, values in d.get("facets", {}).items():
            for column, compact in values.items():
                n.values[column] = _expand(compact)
        n.children = [node(c, set_id) for c in d.get("children", [])]
        return n
    return node(data["paper"], "")


def write(observations: List[Observation], path: Path, order, labels: Optional[Dict[str, str]] = None,
          about: Optional[dict] = None) -> dict:
    """<paper>_record.json from a run's observations; returns the JSON written."""
    facets = Facets(order, levels(order.pack))
    data = to_json(build(observations, facets, labels), facets, about)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def plan_labels(structure, observations: Iterable[Observation]) -> Dict[str, str]:
    """{set_id: set label, full_id: sample label} from the row plan, for the rows that came from it (a set id's last
    three digits are its place in the plan, a sample id's its place in the set; rows from figures and other sources
    are numbered after the plan's sets and get no label)."""
    out: Dict[str, str] = {}
    plan = getattr(structure, "experiment_sets", None) or []
    for o in observations:
        s, k = o.set_id[-3:], o.sample_id[-3:]
        if not (s.isdigit() and 0 < int(s) <= len(plan)):
            continue
        pset = plan[int(s) - 1]
        out.setdefault(o.set_id, pset.set_label)
        if k.isdigit() and 0 < int(k) <= len(pset.samples):
            out.setdefault(o.full_id, pset.samples[int(k) - 1].sample_label)
    return out


def combine(records: List[dict]) -> dict:
    """A queue's papers in one record (combined_record.json): the first paper's levels and facets, every paper."""
    if not records:
        return {"format": FORMAT, "format_version": FORMAT_VERSION, "papers": []}
    head = {k: v for k, v in records[0].items() if k in ("format", "format_version", "levels", "facets")}
    return {**head, "papers": [{k: v for k, v in r.items() if k not in head} for r in records]}


def node_path(paper: Node, full_id: str) -> List[Node]:
    """The nodes from the paper down to a row."""
    def walk(n: Node, path: List[Node]):
        if not n.children:
            return path + [n] if n.id == full_id else None
        for c in n.children:
            found = walk(c, path + [n])
            if found:
                return found
        return None
    return walk(paper, []) or []


def set_value(paper: Node, full_id: str, column: str, payload: Optional[dict]) -> bool:
    """One row's value changed (a reviewer's correction; None removes it): a value its ancestors hold for several
    rows is first handed down to each of them, so only this row changes. False when the row isn't in the tree."""
    path = node_path(paper, full_id)
    if not path:
        return False
    for i, n in enumerate(path[:-1]):
        if column in n.values:                       # held higher up: down one level at a time, to every child
            held = n.values.pop(column)
            for c in n.children:
                c.values.setdefault(column, dict(held))
    row = path[-1]
    if payload is None:
        row.values.pop(column, None)
        if column in row.columns:
            row.columns.remove(column)
    else:
        row.values[column] = payload
        if row.columns and column not in row.columns:
            row.columns.append(column)                # a value the extraction left empty: last in its row
    return True
