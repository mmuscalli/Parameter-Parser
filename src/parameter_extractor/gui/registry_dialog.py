"""
"Remembered variables": view and change what the local variable registry has learned from earlier reviews,
grouped by research area (Standard = every pack, then each pack; Mickey, 2026-11-03).

  - Added columns: columns accepted as "New column" -- research area, category, data type; rename or remove
    (removing also forgets the names that pointed to it, so those variables will be asked about again in the
    next review).
  - Synonyms: "this name in a paper -> that column" mappings -- research area, column; remove.
  - Compounds: each compound's default name, the synonyms PubChem lists for it, and the ACTIVE name its
    columns are written under (compound_names.py); "Convert a dataset CSV…" rewrites an older CSV's columns to
    the active names and the current column format (merging columns of the same compound).
  - Built-in: each pack's template and standard columns -- category and data type can be changed (with a
    warning: the pack's prompts and checks were tested with the defaults); names can't (code depends on them).

Cells with a choice open a list when clicked. Edits are made on a copy and written only on Save. They affect
future runs; CSVs already written are not changed.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QCompleter, QDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QStyledItemDelegate,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from parameter_extractor import packs, variable_categories
from parameter_extractor.registry import STANDARD, VariableRegistry, area_label, areas, common_column_names
from parameter_extractor.value_types import TYPES, column_type

KIND_LABELS = {"species": "Species", "parameter": "Experimental parameter", "figure_axis": "Figure axis"}
AUTOMATIC = "(automatic: placed by its name)"
DEFAULT = "(default)"
WARNING_COLOR = "#8a5a00"
CHANGED_BRUSH = QBrush(QColor(176, 110, 0))
ROLE = Qt.ItemDataRole.UserRole           # on column 0: ("column" | "alias" | "builtin", area, key)
EDITABLE_ROLE = Qt.ItemDataRole.UserRole + 1   # on column 0: the columns with a choice

BUILTIN_WARNING = ("Built-in columns are what the research area's prompts, checks and calculations were tested "
                   "with. Changing a column's category moves it in the dataset; changing its data type converts "
                   "(or leaves out) its values. Either can make results differ from the app's tested parsing.")


class ChoiceDelegate(QStyledItemDelegate):
    """A drop-down for cells with a choice; the dialog says which cells have one and what happens."""

    def __init__(self, dialog: "RegistryDialog", tree: QTreeWidget):
        super().__init__(tree)
        self.dialog, self.tree = dialog, tree

    def createEditor(self, parent, option, index):
        item = self.tree.itemFromIndex(index)
        options, editable = self.dialog.options_for(item, index.column())
        if not options:
            return None
        box = QComboBox(parent, editable=editable)
        box.setAutoFillBackground(True)            # not drawn over the cell's own text
        for label, data in options:
            box.addItem(label, data)
        if editable:
            completer = QCompleter([label for label, _ in options], box)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            box.setCompleter(completer)
        return box

    def setEditorData(self, editor, index):
        item = self.tree.itemFromIndex(index)
        current = self.dialog.current_value(item, index.column())
        i = editor.findData(current)
        if i >= 0:
            editor.setCurrentIndex(i)
        elif editor.isEditable():
            editor.setEditText(str(current or ""))
        if not editor.isEditable():
            QTimer.singleShot(0, editor.showPopup)

    def setModelData(self, editor, model, index):
        item = self.tree.itemFromIndex(index)
        if editor.isEditable():
            text = editor.currentText().strip()
            i = editor.findText(text)
            value = editor.itemData(i) if i >= 0 else text
        else:
            value = editor.currentData()
        self.dialog.choose(item, index.column(), value)


def _tree(headers: List[str], stretch: int) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderLabels(headers)
    t.setUniformRowHeights(True)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.CurrentChanged | QAbstractItemView.EditTrigger.SelectedClicked
                      | QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
    t.header().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    t.header().setStretchLastSection(False)
    return t


class RegistryDialog(QDialog):
    # tree columns
    A_COLUMN, A_AREA, A_CATEGORY, A_TYPE, A_KIND, A_ADDED, A_NAMES = range(7)
    S_NAME, S_AREA, S_COLUMN, S_KIND = range(4)
    B_COLUMN, B_SOURCE, B_CATEGORY, B_TYPE, B_DEFAULT = range(5)
    C_NAME, C_ACTIVE, C_CID, C_SOURCE, C_SYNONYMS = range(5)

    def __init__(self, registry_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remembered variables")
        self.resize(1050, 650)
        self.path = Path(registry_path)
        self.registry = VariableRegistry(self.path)        # edits apply to this copy until Save
        variable_categories.use_local(self.registry.local_categories)
        self.packs = packs.available()
        self._views = {}                                   # pack id -> that pack's view of self.registry
        self._orders = {}                                  # pack id -> its ColumnOrder without the user's choices
        self.builtin_confirmed = False                     # the warning is asked once per opening
        self._filling = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Choices remembered from earlier reviews, by research area: Standard ones apply to every area. "
            "They're applied automatically to future papers; CSVs already written stay as they are. "
            "Click a Research area, Category, Data type or column cell to change it.", wordWrap=True))
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit(placeholderText="part of a column or name", clearButtonEnabled=True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_edit, 1)
        layout.addLayout(filter_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_columns_tab(), "Added columns")
        self.tabs.addTab(self._build_aliases_tab(), "Synonyms")
        self.tabs.addTab(self._build_compounds_tab(), "Compounds")
        self.tabs.addTab(self._build_builtin_tab(), "Built-in")
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        where = QLabel(f"Stored in: {self.path}")
        where.setStyleSheet("color: palette(placeholder-text);")
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom.addWidget(where, 1)
        bottom.addWidget(QPushButton("Open folder", clicked=self._open_folder))
        bottom.addWidget(QPushButton("Cancel", clicked=self.reject))
        self.save_btn = QPushButton("Save", clicked=self._save, default=True)
        bottom.addWidget(self.save_btn)
        layout.addLayout(bottom)
        self._refresh()

    # ---- helpers -------------------------------------------------------------------

    def view(self, pack_id: str) -> VariableRegistry:
        """A pack's view of the registry copy (STANDARD: the active pack's, for the shared columns)."""
        pack_id = packs.current().id if pack_id == STANDARD else pack_id
        if pack_id not in self._views:
            self._views[pack_id] = self.registry.for_pack(pack_id)
        return self._views[pack_id]

    def default_order(self, pack_id: str):
        """Where a pack's columns sit without the user's choices (for the Built-in tab's defaults)."""
        if pack_id not in self._orders:
            from parameter_extractor.column_order import ColumnOrder
            self._orders[pack_id] = ColumnOrder(pack=self.packs[pack_id])
        return self._orders[pack_id]

    def category_options(self, area: str) -> List[Tuple[str, str]]:
        if area == STANDARD:
            cats = variable_categories.table_categories(local=self.registry.local_categories, area=STANDARD)
        elif area in self.packs:
            cats = variable_categories.table_categories(self.packs[area], self.registry.local_categories)
        else:
            cats = []
        return [(c.label, c.id) for c in cats]

    def category_label(self, area: str, category: str) -> str:
        if not category:
            return ""
        return next((label for label, cid in self.category_options(area) if cid == category),
                    f"{category} (not a category of this area)")

    def _group(self, tree: QTreeWidget, area: str, count: int) -> QTreeWidgetItem:
        group = QTreeWidgetItem(tree, [f"{area_label(area)}  ({count})"])
        group.setFirstColumnSpanned(True)
        f = group.font(0)
        f.setBold(True)
        group.setFont(0, f)
        group.setFlags(Qt.ItemFlag.ItemIsEnabled)
        group.setData(0, ROLE, ("group", area, ""))
        return group

    @staticmethod
    def _row(group: QTreeWidgetItem, what: str, area: str, key: str, texts: List[str],
             editable: Tuple[int, ...]) -> QTreeWidgetItem:
        item = QTreeWidgetItem(group, texts)
        item.setData(0, ROLE, (what, area, key))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, EDITABLE_ROLE, list(editable))
        for c in editable:
            item.setToolTip(c, "Click to change")
        return item

    @staticmethod
    def leaves(tree: QTreeWidget, area: Optional[str] = None) -> List[QTreeWidgetItem]:
        """The rows under the research-area groups (one group's with `area`), in order."""
        out = []
        for i in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(i)
            if area is None or group.data(0, ROLE)[1] == area:
                out += [group.child(j) for j in range(group.childCount())]
        return out

    def _expanded(self, tree: QTreeWidget) -> dict:
        return {tree.topLevelItem(i).data(0, ROLE)[1]: tree.topLevelItem(i).isExpanded()
                for i in range(tree.topLevelItemCount())}

    # ---- tabs --------------------------------------------------------------------

    def _build_columns_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.columns_tree = _tree(["Column", "Research area", "Category", "Data type", "Type", "Added",
                                   "Names that map to it"], self.A_NAMES)
        self.columns_tree.setItemDelegate(ChoiceDelegate(self, self.columns_tree))
        v.addWidget(self.columns_tree, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Rename…", clicked=self._rename_column))
        row.addWidget(QPushButton("Remove", clicked=self._remove_column))
        row.addStretch(1)
        v.addLayout(row)
        self.columns_empty = QLabel("No columns added yet. Columns you accept as 'New column' in a review "
                                    "appear here.")
        v.addWidget(self.columns_empty)
        return w

    def _build_aliases_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.alias_tree = _tree(["Name in the paper", "Research area", "Goes into column", "Type"], self.S_NAME)
        self.alias_tree.setItemDelegate(ChoiceDelegate(self, self.alias_tree))
        v.addWidget(self.alias_tree, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Remove", clicked=self._remove_alias))
        row.addStretch(1)
        v.addLayout(row)
        self.alias_empty = QLabel("No synonyms yet. Names you add or map in a review (with Remember "
                                  "ticked) appear here.")
        v.addWidget(self.alias_empty)
        return w

    def _build_compounds_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("The name each compound's columns are written under. Click an Active name to choose "
                           "another of its names (from PubChem). Only the files change: matching and the review "
                           "use the default name.", wordWrap=True))
        self.compound_tree = _tree(["Compound (default name)", "Active name", "PubChem CID", "Source", "Synonyms"],
                                   self.C_SYNONYMS)
        self.compound_tree.setItemDelegate(ChoiceDelegate(self, self.compound_tree))
        v.addWidget(self.compound_tree, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Reset selected to default", clicked=self._reset_selected_compounds))
        row.addWidget(QPushButton("Convert a dataset CSV…", clicked=self._convert_csv))
        row.addStretch(1)
        self.compound_count = QLabel()
        row.addWidget(self.compound_count)
        v.addLayout(row)
        return w

    def _build_builtin_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        warning = QLabel("⚠ " + BUILTIN_WARNING, wordWrap=True)
        warning.setStyleSheet(f"color: {WARNING_COLOR};")
        v.addWidget(warning)
        self.builtin_tree = _tree(["Column", "Source", "Category", "Data type", "Default"], self.B_DEFAULT)
        self.builtin_tree.setItemDelegate(ChoiceDelegate(self, self.builtin_tree))
        v.addWidget(self.builtin_tree, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Reset selected to default", clicked=self._reset_selected_builtin))
        row.addWidget(QPushButton("Reset all built-in changes", clicked=self._reset_all_builtin))
        row.addStretch(1)
        self.builtin_count = QLabel()
        row.addWidget(self.builtin_count)
        v.addLayout(row)
        return w

    # ---- refresh -------------------------------------------------------------------

    def _refresh(self) -> None:
        self._filling = True
        try:
            self._fill_columns()
            self._fill_aliases()
            self._fill_compounds()
            self._fill_builtin()
        finally:
            self._filling = False
        self._apply_filter()

    def _area_order(self) -> List[str]:
        return [a for a, _ in areas()]

    def _fill_columns(self) -> None:
        reg, t = self.registry, self.columns_tree
        open_ = self._expanded(t)
        t.clear()
        by_area = {}
        for col in sorted(reg.all_columns):
            by_area.setdefault(reg.column_area(col), []).append(col)
        for area in self._area_order() + sorted(set(by_area) - set(self._area_order())):
            cols = by_area.get(area, [])
            if not cols:
                continue
            group = self._group(t, area, len(cols))
            for col in cols:
                info = reg.all_columns[col]
                names = ", ".join(reg.display_name(k) for k in reg.aliases_to(col))
                self._row(group, "column", area, col,
                          [col, area_label(area), self.category_label(area, info.get("category", "")) or AUTOMATIC,
                           TYPES.get(info.get("type", "any"), info.get("type", "")),
                           KIND_LABELS.get(info.get("kind"), info.get("kind", "")), info.get("added", ""), names],
                          (self.A_AREA, self.A_CATEGORY, self.A_TYPE))
            group.setExpanded(open_.get(area, True))
        for c in range(self.A_NAMES):
            t.resizeColumnToContents(c)
        self.columns_empty.setVisible(not reg.all_columns)

    def _fill_aliases(self) -> None:
        reg, t = self.registry, self.alias_tree
        open_ = self._expanded(t)
        t.clear()
        by_area = {}
        for key in sorted(reg.all_aliases, key=lambda k: reg.display_name(k).lower()):
            by_area.setdefault(reg.alias_area(key), []).append(key)
        for area in self._area_order() + sorted(set(by_area) - set(self._area_order())):
            keys = by_area.get(area, [])
            if not keys:
                continue
            group = self._group(t, area, len(keys))
            for key in keys:
                kind, _ = reg.split_alias(key)
                self._row(group, "alias", area, key,
                          [reg.display_name(key), area_label(area), reg.all_aliases[key], KIND_LABELS.get(kind, kind)],
                          (self.S_AREA, self.S_COLUMN))
            group.setExpanded(open_.get(area, True))
        t.resizeColumnToContents(self.S_AREA)
        t.setColumnWidth(self.S_COLUMN, 330)
        t.resizeColumnToContents(self.S_KIND)
        self.alias_empty.setVisible(not reg.all_aliases)

    def builtin_columns(self) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """[(area, [(column, source)])]: the columns every pack has (Standard), then each pack's own. The row
        identifiers and provenance columns are left out: they always sit at the start / end of a row."""
        from parameter_extractor.column_order import IDENTIFIERS, PROVENANCE
        common = common_column_names() + IDENTIFIERS + PROVENANCE
        out = [(STANDARD, [(c, "Standard") for c in common_column_names()])]
        for pack_id, pack in self.packs.items():
            v = self.view(pack_id)
            cols = [(c, "Template") for c in v.template_columns if c not in common]
            cols += [(c, "Standard") for c in v.standard_columns if c not in common]
            out.append((pack_id, cols))
        return out

    def _fill_builtin(self) -> None:
        t = self.builtin_tree
        open_ = self._expanded(t)
        t.clear()
        changed = 0
        bold = QFont()
        bold.setBold(True)
        for area, cols in self.builtin_columns():
            group = self._group(t, area, len(cols))
            pack_id = packs.current().id if area == STANDARD else area
            view = self.view(pack_id)
            order = self.default_order(pack_id)
            for col, source in cols:
                choice = view.builtin_choice(col)
                d_cat = order.category_of(col)
                d_type = column_type(col, None, self.packs[pack_id])
                cat = choice.get("category") or d_cat
                dtype = choice.get("type") or d_type
                item = self._row(group, "builtin", area, col,
                                 [col, source, self.category_label(area, cat) or cat, TYPES.get(dtype, dtype),
                                  f"{self.category_label(area, d_cat) or d_cat} · {TYPES.get(d_type, d_type)}"],
                                 (self.B_CATEGORY, self.B_TYPE))
                if choice:
                    changed += 1
                    for c in (self.B_COLUMN, self.B_CATEGORY, self.B_TYPE):
                        item.setFont(c, bold)
                        item.setForeground(c, CHANGED_BRUSH)
                    item.setToolTip(self.B_COLUMN, "Changed from the default (shown on the right)")
            group.setExpanded(open_.get(area, False))
        for c, width in ((self.B_COLUMN, 330), (self.B_SOURCE, 90), (self.B_CATEGORY, 230), (self.B_TYPE, 140)):
            t.setColumnWidth(c, width)          # groups start closed: sizing to contents would see nothing
        self.builtin_count.setText(f"{changed} built-in column(s) changed" if changed else "All at their defaults")

    def compound_names(self, pack_id: str):
        from parameter_extractor.compound_names import CompoundNames
        return CompoundNames(self.view(pack_id), self.packs[pack_id])

    def _fill_compounds(self) -> None:
        t = self.compound_tree
        open_ = self._expanded(t)
        t.clear()
        changed = 0
        bold = QFont()
        bold.setBold(True)
        for pack_id in self.packs:
            compounds = sorted(self.compound_names(pack_id).compounds.values(), key=lambda c: c.name.lower())
            if not compounds:
                continue
            group = self._group(t, pack_id, len(compounds))
            for c in compounds:
                item = self._row(group, "compound", pack_id, c.name,
                                 [c.name, c.shown, str(c.cid or ""), "Built-in" if c.builtin else "Accepted",
                                  ", ".join(c.synonyms)], (self.C_ACTIVE,) if len(c.names) > 1 else ())
                item.setToolTip(self.C_SYNONYMS, "\n".join(c.synonyms) or "No synonyms stored")
                if c.active:
                    changed += 1
                    item.setFont(self.C_ACTIVE, bold)
                    item.setForeground(self.C_ACTIVE, CHANGED_BRUSH)
            group.setExpanded(open_.get(pack_id, False))
        for col, width in ((self.C_NAME, 220), (self.C_ACTIVE, 240), (self.C_CID, 90), (self.C_SOURCE, 80)):
            t.setColumnWidth(col, width)
        self.compound_count.setText(f"{changed} compound(s) shown under another name" if changed
                                    else "All under their default names")

    def _reset_selected_compounds(self) -> None:
        for item in self.compound_tree.selectedItems():
            what, area, key = item.data(0, ROLE)
            if what == "compound":
                self.view(area).set_active_name(key, "")
        self._refresh()

    def _convert_csv(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from parameter_extractor.compound_names import convert_dataset_csv
        path, _ = QFileDialog.getOpenFileName(self, "Dataset CSV to convert", "", "CSV files (*.csv)")
        if not path:
            return
        pack_id, ok = QInputDialog.getItem(self, "Research area", "Compounds of:",
                                           list(self.packs), 0, False)
        if not ok:
            return
        out = Path(path).with_name(Path(path).stem + "_active_names.csv")
        renames = convert_dataset_csv(path, out, self.view(pack_id))
        QMessageBox.information(self, "Converted", f"{len(renames)} column(s) renamed (using the names as "
                                f"shown here, saved or not).\nWritten: {out}")

    def _apply_filter(self) -> None:
        text = self.filter_edit.text().strip().lower()
        for tree in (self.columns_tree, self.alias_tree, self.compound_tree, self.builtin_tree):
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                shown = 0
                for j in range(group.childCount()):
                    item = group.child(j)
                    hit = not text or any(text in item.text(c).lower() for c in range(tree.columnCount()))
                    item.setHidden(not hit)
                    shown += hit
                group.setHidden(bool(text) and not shown)
                if text and shown:
                    group.setExpanded(True)

    # ---- choices (the delegate asks; tests call choose() directly) ----------------------

    def options_for(self, item: QTreeWidgetItem, column: int) -> Tuple[List[Tuple[str, str]], bool]:
        """([(label, value)], editable text) for a cell with a choice; ([], False) for the others."""
        if item is None or column not in (item.data(0, EDITABLE_ROLE) or []):
            return [], False
        what, area, key = item.data(0, ROLE)
        if (what, column) in (("column", self.A_AREA), ("alias", self.S_AREA)):
            return [(label, a) for a, label in areas()], False
        if (what, column) in (("column", self.A_TYPE), ("builtin", self.B_TYPE)):
            opts = [(label, k) for k, label in TYPES.items()]
            return ([(DEFAULT, "")] + opts if what == "builtin" else opts), False
        if (what, column) == ("column", self.A_CATEGORY):
            return [(AUTOMATIC, "")] + self.category_options(area), False
        if (what, column) == ("builtin", self.B_CATEGORY):
            return [(DEFAULT, "")] + self.category_options(area), False
        if (what, column) == ("alias", self.S_COLUMN):
            return [(c, c) for c in self.alias_targets(area)], True
        if (what, column) == ("compound", self.C_ACTIVE):
            c = self.compound_names(area).compounds.get(key)
            return ([(n + ("  (default)" if n == key else ""), n) for n in c.names] if c else []), False
        return [], False

    def alias_targets(self, area: str) -> List[str]:
        """Columns a synonym of this area can go into."""
        if area == STANDARD:
            standard = sorted(c for c in self.registry.all_columns if self.registry.column_area(c) == STANDARD)
            return common_column_names() + standard
        return self.view(area).known_columns() if area in self.packs else []

    def current_value(self, item: QTreeWidgetItem, column: int):
        what, area, key = item.data(0, ROLE)
        reg = self.registry
        if what == "column":
            info = reg.all_columns.get(key, {})
            return {self.A_AREA: area, self.A_CATEGORY: info.get("category", ""),
                    self.A_TYPE: info.get("type", "any")}.get(column)
        if what == "alias":
            return area if column == self.S_AREA else reg.all_aliases.get(key, "")
        if what == "compound":
            c = self.compound_names(area).compounds.get(key)
            return c.shown if c else key
        if what == "builtin":
            choice = self.view(packs.current().id if area == STANDARD else area).builtin_choice(key)
            return choice.get("category" if column == self.B_CATEGORY else "type", "")
        return None

    def choose(self, item: QTreeWidgetItem, column: int, value) -> None:
        """Apply a choice made in a cell."""
        if self._filling or item is None:
            return
        what, area, key = item.data(0, ROLE)
        value = value or ""
        if what == "column":
            {self.A_AREA: lambda: self.registry.set_column_area(key, value),
             self.A_CATEGORY: lambda: self.registry.set_column_category(key, value),
             self.A_TYPE: lambda: self.registry.set_column_type(key, value)}[column]()
        elif what == "alias":
            if column == self.S_AREA:
                self.registry.set_alias_area(key, value)
            elif value.strip():
                self.registry.set_alias_column(key, value.strip())
        elif what == "compound":
            self.view(area).set_active_name(key, value or key)
        elif what == "builtin":
            if not self.confirm_builtin_change():
                QTimer.singleShot(0, self._refresh)
                return
            self.set_builtin(area, key, **({"category": value} if column == self.B_CATEGORY else {"value_type": value}))
            return
        QTimer.singleShot(0, self._refresh)      # not inside the delegate's commit

    def confirm_builtin_change(self) -> bool:
        if self.builtin_confirmed:
            return True
        answer = QMessageBox.warning(self, "Change a built-in column?", BUILTIN_WARNING + "\n\nChange it anyway?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)
        self.builtin_confirmed = answer == QMessageBox.StandardButton.Yes
        return self.builtin_confirmed

    def set_builtin(self, area: str, column: str, value_type: Optional[str] = None,
                    category: Optional[str] = None) -> None:
        self.view(packs.current().id if area == STANDARD else area).set_builtin(column, value_type, category)
        QTimer.singleShot(0, self._refresh)

    def _reset_selected_builtin(self) -> None:
        for item in self.builtin_tree.selectedItems():
            what, area, key = item.data(0, ROLE)
            if what == "builtin":
                self.view(packs.current().id if area == STANDARD else area).set_builtin(key, "", "")
        self._refresh()

    def _reset_all_builtin(self) -> None:
        for area, cols in self.builtin_columns():
            view = self.view(packs.current().id if area == STANDARD else area)
            for col, _ in cols:
                if view.builtin_choice(col):
                    view.set_builtin(col, "", "")
        self._refresh()

    # ---- actions -------------------------------------------------------------------

    def _selected(self, tree: QTreeWidget, what: str) -> Optional[str]:
        item = tree.currentItem()
        data = item.data(0, ROLE) if item else None
        return data[2] if data and data[0] == what else None

    def _selected_column(self):
        return self._selected(self.columns_tree, "column")

    def rename_column(self, old: str, new: str) -> bool:
        try:
            self.registry.rename_column(old, new.strip())
        except ValueError as e:
            QMessageBox.warning(self, "Can't rename", str(e))
            return False
        self._refresh()
        return True

    def _rename_column(self) -> None:
        col = self._selected_column()
        if not col:
            return
        new, ok = QInputDialog.getText(self, "Rename column", f"New name for '{col}':", text=col)
        if ok and new.strip() and new.strip() != col:
            self.rename_column(col, new)

    def remove_column(self, col: str) -> None:
        self.registry.remove_column(col)
        self._refresh()

    def _remove_column(self) -> None:
        col = self._selected_column()
        if not col:
            return
        names = [self.registry.display_name(k) for k in self.registry.aliases_to(col)]
        answer = QMessageBox.question(
            self, "Remove column",
            f"Forget the column '{col}'" + (f" and the names mapped to it ({', '.join(names)})" if names else "")
            + "?\n\nThose variables will be offered in the review again on future papers.")
        if answer == QMessageBox.StandardButton.Yes:
            self.remove_column(col)

    def remove_alias(self, key: str) -> None:
        self.registry.remove_alias(key)
        self._refresh()

    def _remove_alias(self) -> None:
        key = self._selected(self.alias_tree, "alias")
        if key:
            self.remove_alias(key)

    def _open_folder(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))

    def known_in(self, area: str, column: str) -> bool:
        if area == STANDARD:
            return column in self.alias_targets(STANDARD) or any(self.view(p).is_known_column(column)
                                                                 for p in self.packs)
        return area in self.packs and self.view(area).is_known_column(column)

    def problems(self) -> List[str]:
        """Synonyms pointing to a column their research area doesn't have."""
        reg = self.registry
        return [f"{reg.display_name(k)} -> {c} ({area_label(reg.alias_area(k))})"
                for k, c in reg.all_aliases.items() if not self.known_in(reg.alias_area(k), c)]

    def _save(self) -> None:
        bad = self.problems()
        if bad:
            QMessageBox.warning(self, "Check the synonyms", "These point to a column that doesn't exist in their "
                                "research area: " + "; ".join(bad))
            return
        self.registry.save()
        self.accept()
