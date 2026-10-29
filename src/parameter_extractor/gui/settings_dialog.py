"""
Settings (Mickey, 2026-10-24: options consolidated so the main window stays uncluttered): the
things set once -- the Anthropic API key, the optional NASA ADS token, where results are saved,
online lookups. Opened from the menu (Settings…, Cmd+,) or the main window's Settings button.

The widgets live as long as the main window (which reads them at run time and keeps its old
attribute names: key_edit, out_edit, pubchem_box ...); closing the dialog only hides it.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

ADS_HELP = ("Optional. Only needed to look papers up by journal ADS bibcode (e.g. 2023PASJ...75.1030T); "
            "arXiv IDs and DOIs work without it. Free: ui.adsabs.harvard.edu → Account → Settings → API Token.")


def _row(*widgets) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for i, widget in enumerate(widgets):
        h.addWidget(widget, stretch=1 if i == 0 else 0)
    return w


def _secret(placeholder: str):
    edit = QLineEdit(placeholderText=placeholder, echoMode=QLineEdit.EchoMode.Password)
    show = QCheckBox("Show")
    show.toggled.connect(lambda on: edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
    return edit, show


class SettingsDialog(QDialog):
    # emitted when the dialog is closed: the main window saves the settings then (keys to the keychain
    # too), not only when a run starts -- the ADS token was otherwise lost if no extraction followed
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)

        keys = QGroupBox("Accounts")
        form = QFormLayout(keys)
        self.key_edit, self.show_key_box = _secret("sk-ant-…")
        self.remember_key_box = QCheckBox("Remember on this computer (system keychain)")
        form.addRow("Anthropic API key:", _row(self.key_edit, self.show_key_box))
        form.addRow("", self.remember_key_box)
        self.ads_edit, self.show_ads_box = _secret("optional")
        self.ads_edit.setToolTip(ADS_HELP)
        self.remember_ads_box = QCheckBox("Remember on this computer (system keychain)")
        form.addRow("NASA ADS API token:", _row(self.ads_edit, self.show_ads_box))
        form.addRow("", self.remember_ads_box)
        ads_note = QLabel(ADS_HELP, wordWrap=True)
        ads_note.setStyleSheet("color: palette(placeholder-text);")
        form.addRow("", ads_note)
        layout.addWidget(keys)

        files = QGroupBox("Results and lookups")
        form = QFormLayout(files)
        self.out_edit = QLineEdit()
        out_btn = QPushButton("Choose…", clicked=self._choose_output_dir)
        form.addRow("Save results to:", _row(self.out_edit, out_btn))
        self.pubchem_box = QCheckBox("Use online lookups (PubChem names, NASA Exoplanet Archive check)")
        self.pubchem_box.setToolTip("PubChem: recognises different names for the same compound (e.g. 2'-CMP and "
                                    "cytidine 2'-monophosphate). Exoplanet Archive: compares exoplanet values with "
                                    "the archive's parameter set for the same paper. Only species or planet names "
                                    "are sent; results are kept on this computer.")
        form.addRow("", self.pubchem_box)
        layout.addWidget(files)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.hide)
        buttons.accepted.connect(self.hide)
        layout.addWidget(buttons)

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save results to", self.out_edit.text())
        if path:
            self.out_edit.setText(path)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()

    def lock(self, locked: bool) -> None:
        """Read-only while a run uses these settings."""
        for w in (self.key_edit, self.remember_key_box, self.ads_edit, self.remember_ads_box, self.out_edit,
                  self.pubchem_box):
            w.setEnabled(not locked)
