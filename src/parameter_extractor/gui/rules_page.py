"""
The pack editor's Rules tab (Mickey, 2026-11-19: "more information about the row planning rules, and make seeing /
editing rules from different shared prompts more intuitive"; in the style of the Steps and Columns tabs).

Left: the shared prompts a data pack can add rules to (pack_editing.RULE_PROMPTS), each with what it's for and how
many rules it has, then the pack's own whole prompts (view only). Right: the chosen prompt as the model gets it, top
to bottom -- the app's text in parts (one line each; open one to read it), and, where the prompt's {{PACK_RULES}} slot
is, this pack's rules (edited in place: one row per rule) with the rules its linked modules add. A pack with a whole
prompt of its own sees that prompt instead, and whether its rules are used. "Show the whole prompt…" shows it put
together as it is sent (the rules not saved yet included).
"""
from __future__ import annotations

import html
import re
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)

from parameter_extractor.gui import themes
from parameter_extractor.gui.widgets import RowSeparatorDelegate, style_rows
from parameter_extractor.pack_editing import RULE_PROMPTS, items_to_rules, rules_to_items

RULES_ROW_GAP = 13      # rules are long texts: more room between them and the lines (Mickey, 2026-11-06)
SLOT = "{{PACK_RULES}}"
# each shared prompt: its name in the list, and when it's sent
PROMPTS = {
    "structure_planner": ("Planning the rows", "Sent once for every paper, first: the 'Plan the rows' step."),
    "figure_planner": ("Figure suggestions", "Sent for each figure you digitize, for its suggested columns."),
    "focused_search": ("Focused searches", "Sent for each paper of a focused search (a few values across many "
                                           "papers)."),
    "metadata": ("The paper's details", "Sent once for every paper: the 'Read the paper's details' step."),
}
PARTS = re.compile(r"\{\{(PACK_RULES|MODULE_RULES|PAPER_TEXT)\}\}")


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 15px; font-weight: bold;")
    return label


def _muted(text: str = "") -> QLabel:
    label = QLabel(text, wordWrap=True, textFormat=Qt.TextFormat.RichText)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


class _Part(QFrame):
    """A part of the app's text: its first line; opened, all of it."""

    def __init__(self, heading: str, text: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 6)
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        self.toggle = QToolButton(text=f"{heading} -- {len(lines)} line{'s' if len(lines) != 1 else ''}",
                                  checkable=True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        v.addWidget(self.toggle)
        first = lines[0] if lines else ""
        self.preview = _muted(html.escape(first if len(first) < 110 else first[:107] + "…"))
        v.addWidget(self.preview)
        self.full = QLabel(html.escape(text.strip()).replace("\n", "<br>"), wordWrap=True,
                           textFormat=Qt.TextFormat.RichText)
        self.full.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.full.setStyleSheet("font-family: Menlo, monospace; font-size: 11px;")
        self.full.setVisible(False)
        v.addWidget(self.full)
        self.toggle.toggled.connect(self._open)

    def _open(self, on: bool) -> None:
        self.full.setVisible(on)
        self.preview.setVisible(not on)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)


class RulesPage(QWidget):
    """`draft`: the PackDraft (its `rules` are changed here); `saved_pack`: callable -> the pack as saved (its
    modules' rules) or None; `show_modules`: opens the Modules tab."""

    def __init__(self, draft, read_only: bool, saved_pack: Callable, show_modules: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        self.draft, self.read_only, self._saved_pack, self._show_modules = draft, read_only, saved_pack, show_modules
        self.shown: Optional[str] = None
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(_title("Prompts"))
        left.addWidget(_muted("The app's shared prompts this data pack can add rules to. A rule is one short "
                              "instruction, added where the prompt has room for this data pack's rules."))
        self.prompt_list = QListWidget()
        self.prompt_list.setMinimumWidth(270)
        self.prompt_list.setMaximumWidth(330)
        self.prompt_list.setWordWrap(True)
        self.prompt_list.setSpacing(3)
        left.addWidget(self.prompt_list, 1)
        outer.addLayout(left)

        # the chosen prompt, top to bottom
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(14, 0, 6, 0)
        self.body.setSpacing(8)
        head = QHBoxLayout()
        self.heading = _title("")
        head.addWidget(self.heading, 1)
        self.show_btn = QPushButton("Show the whole prompt…", clicked=self.show_prompt)
        self.show_btn.setToolTip("The prompt put together as it is sent, with this data pack's rules (also ones not "
                                 "saved yet).")
        head.addWidget(self.show_btn)
        self.body.addLayout(head)
        self.about = _muted()
        self.body.addWidget(self.about)
        self.note = QLabel(wordWrap=True)
        self.note.setStyleSheet(f"color: {themes.css('warning')};")
        self.body.addWidget(self.note)
        self.parts = QVBoxLayout()                  # the prompt's parts; the rules box goes in at its slot
        self.parts.setSpacing(6)
        self.body.addLayout(self.parts)
        self.body.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)

        # the rules box (kept across prompts; put in at the slot)
        self.rules_box = QFrame()
        self.rules_box.setObjectName("rulesBox")
        self.rules_box.setStyleSheet("#rulesBox { border: 2px solid palette(highlight); border-radius: 8px; }")
        rv = QVBoxLayout(self.rules_box)
        rv.setContentsMargins(12, 10, 12, 10)
        self.rules_title = QLabel(textFormat=Qt.TextFormat.RichText)
        self.rules_title.setStyleSheet("font-weight: bold;")
        rv.addWidget(self.rules_title)
        self.guide = _muted()
        rv.addWidget(self.guide)
        self.rules_table = QTableWidget(0, 1)
        self.rules_table.setHorizontalHeaderLabels(["Rule (double-click to edit)"])
        self.rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rules_table.verticalHeader().setVisible(True)
        style_rows(self.rules_table, RowSeparatorDelegate(self.rules_table, gap=RULES_ROW_GAP))
        self.rules_table.setMinimumHeight(170)
        rv.addWidget(self.rules_table)
        buttons = QHBoxLayout()
        self.rule_buttons = []
        for text, slot in (("Add rule", self.add_rule), ("Remove", self.remove_rule),
                           ("Up", lambda: self.move_rule(-1)), ("Down", lambda: self.move_rule(1))):
            b = QPushButton(text, clicked=lambda _c=False, s=slot: s())
            b.setEnabled(not read_only)
            self.rule_buttons.append(b)
            buttons.addWidget(b)
        buttons.addStretch(1)
        rv.addLayout(buttons)
        self.module_title = QLabel(textFormat=Qt.TextFormat.RichText)
        self.module_title.setStyleSheet("font-weight: bold;")
        rv.addWidget(self.module_title)
        self.module_rules = _muted()
        self.module_rules.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rv.addWidget(self.module_rules)
        self.modules_btn = QPushButton("Choose them in the Modules tab", clicked=lambda: self._show_modules and
                                       self._show_modules())
        rv.addWidget(self.modules_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.rules_table.itemChanged.connect(lambda _i: self.store())   # the list's counts follow
        if read_only:
            from PySide6.QtWidgets import QAbstractItemView
            self.rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.fill_list()
        self.prompt_list.currentRowChanged.connect(self._on_row)
        self._on_row(self.prompt_list.currentRow())        # fill_list chose the first one quietly

    # ---- the list ------------------------------------------------------------------------------------------------

    def _own_prompt(self, name: str) -> str:
        path = self.draft.folder / "prompts" / f"{name}.md"
        return path.read_text() if path.is_file() else ""

    def _status(self, name: str) -> str:
        n = len(rules_to_items(self.draft.rules.get(name, "")))
        rules = f"{n} rule{'s' if n != 1 else ''}" if n else "no rules yet"
        if name in self.draft.own_prompts:
            return f"own whole prompt · {rules}" + ("" if SLOT in self._own_prompt(name) else " (not used)")
        extra = len(self.module_row_rules()[0]) if name == "structure_planner" else 0
        return rules + (f" · {extra} from modules" if extra else "")

    def fill_list(self) -> None:
        row = max(self.prompt_list.currentRow(), 0)
        self.prompt_list.blockSignals(True)
        self.prompt_list.clear()
        for name in RULE_PROMPTS:
            title = PROMPTS.get(name, (name, ""))[0]
            item = QListWidgetItem(f"{title}\n{self._status(name)}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.prompt_list.addItem(item)
        others = [n for n in self.draft.own_prompts if n not in RULE_PROMPTS]
        if others:
            head = QListWidgetItem("This data pack's own prompts")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.prompt_list.addItem(head)
            for name in others:
                item = QListWidgetItem(f"{name}\nwhole prompt of its own (prompts/{name}.md)")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.prompt_list.addItem(item)
        self.prompt_list.setCurrentRow(min(row, self.prompt_list.count() - 1))
        self.prompt_list.blockSignals(False)

    def _refresh_status(self) -> None:
        for r in range(self.prompt_list.count()):
            item = self.prompt_list.item(r)
            name = item.data(Qt.ItemDataRole.UserRole)
            if name in RULE_PROMPTS:
                item.setText(f"{PROMPTS.get(name, (name, ''))[0]}\n{self._status(name)}")

    def _on_row(self, row: int) -> None:
        item = self.prompt_list.item(row) if row >= 0 else None
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if name:
            self.open_prompt(name)

    def select(self, name: str) -> None:
        for r in range(self.prompt_list.count()):
            if self.prompt_list.item(r).data(Qt.ItemDataRole.UserRole) == name:
                self.prompt_list.setCurrentRow(r)
                return

    # ---- one prompt ----------------------------------------------------------------------------------------------

    def template(self, name: str) -> Tuple[str, str]:
        """(the prompt's text, where it comes from) -- the pack's own, else a module's, else the app's."""
        own = self._own_prompt(name)
        if own:
            return own, f"this data pack's own prompts/{name}.md"
        pack = self._saved_pack()
        if pack is not None:
            path = pack.prompt_path(name)
            if path.is_file():
                return path.read_text(), "the app" if "packs" not in path.parts else str(path.name)
        from parameter_extractor.config import settings
        path = settings.PROMPTS_DIR / f"{name}.md"
        return (path.read_text() if path.is_file() else ""), "the app"

    def module_row_rules(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """The row rules the linked modules add to planning the rows: (used, left out by this pack) as
        [(module label, rule)]."""
        pack = self._saved_pack()
        if pack is None:
            return [], []
        from parameter_extractor import module_settings as ms
        used, off = [], []
        for mod in pack.modules:
            left_out = ms.settings_for(pack.own_manifest.module_settings, mod.id).row_rules_off
            for r in mod.manifest.row_rules:
                (off if r in left_out else used).append((mod.label, r))
        return used, off

    def _words(self, text: str) -> str:
        units = self.draft.manifest.get("units", {})
        for key, value in (("RESEARCH_AREA", (self.draft.manifest.get("label") or "").lower()),
                           ("SET_WORD", units.get("set", "set")), ("SAMPLE_WORD", units.get("sample", "sample"))):
            text = text.replace("{{" + key + "}}", value)
        return text

    def open_prompt(self, name: str) -> None:
        """The prompt's parts, top to bottom, with the rules box at its slot."""
        self.store()
        self.shown = name
        while self.parts.count():                   # the previous prompt's parts
            w = self.parts.takeAt(0).widget()
            if w is not None and w is not self.rules_box:
                w.deleteLater()
            elif w is self.rules_box:
                w.setParent(None)
        title, when = PROMPTS.get(name, (name, ""))
        self.heading.setText(title)
        text, source = self.template(name)
        editable = name in RULE_PROMPTS
        own = name in self.draft.own_prompts
        slot = SLOT in text
        self.about.setText(" ".join(x for x in (
            html.escape(RULE_PROMPTS.get(name, "")), html.escape(when),
            f"The prompt's text: {html.escape(source)}.") if x))
        if own and editable and not slot:
            self.note.setText(f"This data pack has a whole {title.lower()} prompt of its own, without a place for "
                              "rules ({{PACK_RULES}}): rules added here aren't used. Its row rules are in the prompt "
                              "itself (prompts/" + name + ".md in the pack's folder).")
        elif own and editable:
            self.note.setText("This data pack has a whole prompt of its own; its rules go where it says "
                              "{{PACK_RULES}}.")
        else:
            self.note.setText("")
        self.note.setVisible(bool(self.note.text()))

        from parameter_extractor.stages.prompt_loader import apply_sections
        text = apply_sections(self._words(text), {})
        pieces = PARTS.split(text)                  # text, slot name, text, slot name, ...
        first_text = True
        for i, piece in enumerate(pieces):
            if i % 2 == 0:
                if piece.strip():
                    heading = ("The app's instructions" if source == "the app" else "The prompt") if first_text \
                        else ("Then: the app's text" if source == "the app" else "Then")
                    self.parts.addWidget(_Part(heading, piece))
                    first_text = False
            elif piece == "PACK_RULES":
                self._fill_rules_box(name)
                self.parts.addWidget(self.rules_box)
            elif piece == "PAPER_TEXT":
                self.parts.addWidget(_muted("<i>… then the paper's text (tables, captions; page images where "
                                            "attached).</i>"))
            elif piece == "MODULE_RULES":
                self.parts.addWidget(_muted("<i>(the rules this step's modules add)</i>"))
        if editable and not slot:                   # rules that aren't used: still shown, after the prompt
            self._fill_rules_box(name, used=False)
            self.parts.addWidget(self.rules_box)
        self.rules_box.setVisible(editable)
        self.show_btn.setEnabled(bool(text))

    def _fill_rules_box(self, name: str, used: bool = True) -> None:
        """The rules box for `name`; `used` False: the prompt has no place for them (shown, marked unused)."""
        units = self.draft.manifest.get("units", {})
        group, row = units.get("set", "set"), units.get("sample", "sample")
        self.rules_title.setText("This data pack's rules <span style='font-weight: normal; color: gray'>-- added "
                                 "here, under 'Rules for this research area'</span>" if used else
                                 "This data pack's rules <span style='font-weight: normal; color: gray'>-- not used: "
                                 "the prompt above has no place for them</span>")
        if name == "structure_planner":
            self.guide.setText(
                f"Good row rules answer three questions, in a few lines: <b>what one row is</b> (one {html.escape(row)}"
                f": a time point, a sample, a table entry), <b>what makes rows one set</b> (one {html.escape(group)}: "
                f"what its rows share, what varies along it), and <b>which results must not become rows</b> "
                f"(controls, values quoted from other papers, ...). The words '{html.escape(group)}' and "
                f"'{html.escape(row)}' are this data pack's (General tab).")
        else:
            self.guide.setText("Short instructions that hold for this research area only: the shared prompt "
                               "already covers what every data pack needs.")
        self.set_rules_items(rules_to_items(self.draft.rules.get(name, "")))
        has_rules = bool(self.rules_items())
        for w in [self.guide, self.rules_table] + self.rule_buttons:   # nothing to show or add where none apply
            w.setVisible(used or has_rules)
        slot_used = used
        used, off = self.module_row_rules() if name == "structure_planner" else ([], [])
        self.module_title.setText(("Added by the linked modules" if slot_used else
                                   "The linked modules' row rules <span style='font-weight: normal; color: gray'>-- "
                                   "not used either (they go in the same place)</span>") if used or off else "")
        lines = [f"• {html.escape(r)} <i>({html.escape(m)})</i>" for m, r in used] + \
            [f"<s>{html.escape(r)}</s> <i>({html.escape(m)}; left out for this data pack)</i>" for m, r in off]
        self.module_rules.setText("<br>".join(lines))
        for w in (self.module_title, self.module_rules, self.modules_btn):
            w.setVisible(bool(used or off))

    # ---- the rules -----------------------------------------------------------------------------------------------

    def rules_items(self) -> list:
        t = self.rules_table
        return [t.item(r, 0).text() for r in range(t.rowCount()) if t.item(r, 0) and t.item(r, 0).text().strip()]

    def set_rules_items(self, items: list) -> None:
        self.rules_table.blockSignals(True)
        self.rules_table.setRowCount(0)
        for text in items:
            self.add_rule(text, edit=False)
        self.rules_table.blockSignals(False)

    def add_rule(self, text: str = "", edit: bool = True) -> None:
        r = self.rules_table.rowCount()
        self.rules_table.insertRow(r)
        self.rules_table.setItem(r, 0, QTableWidgetItem(text if isinstance(text, str) else ""))
        if edit:
            self.rules_table.setCurrentCell(r, 0)
            self.rules_table.editItem(self.rules_table.item(r, 0))

    def remove_rule(self) -> None:
        for r in sorted({i.row() for i in self.rules_table.selectedIndexes()}, reverse=True):
            self.rules_table.removeRow(r)
        self.store()

    def move_rule(self, step: int) -> None:
        r = self.rules_table.currentRow()
        if r < 0 or not 0 <= r + step < self.rules_table.rowCount():
            return
        items = [self.rules_table.item(i, 0).text() if self.rules_table.item(i, 0) else ""
                 for i in range(self.rules_table.rowCount())]
        items[r], items[r + step] = items[r + step], items[r]
        self.set_rules_items(items)
        self.rules_table.setCurrentCell(r + step, 0)
        self.store()

    def store(self) -> None:
        """The shown prompt's rules into the draft."""
        if self.shown in RULE_PROMPTS and not self.read_only:
            self.draft.rules[self.shown] = items_to_rules(self.rules_items())
            self._refresh_status()

    # ---- the whole prompt ----------------------------------------------------------------------------------------

    def assembled(self, name: str) -> str:
        """The prompt as sent (HTML): the app's text with this pack's words, its rules (highlighted) where they go;
        the paper and other per-paper parts as placeholders. Options off (rows from tables only)."""
        from parameter_extractor.stages.prompt_loader import apply_sections
        self.store()
        text, _source = self.template(name)
        text = apply_sections(self._words(text), {})
        rules = self.draft.rules.get(name, "")
        if name == "structure_planner":
            rules = (rules.rstrip() + "\n" if rules.strip() else "") + "".join(
                f"- {r}\n" for _m, r in self.module_row_rules()[0] if r not in rules)
        label = self.draft.manifest.get("label", "")
        out = html.escape(text)
        filled = (f"\nRules for this research area ({html.escape(label)}):\n{html.escape(rules.strip())}\n"
                  if rules.strip() else "")
        out = out.replace(html.escape(SLOT), f"<span style='background:{themes.css('corrected')}; color:"
                                             f"{themes.css('mark_text')}'>{filled}</span>" if filled
                          else "<span style='color:gray'>(no rules: nothing goes here)</span>")
        out = re.sub(r"\{\{(\w+)\}\}", lambda m: f"<span style='color:gray'>[{m.group(1).lower().replace('_', ' ')}"
                                               f"]</span>", out)
        return f"<pre style='white-space: pre-wrap; font-family: Menlo, monospace; font-size: 11px'>{out}</pre>"

    def show_prompt(self) -> None:
        if not self.shown:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{PROMPTS.get(self.shown, (self.shown, ''))[0]}: the whole prompt")
        dlg.resize(860, 700)
        lay = QVBoxLayout(dlg)
        lay.addWidget(_muted("As it is sent for a paper with this data pack: its rules are highlighted (also ones not "
                             "saved yet); the parts in [brackets] are filled in for each paper. Read-only."))
        view = QTextBrowser()
        view.setHtml(self.assembled(self.shown))
        lay.addWidget(view, 1)
        lay.addWidget(QPushButton("Close", clicked=dlg.accept), alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()
