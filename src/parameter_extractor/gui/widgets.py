"""Small reusable widgets."""
from __future__ import annotations
import html

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QStyle,
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


class GroupedHeader(QHeaderView):
    """A table's column header with a band above the column names naming each block of columns
    (the Rows tab's categories: Row, Metadata, Experimental Methodology, ...). `set_groups([(label, first,
    last)])` with section indexes; no groups = an ordinary header."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.groups: list = []
        self.setSectionsClickable(True)

    def set_groups(self, groups: list) -> None:
        self.groups = list(groups)
        self.updateGeometry()
        self.viewport().update()

    def _band(self) -> int:
        return self.fontMetrics().height() + 8 if self.groups else 0

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        size.setHeight(size.height() + self._band())
        return size

    def paintSection(self, painter: QPainter, rect: QRect, index: int) -> None:
        super().paintSection(painter, rect.adjusted(0, self._band(), 0, 0), index)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.groups:
            return
        painter = QPainter(self.viewport())
        band = self._band()
        pal = self.palette()
        base, alt = pal.color(QPalette.ColorRole.Button), pal.color(QPalette.ColorRole.Midlight)
        for n, (label, first, last) in enumerate(self.groups):
            x0 = self.sectionViewportPosition(first)
            x1 = self.sectionViewportPosition(last) + self.sectionSize(last)
            if x1 < 0 or x0 > self.viewport().width():
                continue
            rect = QRect(x0, 0, x1 - x0, band)
            painter.fillRect(rect, alt if n % 2 else base)
            painter.setPen(pal.color(QPalette.ColorRole.Mid))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.setPen(pal.color(QPalette.ColorRole.ButtonText))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            # keep the name in view while the block is scrolled partly out of sight
            visible = rect.intersected(QRect(0, 0, self.viewport().width(), band)).adjusted(6, 0, -6, 0)
            text = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(visible.width(), 0))
            painter.drawText(visible, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.end()
