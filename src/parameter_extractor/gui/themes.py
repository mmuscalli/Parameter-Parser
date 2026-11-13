"""
Themes (Settings > Theme, Mickey 2026-11-12): the window's colours and the highlight colours the app paints itself
(flagged values, corrections, archive rows, boxes on table images, problem levels).

- `Default` is the app as it always looked: the platform's own style and palette (light or dark as macOS is set),
  and the highlight colours below (MARKS' defaults).
- Other themes set a full palette under Qt's Fusion style (the native macOS style ignores most palette colours) and
  their own highlight colours.

The highlight colours are shared QColor objects (`MARKS`) that the windows import (main_window.FLAG...COLOR is
MARKS["flagged_row"]); `apply` changes them IN PLACE, so code reading them at paint / fill time follows the theme --
the open results are refilled after a change (MainWindow._set_theme). Colours in style sheets (`css(name)`) are read
when a window is built: windows opened after the change follow it.

Choosing colours for a theme: text on its background at a contrast of at least 4.5:1 (WCAG AA), highlight cells
drawn with `mark_text` on them -- `contrast()` checks it (tests/test_themes.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from PySide6.QtGui import QColor, QPalette

THEME_KEY = "theme"                     # QSettings
DEFAULT = "default"

# highlight colours: name -> the app's default (Default theme)
_DEFAULT_MARKS = {
    "flagged_row": (255, 243, 205),      # a row with a flag (soft amber)
    "archive_row": (212, 237, 218),      # the fit the Exoplanet Archive took (soft green)
    "archive_diff": (255, 196, 140),     # a value that differs from the archive's (orange)
    "corrected": (196, 222, 255),        # a value you corrected (light blue)
    "flag": (255, 150, 70),              # a flagged value (Flagged values window)
    "flag_checked": (230, 230, 230),     # a flagged value whose flags are all checked
    "group_tint": (110, 140, 210, 28),   # every other block of columns
    "mark_text": (0, 0, 0),              # text on all of the above
    "mark_pen": (255, 110, 0),           # a value boxed on a table image: outline
    "mark_fill": (255, 214, 0, 90),      #   and fill
    "error": (190, 40, 40),              # problem levels (data pack check, warnings)
    "warning": (176, 110, 0),
    "note": (110, 110, 110),
    "muted": (128, 128, 128),            # secondary text drawn by the app
}
MARKS: Dict[str, QColor] = {name: QColor(*rgb) for name, rgb in _DEFAULT_MARKS.items()}


@dataclass
class Theme:
    id: str
    label: str
    description: str = ""
    palette: Dict[str, str] = field(default_factory=dict)     # QPalette role name -> colour; {} = the platform's
    marks: Dict[str, str] = field(default_factory=dict)       # MARKS name -> colour (missing: the default)


# Art Deco: from Mickey's sample palette (charcoal grey 30373E, deep burgundy 7A2038, burnished gold C49B4C, dark teal
# 0A4F54, antique beige E2D2B4) -- a dark theme. Adjusted for readability: the charcoal darkened for text fields and
# lifted for buttons; beige as the text colour (11:1 on the fields); gold and teal brightened where they carry text or
# selection; burgundy (too dark for text on charcoal) only as a fill under light text and, lightened, for errors.
ART_DECO = Theme(
    "art_deco", "Art Deco",
    "Charcoal, burgundy, gold, teal and beige -- a dark theme.",
    palette={
        "Window": "#30373E", "WindowText": "#E8DCC2",
        "Base": "#252B31", "AlternateBase": "#2C3339", "Text": "#E2D2B4",
        "Button": "#3B434B", "ButtonText": "#EADFC8",
        "Highlight": "#167A80", "HighlightedText": "#FBF4E6",
        "ToolTipBase": "#E2D2B4", "ToolTipText": "#252B31",
        "Link": "#D9B565", "LinkVisited": "#C49B4C",
        "PlaceholderText": "#A99F8B", "BrightText": "#FFFFFF",
        "Light": "#4A535C", "Midlight": "#414951", "Mid": "#2A3036", "Dark": "#1E2328", "Shadow": "#14181B",
        "Accent": "#C49B4C",
    },
    marks={
        "flagged_row": "#E9D5A6",    # light gold
        "archive_row": "#A9D3CB",    # light teal
        "archive_diff": "#E3A27A",   # copper
        "corrected": "#9CC6E0",      # light blue (corrections stay blue in every theme)
        "flag": "#D9AE57",           # burnished gold, brightened
        "flag_checked": "#A8A396",   # greyed beige
        "group_tint": "#22C49B4C",   # gold, faint (#AARRGGBB)
        "mark_text": "#1E2328",
        "mark_pen": "#9E2A47",       # burgundy on the white table images
        "mark_fill": "#5AC49B4C",
        "error": "#EC97A3",          # burgundy lightened to read on charcoal (5.5:1)
        "warning": "#D9B565",
        "note": "#A99F8B",
        "muted": "#A99F8B",
    })

# Orchid: from Mickey's palette (coolors.co: pale lavender E8D7F1, mauve D3BCCC, orchid A167A5, deep purple 4A306D,
# dark navy 0E273C) -- a light theme. Lavender window, near-white fields, navy text (14:1); mauve buttons; deep purple
# for selection and links; orchid tints for flags. Flags stay obvious against lavender (a stronger orchid), corrections
# stay blue, and problem colours are darkened to read on lavender.
ORCHID = Theme(
    "orchid", "Orchid",
    "Lavender, mauve, orchid, deep purple and navy -- a light theme.",
    palette={
        "Window": "#E8D7F1", "WindowText": "#0E273C",
        "Base": "#F7F0FA", "AlternateBase": "#EFE3F4", "Text": "#0E273C",
        "Button": "#D3BCCC", "ButtonText": "#0E273C",
        "Highlight": "#4A306D", "HighlightedText": "#F7F0FA",
        "ToolTipBase": "#0E273C", "ToolTipText": "#E8D7F1",
        "Link": "#4A306D", "LinkVisited": "#7A3F80",
        "PlaceholderText": "#65546E", "BrightText": "#FFFFFF",
        "Light": "#FBF7FD", "Midlight": "#F1E6F5", "Mid": "#BFA6BA", "Dark": "#8E7491", "Shadow": "#4A306D",
        "Accent": "#A167A5",
    },
    marks={
        "flagged_row": "#E6BEDD",    # orchid tint: stands out from the lavender
        "archive_row": "#CDE3D8",    # pale green-grey
        "archive_diff": "#E9B48C",   # apricot
        "corrected": "#B9D3EE",      # light blue (corrections stay blue in every theme)
        "flag": "#C58ACA",           # orchid, lifted
        "flag_checked": "#D3BCCC",   # mauve
        "group_tint": "#1E4A306D",   # deep purple, faint (#AARRGGBB)
        "mark_text": "#0E273C",
        "mark_pen": "#8E3F96",       # orchid, darkened, on the white table images
        "mark_fill": "#50A167A5",
        "error": "#A12A4A",
        "warning": "#7A4E00",
        "note": "#5E4E66",
        "muted": "#65546E",
    })

# Enchanted Night: from Mickey's palette (coolors.co: pink lilac FAA6FF, purple 7353BA, deep indigo 2F195F, near
# black 0F1020, pale pink EFC3F5) -- a dark theme. Near-black fields under an indigo-black window, pale pink text, indigo
# buttons, purple selection, lilac links and flags.
ENCHANTED_NIGHT = Theme(
    "enchanted_night", "Enchanted Night",
    "Near black, indigo, purple, lilac and pale pink -- a dark theme.",
    palette={
        "Window": "#17142D", "WindowText": "#F3D6F7",
        "Base": "#0F1020", "AlternateBase": "#191731", "Text": "#EFC3F5",
        "Button": "#2F195F", "ButtonText": "#F3D6F7",
        "Highlight": "#7353BA", "HighlightedText": "#FFFFFF",
        "ToolTipBase": "#EFC3F5", "ToolTipText": "#0F1020",
        "Link": "#FAA6FF", "LinkVisited": "#D9A6F2",
        "PlaceholderText": "#A894C2", "BrightText": "#FFFFFF",
        "Light": "#45307F", "Midlight": "#3A2670", "Mid": "#221642", "Dark": "#0A0B17", "Shadow": "#050510",
        "Accent": "#FAA6FF",
    },
    marks={
        "flagged_row": "#E4BCF0",    # pale lilac
        "archive_row": "#B9D9CB",    # pale green
        "archive_diff": "#F2B38A",   # apricot
        "corrected": "#A9C8F0",      # light blue (corrections stay blue in every theme)
        "flag": "#FAA6FF",           # pink lilac
        "flag_checked": "#B9AFC4",   # greyed lilac
        "group_tint": "#22FAA6FF",   # lilac, faint (#AARRGGBB)
        "mark_text": "#0F1020",
        "mark_pen": "#7353BA",       # purple on the white table images
        "mark_fill": "#5AFAA6FF",
        "error": "#FF93A8",
        "warning": "#F2C46D",
        "note": "#A894C2",
        "muted": "#A894C2",
    })

# Forest Whispers: from Mickey's palette (coolors.co: sage B5CA8D, leaf green 8BB174, grey teal 426B69, navy 222E50,
# dark teal 2A4849) -- a muted dark theme. Dark teal window, deeper teal fields, pale sage text, grey-teal buttons,
# navy selection, sage links and flags.
FOREST_WHISPERS = Theme(
    "forest_whispers", "Forest Whispers",
    "Dark teal, grey teal, navy, leaf green and sage -- a muted dark theme.",
    palette={
        "Window": "#2A4849", "WindowText": "#E6EED8",
        "Base": "#203738", "AlternateBase": "#264042", "Text": "#E4EDD5",
        "Button": "#426B69", "ButtonText": "#F1F5E8",
        "Highlight": "#222E50", "HighlightedText": "#E6EED8",
        "ToolTipBase": "#B5CA8D", "ToolTipText": "#222E50",
        "Link": "#C2D69C", "LinkVisited": "#A9C78F",
        "PlaceholderText": "#A9BDA0", "BrightText": "#FFFFFF",
        "Light": "#527F7C", "Midlight": "#4A7572", "Mid": "#1D3132", "Dark": "#162627", "Shadow": "#0D1718",
        "Accent": "#8BB174",
    },
    marks={
        "flagged_row": "#D9E5BC",    # pale sage
        "archive_row": "#BFD9D0",    # pale teal
        "archive_diff": "#E8B98C",   # apricot
        "corrected": "#B3CBEB",      # light blue (corrections stay blue in every theme)
        "flag": "#B5CA8D",           # sage
        "flag_checked": "#A6B3AA",   # greyed sage
        "group_tint": "#228BB174",   # leaf green, faint (#AARRGGBB)
        "mark_text": "#14201F",
        "mark_pen": "#3D7A2C",       # leaf green, darkened, on the white table images
        "mark_fill": "#5A8BB174",
        "error": "#F4A6A6",
        "warning": "#E9CC80",
        "note": "#B4C6AB",
        "muted": "#B4C6AB",
    })

THEMES: Dict[str, Theme] = {t.id: t for t in (Theme(DEFAULT, "Default", "The app's usual look (follows macOS light "
                                                                         "or dark)."), ART_DECO, ORCHID,
                                                ENCHANTED_NIGHT, FOREST_WHISPERS)}

_original_style: Optional[str] = None
_current = DEFAULT


def current() -> str:
    return _current


def css(name: str) -> str:
    """A highlight colour for a style sheet ('#rrggbb')."""
    return MARKS[name].name()


def _color(text: str) -> QColor:
    return QColor(text)


def build_palette(theme: Theme) -> QPalette:
    pal = QPalette()
    for role_name, value in theme.palette.items():
        role = getattr(QPalette.ColorRole, role_name, None)
        if role is None:
            continue
        color = _color(value)
        pal.setColor(QPalette.ColorGroup.All, role, color)
        if role_name in ("WindowText", "Text", "ButtonText"):        # disabled text: dimmed
            dim = QColor(color)
            dim.setAlphaF(0.45)
            pal.setColor(QPalette.ColorGroup.Disabled, role, dim)
    return pal


def apply(app, theme_id: str) -> str:
    """Use a theme (unknown ids: Default). Returns the id used."""
    global _original_style, _current
    theme = THEMES.get(theme_id) or THEMES[DEFAULT]
    if _original_style is None:
        _original_style = app.style().name()
    for name, rgb in _DEFAULT_MARKS.items():                         # in place: the windows hold these objects
        MARKS[name].setRgb(*rgb[:3], rgb[3] if len(rgb) > 3 else 255)
    for name, value in theme.marks.items():
        MARKS[name].setRgba(_color(value).rgba())
    if theme.palette:
        app.setStyle("Fusion")
        app.setPalette(build_palette(theme))
    else:
        app.setStyle(_original_style)
        app.setPalette(QPalette())                                    # the platform's own again
    _current = theme.id
    _restyle(app)
    return theme.id


def _restyle(app) -> None:
    """Open windows again in the new colours: style sheets and rich text resolve palette colours ('palette(link)',
    links) when they are set, so they are set again."""
    from PySide6.QtWidgets import QLabel
    for widget in app.allWidgets():
        sheet = widget.styleSheet()
        if sheet:
            widget.setStyleSheet("")
            widget.setStyleSheet(sheet)
        if isinstance(widget, QLabel) and "<" in widget.text():
            text = widget.text()
            widget.setText("")                     # (setText ignores an unchanged text)
            widget.setText(text)


def contrast(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio of two opaque colours."""
    def lum(c: QColor) -> float:
        def ch(v: float) -> float:
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c.redF()) + 0.7152 * ch(c.greenF()) + 0.0722 * ch(c.blueF())
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
