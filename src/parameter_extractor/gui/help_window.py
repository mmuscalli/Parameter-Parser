"""
Getting started (Help menu; also offered on first launch). Rewritten 2026-11-12 (Mickey): the workflow as it is now --
the five numbered steps of the main window, what happens during a run (figures, new columns), how to check the
results (Things to check, Review flagged values), and what to do later – in short sections, in the window's theme.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

# (number, title, what to do) – the main window's numbered steps
STEPS = [
    ("1", "Data pack",
     "What to extract, for your research area: its columns, steps and calculations. <i>New…</i> starts your own "
     "from a template, a copy, or a draft made from a few sample papers."),
    ("2", "Papers",
     "Add PDFs (or drop them on the window), type an arXiv ID, DOI, ADS bibcode or link, or add a list (CSV). A "
     "supplement next to a paper, named like it plus <code>_SI</code>, is read with it."),
    ("3", "What to extract",
     "Everything ticked gives the full dataset. Untick whole steps you don't need; untick single values to search "
     "only for those across your papers – quicker and cheaper."),
    ("4", "Options",
     "The model profile (Standard is the default; Economy is cheapest) and how many times values are read. The "
     "groups below it open with a click: <i>Paper text</i>, <i>While reading</i> and <i>Saved with the results</i>. "
     "Hover over any option for what it does."),
    ("5", "Run",
     "Press <i>Extract data</i>. Several papers run one after another; you can cancel at any time and resume later."),
]

# (title, paragraphs)
SECTIONS = [
    ("During a run", [
        "<b>Figures.</b> You're offered the paper's figures to digitize. In the digitizer, set the axes (or "
        "<i>Auto-calibrate</i>), check the suggested series, and add or find the points; the <i>Figure</i> tab holds "
        "the figure-wide settings. Ctrl+Z undoes.",
        "<b>New columns.</b> At the end, values the data pack has no column for are offered for review. What you "
        "accept is remembered for later papers.",
    ]),
    ("Checking the results", [
        "<b>Extracted data</b> – hover a value to see where in the paper it came from; double-click to correct it.",
        "<b>Things to check</b> – every flag, grouped by kind. <i>Review flagged values…</i> opens them beside the "
        "paper's table or figure: tick each once you've looked. Minor notes are there on request.",
        "<b>Figures, Tables, Equations</b> – what was read, as images; <b>Summary</b> – the steps and the cost.",
        "Rows come from the paper's tables and the figures you digitize. To also make rows from results stated in "
        "the text, tick that under <i>Options › While reading</i>.",
    ]),
    ("Later", [
        "Everything is saved as CSV files in the run's folder. <i>File › Open a results folder…</i> shows an earlier "
        "run again. <i>Resume a stopped run…</i> finishes one without repeating the steps already done; <i>Rebuild "
        "a run's dataset…</i> makes it again from its saved answers, at no cost.",
        "<i>Models</i> sets up profiles and model servers; <i>Settings › Theme</i> changes the colours; "
        "<i>Help › How data packs work…</i> explains steps, modules and calculations.",
    ]),
]

FIRST_TIME = ("Before your first run: add your Anthropic API key in <i>Settings…</i> (it is kept in the system "
              "keychain) and choose where results are saved.")


def html(palette: QPalette) -> str:
    """The guide in the window's colours (the theme's text, link and muted colours)."""
    accent = palette.color(QPalette.ColorRole.Link).name()
    muted = palette.color(QPalette.ColorRole.PlaceholderText).name()
    tint = palette.color(QPalette.ColorRole.AlternateBase).name()
    steps = "".join(
        f"<tr><td class='n'>{n}</td><td class='s'><b>{title}</b><br>{text}</td></tr>" for n, title, text in STEPS)
    sections = "".join(
        f"<h3>{title}</h3>" + "".join(f"<p>{p}</p>" for p in paragraphs) for title, paragraphs in SECTIONS)
    return f"""<style>
h2 {{ margin: 0 0 2px 0; font-size: 17pt; }}
h3 {{ margin: 16px 0 4px 0; font-size: 13pt; color: {accent}; }}
p {{ margin: 0 0 7px 0; line-height: 135%; }}
p.lead {{ color: {muted}; margin-bottom: 12px; }}
td.n {{ color: {accent}; font-weight: 700; font-size: 15pt; padding: 2px 12px 10px 0; vertical-align: top; }}
td.s {{ padding: 2px 0 10px 0; vertical-align: top; line-height: 130%; }}
</style>
<h2>Getting started</h2>
<p class='lead'>Parameter Extractor reads the papers you choose and fills a dataset with the values they report,
for you to review. Work down the main window's numbered steps.</p>
<table width='100%' cellpadding='9' cellspacing='0' bgcolor='{tint}'><tr><td>{FIRST_TIME}</td></tr></table>
<h3>The five steps</h3>
<table cellspacing='0'>{steps}</table>
{sections}"""


class GettingStartedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Getting started")
        self.resize(640, 720)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 12)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.browser.viewport().setAutoFillBackground(False)       # the window's own background, as a page
        self.browser.setHtml(html(self.palette()))
        v.addWidget(self.browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).setDefault(True)
        v.addWidget(buttons)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
