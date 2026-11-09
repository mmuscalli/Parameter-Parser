"""
Two helpers of the research-area editor (Mickey, 2026-11-08), each a review window -- nothing changes until Apply:

  CompoundSetupDialog  'Find compounds…': compound_setup.find_compounds -- LOCAL (column names, the draft's surveys,
                       description examples) + PubChem's free name lookups, no model. Lists the compounds found (CID,
                       PubChem title, the columns they'll get, where they were found) and the parameters the chemistry
                       step replaces, each with a tick; Apply rewrites the pack (chemistry step on, prompt copied).
  AdditionsDialog      'Suggest additions from papers…': pack_drafting.suggest_additions -- a cheap survey of each new
                       sample paper (Haiku) + one request comparing them with the pack (Sonnet). Lists the suggested
                       parameters, stages, categories, rules and compounds with a tick each; Apply writes the ticked
                       ones (compounds looked up on PubChem).
"""
from __future__ import annotations
import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor.gui.widgets import style_rows


def _hint(text: str) -> QLabel:
    label = QLabel(text, wordWrap=True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def _checked_item(text: str, on: bool) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
    item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
    return item


def _plain(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setToolTip(text)
    return item


def _table(headers) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    style_rows(t)
    return t


# ---- compounds -----------------------------------------------------------------------------------------------------

class CompoundSetupDialog(QDialog):
    """Review what compound_setup found; `applied` lists what was done after Apply."""

    def __init__(self, folder: Path, parent=None, pubchem_path: Optional[Path] = None, lookups: bool = True):
        super().__init__(parent)
        from parameter_extractor import compound_setup
        from parameter_extractor.pack_editing import PackDraft
        self.folder, self.applied, self.problems = Path(folder), [], []
        self.setWindowTitle("Find compounds and tidy column names")
        self.resize(1080, 720)
        v = QVBoxLayout(self)
        v.addWidget(_hint("Compounds named in this data pack's columns, in its sample papers' examples and in its "
                          "parameter descriptions -- found by the app itself and identified on PubChem (free; only the "
                          "names are sent). Applying switches the chemistry step on: it records every dissolved "
                          "compound in its own column ('initial_MgCl2_aq_mM', 'sampled_UMP_aq_%yield'), matched to the "
                          "compounds below by name and PubChem identity, so the parameters ticked below aren't needed. "
                          "Untick anything that isn't right."))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pubchem = None
            if lookups:
                from parameter_extractor.pubchem import PubChem
                from parameter_extractor.registry import default_pubchem_cache_path
                pubchem = PubChem(pubchem_path or default_pubchem_cache_path())
            self.pubchem = pubchem
            self.plan = compound_setup.find_compounds(PackDraft.load(self.folder), pubchem)
        finally:
            QApplication.restoreOverrideCursor()
        if self.plan.note:
            v.addWidget(_hint(self.plan.note))
        v.addWidget(QLabel(f"<b>Compounds ({len(self.plan.compounds)})</b>"))
        self.compound_table = _table(["Compound", "PubChem CID", "PubChem name", "Columns", "Found in"])
        for c in self.plan.compounds:
            r = self.compound_table.rowCount()
            self.compound_table.insertRow(r)
            self.compound_table.setItem(r, 0, _checked_item(c.name, c.include))
            self.compound_table.setItem(r, 1, _plain(str(c.cid) if c.cid else "not on PubChem"))
            self.compound_table.setItem(r, 2, _plain(c.title))
            self.compound_table.setItem(r, 3, _plain(", ".join(c.columns())))
            self.compound_table.setItem(r, 4, _plain("; ".join(c.sources)))
        self.compound_table.setColumnWidth(0, 170)
        self.compound_table.setColumnWidth(1, 100)
        self.compound_table.setColumnWidth(2, 190)
        self.compound_table.setColumnWidth(3, 280)
        v.addWidget(self.compound_table, 2)
        v.addWidget(QLabel(f"<b>Parameters the chemistry step replaces ({len(self.plan.replacements)})</b>"))
        self.replace_table = _table(["Parameter", "Why"])
        for rep in self.plan.replacements:
            r = self.replace_table.rowCount()
            self.replace_table.insertRow(r)
            self.replace_table.setItem(r, 0, _checked_item(rep.column, rep.include))
            self.replace_table.setItem(r, 1, _plain(rep.reason))
        self.replace_table.setColumnWidth(0, 280)
        v.addWidget(self.replace_table, 1)
        v.addWidget(QLabel(f"<b>Column names changed to the app's conventions ({len(self.plan.renames)})</b>"))
        self.rename_table = _table(["Column", "Becomes", "Why"])
        for rn in self.plan.renames:
            r = self.rename_table.rowCount()
            self.rename_table.insertRow(r)
            self.rename_table.setItem(r, 0, _checked_item(rn.column, rn.include))
            self.rename_table.setItem(r, 1, _plain(rn.new or "(removed: duration_hr)"))
            self.rename_table.setItem(r, 2, _plain(rn.reason))
        self.rename_table.setColumnWidth(0, 260)
        self.rename_table.setColumnWidth(1, 220)
        v.addWidget(self.rename_table, 1)
        if self.plan.not_identified:
            v.addWidget(_hint("Not identified as compounds (left alone): " + ", ".join(self.plan.not_identified)))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_btn = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_btn.setEnabled(not self.plan.empty)
        if self.plan.empty:
            v.addWidget(_hint("No compounds found in this data pack's columns, and its column names already follow "
                              "the app's conventions."))
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def apply(self) -> None:
        from parameter_extractor import compound_setup
        for r, c in enumerate(self.plan.compounds):
            c.include = self.compound_table.item(r, 0).checkState() == Qt.CheckState.Checked
        for r, rep in enumerate(self.plan.replacements):
            rep.include = self.replace_table.item(r, 0).checkState() == Qt.CheckState.Checked
        for r, rn in enumerate(self.plan.renames):
            rn.include = self.rename_table.item(r, 0).checkState() == Qt.CheckState.Checked
        _, self.applied, self.problems = compound_setup.set_up_compounds(self.folder, self.pubchem, plan=self.plan)
        self.accept()


# ---- additions -----------------------------------------------------------------------------------------------------

class _Signals(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)


KIND_LABELS = {"parameter": "Parameter", "stage": "New stage", "category": "New category", "rule": "Rule",
               "compound": "Compound"}


class AdditionsDialog(QDialog):
    """Sample papers -> suggestions -> the ticked ones written into the pack; `applied` after Apply."""

    def __init__(self, folder: Path, config: Callable, parent=None):
        super().__init__(parent)
        from parameter_extractor.gui.paper_list import PaperListPanel
        self.folder, self._config, self.applied, self.problems = Path(folder), config, [], []
        self.result_ = None
        self._cancel = None
        self.setWindowTitle("Suggest additions from papers")
        self.resize(1100, 760)
        v = QVBoxLayout(self)
        v.addWidget(_hint("Add a few papers this data pack hasn't been tuned on. Each is surveyed cheaply for the "
                          "variables it reports (Claude Haiku, a few cents a paper), then one request (Claude Sonnet) "
                          "compares them with the data pack and suggests what's missing: parameters, stages, "
                          "categories, rules and compounds. Nothing changes until you Apply the ticked suggestions."))
        self.papers = PaperListPanel()
        self.papers.setMaximumHeight(200)
        v.addWidget(self.papers)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Get suggestions", clicked=self.run)
        row.addWidget(self.run_btn)
        self.passes_combo = QComboBox()
        for n, text in ((1, "1 survey pass"), (2, "2 survey passes, merged"), (3, "3 survey passes, merged")):
            self.passes_combo.addItem(text, n)
        self.passes_combo.setToolTip("How many times each paper is surveyed (Claude Haiku, about a cent or two a pass "
                                     "per paper); the variables and compounds of all passes are merged.")
        self.passes_combo.setCurrentIndex(max(0, self.passes_combo.findData(
            QSettings().value("draft/survey_passes", 2, type=int))))
        row.addWidget(self.passes_combo)
        self.tidy_box = QCheckBox("App's naming conventions")
        self.tidy_box.setToolTip("Suggested names for quantities the app already has a convention for are changed to it "
                                 "(pH -> initial_pH, reaction temperature -> initial_temperature_C, ...), local.")
        self.tidy_box.setChecked(QSettings().value("draft/tidy_names", True, type=bool))
        row.addWidget(self.tidy_box)
        self.progress = QProgressBar(visible=False, textVisible=False)
        row.addWidget(self.progress, 1)
        v.addLayout(row)
        self.status = _hint("")
        v.addWidget(self.status)
        self.table = _table(["Suggestion", "Type", "Details", "Papers", "Why"])
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 420)
        self.table.setColumnWidth(3, 60)
        v.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_btn = buttons.addButton("Apply ticked suggestions", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_btn.setEnabled(False)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self._cancel_or_close)
        v.addWidget(buttons)

    def run(self) -> None:
        from parameter_extractor import pack_drafting
        items = self.papers.items()
        if not items:
            self.status.setText("Add a few sample papers first.")
            return
        config = self._config()
        if config.needs_api_key and not config.api_key:
            self.status.setText("This reads the papers with the API: add your Anthropic API key in Settings first (or "
                                "choose a local model server there).")
            return
        self._cancel = threading.Event()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_done)
        self.run_btn.setEnabled(False)
        self.papers.set_locked(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        passes, tidy = self.passes_combo.currentData(), self.tidy_box.isChecked()
        QSettings().setValue("draft/survey_passes", passes)
        QSettings().setValue("draft/tidy_names", tidy)

        def work():
            try:
                result = pack_drafting.suggest_additions(self.folder, items, config,
                                                         on_progress=self._signals.progress.emit,
                                                         cancel_event=self._cancel, passes=passes, tidy=tidy)
            except BaseException as e:
                result = e
            self._signals.done.emit(result)
        threading.Thread(target=work, daemon=True, name="pack-additions").start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status.setText(message)

    def _on_done(self, result) -> None:
        self._cancel = None
        self.run_btn.setEnabled(True)
        self.papers.set_locked(False)
        self.progress.setVisible(False)
        if isinstance(result, BaseException):
            from parameter_extractor.errors import RunCancelledError
            self.status.setText("Cancelled." if isinstance(result, RunCancelledError) else str(result))
            return
        self.result_ = result
        self.show_suggestions(result)

    def show_suggestions(self, result) -> None:
        self.result_ = result
        self.table.setRowCount(0)
        for s in result.suggestions:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, _checked_item(s.title, s.include))
            self.table.setItem(r, 1, _plain(KIND_LABELS.get(s.kind, s.kind)))
            self.table.setItem(r, 2, _plain(s.detail))
            self.table.setItem(r, 3, _plain(str(s.papers) if s.papers else ""))
            self.table.setItem(r, 4, _plain(s.reason))
        surveyed = sum(1 for p in result.papers if p.survey)
        failed = [f"{p.name} ({p.error or 'no variables'})" for p in result.papers if not (p.survey and
                                                                                           p.survey.variables)]
        self.status.setText(f"{len(result.suggestions)} suggestion(s) from {surveyed} paper(s), ${result.cost_usd:.3f}."
                            + (f" Not read: {', '.join(failed)}." if failed else "")
                            + (f" Already covered: {', '.join(result.left_out[:8])}." if result.left_out else "")
                            + (f" Notes: {result.notes}" if result.notes else ""))
        self.apply_btn.setEnabled(bool(result.suggestions))

    def apply(self) -> None:
        from parameter_extractor import pack_drafting
        from parameter_extractor.pubchem import PubChem
        from parameter_extractor.registry import default_pubchem_cache_path
        if self.result_ is None:
            return
        for r, s in enumerate(self.result_.suggestions):
            s.include = self.table.item(r, 0).checkState() == Qt.CheckState.Checked
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.applied, self.problems = pack_drafting.apply_additions(
                self.folder, self.result_.suggestions, PubChem(default_pubchem_cache_path()))
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()

    def _cancel_or_close(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self.status.setText("Cancelling after the current request…")
            return
        self.reject()


# ---- shared modules -------------------------------------------------------------------------------------------------

class ModulesDialog(QDialog):
    """Add shared modules (pack_modules.MODULES) to a data pack: each with what it adds, ticked to add; the ones the
    pack has are shown ticked and greyed. Apply writes them (one save) and lists what was done in `applied`."""

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        from parameter_extractor import pack_modules
        from parameter_extractor.pack_editing import PackDraft
        self.setWindowTitle("Add modules")
        self.folder, self.applied, self.problems = Path(folder), [], []
        draft = PackDraft.load(self.folder)
        v = QVBoxLayout(self)
        v.addWidget(_hint("Modules are parts other data packs use and the app keeps refining: a step with its "
                          "prompts and columns, calculations, row rules. Adding one copies it into this data pack, "
                          "where you can still edit it. Steps marked 'runs only for ...' cost nothing on papers that "
                          "don't need them."))
        self.table = _table(["Module", "What it adds"])
        for mid, module in pack_modules.MODULES.items():
            present = bool(module.present(draft))
            item = _checked_item(module.label, present)
            item.setData(Qt.ItemDataRole.UserRole, mid)
            if present:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip("Already in this data pack")
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, _plain(module.description + (" (already in this pack)" if present else "")))
        self.table.setColumnWidth(0, 210)
        v.addWidget(self.table)
        buttons = QDialogButtonBox()
        self.apply_btn = buttons.addButton("Add the ticked modules", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.resize(760, 380)

    def chosen(self) -> list:
        out = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled and item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _apply(self) -> None:
        from parameter_extractor import pack_modules
        from parameter_extractor.pack_editing import PackDraft, check
        chosen = self.chosen()
        if not chosen:
            self.reject()
            return
        done = pack_modules.add_modules(self.folder, chosen)
        labels = {m: pack_modules.MODULES[m].label for m in done}
        self.applied = [f"{labels.get(m, m)}: {line}" for m, lines in done.items() for line in lines]
        self.problems = check(PackDraft.load(self.folder))
        self.accept()
