"""
"Remembered variables": view and undo what the local variable registry has
learned from earlier reviews.

  - Added columns: columns accepted as "New column" -- rename or remove
    (removing also forgets the names that pointed to it, so those variables
    will be asked about again in the next review).
  - Synonyms: "this name in a paper -> that column" mappings -- change the
    column or remove.
  - Built-in: the template's columns and the app's standard columns, for
    reference (read-only; PaperDataTemplate is never modified).

Edits are made on a copy and written only on Save. They affect future runs;
CSVs already written are not changed.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QCompleter, QDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QListWidget, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from parameter_extractor.registry import VariableRegistry

KIND_LABELS = {"species": "Species", "parameter": "Experimental parameter", "figure_axis": "Figure axis"}


class RegistryDialog(QDialog):
    def __init__(self, registry_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remembered variables")
        self.resize(900, 600)
        self.path = Path(registry_path)
        self.registry = VariableRegistry(self.path)        # edits apply to this copy until Save

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choices remembered from earlier reviews. They're applied automatically to future papers. "
            "Changes here affect future runs only; CSVs already written stay as they are.", wordWrap=True)
        layout.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_columns_tab(), "Added columns")
        self.tabs.addTab(self._build_aliases_tab(), "Synonyms")
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

    # ---- tabs --------------------------------------------------------------------

    def _build_columns_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.columns_table = QTableWidget(0, 4)
        self.columns_table.setHorizontalHeaderLabels(["Column", "Type", "Added", "Names that map to it"])
        self.columns_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.columns_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.columns_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.columns_table, 1)
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
        self.alias_table = QTableWidget(0, 3)
        self.alias_table.setHorizontalHeaderLabels(["Name in the paper", "Type", "Goes into column"])
        self.alias_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alias_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.alias_table, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Remove", clicked=self._remove_alias))
        row.addStretch(1)
        v.addLayout(row)
        self.alias_empty = QLabel("No synonyms yet. Names you add or map in a review (with Remember "
                                  "ticked) appear here.")
        v.addWidget(self.alias_empty)
        return w

    def _build_builtin_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(f"PaperDataTemplate columns ({len(self.registry.template_columns)}) and the "
                           f"app's standard columns ({len(self.registry.standard_columns)}), read-only:"))
        lst = QListWidget()
        for c in self.registry.standard_columns:
            lst.addItem(f"{c}    (standard)")
        for c in self.registry.template_columns:
            lst.addItem(c)
        v.addWidget(lst, 1)
        return w

    # ---- refresh -------------------------------------------------------------------

    def _refresh(self) -> None:
        reg = self.registry
        cols = sorted(reg.added_columns)
        t = self.columns_table
        t.setRowCount(len(cols))
        for r, col in enumerate(cols):
            info = reg.added_columns[col]
            names = ", ".join(reg.display_name(k) for k in reg.aliases_to(col))
            for c, text in enumerate([col, KIND_LABELS.get(info.get("kind"), info.get("kind", "")),
                                      info.get("added", ""), names]):
                t.setItem(r, c, QTableWidgetItem(text))
        t.resizeColumnsToContents()
        self.columns_empty.setVisible(not cols)

        keys = sorted(reg.aliases)
        a = self.alias_table
        a.setRowCount(len(keys))
        self._alias_keys = keys
        known = reg.known_columns()
        for r, key in enumerate(keys):
            kind, _ = reg.split_alias(key)
            a.setItem(r, 0, QTableWidgetItem(reg.display_name(key)))
            a.setItem(r, 1, QTableWidgetItem(KIND_LABELS.get(kind, kind)))
            combo = QComboBox(editable=True)
            combo.addItems(known)
            completer = QCompleter(known, combo)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            combo.setCompleter(completer)
            combo.setCurrentText(reg.aliases[key])
            combo.currentTextChanged.connect(lambda text, k=key: self._on_alias_column(k, text))
            a.setCellWidget(r, 2, combo)
        a.resizeColumnToContents(1)
        a.setColumnWidth(2, 300)
        self.alias_empty.setVisible(not keys)

    # ---- actions -------------------------------------------------------------------

    def _selected_column(self):
        r = self.columns_table.currentRow()
        return self.columns_table.item(r, 0).text() if r >= 0 and self.columns_table.item(r, 0) else None

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
        r = self.alias_table.currentRow()
        if 0 <= r < len(self._alias_keys):
            self.remove_alias(self._alias_keys[r])

    def _on_alias_column(self, key: str, column: str) -> None:
        column = column.strip()
        if self.registry.is_known_column(column):
            self.registry.set_alias_column(key, column)

    def _open_folder(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))

    def _save(self) -> None:
        bad = [self.registry.display_name(k) for k, c in self.registry.aliases.items()
               if not self.registry.is_known_column(c)]
        if bad:
            QMessageBox.warning(self, "Check the synonyms", "These point to a column that doesn't exist: "
                                + ", ".join(bad))
            return
        self.registry.save()
        self.accept()
