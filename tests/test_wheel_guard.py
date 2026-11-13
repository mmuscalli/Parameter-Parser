"""
Scrolling past a dropdown or number box doesn't change it (Mickey, 2026-11-12: the Model dropdown and the digitizer's
coordinate system changed while scrolling the page). gui/widgets.WheelGuard, installed on the application by
gui/app.py: the wheel changes such a field only after it was clicked; otherwise the scroll area behind it scrolls.

Run with: python tests/test_wheel_guard.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import time


def _wheel(widget, steps=-1):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, 120 * steps),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    QApplication.processEvents()


def test_wheel_needs_a_click_first():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget
    from parameter_extractor.gui.widgets import install_wheel_guard
    app = QApplication.instance() or QApplication([])
    install_wheel_guard(app)
    assert install_wheel_guard(app) is app._wheel_guard                # once
    area = QScrollArea()
    page = QWidget()
    layout = QVBoxLayout(page)
    combo, spin = QComboBox(), QSpinBox()
    combo.addItems(["a", "b", "c", "d"])
    layout.addSpacing(400)
    layout.addWidget(combo)
    layout.addWidget(spin)
    layout.addSpacing(1200)
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.resize(300, 300)
    area.show()
    for _ in range(5):
        app.processEvents()
        time.sleep(0.02)
    area.verticalScrollBar().setValue(300)
    app.processEvents()
    before = area.verticalScrollBar().value()
    combo.setFocus()                             # focus a window gives its first field: not a click
    app.processEvents()
    _wheel(combo)
    _wheel(spin)
    assert combo.currentIndex() == 0 and spin.value() == 0             # hovering: values unchanged
    assert area.verticalScrollBar().value() != before                  # ... and the page scrolled instead
    # clicked: the wheel goes to the field, until it loses focus
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(spin, press)
    app.processEvents()
    if spin.hasFocus():                          # offscreen focus can be unavailable; then only the guard is checked
        _wheel(spin, steps=1)
        assert spin.value() == 1
        combo.setFocus()
        app.processEvents()
        assert spin._wheel_armed is False
        _wheel(spin, steps=1)
        assert spin.value() == 1
    area.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All wheel-guard tests passed.")
