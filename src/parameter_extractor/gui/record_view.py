"""
The results by experiment (branch levels-and-facets, step 2; Mickey, 2026-11-18: "displaying the experimental data /
structure in a way that's easy to understand and intuitive to change or edit for someone ... without experience using
this specific app").

The paper's record (record_tree.py, <paper>_record.json) as the paper reads: on the left the paper, its sets (the pack's
word: 'experiment set', 'planetary system') and their rows ('sample', 'planet'), each with its label from the paper and
how many things to check it has; on the right everything that applies to the one selected, grouped by kind of value
(conditions, products, ...), each with a name in words, its amount and unit, and what it's recorded for -- this sample,
or its set ('all 3 samples'), or the paper; below, where the selected value came from.

Double-click an amount to correct it: a value shared by several rows asks whether to change it for all of them or only
for the rows under the selection. Right-click a corrected value to undo it. Corrections go through corrections.py like
the table's (the CSVs, the record and corrections.json together), so both tabs always show the same data.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox, QSplitter,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

NODE_ROLE = Qt.ItemDataRole.UserRole
VALUE_ROLE = Qt.ItemDataRole.UserRole + 1


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:]


def plural(word: str, n: int = 2) -> str:
    if n == 1:
        return word
    return word + ("es" if word.endswith(("s", "x", "ch", "sh")) else "s")


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def _text(value) -> str:
    """A value as the dataset writes it (the CSV's text): what corrections compare with."""
    return "" if value is None else str(value)


class RecordView(QWidget):
    """The Experiment sets tab (its title follows the data pack: see title_for)."""
    corrected = Signal()                       # a value was corrected or a correction undone: refresh the table

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.registry_path: Optional[Path] = None
        self._data: Optional[dict] = None
        self._paper = None
        self._parent: Dict[int, object] = {}
        self._filling = False
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 0)
        self.intro = QLabel(wordWrap=True, textFormat=Qt.TextFormat.RichText)
        v.addWidget(self.intro)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._show_node(cur))
        split.addWidget(self.tree)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel(wordWrap=True, textFormat=Qt.TextFormat.RichText)
        rv.addWidget(self.heading)
        self.values = QTreeWidget()
        self.values.setHeaderLabels(["Value", "Amount", "Unit", "Recorded for"])
        self.values.setRootIsDecorated(False)
        self.values.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.values.itemDoubleClicked.connect(self._start_edit)
        self.values.itemChanged.connect(self._edited)
        self.values.currentItemChanged.connect(lambda cur, _prev: self._show_source(cur))
        self.values.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.values.customContextMenuRequested.connect(self._menu)
        head = self.values.header()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in (2, 3):
            head.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.values.setColumnWidth(0, 300)
        vsplit = QSplitter(Qt.Orientation.Vertical)    # the values get most of the room; drag to change it
        vsplit.addWidget(self.values)
        self.source = QTextBrowser(placeholderText="Select a value to see where in the paper it came from.")
        self.source.setMinimumHeight(48)
        vsplit.addWidget(self.source)
        vsplit.setStretchFactor(0, 4)
        vsplit.setStretchFactor(1, 1)
        rv.addWidget(vsplit, 1)
        split.addWidget(right)
        split.setSizes([330, 700])
        v.addWidget(split, 1)

    # ---- the record ---------------------------------------------------------------------------------------------

    @staticmethod
    def title_for(pack) -> str:
        """The tab's title: the pack's word for a set, plural ('Experiment sets', 'Planetary systems')."""
        from parameter_extractor import record_tree
        try:
            word = record_tree.levels(pack)[1].label if len(record_tree.levels(pack)) > 2 else "experiment"
        except Exception:                             # noqa: BLE001
            word = "experiment set"
        return _cap(plural(word))

    def show_result(self, result, registry_path: Optional[Path] = None) -> None:
        self.result, self.registry_path = result, registry_path
        self._load()
        self._fill()

    def _load(self) -> None:
        """The run's record: <paper>_record.json, or -- a run from before it existed -- made from its observations
        file (an opened folder: the run's own record of every value, corrections included) or its rows, and written
        into the run's folder with its corrections marked (so later corrections reach it)."""
        from parameter_extractor import packs, record_tree
        r = self.result
        path = getattr(r, "record_path", None)
        if path and Path(path).is_file():
            self._data = json.loads(Path(path).read_text(encoding="utf-8"))
        else:
            self._data = self._make_record()
        self._paper = record_tree.from_json(self._data)
        self._parent = {}
        self._facet_of: Dict[str, str] = {}

        def walk(node, d):
            for facet, values in d.get("facets", {}).items():
                for column in values:
                    self._facet_of[column] = facet
            for child, cd in zip(node.children, d.get("children", [])):
                self._parent[id(child)] = node
                walk(child, cd)
        walk(self._paper, self._data["paper"])
        self._facet_labels = {f["id"]: f.get("label", f["id"]) for f in self._data.get("facets", [])}
        self._facet_order = [f["id"] for f in self._data.get("facets", [])]
        self._words = [lv["label"] for lv in self._data.get("levels", [])]

    def _make_record(self) -> dict:
        import csv
        from parameter_extractor import corrections as corr, packs, record_tree
        from parameter_extractor.column_order import ColumnOrder
        from parameter_extractor.ingestion.observations import read_observations_csv, rows_to_observations
        r = self.result
        pack = packs.available().get(getattr(r, "pack", "") or "") or packs.current()
        order = ColumnOrder(pack=pack, chosen={a["column"]: a.get("category", "") for a in r.accepted_variables})
        facets = record_tree.Facets(order, record_tree.levels(pack))
        obs_path = getattr(r, "observations_path", None)
        if obs_path and Path(obs_path).is_file():
            entries = {}
            if r.csv_path and Path(r.csv_path).is_file():
                with open(r.csv_path, newline="", encoding="utf-8") as f:
                    entries = {row.get("full_id", ""): row.get("entry_number", "") for row in csv.DictReader(f)}
            observations = read_observations_csv(Path(obs_path), {k: v for k, v in entries.items() if v})
        elif r.rows and not hasattr(r.rows[0], "model_dump"):       # an old folder's saved rows, no observations
            from parameter_extractor.ingestion.observations import Observation, _typed
            observations = [Observation(full_id=row.full_id, set_id=row.set_id, sample_id=row.sample_id,
                                        entry_number=i, column=c, value=_typed(str(v)))
                            for i, row in enumerate(r.rows, 1) for c, v in row.values.items()
                            if v not in ("", None) and c not in ("full_id", "set_id", "sample_id", "entry_number")]
        else:
            observations = rows_to_observations(r.rows)
        data = record_tree.to_json(record_tree.build(observations, facets), facets,
                                   {"paper": r.paper_id, "data_pack": pack.id})
        if r.run_dir and Path(r.run_dir).is_dir() and r.csv_path:
            r.record_path = Path(r.csv_path).with_name(Path(r.csv_path).name.replace("_extracted.csv", "_record.json"))
            r.record_path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            fixes = corr.load(r.run_dir)
            if fixes:                                  # marked as corrected, with the extracted value beside them
                corr._write_record(r.record_path, [(c, True) for c in fixes.values()])
                data = json.loads(r.record_path.read_text(encoding="utf-8"))
        return data

    # ---- the tree on the left -----------------------------------------------------------------------------------

    def _rows_under(self, node) -> List:
        if not node.children:
            return [node]
        return [leaf for c in node.children for leaf in self._rows_under(c)]

    def _flags(self, node) -> int:
        flags = getattr(self.result, "row_flags", {}) or {}
        return sum(len(flags.get(leaf.id, [])) for leaf in self._rows_under(node))

    def _word(self, node) -> str:
        return self._words[node.level] if node.level < len(self._words) else "item"

    def _title(self) -> str:
        meta = self._paper.values.get("paper_title")
        return str(meta["value"]) if meta else (self._data.get("paper") or {}).get("id", "") or "this paper"

    def _fill(self, keep: Optional[str] = None) -> None:
        self._filling = True
        try:
            self.tree.clear()
            paper = self._paper
            rows = self._rows_under(paper)
            set_word = self._words[1] if len(self._words) > 2 else ""
            row_word = self._words[-1] if self._words else "row"
            sets = paper.children if set_word else []
            top = QTreeWidgetItem([f"Paper: {self._title()}"])
            top.setData(0, NODE_ROLE, paper)
            bold = QFont()
            bold.setBold(True)
            top.setFont(0, bold)
            self.tree.addTopLevelItem(top)
            current = top
            def add(parent_item, node):                # any depth: a set, its runs (if any), their samples
                found = None
                for i, child in enumerate(node.children, 1):
                    item = self._node_item(child, i)
                    parent_item.addChild(item)
                    if keep == child.id:
                        found = item
                    found = add(item, child) or found
                    item.setExpanded(len(rows) <= 60)
                return found
            current = add(top, paper) or current
            top.setExpanded(True)
            if sets:
                what = (f"the paper, its {len(sets)} {plural(set_word, len(sets))} and their {len(rows)} "
                        f"{plural(row_word, len(rows))}")
                shared = f"A value recorded for {_a(set_word)} applies to every {row_word} in it."
            else:
                what = f"the paper and its {len(rows)} {plural(row_word, len(rows))}"
                shared = ""
            self.intro.setText(
                f"<b>{html.escape(_cap(what))}.</b> {html.escape(shared)} <span style='color:gray'>Select one to see "
                f"its values; double-click an amount to correct it.</span>")
            self.tree.setCurrentItem(current)
        finally:
            self._filling = False
        self._show_node(self.tree.currentItem())

    def _node_item(self, node, n: int) -> QTreeWidgetItem:
        word = _cap(self._word(node))
        text = f"{word} {n}" + (f": {node.label}" if node.label else "")
        if node.children:
            k = len(self._rows_under(node))
            text += f"  ({k} {plural(self._words[-1], k)})"
        flags = self._flags(node)
        if flags:
            text += f"  -- {flags} to check"
        item = QTreeWidgetItem([text])
        item.setData(0, NODE_ROLE, node)
        item.setToolTip(0, f"{word} {node.id}" + (f" -- {flags} thing(s) to check (Things to check tab)" if flags
                                                  else ""))
        return item

    # ---- the values on the right ---------------------------------------------------------------------------------

    def _ancestors(self, node) -> List:
        """The node and the nodes above it, from the paper down."""
        out = [node]
        while id(out[0]) in self._parent:
            out.insert(0, self._parent[id(out[0])])
        return out

    def _seen(self, payload: dict, selected) -> dict:
        """A value as the selection has it: a row its own copy (stated, or assumed from the other rows)."""
        from parameter_extractor import record_tree
        return record_tree.resolve(payload, selected.id) if not selected.children else payload

    def _recorded_for(self, holder, selected, payload: Optional[dict] = None) -> str:
        from parameter_extractor import record_tree
        n = len(self._rows_under(holder))
        row_word = self._words[-1] if self._words else "row"
        payload = payload or {}
        mine = self._seen(payload, selected)
        if not selected.children and record_tree._is_assumed(mine):
            return f"this {row_word} -- assumed: the others state it, this one doesn't"
        if holder is selected and not holder.children:
            return f"this {row_word}"
        if holder.level == 0:
            text = f"the paper (every {row_word})" if n > 1 else "the paper"
        else:
            text = f"{'this' if holder is selected else 'its'} {self._word(holder)} (all {n} {plural(row_word, n)})"
        assumed = payload.get(record_tree.ASSUMED)
        if assumed and selected.children:
            k = len([r for r in assumed["rows"] if r in {x.id for x in self._rows_under(selected)}])
            if k:
                text += f" -- assumed for {k} of them"
        return text

    def _show_node(self, item) -> None:
        if self._filling or item is None or self._paper is None:
            return
        from parameter_extractor import column_labels
        node = item.data(0, NODE_ROLE)
        pack_id = self._data.get("data_pack", "")
        self._filling = True
        try:
            self.values.clear()
            self.source.clear()
            word = _cap(self._word(node))
            n_rows = len(self._rows_under(node))
            row_word = self._words[-1] if self._words else "row"
            if node.level == 0:
                lead = f"<b>The paper</b>: {html.escape(self._title())}"
                note = f"Values recorded once for the whole paper; select a {html.escape(self._words[1] if len(self._words) > 2 else row_word)} for more."
            elif node.children:
                lead = f"<b>{html.escape(word)}</b>" + (f": {html.escape(node.label)}" if node.label else "")
                note = (f"{n_rows} {plural(row_word, n_rows)}. Shown: what applies to all of them; what differs "
                        f"between them is listed under each {html.escape(row_word)}.")
            else:
                lead = f"<b>{html.escape(word)}</b>" + (f": {html.escape(node.label)}" if node.label else "")
                note = f"Everything recorded for this {html.escape(row_word)}, with what it shares with others."
            self.heading.setText(f"{lead}<br><span style='color:gray'>{note}</span>")
            holders = self._ancestors(node)
            on_paper = len(self._paper.values) if node.level > 0 else 0
            if node.level > 0:                       # the paper's own values are shown on the paper only
                holders = holders[1:]
            entries = [(column, payload, holder) for holder in holders for column, payload in holder.values.items()]
            groups: Dict[str, list] = {}
            for e in entries:
                groups.setdefault(self._facet_of.get(e[0], "other"), []).append(e)
            bold = QFont()
            bold.setBold(True)
            set_word = self._words[1] if len(self._words) > 2 else "set"
            labels = dict(self._facet_labels, row=f"What {'this' if node.level == 1 else 'its'} {set_word} varies",
                          provenance="Notes on how it was read")
            for facet in sorted(groups, key=lambda f: self._facet_order.index(f) if f in self._facet_order else 10**6):
                head = QTreeWidgetItem([labels.get(facet, _cap(facet))])
                head.setFont(0, bold)
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.values.addTopLevelItem(head)
                head.setFirstColumnSpanned(True)
                for column, held, holder in groups[facet]:
                    payload = self._seen(held, node)
                    name = column_labels.readable(column, pack_id)
                    corrected = bool(payload.get("corrected"))
                    shown = _text(payload.get("value"))
                    if column == "set_independent_variable":     # a column's name: in words
                        shown = ", ".join(column_labels.readable(c.strip(), pack_id) for c in shown.split(",") if c)
                    item = QTreeWidgetItem([name, shown, payload.get("unit", "") or "",
                                            self._recorded_for(holder, node, held)])
                    item.setData(0, VALUE_ROLE, (column, holder))
                    item.setToolTip(0, column)
                    if self._correctable(column):
                        item.setToolTip(1, "Double-click to correct" + (" (corrected: right-click to undo)"
                                                                       if corrected else ""))
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        item.setToolTip(1, "Worked out by the app from the other values: correct those instead")
                    if corrected:
                        f = item.font(1)
                        f.setItalic(True)
                        item.setFont(1, f)
                        item.setText(3, item.text(3) + " -- corrected")
                    if holder is not node:
                        item.setForeground(3, self.palette().placeholderText())
                    if "assumed" in item.text(3):              # not stated for (all of) it: shown lighter
                        item.setForeground(1, self.palette().placeholderText())
                    self.values.addTopLevelItem(item)
            if not entries:
                self.values.addTopLevelItem(QTreeWidgetItem([f"Nothing recorded for this {self._word(node)} "
                                                             f"itself: see its {plural(row_word)}."]))
            if on_paper:
                note = QTreeWidgetItem([f"Also {on_paper} value{'s' if on_paper != 1 else ''} recorded for the whole "
                                        f"paper (title, authors, ...): select the paper to see them."])
                note.setForeground(0, self.palette().placeholderText())
                note.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.values.addTopLevelItem(note)
                note.setFirstColumnSpanned(True)
        finally:
            self._filling = False

    def _show_source(self, item) -> None:
        if item is None or item.data(0, VALUE_ROLE) is None:
            self.source.clear()
            return
        from parameter_extractor import column_labels
        column, holder = item.data(0, VALUE_ROLE)
        node = self.tree.currentItem().data(0, NODE_ROLE)
        p = self._seen(holder.values.get(column, {}), node)
        parts = [f"<b>{html.escape(column_labels.readable(column, self._data.get('data_pack', '')))}</b> "
                 f"<span style='color:gray'>(column {html.escape(column)})</span>"]
        about = column_labels.description(column, self._data.get("data_pack", ""))
        if about:
            parts.append(f"<span style='color:gray'>{html.escape(about)}</span>")
        where = ", ".join(x for x in (p.get("source", ""), f"page {p['page']}" if p.get("page") else "") if x)
        if where:
            parts.append(f"<b>From:</b> {html.escape(where)}")
        if p.get("quote"):
            check = {"yes": "found word for word in the paper", "table image": "read from the table's image",
                     "no": "the model's wording -- not found in the paper's text"}.get(p.get("quote_in_paper", ""), "")
            parts.append(f"<b>Quote:</b> <i>“{html.escape(str(p['quote']))}”</i>"
                         + (f" <span style='color:gray'>({check})</span>" if check else ""))
        if p.get("confidence"):
            parts.append(f"<b>Confidence:</b> {html.escape(str(p['confidence']))}")
        from parameter_extractor import record_tree
        row_word = self._words[-1] if self._words else "row"
        if record_tree._is_assumed(p):
            parts.append(f"<b>Assumed</b>: the paper doesn't state it for this {html.escape(row_word)}; the "
                         f"{html.escape(plural(row_word))} around it that do all give this value, so it is assumed "
                         f"the same (flagged under Things to check). Correct it if the paper says otherwise.")
        elif record_tree.ASSUMED in p and node.children:
            k = len(p[record_tree.ASSUMED]["rows"])
            parts.append(f"<b>Assumed for {k} {html.escape(plural(row_word, k))}</b> that don't state it: the "
                         f"others all give this value.")
        if p.get("origin"):
            parts.append(f"<span style='color:gray'>Found by: {html.escape(str(p['origin']))}</span>")
        if p.get("corrected"):
            parts.append(f"<b>Corrected</b> by you (extracted: {html.escape(_text(p.get('extracted_value')) or 'empty')}"
                         f"){': ' + html.escape(p['corrected'][5:]) if str(p['corrected']).startswith('yes: ') else ''}")
        self.source.setHtml("<br>".join(parts))

    # ---- correcting ----------------------------------------------------------------------------------------------

    def _correctable(self, column: str) -> bool:
        """Values the reviewer may change: not the row's ids, what a set varies or the reading notes (worked out
        from the other values)."""
        from parameter_extractor import corrections as corr
        return column not in corr.FIXED_COLUMNS and self._facet_of.get(column) not in ("row", "provenance")

    def _start_edit(self, item, column: int) -> None:
        data = item.data(0, VALUE_ROLE)
        if data is not None and self._editable() and self._correctable(data[0]):
            self.values.editItem(item, 1)

    def _editable(self) -> bool:
        r = self.result
        return bool(r is not None and r.run_dir and getattr(r, "record_path", None))

    def _targets(self, holder) -> Optional[List[str]]:
        """The rows a change of this value applies to: all that share it, or -- when the selection covers only some
        of them -- the person chooses. None = cancelled."""
        node = self.tree.currentItem().data(0, NODE_ROLE)
        shared = [leaf.id for leaf in self._rows_under(holder)]
        here = [leaf.id for leaf in self._rows_under(node) if leaf.id in shared]
        if len(shared) <= 1 or set(here) == set(shared):
            return shared
        row_word = self._words[-1] if self._words else "row"
        box = QMessageBox(self)
        box.setWindowTitle("Change a shared value")
        box.setText(f"This value is shared by {len(shared)} {plural(row_word, len(shared))}.")
        box.setInformativeText(f"Change it for all of them, or only for the {len(here)} "
                               f"{plural(row_word, len(here))} you selected?")
        all_btn = box.addButton(f"All {len(shared)}", QMessageBox.ButtonRole.AcceptRole)
        some_btn = box.addButton(f"Only {'this one' if len(here) == 1 else f'these {len(here)}'}",
                                 QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is all_btn:
            return shared
        if box.clickedButton() is some_btn:
            return here
        return None

    def _edited(self, item, col: int) -> None:
        if self._filling or col != 1 or item.data(0, VALUE_ROLE) is None:
            return
        from parameter_extractor import corrections as corr
        column, holder = item.data(0, VALUE_ROLE)
        before = _text(self._seen(holder.values.get(column, {}),
                                  self.tree.currentItem().data(0, NODE_ROLE)).get("value"))
        text = item.text(1)
        if text == before:
            return
        registry = None
        try:
            from parameter_extractor.registry import VariableRegistry
            registry = VariableRegistry(self.registry_path) if self.registry_path else None
        except Exception:                             # noqa: BLE001
            pass
        value, problem = corr.stored_value(column, text, registry)
        if problem:
            QMessageBox.warning(self, "Not a valid value", f"{problem}. The value wasn't changed.")
            self._reshow()
            return
        targets = self._targets(holder)
        if not targets:
            self._reshow()
            return
        try:
            corr.correct_many(self.result.run_dir, [(full_id, column, before, value) for full_id in targets])
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Not saved", str(e))
        self._after_change()

    def _menu(self, pos) -> None:
        item = self.values.itemAt(pos)
        if item is None or item.data(0, VALUE_ROLE) is None or not self._editable():
            return
        from parameter_extractor import corrections as corr
        column, holder = item.data(0, VALUE_ROLE)
        menu = QMenu(self)
        edit = menu.addAction("Correct this value… (or double-click it)")
        fixes = corr.load(self.result.run_dir)
        mine = [leaf.id for leaf in self._rows_under(holder) if (leaf.id, column) in fixes]
        undo = menu.addAction(f"Undo my correction (back to "
                              f"{_text(holder.values[column].get('extracted_value')) or 'empty'})") if mine else None
        note = menu.addAction("Add or change the correction's note…") if mine else None
        chosen = menu.exec(self.values.viewport().mapToGlobal(pos))
        if chosen is edit:
            self.values.editItem(item, 1)
        elif undo is not None and chosen is undo:
            corr.restore(self.result.run_dir, [(full_id, column, None) for full_id in mine])
            self._after_change()
        elif note is not None and chosen is note:
            text, ok = QInputDialog.getText(self, "Note", "Why this value was corrected:",
                                            text=fixes[(mine[0], column)].note)
            if ok:
                for full_id in mine:
                    corr.set_note(self.result.run_dir, full_id, column, text.strip())
                self._after_change()

    def _reshow(self) -> None:
        self._show_node(self.tree.currentItem())

    def _after_change(self) -> None:
        """Read the record back (corrections.py wrote it), keep the selection, tell the window."""
        current = self.tree.currentItem()
        keep = current.data(0, NODE_ROLE).id if current is not None else None
        self._load()
        self._fill(keep)
        self.corrected.emit()

    def refresh(self) -> None:
        """After a correction made elsewhere (the Extracted data table)."""
        if self.result is not None:
            self._after_change_quiet()

    def _after_change_quiet(self) -> None:
        current = self.tree.currentItem()
        keep = current.data(0, NODE_ROLE).id if current is not None else None
        self._load()
        self._fill(keep)
