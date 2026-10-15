"""Small reusable widgets."""
from __future__ import annotations
import html

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QPlainTextEdit, QStyle,
                               QVBoxLayout)


class ExpandingLineEdit(QLineEdit):
    """A one-line text field for text that's often too long to fit: hovering shows
    the full text wrapped, and the button at its right end opens a pop-out editor.
    Same API as QLineEdit (text, setText, editingFinished, ...)."""

    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        self._title, self._hint = title, hint
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.expand_action = self.addAction(icon, QLineEdit.ActionPosition.TrailingPosition)
        self.expand_action.setToolTip("Show the full text")
        self.expand_action.triggered.connect(self.open_editor)
        self.textChanged.connect(self._update_tooltip)
        self._update_tooltip(self.text())

    def _update_tooltip(self, text: str) -> None:
        parts = []
        if text:
            parts.append(f"<p style='white-space: pre-wrap;'>{html.escape(text)}</p>")
        if self._hint:
            parts.append(f"<p><i>{html.escape(self._hint)}</i></p>")
        # rich text so Qt wraps it instead of showing one very long line
        self.setToolTip(f"<qt>{''.join(parts)}</qt>" if parts else "")

    def open_editor(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self._title)
        dialog.resize(560, 300)
        layout = QVBoxLayout(dialog)
        if self._hint:
            hint = QLabel(self._hint, wordWrap=True)
            hint.setStyleSheet("color: palette(placeholder-text);")
            layout.addWidget(hint)
        editor = QPlainTextEdit(self.text())
        editor.setReadOnly(self.isReadOnly() or not self.isEnabled())
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self._editor = editor                    # for tests
        if dialog.exec() == QDialog.DialogCode.Accepted and not editor.isReadOnly():
            new = " ".join(editor.toPlainText().split())     # one line: newlines become spaces
            if new != self.text():
                self.setText(new)
                self.editingFinished.emit()
