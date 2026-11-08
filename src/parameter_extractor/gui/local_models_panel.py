"""
Settings > Model provider, the local part (2026-11-08; local_models.py): the server (Ollama or an OpenAI-compatible
one), its models -- context length and whether each reads images -- and the user's model profiles, the local
counterpart of Standard / Balanced / Economy (which model plans the rows, which does the extraction steps, which
suggests figure settings). Saved to <app data>/local_models.json when Settings closes; the server's API key, if it
needs one, goes to the system keychain like the Anthropic key.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from parameter_extractor import local_models
from parameter_extractor.local_models import LocalModel, LocalSettings

CONTEXT_STEPS = [8192, 16384, 32768, 49152, 65536, 98304, 131072, 262144]
NOTE = ("Local models run on your own computer or server: nothing is sent to Anthropic and there's no cost, but the "
        "results aren't validated for this app the way the Anthropic models are, and a paper can take many minutes. "
        "A model needs a context long enough for the paper and the step's instructions (about 32K-64K tokens for most "
        "papers) -- and the memory for it. Models marked as reading images also get the table and figure images.")


class LocalModelsPanel(QWidget):
    changed = Signal()                    # profiles added / removed / renamed (the main window's Models list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_models: List[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.kind_combo = QComboBox()
        for kind, label in local_models.KINDS.items():
            self.kind_combo.addItem(label, kind)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Server:", self.kind_combo)
        self.url_edit = QLineEdit()
        self.url_edit.setToolTip("Where the server listens. Ollama: http://localhost:11434; LM Studio: "
                                 "http://localhost:1234; llama.cpp's llama-server: http://localhost:8080.")
        self.test_btn = QPushButton("Test connection", clicked=self.refresh_models)
        self.test_btn.setToolTip("Lists the server's models below.")
        row = QHBoxLayout()
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.test_btn)
        form.addRow("Address:", row)
        self.key_edit = QLineEdit(placeholderText="only if the server asks for one",
                                  echoMode=QLineEdit.EchoMode.Password)
        self.key_label = QLabel("API key:")
        form.addRow(self.key_label, self.key_edit)
        limits = QHBoxLayout()
        self.timeout_spin = QSpinBox(minimum=60, maximum=7200, singleStep=60, suffix=" s")
        self.timeout_spin.setToolTip("Longest wait for the next part of an answer. A local machine can take several "
                                     "minutes just to read a long paper.")
        self.parallel_spin = QSpinBox(minimum=1, maximum=16)
        self.parallel_spin.setToolTip("How many requests the server answers at once (Ollama: OLLAMA_NUM_PARALLEL; "
                                      "usually 1). The app's steps wait for each other beyond that.")
        limits.addWidget(QLabel("Time limit:"))
        limits.addWidget(self.timeout_spin)
        limits.addSpacing(16)
        limits.addWidget(QLabel("Requests at once:"))
        limits.addWidget(self.parallel_spin)
        limits.addStretch(1)
        form.addRow("", limits)
        v.addLayout(form)
        self.status = QLabel(wordWrap=True)
        self.status.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.status)

        v.addWidget(QLabel("<b>Models</b>"))
        self.models_table = QTableWidget(0, 3)
        self.models_table.setHorizontalHeaderLabels(["Model", "Context length (tokens)", "Reads images"])
        self.models_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.models_table.verticalHeader().setVisible(False)
        self.models_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.models_table.setMaximumHeight(130)
        v.addWidget(self.models_table)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("<b>Model profiles</b>"))
        prow.addStretch(1)
        self.add_profile_btn = QPushButton("Add profile", clicked=lambda: self.add_profile())
        self.remove_profile_btn = QPushButton("Remove", clicked=self.remove_profile)
        prow.addWidget(self.add_profile_btn)
        prow.addWidget(self.remove_profile_btn)
        v.addLayout(prow)
        self.profiles_table = QTableWidget(0, 1 + len(local_models.PROFILE_ROLES))
        self.profiles_table.setHorizontalHeaderLabels(["Profile"] + [label for _, label in local_models.PROFILE_ROLES])
        self.profiles_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.profiles_table.verticalHeader().setVisible(False)
        self.profiles_table.setToolTip("Like Standard / Balanced / Economy: which model does what. Choose one in the "
                                       "main window's Models list. E.g. a large model to plan the rows and a faster "
                                       "one for the extraction steps.")
        self.profiles_table.setMaximumHeight(120)
        self.profiles_table.itemChanged.connect(lambda _i: self.changed.emit())
        v.addWidget(self.profiles_table)
        note = QLabel(NOTE, wordWrap=True)
        note.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(note)

    # ---- load / read back -------------------------------------------------------------------------
    def load(self, local: LocalSettings) -> None:
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(local.kind)))
        self.url_edit.setText(local.url)
        self.key_edit.setText(local.api_key)
        self.timeout_spin.setValue(int(local.timeout_sec))
        self.parallel_spin.setValue(int(local.parallel or 1))
        self._kind_changed(update_url=False)
        self._fill_models(local.models)
        self.profiles_table.setRowCount(0)
        for name, roles in local.profiles.items():
            self.add_profile(name, roles)

    def settings(self) -> LocalSettings:
        return LocalSettings(kind=self.kind_combo.currentData(), url=self.url_edit.text().strip(),
                             timeout_sec=self.timeout_spin.value(), parallel=self.parallel_spin.value(),
                             models=self._models(), profiles=self._profiles(), api_key=self.key_edit.text().strip())

    def _models(self) -> Dict[str, LocalModel]:
        out = {}
        for r in range(self.models_table.rowCount()):
            name = self.models_table.item(r, 0).text()
            context = self.models_table.cellWidget(r, 1)
            vision = self.models_table.cellWidget(r, 2).findChild(QCheckBox)
            out[name] = LocalModel(context=context.value(), vision=vision.isChecked())
        return out

    def _profiles(self) -> Dict[str, Dict[str, str]]:
        out = {}
        for r in range(self.profiles_table.rowCount()):
            item = self.profiles_table.item(r, 0)
            name = item.text().strip() if item else ""
            if not name:
                continue
            out[name] = {role: self.profiles_table.cellWidget(r, 1 + i).currentText()
                         for i, (role, _) in enumerate(local_models.PROFILE_ROLES)
                         if self.profiles_table.cellWidget(r, 1 + i).currentText()}
        return out

    def model_names(self) -> List[str]:
        return [self.models_table.item(r, 0).text() for r in range(self.models_table.rowCount())]

    # ---- models -----------------------------------------------------------------------------------
    def _kind_changed(self, *_a, update_url: bool = True) -> None:
        kind = self.kind_combo.currentData()
        if update_url and (not self.url_edit.text().strip() or self.url_edit.text().strip() in
                           local_models.DEFAULT_URLS.values()):
            self.url_edit.setText(local_models.DEFAULT_URLS[kind])
        self.key_edit.setVisible(kind == "openai")
        self.key_label.setVisible(kind == "openai")

    def refresh_models(self) -> bool:
        """Ask the server for its models; keeps the settings of models already listed."""
        local = self.settings()
        try:
            found = local_models.list_models(local)
        except Exception as e:                     # shown, never raised: the dialog stays usable
            self.status.setText(str(e))
            return False
        self._server_models = found
        models = dict(local.models)
        for m in found:
            if m["name"] not in models:
                context = min(local_models.DEFAULT_CONTEXT, m["max_context"] or local_models.DEFAULT_CONTEXT)
                models[m["name"]] = LocalModel(context=context, vision=bool(m["vision"]))
        names = {m["name"] for m in found}
        self._fill_models(models, missing={n for n in models if n not in names})
        self.status.setText(f"Connected: {len(found)} model(s) on the server." if found else
                            "Connected, but the server has no models yet (Ollama: 'ollama pull <model>').")
        self._refresh_profile_choices()
        return True

    def _fill_models(self, models: Dict[str, LocalModel], missing=frozenset()) -> None:
        maxima = {m["name"]: m["max_context"] for m in self._server_models}
        self.models_table.setRowCount(0)
        for name, spec in models.items():
            r = self.models_table.rowCount()
            self.models_table.insertRow(r)
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if name in missing:
                item.setToolTip("Not found on the server the last time it was asked.")
                item.setForeground(Qt.GlobalColor.gray)
            self.models_table.setItem(r, 0, item)
            spin = QSpinBox(minimum=2048, maximum=1_048_576, singleStep=8192)
            spin.setValue(spec.context)
            spin.setToolTip("Tokens the model holds at once (paper + instructions + answer)."
                            + (f" The model allows up to {maxima[name]:,}." if maxima.get(name) else "")
                            + " Longer needs more memory.")
            self.models_table.setCellWidget(r, 1, spin)
            box = QCheckBox()
            box.setChecked(spec.vision)
            box.setToolTip("Send this model the table and figure images (only for models that read images).")
            holder = QWidget()
            h = QHBoxLayout(holder)
            h.setContentsMargins(6, 0, 0, 0)
            h.addWidget(box)
            self.models_table.setCellWidget(r, 2, holder)
        self.models_table.resizeColumnToContents(1)

    # ---- profiles ---------------------------------------------------------------------------------
    def add_profile(self, name: Optional[str] = None, roles: Optional[Dict[str, str]] = None) -> None:
        r = self.profiles_table.rowCount()
        names = self.model_names()
        if name is None:
            taken = set(self._profiles())
            name = next(f"Local {i}" for i in range(1, 100) if f"Local {i}" not in taken)
            first = names[0] if names else ""
            roles = {role: first for role, _ in local_models.PROFILE_ROLES}
        self.profiles_table.blockSignals(True)
        self.profiles_table.insertRow(r)
        self.profiles_table.setItem(r, 0, QTableWidgetItem(name))
        for i, (role, _) in enumerate(local_models.PROFILE_ROLES):
            combo = QComboBox()
            combo.addItems(names)
            chosen = (roles or {}).get(role, "")
            if chosen and chosen not in names:
                combo.addItem(chosen)
            combo.setCurrentText(chosen)
            combo.currentTextChanged.connect(lambda _t: self.changed.emit())
            self.profiles_table.setCellWidget(r, 1 + i, combo)
        self.profiles_table.blockSignals(False)
        self.changed.emit()

    def remove_profile(self) -> None:
        r = self.profiles_table.currentRow()
        if r >= 0:
            self.profiles_table.removeRow(r)
            self.changed.emit()

    def _refresh_profile_choices(self) -> None:
        names = self.model_names()
        for r in range(self.profiles_table.rowCount()):
            for i in range(len(local_models.PROFILE_ROLES)):
                combo = self.profiles_table.cellWidget(r, 1 + i)
                current = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                if current and current not in names:
                    combo.addItem(current)
                combo.setCurrentText(current or (names[0] if names else ""))
                combo.blockSignals(False)

    def set_locked(self, locked: bool) -> None:
        for w in (self.kind_combo, self.url_edit, self.key_edit, self.test_btn, self.timeout_spin,
                  self.parallel_spin, self.models_table, self.profiles_table, self.add_profile_btn,
                  self.remove_profile_btn):
            w.setEnabled(not locked)
