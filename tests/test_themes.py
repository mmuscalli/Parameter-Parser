"""
Themes (Settings > Theme, gui/themes.py, 2026-11-12): Default keeps the app's colours exactly; every other theme keeps
text readable (WCAG AA contrast, 4.5:1, for text on its background and on every highlight colour); switching changes
the shared highlight colours in place (the windows hold them), is remembered, and back to Default restores everything.

Run with: python tests/test_themes.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QCoreApplication.setOrganizationName("ParameterExtractorTests")
app = QApplication.instance() or QApplication([])

from parameter_extractor.gui import themes  # noqa: E402

TEXT_PAIRS = [("Text", "Base"), ("Text", "AlternateBase"), ("WindowText", "Window"), ("ButtonText", "Button"),
              ("HighlightedText", "Highlight"), ("ToolTipText", "ToolTipBase"), ("Link", "Window"), ("Link", "Base")]
MARK_BACKGROUNDS = ["flagged_row", "archive_row", "archive_diff", "corrected", "flag", "flag_checked"]


def test_every_theme_is_readable():
    for theme in themes.THEMES.values():
        if not theme.palette:
            continue
        pal = {k: QColor(v) for k, v in theme.palette.items()}
        for fg, bg in TEXT_PAIRS:
            ratio = themes.contrast(pal[fg], pal[bg])
            assert ratio >= 4.5, (theme.id, fg, bg, round(ratio, 2))
        assert themes.contrast(pal["PlaceholderText"], pal["Base"]) >= 4.5, theme.id
        text = QColor(theme.marks["mark_text"])
        for name in MARK_BACKGROUNDS:
            assert themes.contrast(text, QColor(theme.marks[name])) >= 4.5, (theme.id, name)
        for name in ("error", "warning", "note", "muted"):
            assert themes.contrast(QColor(theme.marks[name]), pal["Window"]) >= 4.5, (theme.id, name)


def test_switching_and_back_to_default():
    from parameter_extractor.gui import flagged_values, main_window
    default_flag = QColor(flagged_values.FLAG_COLOR)
    style = app.style().name()
    assert main_window.CORRECTED_COLOR is themes.MARKS["corrected"] is flagged_values.CORRECTED_COLOR
    assert default_flag.name() == "#ff9646"                          # Default = the app's colours as they were
    themes.apply(app, "art_deco")
    assert flagged_values.FLAG_COLOR.name() == QColor(themes.ART_DECO.marks["flag"]).name()   # changed in place
    assert app.style().name().lower() == "fusion"
    assert app.palette().color(app.palette().ColorRole.Base).name() == themes.ART_DECO.palette["Base"].lower()
    themes.apply(app, "default")
    assert flagged_values.FLAG_COLOR == default_flag and app.style().name() == style
    assert themes.MARKS["group_tint"].alpha() == 28
    assert themes.apply(app, "no such theme") == "default"


def test_the_settings_menu():
    from parameter_extractor.gui import main_window
    QSettings().clear()
    w = main_window.MainWindow()
    labels = [a.text() for a in w.theme_menu.actions()]
    assert labels == [t.label for t in themes.THEMES.values()] and w.theme_actions.checkedAction().text() == "Default"
    next(a for a in w.theme_menu.actions() if a.data() == "art_deco").trigger()
    assert themes.current() == "art_deco" and QSettings().value(themes.THEME_KEY) == "art_deco"
    assert w.theme_actions.checkedAction().data() == "art_deco"
    w._set_theme("default")
    assert QSettings().value(themes.THEME_KEY) == "default"
    w.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All theme tests passed.")
