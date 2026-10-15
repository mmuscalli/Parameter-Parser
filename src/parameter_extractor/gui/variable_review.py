"""
"Review new variables": shown before the CSV is written whenever the paper
reports variables that have no column yet (or a searched-for parameter wasn't
found). Nothing here goes into the dataset unless the user adds it:

  - Don't add (default)  -- values stay out of the CSV (kept in new_variables.json)
  - New column           -- values go into a new column (name editable),
                            added after the template's columns
  - Existing column      -- values go into a column that already exists (the
                            name is treated as a synonym of it from now on)

With "Remember" ticked, the choice is saved to the local registry and the
variable is recognised automatically on later papers. Individual values can
be edited first (e.g. "300 rpm" -> 300). PaperDataTemplate itself is never
modified.
"""
from __future__ import annotations
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor.ingestion.new_variables import VariableDecision, VariableGroup
from parameter_extractor.registry import VariableRegistry

ACTIONS = [("ignore", "Don't add"), ("new_column", "New column"), ("existing_column", "Existing column")]
KIND_LABELS = {"species": "Species", "parameter": "Experimental parameter", "figure_axis": "Figure axis",
               "assumed_value": "ASSUMED value (not stated in the paper)"}
COLS = ["Variable", "Type", "Values", "Example", "Add as", "Column", "Remember"]


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

        self.table = QTableWidget(len(groups), len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.action_boxes, self.column_boxes, self.remember_boxes = [], [], []
        for r, g in enumerate(groups):
            example = next((_value_text(v) for v in g.values if _value_text(v)), "")
            for c, text in enumerate([g.name, KIND_LABELS[g.kind], str(len(g.values)), example]):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(r, c, item)
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
            remember = QCheckBox()
            remember.setChecked(g.kind != "assumed_value")
            remember.setEnabled(False)
            if g.kind == "assumed_value":     # a guess is decided per paper: never remembered
                remember.setToolTip("Assumed values are never remembered for later papers.")
                for c in range(4):
                    self.table.item(r, c).setForeground(Qt.GlobalColor.darkRed)
            action.currentIndexChanged.connect(lambda i, row=r: self._on_action(row, i))
            self.table.setCellWidget(r, 4, action)
            self.table.setCellWidget(r, 5, column)
            self.table.setCellWidget(r, 6, self._centered(remember))
            self.action_boxes.append(action)
            self.column_boxes.append(column)
            self.remember_boxes.append(remember)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(5, 260)

        self._shown = -1
        self.values_table = QTableWidget(0, 4)
        self.values_table.setHorizontalHeaderLabels(["Applies to", "Value (editable)", "Quote", "From"])
        self.values_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.values_table.itemChanged.connect(self._on_value_edited)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_values(row))

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.values_table)
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
            self.table.selectRow(0)
            self._show_values(0)

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

    def _on_action(self, row: int, index: int) -> None:
        action = ACTIONS[index][0]
        self.column_boxes[row].setEnabled(action != "ignore")
        self.remember_boxes[row].setEnabled(action != "ignore" and self.groups[row].kind != "assumed_value")

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
        for i, v in enumerate(values):
            for c, text in enumerate([_where(v), _value_text(v), v.quote or "", v.origin]):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if c != 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                t.setItem(i, c, item)
        t.resizeColumnToContents(0)
        t.blockSignals(False)

    def _on_value_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 1 or not (0 <= self._shown < len(self.groups)):
            return
        v = self.groups[self._shown].values[item.row()]
        text = item.text().strip()
        try:
            v.value, v.value_text = float(text), None
        except ValueError:
            v.value, v.value_text = None, text
        if item.row() == 0:     # keep the summary line's example in step with the edit
            self.table.item(self._shown, 3).setText(_value_text(v))

    # ---- result --------------------------------------------------------------------

    def decisions(self) -> List[VariableDecision]:
        out = []
        for r, g in enumerate(self.groups):
            action = ACTIONS[self.action_boxes[r].currentIndex()][0]
            column = self.column_boxes[r].currentText().strip()
            if action == "new_column" and self.registry.is_known_column(column):
                action = "existing_column"      # typed an existing name: it's a merge
            out.append(VariableDecision(alias_name=g.alias_name, kind=g.kind, action=action, column=column,
                                        remember=self.remember_boxes[r].isChecked()))
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
