"""
"Review new variables": shown before the CSV is written whenever the paper
reports variables that have no column yet (or a searched-for parameter wasn't
found). Nothing here goes into the dataset unless the user adds it:

  - Don't add (default)  -- values stay out of the CSV (kept in new_variables.json)
  - New column           -- values go into a new column (name editable),
                            added after the template's columns
  - Existing column      -- values go into a column that already exists (the
                            name is treated as a synonym of it from now on)

"Data type" restricts what the column holds (value_types.py: number, whole number, text, yes / no):
values are converted to it ('triplicate' -> 3) and one that can't be blocks "Build dataset" until it's
edited or the type changed. Built-in columns show their own type; a new column's type is remembered.

With "Remember" ticked, the choice is saved to the local registry and the
variable is recognised automatically on later papers. Individual values can
be edited first (e.g. "300 rpm" -> 300). PaperDataTemplate itself is never
modified.

Variables are listed under their category (variable_categories.py: the pack's own, e.g. Chemical
Species, then Metadata / Experimental Methodology, then figure columns and assumed values), each
with a header line saying what belongs there and in what format; a value that doesn't follow its
category's format is marked with ⚠. Methods taking `row` mean the variable's index in `groups`;
the table has the header lines in between (`_table_row`, `_group_at`).

A compound found both in a table (or the text) and on a figure axis is ONE line (new_variables
`_merge_figure_axes_into_compounds`), named with both sources; every value has an Include box, and such a line
has one switch per source above its values (e.g. leave out Fig. 3's readings). Unticked values stay out of the CSV
(kept as left out in new_variables.json).
"""
from __future__ import annotations
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor.ingestion.new_variables import VariableDecision, VariableGroup, stored_value
from parameter_extractor.names import closest_names, vocabulary
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.value_types import TYPES, column_type
from parameter_extractor.variable_categories import by_id

ACTIONS = [("ignore", "Don't add"), ("new_column", "New column"), ("existing_column", "Existing column")]
KIND_LABELS = {"species": "Species", "parameter": "Experimental parameter", "figure_axis": "Figure axis",
               "assumed_value": "ASSUMED value (not stated in the paper)"}
COLS = ["Variable", "Type", "Values", "Example", "Similar existing", "Add as", "Column", "Data type", "Remember"]
ACTION_COL, COLUMN_COL, DTYPE_COL, REMEMBER_COL = 5, 6, 7, 8
INCLUDE_COL = 5                    # in the values table
# a new column's suggested data type, from its category's format (variable_categories.py)
CATEGORY_TYPE = {"number": "number", "text": "text"}


def _value_text(v) -> str:
    if v.value is not None:
        return f"{v.value:g}" + (f" {v.unit}" if v.unit and v.unit not in ("mM", "%") else "")
    return v.value_text or ""


def _where(v) -> str:
    if v.set_label is None:
        return "whole paper"
    return v.set_label + (f" / {v.sample_label}" if v.sample_label else "")


class VariableReviewDialog(QDialog):
    def __init__(self, groups: List[VariableGroup], unfound_terms: List[str], registry: VariableRegistry,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review new variables")
        self.resize(1250, 760)
        self.groups, self.registry = groups, registry
        self._shown = -1
        self._columns = registry.known_columns()

        intro = QLabel(
            f"This paper reports <b>{len(groups)}</b> variable(s) with no column in the dataset yet. "
            "Choose what to add &mdash; <b>nothing here goes into the CSV unless you add it</b>. "
            "With <i>Remember</i> ticked, your choice is reused automatically for later papers. "
            "Select a variable to see and edit its values.", wordWrap=True)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        if unfound_terms:
            nf = QLabel("Searched for, but <b>not stated in the paper</b>: " + "; ".join(unfound_terms),
                        wordWrap=True)
            nf.setStyleSheet("background: palette(alternate-base); padding: 6px;")
            layout.addWidget(nf)

        headers = []                       # (table row, category id) of each category's header line
        self._table_row, self._group_at = [], {}
        for i, g in enumerate(groups):
            if not headers or headers[-1][1] != g.category:
                headers.append((i + len(headers), g.category))
            self._table_row.append(i + len(headers))
            self._group_at[self._table_row[-1]] = i
        self.table = QTableWidget(len(groups) + len(headers), len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.action_boxes, self.column_boxes, self.remember_boxes, self.type_boxes = [], [], [], []
        for r, g in enumerate(groups):
            t = self._table_row[r]
            example = next((_value_text(v) for v in g.values if _value_text(v)), "")
            notes = sorted({v.format_note for v in g.values if v.format_note})
            similar = self._similar(g)
            identity = next((v for v in g.values if v.pubchem_cid), None)
            sources = g.sources
            name = g.name + (f"   (in {' and '.join(sources)})" if g.merged else "")
            for c, text in enumerate([name, KIND_LABELS[g.kind], str(len(g.values)),
                                      ("⚠ " if notes else "") + example, similar]):
                item = QTableWidgetItem(text)
                item.setToolTip(text + ("\n\nFormat: " + "; ".join(notes) if c == 3 and notes else ""))
                if c == 2 and len(sources) > 1:
                    item.setToolTip("\n".join(f"{label}: {n} value(s)" for label, n in sources.items()))
                if c == 0 and g.merged:
                    item.setToolTip(f"{g.name} appears in {' and '.join(sources)}: one decision adds all of its "
                                    "values. To keep only some, untick them (or a whole source) in the list below.")
                if c == 0 and identity:
                    item.setToolTip(f"{text}\nPubChem: {identity.pubchem_title} (CID {identity.pubchem_cid})")
                self.table.setItem(t, c, item)
            action = QComboBox()
            for _, label in ACTIONS:
                action.addItem(label)
            column = QComboBox(editable=True)
            column.addItems(self._columns)
            completer = QCompleter(self._columns, column)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            column.setCompleter(completer)
            column.setCurrentText(g.proposed_column)
            column.setEnabled(False)
            dtype = QComboBox()
            for key, label in TYPES.items():
                dtype.addItem(label, key)
            dtype.setEnabled(False)
            dtype.setToolTip("What the column holds. Values are converted to it ('triplicate' -> 3 for a whole "
                             "number); a value that can't be is marked below and must be edited first.")
            remember = QCheckBox()
            remember.setChecked(g.kind != "assumed_value")
            remember.setEnabled(False)
            if g.kind == "assumed_value":     # a guess is decided per paper: never remembered
                remember.setToolTip("Assumed values are never remembered for later papers.")
                for c in range(4):
                    self.table.item(t, c).setForeground(Qt.GlobalColor.darkRed)
            action.currentIndexChanged.connect(lambda i, row=r: self._on_action(row, i))
            column.currentTextChanged.connect(lambda _t, row=r: self._on_column(row))
            dtype.currentIndexChanged.connect(lambda _i, row=r: self._refresh_preview(row))
            self.table.setCellWidget(t, ACTION_COL, action)
            self.table.setCellWidget(t, COLUMN_COL, column)
            self.table.setCellWidget(t, DTYPE_COL, dtype)
            self.table.setCellWidget(t, REMEMBER_COL, self._centered(remember))
            self.action_boxes.append(action)
            self.column_boxes.append(column)
            self.remember_boxes.append(remember)
            self.type_boxes.append(dtype)
        for r in range(len(groups)):
            self._on_column(r)                              # each data type box shows its column's type
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, min(self.table.columnWidth(0), 320))
        self.table.setColumnWidth(COLUMN_COL, 260)
        self.table.verticalHeader().setVisible(False)       # numbers would count the header lines
        for row, category_id in headers:                    # after sizing: spanned text doesn't widen column 0
            self._add_header(row, category_id, sum(1 for g in groups if g.category == category_id))

        self.values_table = QTableWidget(0, 6)
        self.values_table.setHorizontalHeaderLabels(["Applies to", "Value (editable)", "Stored as", "Quote", "From",
                                                     "Include"])
        self.values_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.values_table.itemChanged.connect(self._on_value_edited)
        self.table.currentCellChanged.connect(self._on_current_cell)

        # one switch per source for a line found in several (a table and a figure)
        self.source_row = QHBoxLayout()
        self.source_box = QWidget()
        self.source_box.setLayout(self.source_row)
        self.source_box.hide()
        self.source_checks = {}
        values_panel = QWidget()
        vp = QVBoxLayout(values_panel)
        vp.setContentsMargins(0, 0, 0, 0)
        vp.addWidget(self.source_box)
        vp.addWidget(self.values_table, 1)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(values_panel)
        split.setSizes([380, 260])
        layout.addWidget(split, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Add all as suggested", clicked=self._accept_suggestions))
        buttons.addStretch(1)
        buttons.addWidget(QPushButton("Don't add any", clicked=self._add_none))
        self.build_btn = QPushButton("Build dataset", clicked=self._finish, default=True)
        buttons.addWidget(self.build_btn)
        layout.addLayout(buttons)
        if groups:
            self.table.selectRow(self._table_row[0])
            self._show_values(0)

    def _add_header(self, row: int, category_id: str, count: int) -> None:
        """A category's header line across the table: its name, what belongs there, its format."""
        category = by_id(category_id)
        label = category.label if category else "Other"
        text = f"{label}  ({count})"
        if category and category.id not in ("figure", "assumed"):
            text += f"   ·   format: {category.format_rule()}"
        if category and category.description:
            text += f"   ·   {category.description}"
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)            # not selectable
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setBackground(self.palette().alternateBase())
        item.setToolTip(text)
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, len(COLS))

    def category_headers(self) -> List[str]:
        """The header lines' texts, in order (tests)."""
        return [self.table.item(r, 0).text() for r in range(self.table.rowCount()) if r not in self._group_at]

    def _on_current_cell(self, table_row: int, *_):
        if table_row in self._group_at:
            self._show_values(self._group_at[table_row])

    @staticmethod
    def _centered(widget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(widget)
        return w

    # ---- interaction -----------------------------------------------------------

    def set_action(self, row: int, action: str, column: str = None) -> None:
        self.action_boxes[row].setCurrentIndex([a for a, _ in ACTIONS].index(action))
        if column is not None:
            self.column_boxes[row].setCurrentText(column)

    def _similar(self, g: VariableGroup) -> str:
        """A hint only -- never applied automatically."""
        if self.registry.is_known_column(g.proposed_column):
            return ""
        pool = vocabulary() if g.kind == "species" else self._columns
        return ", ".join(closest_names(g.name, pool, n=2))

    def _on_action(self, row: int, index: int) -> None:
        action = ACTIONS[index][0]
        self.column_boxes[row].setEnabled(action != "ignore")
        self.remember_boxes[row].setEnabled(action != "ignore" and self.groups[row].kind != "assumed_value")
        self._on_column(row)

    def _fixed_type(self, column: str) -> bool:
        """A built-in column (template or the pack's stages): its data type is shown, not changed here."""
        return self.registry.is_known_column(column) and column not in self.registry.added_columns

    def _on_column(self, row: int) -> None:
        """The data type box follows the chosen column: a known column's own type (fixed for built-in
        ones), else the category's suggestion for a new column."""
        box = self.type_boxes[row]
        action = ACTIONS[self.action_boxes[row].currentIndex()][0]
        column = self.column_boxes[row].currentText().strip()
        if self.registry.is_known_column(column):
            kind = column_type(column, self.registry)
        else:
            category = by_id(self.groups[row].category)
            kind = CATEGORY_TYPE.get(category.value_type if category else "", "any")
        box.blockSignals(True)
        box.setCurrentIndex(max(box.findData(kind), 0))
        box.blockSignals(False)
        box.setEnabled(action != "ignore" and not self._fixed_type(column))
        self._refresh_preview(row)

    def value_type(self, row: int) -> str:
        return self.type_boxes[row].currentData() or "any"

    def set_value_type(self, row: int, value_type: str) -> None:
        self.type_boxes[row].setCurrentIndex(self.type_boxes[row].findData(value_type))

    def _refresh_preview(self, row: int) -> None:
        if row == self._shown:
            self._show_values(row)

    def _accept_suggestions(self) -> None:
        """Suggested columns for new variables -- but assumed values stay "Don't add":
        including a guess is always a deliberate, per-value choice."""
        for r, g in enumerate(self.groups):
            if g.kind == "assumed_value":
                continue
            known = self.registry.is_known_column(g.proposed_column)
            self.set_action(r, "existing_column" if known else "new_column", g.proposed_column)

    def _add_none(self) -> None:
        for r in range(len(self.groups)):
            self.set_action(r, "ignore")
        self._finish()

    def _show_values(self, row: int) -> None:
        self._shown = row
        t = self.values_table
        t.blockSignals(True)
        values = self.groups[row].values if 0 <= row < len(self.groups) else []
        t.setRowCount(len(values))
        action = ACTIONS[self.action_boxes[row].currentIndex()][0] if values else "ignore"
        column = self.column_boxes[row].currentText().strip() if values else ""
        self._fill_source_checks(values)
        for i, v in enumerate(values):
            refused = False
            if not v.include:
                stored = "(left out)"
            elif action == "ignore" or not column:
                stored = "(not added)"
            else:
                value, note = stored_value(v, column, self.value_type(row))
                refused = note.startswith("not stored")
                stored = ("⚠ " + note[len("not stored: "):] if refused else
                          (f"{value:g}" if isinstance(value, float) else str(value)) + (f"  ({note})" if note else ""))
            for c, text in enumerate([_where(v), _value_text(v), stored, v.quote or "", v.origin]):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if c != 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 2 and refused:
                    item.setForeground(Qt.GlobalColor.darkRed)
                if not v.include:
                    item.setForeground(Qt.GlobalColor.gray)
                t.setItem(i, c, item)
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            box.setCheckState(Qt.CheckState.Checked if v.include else Qt.CheckState.Unchecked)
            box.setToolTip("Unticked: this value stays out of the CSV (kept as left out)")
            t.setItem(i, INCLUDE_COL, box)
        t.resizeColumnToContents(0)
        t.blockSignals(False)

    def _fill_source_checks(self, values) -> None:
        """'Include: [x] Table 1 (4)  [x] Fig. 3 (8)' above the values of a line found in several sources."""
        from parameter_extractor.ingestion.new_variables import source_label
        while self.source_row.count():
            w = self.source_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.source_checks = {}
        by_source = {}
        for v in values:
            by_source.setdefault(source_label(v), []).append(v)
        merged = any(v.kind == "figure_axis" for v in values) and any(v.kind != "figure_axis" for v in values)
        self.source_box.setVisible(merged)
        if not merged:
            return
        self.source_row.addWidget(QLabel("Include values from:"))
        for label, vs in by_source.items():
            box = QCheckBox(f"{label} ({len(vs)})")
            box.setTristate(False)
            box.setChecked(all(v.include for v in vs))
            box.toggled.connect(lambda on, vs=vs: self._set_included(vs, on))
            self.source_row.addWidget(box)
            self.source_checks[label] = box
        self.source_row.addStretch(1)

    def _set_included(self, values, on: bool) -> None:
        for v in values:
            v.include = on
        self._show_values(self._shown)

    def _on_value_edited(self, item: QTableWidgetItem) -> None:
        if item.column() == INCLUDE_COL and 0 <= self._shown < len(self.groups):
            v = self.groups[self._shown].values[item.row()]
            on = item.checkState() == Qt.CheckState.Checked
            if v.include != on:
                v.include = on
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._show_values(self._shown))   # not inside the item's signal
            return
        if item.column() != 1 or not (0 <= self._shown < len(self.groups)):
            return
        v = self.groups[self._shown].values[item.row()]
        text = item.text().strip()
        try:
            v.value, v.value_text = float(text), None
        except ValueError:
            v.value, v.value_text, v.unit = None, text, None     # the unit is in the text now
        if item.row() == 0:     # keep the summary line's example in step with the edit
            self.table.item(self._table_row[self._shown], 3).setText(_value_text(v))

    # ---- result --------------------------------------------------------------------

    def decisions(self) -> List[VariableDecision]:
        out = []
        for r, g in enumerate(self.groups):
            action = ACTIONS[self.action_boxes[r].currentIndex()][0]
            column = self.column_boxes[r].currentText().strip()
            if action == "new_column" and self.registry.is_known_column(column):
                action = "existing_column"      # typed an existing name: it's a merge
            out.append(VariableDecision(alias_name=g.alias_name, kind=g.kind, action=action, column=column,
                                        remember=self.remember_boxes[r].isChecked(),
                                        value_type="" if self._fixed_type(column) else self.value_type(r)))
        return out

    def problems(self) -> List[str]:
        issues = []
        for r, (g, d) in enumerate(zip(self.groups, self.decisions())):
            if d.action == "ignore":
                continue
            if not d.column:
                issues.append(f"'{g.name}': enter a column name.")
            elif any(ch in d.column for ch in ",\n\t\""):
                issues.append(f"'{g.name}': column names can't contain commas, quotes or line breaks.")
            elif d.action == "existing_column" and not self.registry.is_known_column(d.column):
                issues.append(f"'{g.name}': '{d.column}' isn't an existing column -- choose one from the "
                              f"list, or pick 'New column'.")
            else:
                kind = d.value_type or column_type(d.column, self.registry)
                notes = [(v, stored_value(v, d.column, kind)[1]) for v in g.values if v.include]
                bad = [_value_text(v) for v, n in notes if n.startswith("not converted")]
                wrong = [_value_text(v) for v, n in notes if n.startswith("not stored")]
                if bad:
                    issues.append(f"'{g.name}': {', '.join(repr(b) for b in bad[:3])} can't be converted to the "
                                  f"unit of {d.column}. Edit the value(s) below, or choose another column.")
                if wrong:
                    issues.append(f"'{g.name}': {', '.join(repr(b) for b in wrong[:3])} can't be stored as "
                                  f"{TYPES[kind].lower()}. Edit the value(s) below, or choose another data type.")
        return issues

    def _finish(self) -> None:
        issues = self.problems()
        if issues:
            QMessageBox.warning(self, "Check the columns", "\n".join(issues))
            return
        self.accept()

    def reject(self) -> None:
        """Closing the window adds nothing (same as "Don't add any")."""
        for r in range(len(self.groups)):
            self.set_action(r, "ignore")
        super().reject()
