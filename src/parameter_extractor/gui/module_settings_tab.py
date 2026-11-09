"""
The settings part of the data pack editor's Modules tab (Mickey, 2026-11-09): this pack's changes to the modules it links --
which of a module's steps, values, calculations and rules it uses, the unit a value is stored in, a step's trigger
words. The module itself stays shared (modules/<id>/, linked by reference); only the differences are kept, in the
pack's pack.json "module_settings" (module_settings.py), so anything left alone follows the module and its updates.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from parameter_extractor import module_settings as ms
from parameter_extractor.gui.widgets import in_cell, style_rows



def _hint(text: str) -> QLabel:
    label = QLabel(text, wordWrap=True)
    label.setStyleSheet("color: gray;")
    return label


def _rule_list(rules: List[str], off: List[str], read_only: bool, on_change) -> QListWidget:
    """Checkable rules, wrapped (ticked = used)."""
    lst = QListWidget()
    lst.setWordWrap(True)
    lst.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    for rule in rules:
        item = QListWidgetItem(rule)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsUserCheckable if not read_only
                                                   else Qt.ItemFlag.NoItemFlags))
        item.setCheckState(Qt.CheckState.Unchecked if rule in off else Qt.CheckState.Checked)
        lst.addItem(item)
    lst.setFixedHeight(min(16 + 30 * len(rules) + 12 * sum(len(r) > 150 for r in rules), 230))
    lst.itemChanged.connect(lambda _i: on_change())
    return lst


def _unticked(lst: QListWidget) -> List[str]:
    return [lst.item(i).text() for i in range(lst.count()) if lst.item(i).checkState() != Qt.CheckState.Checked]


class ModuleSettingsEditor:
    """This pack's settings for its linked modules, edited one module at a time: `build(mod)` returns the settings
    section for the editor's Modules tab (the module's steps, values, calculations, rules, instrument families);
    `values(linked ids)` -> the pack.json "module_settings" (Mickey, 2026-11-09: one Modules tab, not two)."""

    def __init__(self, raw: Optional[dict], read_only: bool = False, on_change=None):
        self.read_only = read_only
        self._on_change = on_change or (lambda: None)
        self.settings: Dict[str, ms.ModuleSettings] = {mid: ms.settings_for(raw, mid) for mid in (raw or {})}
        self._shown: Optional[str] = None
        self._collect = None                      # reads the shown module's widgets back into self.settings
        self.values_table: Optional[QTableWidget] = None

    def changed(self, mid: str) -> bool:
        if mid == self._shown:
            self.store()
        return mid in self.settings and not ms.is_default(self.settings[mid])

    def store(self) -> None:
        if self._collect is not None and self._shown is not None:
            self.settings[self._shown] = self._collect()

    def release(self) -> None:
        """Keep the shown module's edits and let go of its widgets (its page is about to be replaced)."""
        self.store()
        self._collect = None
        self._shown = None

    def values(self, linked_ids) -> dict:
        """pack.json's "module_settings": the changes for the linked modules only."""
        self.store()
        out = {mid: ms.cleaned(s) for mid, s in self.settings.items() if mid in set(linked_ids)}
        return {mid: d for mid, d in out.items() if d}

    def reset(self, mid: str) -> None:
        if mid == self._shown:
            self._collect = None
        self.settings.pop(mid, None)

    def build(self, mod) -> QWidget:
        """The settings section of one linked module (the previous one's edits are kept first)."""
        self.store()
        self._collect = None                      # nothing to read back while the new section is built
        self._shown = mod.id
        settings = self.settings.get(mod.id, ms.ModuleSettings())
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(14)
        collectors = []

        def on_change():
            self.store()
            self._on_change()
        from parameter_extractor.stages.optional import _specs_in
        specs = list(_specs_in(mod.stages_dir).values()) if mod.stages_dir.is_dir() else []
        for spec in specs:
            collectors.append(self._step_box(pv, spec, settings, on_change))
        params = [(spec.label, p.column, p.unit, p.kind, p.description) for spec in specs for p in spec.parameters]
        params += [("added to your first step", p["column"], p.get("unit", ""), p.get("kind", "number"),
                    p.get("description", "")) for p in mod.manifest.pack_parameters]
        if params:
            collectors.append(self._values_box(pv, mod, params, settings, on_change))
        if mod.manifest.postprocess:
            box = QGroupBox("Calculations (on your computer; no model requests)")
            bv = QVBoxLayout(box)
            from parameter_extractor.pack_editing import CALCULATIONS
            ticks = {}
            for calc in mod.manifest.postprocess:
                cb = QCheckBox(f"{calc} -- {CALCULATIONS.get(calc, ('', ''))[0]}",
                               checked=calc not in settings.calculations_off)
                cb.setEnabled(not self.read_only)
                cb.toggled.connect(on_change)
                bv.addWidget(cb)
                ticks[calc] = cb
            pv.addWidget(box)
            collectors.append(lambda s, t=ticks: s.calculations_off.extend(c for c, cb in t.items()
                                                                           if not cb.isChecked()))
        prompt_rules = [r for rules in mod.manifest.prompt_rules.values() for r in rules]
        for title_text, rules, attr in (
                ("Rules the module adds to planning the rows", mod.manifest.row_rules, "row_rules_off"),
                ("Rules the module adds to this data pack's own steps", mod.manifest.stage_rules, "stage_rules_off"),
                ("Rules the module adds to the " + " / ".join(mod.manifest.prompt_rules) + " step", prompt_rules,
                 "prompt_rules_off")):
            if not rules:
                continue
            box = QGroupBox(title_text + " (untick to leave one out)")
            bv = QVBoxLayout(box)
            lst = _rule_list(rules, getattr(settings, attr), self.read_only, on_change)
            bv.addWidget(lst)
            pv.addWidget(box)
            collectors.append(lambda s, l=lst, a=attr: getattr(s, a).extend(_unticked(l)))
        vocab_path = mod.file("analysis_vocab.json")
        if vocab_path:
            import json
            fams = json.loads(vocab_path.read_text()).get("families", {})
            box = QGroupBox("Instrument families the analysis step looks for (untick to leave a family out)")
            from PySide6.QtWidgets import QGridLayout
            grid = QGridLayout(box)
            ticks = {}
            for i, (fid, fam) in enumerate((f, x) for f, x in fams.items() if f != "general"):
                cb = QCheckBox(fam.get("label", fid), checked=fid not in settings.families_off)
                cb.setToolTip(f"{fid}: {len(fam.get('settings', []))} settings")
                cb.setEnabled(not self.read_only)
                cb.toggled.connect(on_change)
                grid.addWidget(cb, i // 2, i % 2)
                ticks[fid] = cb
            pv.addWidget(box)
            collectors.append(lambda s, t=ticks: s.families_off.extend(f for f, cb in t.items() if not cb.isChecked()))
        if len(collectors) == 0:
            pv.addWidget(_hint("This module has nothing a data pack can change: it brings a built-in step and its "
                               "columns as they are."))

        def collect() -> ms.ModuleSettings:
            s = ms.ModuleSettings()
            for c in collectors:
                c(s)
            return s
        self._collect = collect
        return page

    def _step_box(self, pv, spec, settings: ms.ModuleSettings, on_change):
        st = settings.steps.get(spec.name, ms.StepSetting())
        box = QGroupBox(f"Step: {spec.label}  (one model request per paper it runs for)")
        bv = QVBoxLayout(box)
        on = QCheckBox("Run this step in this data pack", checked=not st.off)
        bv.addWidget(on)
        from parameter_extractor.pack_overview import trigger_text
        bv.addWidget(_hint("Runs for: " + trigger_text(spec)))
        words = None
        if spec.trigger.keywords:
            row = QHBoxLayout()
            row.addWidget(QLabel("Trigger words:"))
            words = QLineEdit(", ".join(st.keywords) if st.keywords is not None else "")
            words.setPlaceholderText("the module's: " + ", ".join(spec.trigger.keywords))
            words.setToolTip("Comma-separated. The step runs for papers that mention any of them; leave empty to use "
                             "the module's words.")
            row.addWidget(words, 1)
            bv.addLayout(row)
        images = QCheckBox("Send the paper's table images with this step",
                           checked=spec.table_images if st.table_images is None else st.table_images)
        bv.addWidget(images)
        rules = None
        if spec.rules:
            bv.addWidget(QLabel("The module's rules for this step (untick to leave one out):"))
            rules = _rule_list(spec.rules, st.rules_off, self.read_only, on_change)
            bv.addWidget(rules)
        bv.addWidget(QLabel("Your own extra rules for this step (one per line):"))
        extra = QPlainTextEdit("\n".join(st.extra_rules))
        extra.setMaximumHeight(70)
        bv.addWidget(extra)
        for w in (on, images):
            w.setEnabled(not self.read_only)
            w.toggled.connect(on_change)
        for w in (words, extra):
            if w is not None:
                w.setReadOnly(self.read_only)
                w.textChanged.connect(on_change)
        pv.addWidget(box)

        def collect(s: ms.ModuleSettings, spec=spec):
            new = ms.StepSetting(off=not on.isChecked())
            if words is not None and words.text().strip():
                new.keywords = [w.strip() for w in words.text().split(",") if w.strip()]
            if images.isChecked() != spec.table_images:
                new.table_images = images.isChecked()
            if rules is not None:
                new.rules_off = _unticked(rules)
            new.extra_rules = [l.strip() for l in extra.toPlainText().splitlines() if l.strip()]
            if ms.cleaned(ms.ModuleSettings(steps={spec.name: new})):
                s.steps[spec.name] = new
        return collect

    def _values_box(self, pv, mod, params, settings: ms.ModuleSettings, on_change):
        box = QGroupBox("Values (columns) the module fills")
        bv = QVBoxLayout(box)
        bv.addWidget(_hint("Untick a value to leave it out of this data pack. 'Stored in' is the unit the values are "
                           "saved in: the column is named after it (half_life_hr -> half_life_min) and every value is "
                           "converted into it. A description you write replaces the module's in the request."))
        table = QTableWidget(len(params), 5)
        table.setHorizontalHeaderLabels(["Use", "Column", "Stored in", "Description (empty = the module's)", "From"])
        table.verticalHeader().setVisible(False)
        head = table.horizontalHeader()
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for c, w in ((0, 50), (1, 260), (2, 170), (4, 170)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            table.setColumnWidth(c, w)
        style_rows(table)
        rows = []
        for r, (where, col, unit, kind, desc) in enumerate(params):
            ps = settings.parameters.get(col, ms.ParameterSetting())
            use = QCheckBox(checked=not ps.off)
            use.setEnabled(not self.read_only)
            use.toggled.connect(on_change)
            table.setCellWidget(r, 0, in_cell(use))
            name = QTableWidgetItem(col)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, 1, name)
            combo = QComboBox()
            choices = ms.unit_choices(col, unit) if kind != "text" else []
            fixed = mod.manifest.fixed.get(col)
            if not choices:
                combo.addItem(unit or ("text" if kind == "text" else "no unit"), "")
                combo.setEnabled(False)
            else:
                for u, c in choices:
                    combo.addItem(u + ("  (module's)" if c == col else ""), u if c != col else "")
                if ps.unit:
                    i = combo.findData(ps.unit)
                    combo.setCurrentIndex(max(i, 0))
                combo.setEnabled(not self.read_only and not fixed)
            if fixed:
                combo.setToolTip(f"Fixed: {fixed}.")

            def renamed(_i=0, combo=combo, name=name, col=col, unit=unit):
                u = combo.currentData()
                name.setText(ms.column_in_unit(col, unit, u) or col if u else col)
                on_change()
            combo.currentIndexChanged.connect(renamed)
            renamed()
            table.setCellWidget(r, 2, in_cell(combo))
            d = QTableWidgetItem(ps.description)
            d.setToolTip("Module's description: " + desc)
            if self.read_only:
                d.setFlags(d.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, 3, d)
            src = QTableWidgetItem(where)
            src.setFlags(src.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, 4, src)
            rows.append((col, use, combo, d))
        table.itemChanged.connect(lambda it: on_change() if it.column() == 3 else None)
        table.setFixedHeight(min(40 + 54 * len(params), 440))
        bv.addWidget(table)
        pv.addWidget(box)
        self.values_table = table

        def collect(s: ms.ModuleSettings):
            for col, use, combo, d in rows:
                p = ms.ParameterSetting(off=not use.isChecked(), unit=combo.currentData() or "",
                                        description=d.text().strip())
                if p.off or p.unit or p.description:
                    s.parameters[col] = p
        return collect
