"""Small reusable widgets."""
from __future__ import annotations
import html

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QLineEdit, QPlainTextEdit, QStyle,
                               QStyledItemDelegate, QTableWidget,
                               QToolTip, QVBoxLayout, QWidget)


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



class ColumnGroupBand(QWidget):
    """A strip above a table naming each block of columns once, centred over the block (the Rows tab's
    categories: Row, Metadata, Experimental Methodology, ...). Its own widget rather than part of the
    header, so the platform's header drawing can't repeat or clip it; it follows scrolling and column
    resizing. `set_groups([(label, first column, last column)])`."""

    def __init__(self, table, parent=None):
        super().__init__(parent)
        self.table = table
        self.groups: list = []
        header = table.horizontalHeader()
        header.sectionResized.connect(lambda *_: self.update())
        header.sectionMoved.connect(lambda *_: self.update())
        header.geometriesChanged.connect(self.update)
        table.horizontalScrollBar().valueChanged.connect(lambda *_: self.update())
        self.setFixedHeight(self.fontMetrics().height() + 10)
        self.setHidden(True)

    def set_groups(self, groups: list) -> None:
        self.groups = list(groups)
        self.setHidden(not self.groups)
        self.update()

    def _span(self, first: int, last: int) -> tuple:
        header = self.table.horizontalHeader()
        left = self.table.frameWidth() + (self.table.verticalHeader().width()
                                          if self.table.verticalHeader().isVisible() else 0)
        return (left + header.sectionViewportPosition(first),
                left + header.sectionViewportPosition(last) + header.sectionSize(last))

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:          # a block's full name (narrow blocks are shortened)
            x = e.position().x() if hasattr(e, "position") else e.pos().x()
            label = next((g[0] for g in self.groups if self._span(g[1], g[2])[0] <= x < self._span(g[1], g[2])[1]), "")
            if label:
                QToolTip.showText(e.globalPos(), label, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def paintEvent(self, event) -> None:
        if not self.groups:
            return
        painter = QPainter(self)
        header = self.table.horizontalHeader()
        # the table's columns start after its frame and its row-number column
        left = self.table.frameWidth() + (self.table.verticalHeader().width()
                                          if self.table.verticalHeader().isVisible() else 0)
        right = left + header.viewport().width()
        pal = self.palette()
        base, alt = pal.color(QPalette.ColorRole.Button), pal.color(QPalette.ColorRole.Midlight)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        for n, (label, first, last) in enumerate(self.groups):
            x0 = left + header.sectionViewportPosition(first)
            x1 = left + header.sectionViewportPosition(last) + header.sectionSize(last)
            x0, x1 = max(x0, left), min(x1, right)
            if x1 <= x0:
                continue
            rect = QRect(x0, 0, x1 - x0, self.height())
            painter.fillRect(rect, alt if n % 2 else base)
            painter.setPen(pal.color(QPalette.ColorRole.Mid))
            painter.drawLine(rect.topRight(), rect.bottomRight())
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            painter.setPen(pal.color(QPalette.ColorRole.ButtonText))
            text = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(rect.width() - 8, 0))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)     # once, centred over the visible part
        painter.end()


# ---- spaced rows: the style of the app's multi-column lists (Mickey, 2026-11-04/05) ------------------------------

ROW_GAP = 7       # px above and below each row's content; a faint line in the middle of the space between rows


class RowSeparatorDelegate(QStyledItemDelegate):
    """Taller rows (long texts wrap onto several lines) with a subtle line between them; `gap` = px above and
    below the text (larger for lists of long texts, e.g. the pack editor's rules)."""

    def __init__(self, parent=None, gap: int = ROW_GAP):
        super().__init__(parent)
        self.gap = gap

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), size.height() + 2 * self.gap)

    def paint(self, painter, option, index):
        g = self.gap
        option.rect.adjust(0, g, 0, -g)          # the text sits inside the gap
        super().paint(painter, option, index)
        option.rect.adjust(0, -g, 0, g)
        if index.row() < index.model().rowCount() - 1:
            line = QColor(option.palette.text().color())
            line.setAlphaF(0.14)
            painter.save()
            painter.setPen(QPen(line, 1))
            y = option.rect.bottom()
            painter.drawLine(option.rect.left(), y, option.rect.right(), y)
            painter.restore()


def in_cell(widget: QWidget) -> QWidget:
    """A cell widget (combo box, spin box) kept at its natural height, centred in the taller row; find it again
    with `table.cellWidget(r, c).findChild(...)`."""
    holder = QWidget()
    v = QVBoxLayout(holder)
    v.setContentsMargins(2, ROW_GAP, 2, ROW_GAP)
    v.addWidget(widget, alignment=Qt.AlignmentFlag.AlignVCenter)
    return holder


def style_rows(table: QTableWidget, delegate: "RowSeparatorDelegate" = None) -> None:
    """The spaced-rows style for a multi-column list: no grid, a faint line between rows, long texts wrapped (no
    '...'), row heights following the column widths (refitted once the layout settles). The default for every
    scrollable multi-column list of settings."""
    table.setShowGrid(False)
    table.setWordWrap(True)
    table.setTextElideMode(Qt.TextElideMode.ElideNone)
    table.setItemDelegate(delegate or RowSeparatorDelegate(table))
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    refit = lambda *_: QTimer.singleShot(0, table.resizeRowsToContents)
    table.horizontalHeader().sectionResized.connect(refit)
    table.model().rowsInserted.connect(refit)
    table.model().dataChanged.connect(refit)
