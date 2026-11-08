"""
The main window's Parameters panel (Mickey, 2026-11-08: one search page instead of three windows): the research
area's switchable extraction stages, each with its parameters, as a tree of checkboxes.

What the ticks mean:
- everything ticked (the default) -- a full extraction;
- a whole stage unticked -- a full extraction without that stage (the old "Extraction stages" checkboxes; each
  research area remembers them, QSettings stages/<pack>/<stage>);
- single parameters unticked inside a stage -- a FOCUSED SEARCH for the ticked parameters only (focused_search.py:
  one small call per paper, only the passages that matter).
"""
from __future__ import annotations
from typing import Dict, List, Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

STAGE_ROLE = Qt.ItemDataRole.UserRole          # on a group: the stage name; on a parameter: its column


class ParameterPanel(QWidget):
    changed = Signal()                          # ticks changed (the mode may have changed)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings()
        self.pack_id: Optional[str] = None
        self.groups: Dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.filter_edit = QLineEdit(placeholderText="Filter parameters…", clearButtonEnabled=True)
        self.filter_edit.textChanged.connect(self._filter)
        top.addWidget(self.filter_edit, 1)
        self.all_btn = QPushButton("Tick all", clicked=self.tick_all)
        self.all_btn.setToolTip("Back to a full extraction: every stage and parameter ticked.")
        top.addWidget(self.all_btn)
        layout.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Stage / parameter", "What it is"])
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)
        self.always_label = QLabel(wordWrap=True)
        self.always_label.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self.always_label)
        self._filling = False

    # ---- filling ---------------------------------------------------------------------------------
    def load(self, pack_id: str) -> None:
        """The area's stages and their parameters; stages ticked as the area last had them."""
        from parameter_extractor import packs
        from parameter_extractor.focused_search import available_parameters
        from parameter_extractor.stages.optional import toggleable_stages
        self.pack_id = pack_id
        pack = packs.available().get(pack_id)
        self._filling = True
        self.tree.clear()
        self.groups: Dict[str, QTreeWidgetItem] = {}
        params = available_parameters(pack, {}) if pack else []
        for t in (toggleable_stages(pack) if pack else []):
            label = t.label + (" (when the paper calls for it)" if t.conditional else "")
            group = QTreeWidgetItem([label, t.description])
            group.setData(0, STAGE_ROLE, t.name)
            group.setToolTip(0, t.description)
            group.setToolTip(1, t.description)
            flags = group.flags() | Qt.ItemFlag.ItemIsUserCheckable
            stage_params = [p for p in params if p.group == t.label]
            if stage_params:
                flags |= Qt.ItemFlag.ItemIsAutoTristate
            group.setFlags(flags & ~Qt.ItemFlag.ItemIsSelectable)
            on = self._settings.value(f"stages/{pack_id}/{t.name}", True, type=bool)
            group.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(group)
            for p in stage_params:
                item = QTreeWidgetItem([p.column, p.description + (f" [{p.unit}]" if p.unit else "")])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                item.setData(0, STAGE_ROLE, p.column)
                item.setToolTip(1, p.description)
                group.addChild(item)
            self.groups[t.name] = group
        always = [s for s in ("structure_planner", "chemistry") if s == "structure_planner" or (pack and pack.uses(s))]
        names = {"structure_planner": "planning the rows", "chemistry": "solution chemistry (compounds)"}
        self.always_label.setText("Always part of a full extraction: " + ", ".join(names[s] for s in always)
                                  + ". Untick single parameters to search only for those (a focused search).")
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), 300))
        self._filling = False
        self._filter(self.filter_edit.text())
        self.changed.emit()

    # ---- state -----------------------------------------------------------------------------------
    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        group = item if item.parent() is None else item.parent()
        name = group.data(0, STAGE_ROLE)
        if self.pack_id and name and group.checkState(0) != Qt.CheckState.PartiallyChecked:
            self._settings.setValue(f"stages/{self.pack_id}/{name}", group.checkState(0) == Qt.CheckState.Checked)
        self.changed.emit()

    def set_stage(self, name: str, on: bool) -> None:
        group = self.groups.get(name)
        if group is not None:
            group.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            if not group.childCount():               # no children: autotristate doesn't fire for them
                self._item_changed(group, 0)

    def stage_on(self, name: str) -> bool:
        group = self.groups.get(name)
        return group is not None and group.checkState(0) != Qt.CheckState.Unchecked

    def tick_all(self) -> None:
        for name in self.groups:
            self.set_stage(name, True)

    def optional_stage_choices(self) -> dict:
        """RunConfig.optional_stages: a stage with nothing ticked is 'off'; the rest run as usual."""
        return {name: "auto" if g.checkState(0) != Qt.CheckState.Unchecked else "off" for name, g in self.groups.items()}

    @property
    def focused(self) -> bool:
        """Single parameters unticked inside a stage: a focused search, not a full extraction."""
        return any(g.checkState(0) == Qt.CheckState.PartiallyChecked for g in self.groups.values())

    def checked_columns(self) -> List[str]:
        out = []
        for g in self.groups.values():
            for j in range(g.childCount()):
                if g.child(j).checkState(0) == Qt.CheckState.Checked:
                    out.append(g.child(j).data(0, STAGE_ROLE))
        return out

    def stages_off(self) -> List[str]:
        return [g.text(0).split(" (")[0] for g in self.groups.values() if g.checkState(0) == Qt.CheckState.Unchecked]

    def set_column(self, column: str, on: bool) -> None:
        for g in self.groups.values():
            for j in range(g.childCount()):
                if g.child(j).data(0, STAGE_ROLE) == column:
                    g.child(j).setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        for g in self.groups.values():
            visible = 0
            for j in range(g.childCount()):
                child = g.child(j)
                hide = bool(t) and t not in child.text(0).lower() and t not in child.text(1).lower()
                child.setHidden(hide)
                visible += not hide
            g.setHidden(bool(t) and visible == 0 and t not in g.text(0).lower())
            g.setExpanded(bool(t) and visible > 0)
