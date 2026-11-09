"""
The main window's Parameters panel (Mickey, 2026-11-08: one search page instead of three windows): the research
area's switchable extraction stages, each with its parameters, as a tree of checkboxes.

What the ticks mean:
- everything ticked (the default) -- a full extraction;
- a whole stage unticked -- a full extraction without that stage (the old "Extraction stages" checkboxes; each
  data pack remembers them, QSettings stages/<pack>/<stage>);
- single parameters unticked inside a stage -- a FOCUSED SEARCH for the ticked parameters only (focused_search.py:
  one small call per paper, only the passages that matter).

Steps whose columns are built from a vocabulary (scopes.py: the chemistry step's compounds, the analysis step's
instrument families) are groups of their vocabulary's items: unticking some NARROWS that step in a full extraction
(RunConfig.scopes) -- it isn't a focused search; unticking all switches the step off.
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
        self.scope_groups: Dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.filter_edit = QLineEdit(placeholderText="Find a value…", clearButtonEnabled=True)
        self.filter_edit.textChanged.connect(self._filter)
        top.addWidget(self.filter_edit, 1)
        self.all_btn = QPushButton("Tick all", clicked=self.tick_all)
        self.all_btn.setToolTip("Tick everything again: the full dataset.")
        top.addWidget(self.all_btn)
        layout.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Step / value", "What it is"])
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)
        self.always_label = QLabel(wordWrap=True)
        self.always_label.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self.always_label)
        self._filling = False

    # ---- filling ---------------------------------------------------------------------------------
    def load(self, pack_id: str, registry_path=None) -> None:
        """The area's stages and their parameters, and its constructed-parameter groups (compounds, instrument
        families); stages ticked as the area last had them."""
        from parameter_extractor import packs, scopes
        from parameter_extractor.focused_search import available_parameters
        from parameter_extractor.stages.optional import toggleable_stages
        self.pack_id = pack_id
        pack = packs.available().get(pack_id)
        self._filling = True
        self.tree.clear()
        self.groups: Dict[str, QTreeWidgetItem] = {}
        self.scope_groups: Dict[str, QTreeWidgetItem] = {}
        params = available_parameters(pack, {}) if pack else []
        registry = None
        if pack is not None:
            try:
                from parameter_extractor.registry import VariableRegistry
                registry = VariableRegistry(registry_path, pack=pack) if registry_path else None
            except Exception:                    # a damaged registry file: the bundled compounds only
                registry = None
        built = {g.step: g for g in (scopes.groups(pack, registry) if pack else [])}
        if "chemistry" in built:                 # the core step first
            self._add_scope_group(built.pop("chemistry"), pack_id)
        for t in (toggleable_stages(pack) if pack else []):
            if t.name in built:                  # a vocabulary-built step: its items, not parameters
                self._add_scope_group(built.pop(t.name), pack_id, t.label, t.conditional)
                continue
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
        self.always_label.setText("Everything ticked: the full dataset. Untick a whole step to skip it. Untick single "
                                  "values to search only for those (quicker and cheaper). Unticking compounds or "
                                  "instrument families limits those steps to the ones left ticked.")
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), 300))
        self._filling = False
        self._filter(self.filter_edit.text())
        self.changed.emit()

    def _add_scope_group(self, group_def, pack_id: str, label: str = "", conditional: bool = False) -> None:
        """A vocabulary-built step: one child per vocabulary item (scopes.ScopeGroup)."""
        title = (label or group_def.label) + (" (when the paper calls for it)" if conditional else "")
        group = QTreeWidgetItem([title, group_def.description])
        group.setData(0, STAGE_ROLE, group_def.step)
        group.setToolTip(0, group_def.description)
        group.setToolTip(1, group_def.description)
        group.setFlags((group.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                       & ~Qt.ItemFlag.ItemIsSelectable)
        on = self._settings.value(f"stages/{pack_id}/{group_def.step}", True, type=bool)
        group.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.tree.addTopLevelItem(group)
        for it in group_def.items:
            item = QTreeWidgetItem([it.label, it.detail])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setData(0, STAGE_ROLE, it.key)
            item.setToolTip(0, it.tip)
            item.setToolTip(1, it.tip)
            group.addChild(item)
        self.groups[group_def.step] = group
        self.scope_groups[group_def.step] = group

    def scopes(self) -> dict:
        """RunConfig.scopes: the ticked items of each vocabulary-built step that's only partly ticked."""
        out = {}
        for step, g in self.scope_groups.items():
            if g.checkState(0) == Qt.CheckState.PartiallyChecked:
                out[step] = [g.child(j).data(0, STAGE_ROLE) for j in range(g.childCount())
                             if g.child(j).checkState(0) == Qt.CheckState.Checked]
        return out

    def scope_summary(self) -> str:
        """'compounds: 5 of 129; analysis: NMR, Mass spectrometry' for the mode line ('' when nothing is narrowed)."""
        parts = []
        for step, keys in self.scopes().items():
            g = self.scope_groups[step]
            labels = [g.child(j).text(0) for j in range(g.childCount()) if g.child(j).data(0, STAGE_ROLE) in keys]
            name = "compounds" if step == "chemistry" else g.text(0).split(" (")[0].lower()
            parts.append(f"{name}: " + (", ".join(labels) if len(labels) <= 3 else f"{len(labels)} of {g.childCount()}"))
        return "; ".join(parts)

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
        return any(g.checkState(0) == Qt.CheckState.PartiallyChecked for name, g in self.groups.items()
                   if name not in self.scope_groups)

    def checked_columns(self) -> List[str]:
        out = []
        for name, g in self.groups.items():
            if name in self.scope_groups:         # compounds / families aren't searchable parameters
                continue
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
