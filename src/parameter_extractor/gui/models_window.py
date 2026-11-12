"""
Models > Model profiles… / Connections… (Mickey, 2026-11-11; model_profiles.py): the window for which models read a
paper, where they run, and the request settings data packs and modules don't decide.

Tab Profiles: the built-in Claude profiles (Standard, Balanced, Economy -- the tested defaults: locked until the user
confirms a change, then marked as changed, with Reset to default) and the user's own, on any connection. Each has a
model per role and advanced settings (output cap, temperature, prompt caching, steps at once, retries, prices of
models the price table doesn't know).
Tab Connections: the Anthropic API (its key is in Settings) and model servers, local or hosted (Ollama or
OpenAI-compatible): address, key (system keychain), time limit, requests at once, Test connection, and each model's
context length, whether it reads images, and prices.

Edits go to a working copy; Save writes model_profiles.json (and server keys to the keychain), Cancel drops them.
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from parameter_extractor.gui import themes
from parameter_extractor import local_models
from parameter_extractor import model_profiles as mp
from parameter_extractor.pricing import PRICES, PRICES_CHECKED

ID_ROLE = Qt.ItemDataRole.UserRole
WARNING_STYLE = "background: rgba(255, 193, 7, 0.18); border: 1px solid rgba(200, 140, 0, 0.6); padding: 6px;"
BUILTIN_NOTE = ("<b>A tested default.</b> The app's measured accuracy and costs are for this profile as it ships. "
                "Changing it affects every run that uses it; Reset to default brings it back.")
CHANGED_NOTE = ("<b>Changed from the tested default.</b> The accuracy and costs measured for {label} no longer apply "
                "to it. Reset to default brings it back.")
HELP = {
    "max_tokens": "The longest answer one step may write, in tokens. Each step also has its own budget, which this "
                  "caps. Default 64,000.",
    "temperature": "Lower values give more repeatable answers. Not set: the model's own default (Claude's is 1.0; the "
                   "app's measurements were made that way). Model servers get 0 unless set.",
    "prompt_caching": "The paper is sent once and the other steps read it at a tenth of the price. Turning it off makes "
                      "every step pay for the whole paper (useful only for measurements).",
    "parallel_steps": "How many of a paper's steps are sent at the same time (default 6). Lower it if your API key "
                      "hits its per-minute limit. A model server's own limit (Connections) still applies.",
    "retries": "How often a request is tried again when the API is busy or rate-limited (default 5).",
    "prices": "Price per million tokens for models the app's price table doesn't know, so the cost shown stays "
              f"right (the table was checked {PRICES_CHECKED}).",
    "thinking": "Models like qwen3 and gemma4 reason before they answer (about 1,000 tokens a request): more time, "
                "and less room left for the answer. Off: they answer directly (Ollama's think option). Whether the "
                "results hold without it is a measurement, not a given.",
    "context": "Tokens the model holds at once (paper + instructions + answer). Enter what fits in the server's "
               "memory, not the model's reported maximum: a larger value moves the model partly onto the CPU and "
               "makes it several times slower.",
}


def _help_label(text: str) -> QLabel:
    label = QLabel(text, wordWrap=True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def _price_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox(minimum=-0.01, maximum=1000.0, decimals=3, singleStep=0.1, prefix="$")
    spin.setSpecialValueText("—")            # -0.01 shows as '—': not set
    spin.setValue(-0.01)
    return spin


def _price_of(spin: QDoubleSpinBox) -> Optional[float]:
    return None if spin.value() < 0 else round(spin.value(), 4)


class ModelsWindow(QDialog):
    def __init__(self, parent=None, store: Optional[mp.ModelStore] = None, keys=None, tab: str = "profiles"):
        super().__init__(parent)
        self.setWindowTitle("Models")
        self.resize(1080, 720)
        self.store = store or mp.ModelStore()
        if keys is None:
            from parameter_extractor.gui import key_store as keys
        self.keys = keys
        self.saved = False
        self._unlocked = set()                 # built-in profiles the user confirmed changing (this window)
        self._new_keys: Dict[str, str] = {}    # connection account -> key typed here (saved on Save)
        self._profile_id: Optional[str] = None
        self._conn_id: Optional[str] = None
        self._loading = False

        v = QVBoxLayout(self)
        intro = _help_label("Which models read a paper, where they run, and the settings of those requests that data "
                            "packs don't decide. The Claude profiles are the tested defaults; profiles you add here "
                            "appear in the main window's Model list.")
        v.addWidget(intro)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._profiles_tab(), "Profiles")
        self.tabs.addTab(self._connections_tab(), "Connections")
        v.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        if self.store.migrated_from is not None:
            intro.setText(intro.text() + f"<br><i>Your local server settings were brought over from "
                                         f"{self.store.migrated_from.name} (Settings › Model provider) as the "
                                         f"connection 'Local server'. Save to keep them here.</i>")
        self._fill_profiles()
        self._fill_connections()
        self.tabs.setCurrentIndex(1 if tab == "connections" else 0)

    # ==== profiles =====================================================================================================
    def _profiles_tab(self) -> QWidget:
        w = QWidget()
        split = QSplitter(Qt.Orientation.Horizontal, w)
        lay = QHBoxLayout(w)
        lay.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._profile_selected)
        lv.addWidget(self.profile_list, 1)
        row = QHBoxLayout()
        self.new_btn = QPushButton("New profile")          # a push button with a menu: the same look as its neighbours
        self.new_menu = QMenu(self.new_btn)
        self.new_btn.setMenu(self.new_menu)
        self.new_menu.aboutToShow.connect(self._fill_new_menu)
        self.duplicate_btn = QPushButton("Duplicate", clicked=lambda: self.duplicate_profile())
        self.remove_btn = QPushButton("Remove", clicked=self.remove_profile)
        for b in (self.new_btn, self.duplicate_btn, self.remove_btn):
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        scroll = QScrollArea(widgetResizable=True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        ev = QVBoxLayout(body)
        self.note_label = QLabel(wordWrap=True)
        self.note_label.setStyleSheet(WARNING_STYLE)
        ev.addWidget(self.note_label)
        actions = QHBoxLayout()
        self.unlock_btn = QPushButton("Change these settings…", clicked=self.unlock)
        self.reset_btn = QPushButton("Reset to default", clicked=self.reset_profile)
        actions.addWidget(self.unlock_btn)
        actions.addWidget(self.reset_btn)
        actions.addStretch(1)
        ev.addLayout(actions)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_edit = QLineEdit()
        form.addRow("Name:", self.name_edit)
        self.connection_combo = QComboBox()
        form.addRow("Runs on:", self.connection_combo)
        self.description_edit = QLineEdit(placeholderText="optional: what this profile is for")
        form.addRow("Description:", self.description_edit)
        ev.addLayout(form)

        roles = QGroupBox("Models")
        rf = QFormLayout(roles)
        rf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.role_combos: Dict[str, QComboBox] = {}
        for role, label in mp.ROLES:
            combo = QComboBox(editable=True)
            combo.setToolTip(mp.ROLE_HELP[role])
            combo.currentTextChanged.connect(self._profile_edited)
            self.role_combos[role] = combo
            rf.addRow(f"{label}:", combo)
        ev.addWidget(roles)

        adv = QGroupBox("Advanced")
        af = QFormLayout(adv)
        self.max_tokens_spin = QSpinBox(minimum=1024, maximum=200_000, singleStep=1024)
        self.max_tokens_spin.setToolTip(HELP["max_tokens"])
        af.addRow("Output cap (tokens):", self.max_tokens_spin)
        trow = QHBoxLayout()
        self.temp_box = QCheckBox("Set")
        self.temp_spin = QDoubleSpinBox(minimum=0.0, maximum=2.0, singleStep=0.1, decimals=2)
        self.temp_box.toggled.connect(self.temp_spin.setEnabled)
        trow.addWidget(self.temp_box)
        trow.addWidget(self.temp_spin)
        trow.addStretch(1)
        for wdg in (self.temp_box, self.temp_spin):
            wdg.setToolTip(HELP["temperature"])
        af.addRow("Temperature:", trow)
        self.caching_box = QCheckBox("Reuse the paper across a run's steps (prompt caching)")
        self.caching_box.setToolTip(HELP["prompt_caching"])
        af.addRow("", self.caching_box)
        self.parallel_spin = QSpinBox(minimum=1, maximum=16)
        self.parallel_spin.setToolTip(HELP["parallel_steps"])
        af.addRow("Steps at once:", self.parallel_spin)
        self.retries_spin = QSpinBox(minimum=0, maximum=10)
        self.retries_spin.setToolTip(HELP["retries"])
        self.retries_label = QLabel("Retries:")
        af.addRow(self.retries_label, self.retries_spin)
        for wdg in (self.max_tokens_spin, self.temp_spin, self.parallel_spin, self.retries_spin):
            wdg.valueChanged.connect(self._profile_edited)
        for wdg in (self.temp_box, self.caching_box):
            wdg.toggled.connect(self._profile_edited)
        self.name_edit.textChanged.connect(self._profile_edited)
        self.description_edit.textChanged.connect(self._profile_edited)
        self.connection_combo.currentIndexChanged.connect(self._connection_changed)
        ev.addWidget(adv)

        self.prices_box = QGroupBox("Prices of models the app doesn't know ($ per million tokens)")
        pv = QVBoxLayout(self.prices_box)
        pv.addWidget(_help_label(HELP["prices"]))
        self.prices_table = QTableWidget(0, 3)
        self.prices_table.setHorizontalHeaderLabels(["Model", "Input", "Output"])
        self.prices_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.prices_table.verticalHeader().setVisible(False)
        self.prices_table.setMaximumHeight(130)
        pv.addWidget(self.prices_table)
        ev.addWidget(self.prices_box)
        self.problems_label = QLabel(wordWrap=True)
        self.problems_label.setStyleSheet(f"color: {themes.css('error')};")
        ev.addWidget(self.problems_label)
        ev.addStretch(1)
        split.addWidget(scroll)
        split.setSizes([300, 760])
        return w

    def _fill_profiles(self, select: Optional[str] = None) -> None:
        self._loading = True
        self.profile_list.clear()
        last_conn = None
        for p in self.store.profiles():
            if p.connection != last_conn:
                conn = self.store.connection(p.connection)
                header = QListWidgetItem(conn.name if conn else p.connection)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self.profile_list.addItem(header)
                last_conn = p.connection
            item = QListWidgetItem(self._list_text(p))
            item.setData(ID_ROLE, p.id)
            item.setToolTip(mp.summary(self.store, p))
            self.profile_list.addItem(item)
        self._loading = False
        self.select_profile(select or self._profile_id or "standard")

    def _list_text(self, p: mp.Profile) -> str:
        if p.builtin:
            return f"    {p.label}" + (" (default)" if p.id == "standard" else "") + \
                ("  • changed" if self.store.is_changed(p.id) else "")
        return f"    {p.label}"

    def select_profile(self, pid: str) -> None:
        for r in range(self.profile_list.count()):
            if self.profile_list.item(r).data(ID_ROLE) == pid:
                self.profile_list.setCurrentRow(r)
                return

    def _fill_new_menu(self) -> None:
        self.new_menu.clear()
        for conn in self.store.all_connections():
            self.new_menu.addAction(f"On {conn.name}…", lambda c=conn.id: self.new_profile(c))
        if not self.store.connections:
            self.new_menu.addSeparator()
            self.new_menu.addAction("Add a model server first (Connections tab)…",
                                    lambda: self.tabs.setCurrentIndex(1))

    def _current(self) -> Optional[mp.Profile]:
        return self.store.profile(self._profile_id) if self._profile_id else None

    def _profile_selected(self, item, _previous=None) -> None:
        if self._loading:
            return
        self._commit_profile()
        pid = item.data(ID_ROLE) if item is not None else None
        if pid is None:
            return
        self._profile_id = pid
        self._load_profile(self.store.profile(pid))

    def _load_profile(self, p: mp.Profile) -> None:
        self._loading = True
        conn = self.store.connection(p.connection)
        anthropic = conn is not None and conn.is_anthropic
        self.name_edit.setText(p.label)
        self.description_edit.setText(p.description)
        self.connection_combo.clear()
        for c in self.store.all_connections():
            self.connection_combo.addItem(c.name, c.id)
        self.connection_combo.setCurrentIndex(max(0, self.connection_combo.findData(p.connection)))
        self._fill_role_choices(conn, p.roles)
        self.max_tokens_spin.setValue(int(p.max_tokens))
        self.temp_box.setChecked(p.temperature is not None)
        self.temp_spin.setValue(float(p.temperature or 0.0))
        self.temp_spin.setEnabled(p.temperature is not None)
        self.caching_box.setChecked(bool(p.prompt_caching))
        self.parallel_spin.setValue(int(p.parallel_steps))
        self.retries_spin.setValue(int(p.retries))
        for wdg in (self.caching_box, self.retries_spin, self.retries_label):
            wdg.setVisible(anthropic)                    # Claude-only settings
        self._fill_prices(p)
        self._loading = False
        self._update_state()

    def _fill_role_choices(self, conn, roles: Dict[str, str]) -> None:
        names = list(conn.models) if conn else []
        for role, combo in self.role_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            chosen = roles.get(role, "")
            if chosen and chosen not in names:
                combo.addItem(chosen)
            combo.setCurrentText(chosen)
            combo.blockSignals(False)

    def _fill_prices(self, p: mp.Profile) -> None:
        conn = self.store.connection(p.connection)
        unknown = []
        if conn is not None and conn.is_anthropic:
            from parameter_extractor.pricing import _tiers
            unknown = sorted({m for m in self._roles_now().values() if m and _tiers(m) is None})
        self.prices_table.setRowCount(0)
        for model in unknown:
            r = self.prices_table.rowCount()
            self.prices_table.insertRow(r)
            item = QTableWidgetItem(model)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.prices_table.setItem(r, 0, item)
            for c, key in ((1, "input"), (2, "output")):
                spin = _price_spin()
                value = (p.prices.get(model) or {}).get(key)
                if value is not None:
                    spin.setValue(float(value))
                spin.valueChanged.connect(self._profile_edited)
                self.prices_table.setCellWidget(r, c, spin)
        self.prices_box.setVisible(bool(unknown))

    def _roles_now(self) -> Dict[str, str]:
        return {role: combo.currentText().strip() for role, combo in self.role_combos.items()}

    def _editable(self, p: mp.Profile) -> bool:
        return not p.builtin or p.id in self._unlocked or self.store.is_changed(p.id)

    def _update_state(self) -> None:
        p = self._current()
        if p is None:
            return
        editable = self._editable(p)
        for wdg in [self.max_tokens_spin, self.temp_box, self.caching_box, self.parallel_spin, self.retries_spin,
                    self.prices_table, *self.role_combos.values()]:
            wdg.setEnabled(editable)
        self.temp_spin.setEnabled(editable and self.temp_box.isChecked())
        self.name_edit.setEnabled(not p.builtin)
        self.description_edit.setEnabled(not p.builtin)
        self.connection_combo.setEnabled(not p.builtin)
        self.remove_btn.setEnabled(not p.builtin)
        changed = p.builtin and self.store.is_changed(p.id)
        self.note_label.setVisible(p.builtin)
        self.note_label.setText(CHANGED_NOTE.format(label=p.label) if changed else BUILTIN_NOTE)
        self.unlock_btn.setVisible(p.builtin and not editable)
        self.reset_btn.setVisible(p.builtin)
        self.reset_btn.setEnabled(changed)
        problems = self.store.problems(p)
        self.problems_label.setText(("This profile can't run: " + "; ".join(problems) + ".") if problems else "")

    def _confirm_change(self, label: str) -> bool:
        """Asked before a built-in profile can be changed (tests replace it)."""
        answer = QMessageBox.warning(
            self, "Change a default profile?",
            f"{label} is one of the app's tested defaults: its accuracy and costs were measured as it ships, and every "
            f"run that uses it will use your changes.\n\nYou can always go back with Reset to default.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Ok

    def unlock(self) -> None:
        p = self._current()
        if p is not None and p.builtin and self._confirm_change(p.label):
            self._unlocked.add(p.id)
            self._update_state()

    def _profile_edited(self, *_a) -> None:
        if self._loading:
            return
        self._commit_profile()
        p = self._current()
        if p is not None:
            self._loading = True
            self._fill_prices(p)
            self._loading = False
            item = self.profile_list.currentItem()
            if item is not None:
                item.setText(self._list_text(p))
                item.setToolTip(mp.summary(self.store, p))
        self._update_state()

    def _commit_profile(self) -> None:
        """The editor's values into the working copy."""
        p = self._current()
        if p is None or self._loading or not self._editable(p):
            return
        p.roles = {r: m for r, m in self._roles_now().items() if m}
        p.max_tokens = self.max_tokens_spin.value()
        p.temperature = round(self.temp_spin.value(), 2) if self.temp_box.isChecked() else None
        p.prompt_caching = self.caching_box.isChecked()
        p.parallel_steps = self.parallel_spin.value()
        p.retries = self.retries_spin.value()
        prices = {}
        for r in range(self.prices_table.rowCount()):
            model = self.prices_table.item(r, 0).text()
            i, o = (_price_of(self.prices_table.cellWidget(r, c)) for c in (1, 2))
            if i is not None or o is not None:
                prices[model] = {"input": i or 0.0, "output": o or 0.0}
        p.prices = prices
        if not p.builtin:
            p.label = self.name_edit.text().strip() or p.label
            p.description = self.description_edit.text().strip()
            p.connection = self.connection_combo.currentData() or p.connection
        self.store.update(p)

    def _connection_changed(self, _i) -> None:
        if self._loading:
            return
        p = self._current()
        if p is None or p.builtin:
            return
        self._commit_profile()
        conn = self.store.connection(p.connection)
        self._loading = True
        self._fill_role_choices(conn, p.roles)
        anthropic = conn is not None and conn.is_anthropic
        for wdg in (self.caching_box, self.retries_spin, self.retries_label):
            wdg.setVisible(anthropic)
        self._loading = False
        self._profile_edited()
        self._fill_profiles(select=p.id)

    def new_profile(self, connection: str, label: Optional[str] = None) -> None:
        self._commit_profile()
        if label is None:
            conn = self.store.connection(connection)
            label, ok = QInputDialog.getText(self, "New profile", f"Name of the new profile on {conn.name}:")
            if not ok or not label.strip():
                return
        p = self.store.add_profile(label.strip(), connection)
        self._fill_profiles(select=p.id)

    def duplicate_profile(self, label: Optional[str] = None) -> None:
        p = self._current()
        if p is None:
            return
        self._commit_profile()
        if label is None:
            label, ok = QInputDialog.getText(self, "Duplicate", "Name of the copy:", text=f"{p.label} (copy)")
            if not ok or not label.strip():
                return
        copy = self.store.add_profile(label.strip(), p.connection, copy_of=p.id)
        self._fill_profiles(select=copy.id)

    def remove_profile(self) -> None:
        p = self._current()
        if p is None or p.builtin:
            return
        self.store.remove_profile(p.id)
        self._profile_id = None
        self._fill_profiles(select="standard")

    def reset_profile(self) -> None:
        p = self._current()
        if p is None or not p.builtin:
            return
        self.store.reset(p.id)
        self._unlocked.discard(p.id)
        self._profile_id = None                     # nothing to commit: the default is back
        self._fill_profiles(select=p.id)

    # ==== connections ===================================================================================================
    def _connections_tab(self) -> QWidget:
        w = QWidget()
        split = QSplitter(Qt.Orientation.Horizontal, w)
        lay = QHBoxLayout(w)
        lay.addWidget(split)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.conn_list = QListWidget()
        self.conn_list.currentItemChanged.connect(self._conn_selected)
        lv.addWidget(self.conn_list, 1)
        row = QHBoxLayout()
        self.add_server_btn = QPushButton("Add a server")
        menu = QMenu(self.add_server_btn)
        menu.addAction("Ollama (local)…", lambda: self.add_server("ollama"))
        menu.addAction("OpenAI-compatible (LM Studio, llama.cpp, vLLM, or a hosted service)…",
                       lambda: self.add_server("openai"))
        self.add_server_btn.setMenu(menu)
        self.remove_server_btn = QPushButton("Remove", clicked=self.remove_server)
        row.addWidget(self.add_server_btn)
        row.addWidget(self.remove_server_btn)
        lv.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        self.anthropic_info = _help_label(
            "Claude models through the Anthropic API, with the API key set in Settings. These are the models the "
            f"app is validated with. Prices come from the app's table (checked {PRICES_CHECKED}); a model not in it "
            "can still be used in a profile, with prices entered there.")
        rv.addWidget(self.anthropic_info)
        self.server_box = QWidget()
        sf = QFormLayout(self.server_box)
        sf.setContentsMargins(0, 0, 0, 0)
        sf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.conn_name_edit = QLineEdit()
        sf.addRow("Name:", self.conn_name_edit)
        self.kind_combo = QComboBox()
        for kind, label in local_models.KINDS.items():
            self.kind_combo.addItem(label, kind)
        sf.addRow("Type:", self.kind_combo)
        self.url_edit = QLineEdit()
        self.url_edit.setToolTip("Where the server listens. Ollama: http://localhost:11434; LM Studio: "
                                 "http://localhost:1234; a hosted service: its https address (e.g. "
                                 "https://api.openai.com or https://openrouter.ai/api).")
        self.test_btn = QPushButton("Test connection", clicked=self.test_connection)
        urow = QHBoxLayout()
        urow.addWidget(self.url_edit, 1)
        urow.addWidget(self.test_btn)
        sf.addRow("Address:", urow)
        self.conn_key_edit = QLineEdit(placeholderText="only if the server asks for one (kept in the system keychain)",
                                       echoMode=QLineEdit.EchoMode.Password)
        sf.addRow("API key:", self.conn_key_edit)
        self.timeout_spin = QSpinBox(minimum=30, maximum=7200, singleStep=60, suffix=" s", maximumWidth=140)
        self.timeout_spin.setToolTip("Longest wait for the next part of an answer. A local machine can take several "
                                     "minutes just to read a long paper.")
        sf.addRow("Time limit:", self.timeout_spin)
        self.server_parallel_spin = QSpinBox(minimum=1, maximum=64, maximumWidth=140)
        self.server_parallel_spin.setToolTip("How many requests the server answers at once (Ollama: usually 1). "
                                             "The app's steps wait their turn beyond that.")
        sf.addRow("Requests at once:", self.server_parallel_spin)
        rv.addWidget(self.server_box)
        self.conn_status = _help_label("")
        rv.addWidget(self.conn_status)
        rv.addWidget(QLabel("<b>Models</b>"))
        self.models_table = QTableWidget(0, 6)
        self.models_table.setHorizontalHeaderLabels(["Model", "Context (tokens)", "Reads images",
                                                     "Input $/M tokens", "Output $/M tokens", "Thinking"])
        self.models_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.models_table.verticalHeader().setVisible(False)
        self.models_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        rv.addWidget(self.models_table, 1)
        mrow = QHBoxLayout()
        self.add_model_btn = QPushButton("Add a model by name…", clicked=lambda: self.add_model())
        self.remove_model_btn = QPushButton("Remove model", clicked=self.remove_model)
        mrow.addWidget(self.add_model_btn)
        mrow.addWidget(self.remove_model_btn)
        mrow.addStretch(1)
        rv.addLayout(mrow)
        self.models_note = _help_label(HELP["context"] + " Prices: leave '—' on a server on your own computer or "
                                       "network (free); a hosted service's cost shows as unknown without them.")
        rv.addWidget(self.models_note)
        for wdg in (self.conn_name_edit, self.url_edit):
            wdg.textChanged.connect(self._conn_edited)
        self.conn_key_edit.textChanged.connect(self._key_edited)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.timeout_spin.valueChanged.connect(self._conn_edited)
        self.server_parallel_spin.valueChanged.connect(self._conn_edited)
        split.addWidget(right)
        split.setSizes([300, 760])
        return w

    def _fill_connections(self, select: Optional[str] = None) -> None:
        self._loading = True
        self.conn_list.clear()
        for c in self.store.all_connections():
            item = QListWidgetItem(c.name)
            item.setData(ID_ROLE, c.id)
            item.setToolTip(f"{mp.KINDS.get(c.kind, c.kind)}" + (f" at {c.url}" if c.url else ""))
            self.conn_list.addItem(item)
        self._loading = False
        wanted = select or self._conn_id or mp.ANTHROPIC
        for r in range(self.conn_list.count()):
            if self.conn_list.item(r).data(ID_ROLE) == wanted:
                self.conn_list.setCurrentRow(r)

    def _conn(self) -> Optional[mp.Connection]:
        return self.store.connection(self._conn_id) if self._conn_id else None

    def _conn_selected(self, item, _previous=None) -> None:
        if self._loading:
            return
        self._commit_connection()
        cid = item.data(ID_ROLE) if item is not None else None
        if cid is None:
            return
        self._conn_id = cid
        conn = self.store.connection(cid)
        self._loading = True
        anthropic = conn.is_anthropic
        self.anthropic_info.setVisible(anthropic)
        self.server_box.setVisible(not anthropic)
        for wdg in (self.add_model_btn, self.remove_model_btn, self.models_note):
            wdg.setVisible(not anthropic)
        self.remove_server_btn.setEnabled(not anthropic)
        self.conn_status.setText("")
        if not anthropic:
            self.conn_name_edit.setText(conn.name)
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(conn.kind)))
            self.url_edit.setText(conn.url)
            self.conn_key_edit.setText(self._new_keys.get(conn.account, "") or self._stored_key(conn))
            self.conn_key_edit.setEnabled(conn.kind == "openai")
            self.timeout_spin.setValue(int(conn.timeout_sec))
            self.server_parallel_spin.setValue(int(conn.parallel))
        self._fill_models(conn)
        self._loading = False

    def _stored_key(self, conn: mp.Connection) -> str:
        try:
            return self.keys.load_key(conn.account) or ""
        except Exception:
            return ""

    def _fill_models(self, conn: mp.Connection, maxima: Optional[dict] = None, missing=frozenset()) -> None:
        t = self.models_table
        t.setRowCount(0)
        anthropic = conn.is_anthropic
        for name, spec in conn.models.items():
            r = t.rowCount()
            t.insertRow(r)
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if name in missing:
                item.setToolTip("Not found on the server the last time it was asked.")
                item.setForeground(Qt.GlobalColor.gray)
            t.setItem(r, 0, item)
            if anthropic:
                tiers = PRICES.get(name, [(None, None, None, None, None)])
                for c, text in ((1, "200,000"), (2, "yes"), (3, f"${tiers[0][1]:g}" if tiers[0][1] is not None else "—"),
                                (4, f"${tiers[0][2]:g}" if tiers[0][2] is not None else "—"), (5, "—")):
                    cell = QTableWidgetItem(text)
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    t.setItem(r, c, cell)
                continue
            spin = QSpinBox(minimum=2048, maximum=2_097_152, singleStep=8192)
            spin.setValue(int(spec.context))
            spin.setToolTip(HELP["context"] + (f" The server reports a maximum of {maxima[name]:,}."
                                               if maxima and maxima.get(name) else ""))
            spin.valueChanged.connect(self._conn_edited)
            t.setCellWidget(r, 1, spin)
            box = QCheckBox()
            box.setChecked(bool(spec.vision))
            box.setToolTip("Send this model the table and figure images (only for models that read images).")
            box.toggled.connect(self._conn_edited)
            holder = QWidget()
            h = QHBoxLayout(holder)
            h.setContentsMargins(8, 0, 0, 0)
            h.addWidget(box)
            t.setCellWidget(r, 2, holder)
            for c, value in ((3, spec.price_input), (4, spec.price_output)):
                p = _price_spin()
                if value is not None:
                    p.setValue(float(value))
                p.valueChanged.connect(self._conn_edited)
                t.setCellWidget(r, c, p)
            think = QComboBox()
            think.addItem("As the model decides", "model")
            think.addItem("Off", "off")
            think.setCurrentIndex(max(0, think.findData(getattr(spec, "thinking", "model"))))
            think.setEnabled(conn.kind == "ollama")
            think.setToolTip(HELP["thinking"] if conn.kind == "ollama" else
                             "Only for Ollama: OpenAI-compatible servers have no standard switch for it.")
            think.currentIndexChanged.connect(self._conn_edited)
            t.setCellWidget(r, 5, think)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _models_from_table(self) -> Dict[str, mp.ServerModel]:
        out = {}
        t = self.models_table
        for r in range(t.rowCount()):
            name = t.item(r, 0).text()
            context = t.cellWidget(r, 1)
            vision = t.cellWidget(r, 2)
            if context is None or vision is None:          # the Anthropic table is read-only text
                return {}
            out[name] = mp.ServerModel(context=context.value(), vision=vision.findChild(QCheckBox).isChecked(),
                                       price_input=_price_of(t.cellWidget(r, 3)),
                                       price_output=_price_of(t.cellWidget(r, 4)),
                                       thinking=t.cellWidget(r, 5).currentData() or "model")
        return out

    def _commit_connection(self) -> None:
        conn = self._conn()
        if conn is None or conn.is_anthropic or self._loading:
            return
        conn.name = self.conn_name_edit.text().strip() or conn.name
        conn.kind = self.kind_combo.currentData() or conn.kind
        conn.url = self.url_edit.text().strip()
        conn.timeout_sec = self.timeout_spin.value()
        conn.parallel = self.server_parallel_spin.value()
        conn.models = self._models_from_table()

    def _conn_edited(self, *_a) -> None:
        if self._loading:
            return
        self._commit_connection()
        conn = self._conn()
        item = self.conn_list.currentItem()
        if conn is not None and item is not None and not conn.is_anthropic:
            item.setText(conn.name)

    def _key_edited(self, text: str) -> None:
        conn = self._conn()
        if conn is not None and not self._loading and not conn.is_anthropic:
            self._new_keys[conn.account] = text.strip()

    def _kind_changed(self, _i) -> None:
        if self._loading:
            return
        kind = self.kind_combo.currentData()
        if not self.url_edit.text().strip() or self.url_edit.text().strip() in local_models.DEFAULT_URLS.values():
            self.url_edit.setText(local_models.DEFAULT_URLS[kind])
        self.conn_key_edit.setEnabled(kind == "openai")
        self._conn_edited()

    def add_server(self, kind: str, name: Optional[str] = None) -> None:
        self._commit_connection()
        if name is None:
            default = "Local server" if kind == "ollama" else "Model server"
            name, ok = QInputDialog.getText(self, "Add a server", "Name for this server:", text=default)
            if not ok or not name.strip():
                return
        conn = self.store.add_connection(name.strip(), kind)
        self._fill_connections(select=conn.id)

    def remove_server(self) -> None:
        conn = self._conn()
        if conn is None or conn.is_anthropic:
            return
        gone = self.store.remove_connection(conn.id)
        if gone:
            QMessageBox.information(self, "Server removed", f"Its profiles were removed too: {', '.join(gone)}.")
        self._conn_id = None
        self._fill_connections(select=mp.ANTHROPIC)
        self._fill_profiles(select="standard")

    def add_model(self, name: Optional[str] = None) -> None:
        conn = self._conn()
        if conn is None or conn.is_anthropic:
            return
        self._commit_connection()
        if name is None:
            name, ok = QInputDialog.getText(self, "Add a model", "The model's name as the server knows it:")
            if not ok or not name.strip():
                return
        conn.models.setdefault(name.strip(), mp.ServerModel())
        self._loading = True
        self._fill_models(conn)
        self._loading = False

    def remove_model(self) -> None:
        conn = self._conn()
        r = self.models_table.currentRow()
        if conn is None or conn.is_anthropic or r < 0:
            return
        self._commit_connection()
        conn.models.pop(self.models_table.item(r, 0).text(), None)
        self._loading = True
        self._fill_models(conn)
        self._loading = False

    def test_connection(self) -> bool:
        """Asks the server for its models; keeps the settings of models already listed, adds the new ones."""
        conn = self._conn()
        if conn is None or conn.is_anthropic:
            return False
        self._commit_connection()
        settings = local_models.LocalSettings(kind=conn.kind, url=conn.url, timeout_sec=conn.timeout_sec,
                                              parallel=conn.parallel, api_key=self.conn_key_edit.text().strip())
        try:
            found = local_models.list_models(settings)
        except Exception as e:                         # shown, never raised: the window stays usable
            self.conn_status.setText(str(e))
            return False
        for m in found:
            if m["name"] not in conn.models:
                context = min(local_models.DEFAULT_CONTEXT, m["max_context"] or local_models.DEFAULT_CONTEXT)
                conn.models[m["name"]] = mp.ServerModel(context=context, vision=bool(m["vision"]))
        names = {m["name"] for m in found}
        self._loading = True
        self._fill_models(conn, maxima={m["name"]: m["max_context"] for m in found},
                          missing={n for n in conn.models if n not in names})
        self._loading = False
        self.conn_status.setText(f"Connected: {len(found)} model(s) on the server." if found else
                                 "Connected, but the server has no models yet (Ollama: 'ollama pull <model>').")
        return True

    # ==== saving =====================================================================================================
    def save(self) -> None:
        self._commit_profile()
        self._commit_connection()
        self.store.save()
        for account, key in self._new_keys.items():
            try:
                if key:
                    self.keys.save_key(key, account)
                else:
                    self.keys.delete_key(account)
            except Exception:
                pass                                   # the keychain fails soft (key_store)
        self.saved = True
        self.accept()
