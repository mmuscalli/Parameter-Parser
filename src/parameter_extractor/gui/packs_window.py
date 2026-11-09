"""
The Data Packs window (Mickey, 2026-11-09: a standalone place for data packs -- look at them, make new ones, copy,
edit, check, remove -- and for the shared modules they link).

Tab "Data packs": every pack (the app's own and yours) on the left; the selected one on the right -- what it is made of
(its own parts, the modules it links and whether it changes them) and what happens to each paper with it (every model
request and where it comes from, every calculation; pack_overview.py). Tab "Modules": every shared module, what it
brings and which data packs link it. The actions use the main window's (new / copy / edit / remove), so lists stay in
step.
"""
from __future__ import annotations
from html import escape
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from parameter_extractor import packs


def pack_html(pack: packs.Pack) -> str:
    """A data pack's make-up and its way of reading a paper."""
    from parameter_extractor import module_settings as ms, pack_overview
    from parameter_extractor.stages.optional import _specs_in
    m, own = pack.manifest, pack.own_manifest
    kind = "part of the app (read-only; copy it to change it)" if packs.BUILTIN_DIR in pack.folder.parents \
        else "yours"
    own_steps = list(_specs_in(pack.folder / "stages").values()) if (pack.folder / "stages").is_dir() else []
    def row(term, value):
        return f"<tr><td class='term' width='26%' valign='top'>{escape(term)}</td><td valign='top'>{value}</td></tr>"
    defined = "".join([
        row("Rows", f"a group of rows is a <i>{escape(m.units.get('set', 'set'))}</i>, one row a "
                    f"<i>{escape(m.units.get('sample', 'sample'))}</i>"),
        row("Columns", str(len(pack.template_columns))),
        row("Its own steps", escape(", ".join(s.label for s in own_steps)) or "none"),
        row("Its own built-in steps", escape(", ".join(own.builtin_stages)) or "none"),
        row("Its own calculations", escape(", ".join(own.postprocess)) or "none"),
        row("Formulas", str(len(own.formulas)))])
    parts = [pack_overview.STYLE, f"<h2>{escape(pack.label)}</h2><p class='muted'>{escape(kind)} &nbsp;·&nbsp; "
             f"folder: {escape(str(pack.folder))}</p>",
             f"<p>{escape(m.description)}</p>" if m.description else "",
             "<h3>Defined by this data pack</h3>",
             f"<table cellpadding='6' cellspacing='0' width='100%'>{defined}</table>",
             "<h3>Modules it links (shared)</h3>"]
    if pack.modules:
        rows = []
        for mod in pack.modules:
            settings = ms.settings_for(own.module_settings, mod.id)
            notes = [] if mod.id in own.modules else ["brought along by another module"]
            if not ms.is_default(settings):
                notes.append("changed for this data pack")
            rows.append(f"<tr><td class='term' width='26%' valign='top'>{escape(mod.label)}"
                        + (f"<br><span class='muted'>{escape('; '.join(notes))}</span>" if notes else "")
                        + f"</td><td valign='top'>{escape(mod.manifest.description)}</td></tr>")
        parts.append("<table cellpadding='6' cellspacing='0' width='100%'>" + "".join(rows) + "</table>")
    else:
        parts.append("<p>none</p>")
    parts.append("<h2>What happens to each paper</h2>")
    parts.append(pack_overview.as_html(pack_overview.paper_flow(pack)))
    return "".join(parts)


def module_html(mod, users) -> str:
    from parameter_extractor import pack_modules
    from parameter_extractor.pack_overview import STYLE
    lines = "".join(f"<tr><td valign='top'>•</td><td>{escape(l)}</td></tr>" for l in pack_modules.describe(mod.id))
    where = "part of the app" if mod.builtin else "yours"
    used = ", ".join(escape(p.label) for p in users) or "no data pack yet"
    return (STYLE + f"<h2>{escape(mod.label)}</h2><p class='muted'>{where} &nbsp;·&nbsp; folder: "
            f"{escape(str(mod.folder))}</p><p>{escape(mod.manifest.description)}</p>"
            f"<h3>What it brings</h3><table cellpadding='4' cellspacing='0'>{lines}</table>"
            f"<h3>Linked by</h3><p>{used}</p>"
            "<p class='muted'>A module is the same in every data pack that links it. A data pack can change how it "
            "works for that pack only, on the pack's Modules tab (Edit…).</p>")


class DataPacksWindow(QDialog):
    """See the module docstring. `main` is the main window (its pack actions and its Data pack list)."""

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.setWindowTitle("Data packs")
        self.resize(1180, 780)
        v = QVBoxLayout(self)
        intro = QLabel("A <b>data pack</b> holds everything the app needs for one field: its columns, how rows are "
                       "planned, its own extraction steps and calculations, and the shared <b>modules</b> it links. "
                       "Each <b>step</b> is one request to the AI model per paper; <b>calculations</b> run on your "
                       "computer. Select a data pack to see what it is made of and what happens to each paper.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._packs_tab(), "Data packs")
        self.tabs.addTab(self._modules_tab(), "Modules (shared)")
        v.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(QPushButton("Close", clicked=self.accept))
        v.addLayout(bottom)
        self.refresh()

    # ---- data packs ----------------------------------------------------------------------------------------------

    def _packs_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.pack_list = QListWidget()
        self.pack_list.currentRowChanged.connect(lambda _r: self._show_pack())
        self.pack_list.itemDoubleClicked.connect(lambda _i: self._edit())
        split.addWidget(self.pack_list)
        self.pack_view = QTextBrowser()
        self.pack_view.document().setDocumentMargin(18)
        split.addWidget(self.pack_view)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([300, 880])
        v.addWidget(split, 1)
        row = QHBoxLayout()
        self.use_btn = QPushButton("Use for the next run", clicked=self._use)
        self.use_btn.setToolTip("Choose this data pack in the main window's step 1.")
        self.new_btn = QPushButton("New…", clicked=self._new)
        self.copy_btn = QPushButton("Copy…", clicked=self._copy)
        self.copy_btn.setToolTip("A new data pack of your own, starting as a copy of this one (how the app's own are "
                                 "changed).")
        self.edit_btn = QPushButton("Edit…", clicked=self._edit)
        self.edit_btn.setToolTip("Open the data pack's editor: its columns, steps, rules, formulas, modules and module "
                                 "settings. The app's own packs open read-only.")
        self.check_btn = QPushButton("Check…", clicked=lambda: self._edit("Check"))
        self.remove_btn = QPushButton("Remove…", clicked=self._remove)
        self.folder_btn = QPushButton("Open folder", clicked=self._open_folder)
        for b in (self.use_btn, self.new_btn, self.copy_btn, self.edit_btn, self.check_btn, self.remove_btn,
                  self.folder_btn):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def refresh(self, select: Optional[str] = None) -> None:
        keep = select or self.current_id() or (self.main.pack_combo.currentData() if self.main else None)
        self.pack_list.blockSignals(True)
        self.pack_list.clear()
        for pid, pack in packs.available().items():
            builtin = packs.BUILTIN_DIR in pack.folder.parents
            item = QListWidgetItem(pack.label + ("   (app)" if builtin else "   (yours)"))
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setToolTip(pack.manifest.description)
            self.pack_list.addItem(item)
        self.pack_list.blockSignals(False)
        ids = [self.pack_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pack_list.count())]
        self.pack_list.setCurrentRow(ids.index(keep) if keep in ids else 0)
        self._show_pack()
        self._fill_modules()

    def current_id(self) -> Optional[str]:
        item = self.pack_list.currentItem() if hasattr(self, "pack_list") else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def current_pack(self) -> Optional[packs.Pack]:
        return packs.available().get(self.current_id() or "")

    def _show_pack(self) -> None:
        pack = self.current_pack()
        if pack is None:
            self.pack_view.setHtml("")
            return
        try:
            self.pack_view.setHtml(pack_html(pack))
        except Exception as e:                    # a pack that can't load: say so, keep the window usable
            self.pack_view.setHtml(f"<p>This data pack can't be loaded: {escape(str(e))}</p>")
        builtin = packs.BUILTIN_DIR in pack.folder.parents
        self.remove_btn.setEnabled(not builtin)
        self.remove_btn.setToolTip("The app's own data packs can't be removed." if builtin else
                                   "Delete this data pack's folder (asks twice).")

    def _use(self) -> None:
        pid = self.current_id()
        i = self.main.pack_combo.findData(pid)
        if i >= 0:
            self.main.pack_combo.setCurrentIndex(i)

    def _aside(self, open_window) -> None:
        """Run a window that takes over the input (the editor, New / Copy) with this one out of the way, then come
        back (Mickey, 2026-11-09: switching apps brought this window on top of the open editor, unusable)."""
        self.hide()
        try:
            open_window()
        finally:
            self.show()
            self.raise_()
            self.activateWindow()

    def _new(self) -> None:
        before = set(packs.available())
        self._aside(lambda: self.main.new_pack())
        self.refresh(select=next(iter(set(packs.available()) - before), None))

    def _copy(self) -> None:
        before = set(packs.available())
        source = self.current_id()
        self._aside(lambda: self.main.new_pack(source=source))
        self.refresh(select=next(iter(set(packs.available()) - before), None))

    def _edit(self, tab=0) -> None:
        pack = self.current_pack()
        if pack is not None:
            self._aside(lambda: self.main._open_pack_editor(pack.folder, tab))
            self.refresh(select=pack.id)

    def _remove(self) -> None:
        from parameter_extractor.gui.pack_windows import remove_pack
        pack = self.current_pack()
        if pack is not None and remove_pack(self, pack):
            self.main.refresh_packs()
            self.refresh()

    def _open_folder(self) -> None:
        pack = self.current_pack()
        if pack is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pack.folder)))

    # ---- modules -------------------------------------------------------------------------------------------------

    def _modules_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.module_list = QListWidget()
        self.module_list.currentRowChanged.connect(lambda _r: self._show_module())
        split.addWidget(self.module_list)
        self.module_view = QTextBrowser()
        self.module_view.document().setDocumentMargin(18)
        split.addWidget(self.module_view)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([300, 880])
        v.addWidget(split, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Modules are linked into data packs on their Modules tab (Edit…); your own modules go in "
                             "the modules folder.", wordWrap=True), 1)
        row.addWidget(QPushButton("Open my modules folder", clicked=self._open_modules_folder))
        v.addLayout(row)
        return w

    def _fill_modules(self) -> None:
        from parameter_extractor import modules
        modules.clear_cache()
        keep = self.module_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.module_list.currentItem() else None
        self.module_list.blockSignals(True)
        self.module_list.clear()
        for mid, mod in modules.available().items():
            item = QListWidgetItem(mod.label + ("" if mod.builtin else "   (yours)"))
            item.setData(Qt.ItemDataRole.UserRole, mid)
            item.setToolTip(mod.manifest.description)
            self.module_list.addItem(item)
        self.module_list.blockSignals(False)
        ids = [self.module_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.module_list.count())]
        if ids:
            self.module_list.setCurrentRow(ids.index(keep) if keep in ids else 0)
        self._show_module()

    def _show_module(self) -> None:
        from parameter_extractor import modules
        item = self.module_list.currentItem()
        mod = modules.available().get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        if mod is None:
            self.module_view.setHtml("")
            return
        users = [p for p in packs.available().values() if mod.id in p.module_ids()]
        self.module_view.setHtml(module_html(mod, users))

    def _open_modules_folder(self) -> None:
        from parameter_extractor import modules
        folder = modules.user_modules_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
