"""
Shared modules for data packs (modules/, pack_modules.py, 2026-11-09): linked by reference, not copied -- technique
detection in paper surveys, the analysis / solution-chemistry / kinetics / wet-dry / totals modules merged at load,
the prebiotic pack built from them, migrating packs made with copies, drafting linking modules, the editor's Modules
tab, and the app's own packs refused. No API, no network.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pack_facts as pf  # noqa: E402
from parameter_extractor import pack_modules, packs
from parameter_extractor.pack_drafting import PaperSurvey, SurveyVariable


def _survey(method_text: str) -> PaperSurvey:
    return PaperSurvey(field="x", row_unit="r", set_unit="s", notes="", compounds=[], variables=[
        SurveyVariable(name="analysis method", column="analysis_method", unit="", kind="text", role="method",
                       description="how products were measured", level="paper", uncertainty=False, where="text",
                       example=method_text),
        SurveyVariable(name="temperature", column="temperature", unit="°C", kind="number", role="condition",
                       description="heating temperature, measured by thermocouple", level="set", uncertainty=False,
                       where="table", example="80 °C")])


def test_techniques_named():
    named = pack_modules.techniques_named(["GC-MS and direct MS", "UHPLC/MSMS (Shimadzu LCMS-8040)",
                                           "Raman spectroscopy; SEM/EDX", "1H NMR", "reversed-phase HPLC"])
    for t in ("GC-MS", "UHPLC", "Raman", "NMR-1H", "RP-HPLC"):
        assert t in named, (t, named)
    assert "HPLC" not in named and "NMR" not in named         # the specific ones only
    assert pack_modules.techniques_named(["N-body simulation of impact rates", "a model of carbon delivery"]) == []
    papers = [SimpleNamespace(name="a", survey=_survey("HPLC with UV detection")),
              SimpleNamespace(name="b", survey=_survey("not stated")), SimpleNamespace(name="c", survey=None)]
    assert pack_modules.analysis_evidence(papers) == {"a": ["HPLC"]}


def _new_pack(tmp: Path):
    return packs.create_pack("modules_test", "Modules test", "", base=tmp / "packs")


def test_analysis_module():
    """Linked, not copied: the pack lists the module; the step, its vocabulary, hints and category come from it."""
    from parameter_extractor.pack_editing import PackDraft, check
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        draft = PackDraft.load(pack.folder)
        draft.stages[next(iter(draft.stages))]["open_ended"] = True
        draft.save()
        lines = pack_modules.add_modules(pack.folder, ["analysis"])["analysis"]
        assert lines and all(l.startswith("linked") for l in lines), lines
        own = json.loads((pack.folder / "pack.json").read_text())
        assert own["modules"] == ["sample_time", "analysis"] and "analysis" not in own.get("builtin_stages", [])
        assert not (pack.folder / "analysis_vocab.json").exists()                  # nothing copied
        merged = packs.Pack(pack.folder)
        assert "analysis" in merged.manifest.builtin_stages
        assert any(c["id"] == "analysis" for c in merged.manifest.variable_categories)
        assert merged.file("analysis_vocab.json") == pack_modules._source_vocab_path()
        from parameter_extractor.stages.optional import load_specs
        assert all("analysis" in s.hint_by_stage for s in load_specs(merged).values() if s.open_ended)
        d = PackDraft.load(pack.folder)
        assert "analysis" in d.effective_steps()
        assert not [p for p in check(d) if p.level == "error"], check(d)
        assert pack_modules.add_modules(pack.folder, ["analysis"]) == {"analysis": []}    # already linked
        packs.activate("modules_test")
        from parameter_extractor.stages import analysis
        assert "RP-HPLC" in analysis.prompt_text("P", "PLAN")
        packs.activate("prebiotic_chemistry")
        assert pack_modules.remove_module(pack.folder, "analysis")
        assert "analysis" not in packs.Pack(pack.folder).manifest.builtin_stages


def test_solution_chemistry_module():
    from parameter_extractor.pack_editing import PackDraft, check
    from parameter_extractor.stages.optional import load_specs
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        pack_modules.add_module(pack.folder, "solution_chemistry")
        merged = packs.Pack(pack.folder)
        assert "chemistry" in merged.manifest.builtin_stages
        assert all(c in merged.manifest.postprocess for c in ("amounts", "mixing", "water_type"))
        cols = [p.column for s in load_specs(merged).values() for p in s.parameters]
        assert "solvent_volume_mL" in cols and "solvent_name" in cols         # the module's parameters, merged in
        assert not (pack.folder / "prompts" / "chemistry.md").exists()
        assert merged.prompt_path("chemistry").parent.parent.name == "solution_chemistry"
        d = PackDraft.load(pack.folder)
        assert not [p for p in check(d) if p.level == "error"], check(d)
        assert pack_modules.add_module(pack.folder, "solution_chemistry") == ["Solution chemistry: already in the pack"]
        try:
            pack_modules.add_module(packs.BUILTIN_DIR / "exoplanets", "analysis")
            raise AssertionError("an app pack was changed")
        except ValueError:
            pass


def test_prebiotic_uses_the_modules():
    pack = packs.get("prebiotic_chemistry") if hasattr(packs, "get") else packs.Pack(packs.BUILTIN_DIR / "prebiotic_chemistry")
    # its steps and calculations come from the modules it links (whichever those are): none written in the pack
    assert pack.own_manifest.builtin_stages == []
    mods = pack.module_ids()
    assert mods and set(mods) == set(pf.module_ids("prebiotic_chemistry"))
    assert ("chemistry" in pack.manifest.builtin_stages) == ("solution_chemistry" in mods)
    from parameter_extractor.stages.optional import load_specs
    specs = set(load_specs(pack))
    assert "experimental_conditions" in specs                            # the pack's own step
    from parameter_extractor import module_settings as ms
    from parameter_extractor.stages.optional import _specs_in
    own = {p.column for s in _specs_in(pack.folder / "stages").values() for p in s.parameters}
    for mod in pack.modules:                     # every linked module's steps, unless the pack switches one off
        st = ms.settings_for(pack.own_manifest.module_settings, mod.id).steps
        recorded = {f.stem for f in mod.stage_files()      # the pack's own steps record all of it: theirs stand
                    if all(q["column"] in own for q in json.loads(f.read_text())["parameters"])}
        assert {f.stem for f in mod.stage_files() if not (f.stem in st and st[f.stem].off) and f.stem not in recorded} \
            <= specs, mod.id


def test_a_module_step_the_pack_already_records_is_left_out():
    import shutil
    from parameter_extractor.stages.optional import load_specs
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "prebiotic_copy"
        shutil.copytree(packs.BUILTIN_DIR / "prebiotic_chemistry", folder)
        manifest = json.loads((folder / "pack.json").read_text())
        manifest["id"], manifest["modules"] = "prebiotic_copy", ["lab_experiment"] + manifest["modules"]
        (folder / "pack.json").write_text(json.dumps(manifest))
        specs = load_specs(packs.Pack(folder))
        assert "lab_conditions" not in specs and "experimental_conditions" in specs     # the pack's own step stands


def test_a_module_brings_its_compounds():
    """A module's compounds.json (species + their columns) reaches a pack that links it, after the pack's own; the
    prebiotic pack, the modules' source, has them all already."""
    from parameter_extractor import modules
    with tempfile.TemporaryDirectory() as tmp:
        pack = _new_pack(Path(tmp))
        manifest = json.loads((pack.folder / "pack.json").read_text())
        manifest["modules"] = ["peptides_oligomers"]
        (pack.folder / "pack.json").write_text(json.dumps(manifest))
        linked = packs.Pack(pack.folder)
        brought = json.loads((modules.available()["peptides_oligomers"].folder / "compounds.json").read_text())
        assert "Gly-Gly" in linked.species_names and set(brought["species_names"]) <= set(linked.species_names)
        assert "sampled_Gly-Gly_aq_mM" in linked.template_columns
    pre = packs.available()["prebiotic_chemistry"]
    own = json.loads((pre.folder / pre.manifest.template).read_text())
    assert pre.species_names == own["species_names"] and pre.template_columns == own["all_columns"]


def test_the_sample_time_module():
    """Each row's time in the module format (2026-11-25, Mickey): sample_time brings duration_hr (the row plan's time),
    its label and fill settings and the is_last_sample formula; a pack can describe the time its own way (one
    row-planning rule) or switch it off (no column); the prebiotic pack's settings and prompts are as before."""
    from parameter_extractor import modules
    pre = packs.available()["prebiotic_chemistry"]
    assert "sample_time" in pre.module_ids() and pre.row_value_column("duration_hr") == "duration_hr"
    assert {f["column"] for f in pre.manifest.formulas} >= {"is_last_sample", "total_sampled_peptides_mM",
                                                           "is_max_peptide_yield"}
    assert "in this data pack:" not in pre.prompt_rules("structure_planner")          # no description of its own
    with tempfile.TemporaryDirectory() as tmp:
        pack = _new_pack(Path(tmp))
        manifest = json.loads((pack.folder / "pack.json").read_text())
        manifest["modules"] = []                                                    # a new pack links it: unlinked
        (pack.folder / "pack.json").write_text(json.dumps(manifest))
        assert packs.Pack(pack.folder).row_value_column("duration_hr") is None        # no module, not in its columns
        manifest["modules"] = ["sample_time"]
        (pack.folder / "pack.json").write_text(json.dumps(manifest))
        linked = packs.Pack(pack.folder)
        assert "duration_hr" in linked.template_columns and linked.manifest.label_columns["time"] == "duration_hr"
        assert any(f["column"] == "is_last_sample" for f in linked.manifest.formulas)
        manifest["module_settings"] = {"sample_time": {"parameters": {"duration_hr": {
            "description": "time since the first wet-dry cycle began"}}}}
        (pack.folder / "pack.json").write_text(json.dumps(manifest))
        described = packs.Pack(pack.folder)
        assert "time since the first wet-dry cycle began" in described.prompt_rules("structure_planner")
        manifest["module_settings"] = {"sample_time": {"parameters": {"duration_hr": {"off": True}}}}
        (pack.folder / "pack.json").write_text(json.dumps(manifest))
        off = packs.Pack(pack.folder)
        assert "duration_hr" not in off.template_columns and off.row_value_column("duration_hr") is None
    assert modules.available()["sample_time"].manifest.fixed            # the name and unit the app reads stay


def test_the_core_modules():
    """Rows and Paper details (2026-11-25, Mickey: no app-only parts): part of every pack, never in its module list,
    never among the modules to link; they hold the row plan and the paper's details and the columns every pack gets
    (the same columns, in the same order, as packs/common_columns.json had)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor import modules, pack_overview
    core = modules.core()
    assert list(core) == ["rows", "paper_details"] and not set(core) & set(modules.available())
    assert modules.unknown(["rows", "paper_details"]) == [] and modules.resolve(["rows"]) == []   # listed: harmless
    assert [c["column"] for c in packs.common_columns()] == ["paper_title", "paper_DOI", "author_list",
                                                            "year_published", "journal_published", "data_location",
                                                            "paper_arxiv_id", "result_type"]
    pre = packs.available()["prebiotic_chemistry"]
    assert [m.id for m in pre.core_modules] == ["rows", "paper_details"] and "rows" not in pre.module_ids()
    flow = {s.name: s.source for s in pack_overview.paper_flow(packs.available()["exoplanets"])}
    assert flow["metadata"] == pack_overview.CORE_DETAILS
    assert flow["set_variables"] == "the Rows module (core)"              # its calculation (2026-11-25)
    assert core["rows"].manifest.postprocess == ["set_variables"]
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        e = PackEditor(pack.folder)
        t = e.module_table
        first = [t.item(r, 0) for r in range(t.rowCount()) if e._module_row_id(r)][:2]     # after the group heading
        assert [i.data(Qt.ItemDataRole.UserRole) for i in first] == ["rows", "paper_details"]
        assert all(i.checkState() == Qt.CheckState.Checked and not i.flags() & Qt.ItemFlag.ItemIsUserCheckable
                   for i in first)
        e._show_module(t.row(first[0]))
        from PySide6.QtWidgets import QLabel
        page_text = " ".join(lbl.text() for lbl in e.module_scroll.widget().findChildren(QLabel))
        assert "full_id" in page_text and "can't be unlinked" in page_text and "set_variables" in page_text
        assert e.save()
        own = json.loads((pack.folder / "pack.json").read_text())
        assert "rows" not in own["modules"] and "paper_details" not in own["modules"]


def test_migrate_copies():
    """A pack made when modules were copied: identical copies become links, the pack's own changes stay."""
    from parameter_extractor.pack_editing import PackDraft
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        m = json.loads((pack.folder / "pack.json").read_text())
        m["builtin_stages"] = ["analysis", "chemistry"]
        m["postprocess"] = ["normalize_species", "mixing", "molar_ratios", "amounts", "water_type", "my_own"]
        (pack.folder / "pack.json").write_text(json.dumps(m))
        (pack.folder / "analysis_vocab.json").write_bytes(pack_modules._source_vocab_path().read_bytes())
        (pack.folder / "prompts").mkdir(exist_ok=True)
        (pack.folder / "prompts" / "chemistry.md").write_text("my own changed prompt")
        lines = pack_modules.migrate_copies(pack.folder)
        own = json.loads((pack.folder / "pack.json").read_text())
        assert set(own["modules"]) >= {"analysis", "solution_chemistry"}, lines
        assert own["builtin_stages"] == [] and own["postprocess"] == ["my_own"]
        assert not (pack.folder / "analysis_vocab.json").exists()
        assert (pack.folder / "prompts" / "chemistry.md").read_text() == "my own changed prompt"   # differs: kept
        assert packs.Pack(pack.folder).prompt_path("chemistry") == pack.folder / "prompts" / "chemistry.md"
        assert pack_modules.migrate_copies(pack.folder) == []                 # nothing left to migrate
        assert PackDraft.load(pack.folder).effective_steps()


def test_drafting_adds_the_analysis_module():
    from test_pack_drafting import EDER, KIM, PROPOSAL
    if not (EDER.is_file() and KIM.is_file()):
        print(f"SKIP: needs {EDER} and {KIM}")
        return
    from parameter_extractor import api_client, pack_drafting
    from parameter_extractor.config.run_config import RunConfig

    def call(ctx, *, stage, response_model, **kw):
        return _survey("RP-HPLC (C18, UV 210 nm)") if stage == "pack_survey" else PROPOSAL
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"), \
            patch.object(api_client, "call_structured", call):
        cfg = RunConfig(api_key="test", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
        r = pack_drafting.draft_pack([EDER, KIM], "with_modules", "With modules", "", cfg)
        manifest = json.loads((r.pack.folder / "pack.json").read_text())
        assert "analysis" in manifest["modules"] and not (r.pack.folder / "analysis_vocab.json").exists()
        assert r.module_evidence["analysis"] == {"eder1994": ["RP-HPLC"], "kim2019": ["RP-HPLC"]}
        assert "## Shared modules linked" in (r.pack.folder / "drafted_from.md").read_text()
        r2 = pack_drafting.draft_pack([EDER], "without_modules", "Without", "", cfg, modules_on=False)
        assert "analysis" not in json.loads((r2.pack.folder / "pack.json").read_text()).get("modules", [])


def test_kinetics_wet_dry_and_totals_modules():
    from parameter_extractor.pack_editing import PackDraft, check
    from parameter_extractor.stages.optional import load_specs
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        done = pack_modules.add_modules(pack.folder, ["kinetics", "wet_dry", "peptides_oligomers"])
        assert set(done) >= {"kinetics", "wet_dry", "peptides_oligomers"}
        merged = packs.Pack(pack.folder)
        assert "solution_chemistry" in merged.module_ids()                       # totals bring it along
        assert {"kinetics", "wet_dry"} <= {c["id"] for c in merged.manifest.variable_categories}
        assert "Cycle 1 = 24" in merged.prompt_rules("structure_planner")
        assert {"peptide_totals", "oligomer_totals", "amounts"} <= set(merged.manifest.postprocess)
        assert "chemistry" in merged.manifest.builtin_stages
        assert {"total_sampled_peptides_yield", "max_oligomer_length_nt"} <= {e["column"] for e in merged.standard_column_entries}
        assert {"kinetics", "wet_dry"} <= set(load_specs(merged))
        d = PackDraft.load(pack.folder)
        assert {"rate_constant_first_order_per_hr", "cycle_number"} <= set(d.all_columns())
        assert not [p for p in check(d) if p.level == "error"], [str(p) for p in check(d)]
        assert not list((pack.folder / "stages").glob("kinetics*.json"))           # not copied
        assert pack_modules.add_modules(pack.folder, ["kinetics", "wet_dry", "peptides_oligomers"]) == \
            {"kinetics": [], "wet_dry": [], "peptides_oligomers": []}                # nothing twice


def test_evidence_for_modules():
    def survey(words, compounds=()):
        from parameter_extractor.pack_drafting import SurveyCompound
        return PaperSurvey(field="x", row_unit="r", set_unit="s", notes=words, variables=[], compounds=[
            SurveyCompound(name=c, full_name="", role="product", example="") for c in compounds])
    papers = [SimpleNamespace(name="a", survey=survey("first-order rate constants and half-lives were fitted")),
              SimpleNamespace(name="b", survey=survey("ten wet-dry cycles at 80 °C")),
              SimpleNamespace(name="c", survey=survey("", compounds=["Gly-Gly", "(pA)4"])),
              SimpleNamespace(name="d", survey=survey("N-body simulation of impacts"))]
    ev = pack_modules.evidence_for(papers)
    assert set(ev["kinetics"]) == {"a"} and set(ev["wet_dry"]) == {"b"} and "c" in ev["peptides_oligomers"]
    assert all("d" not in found for found in ev.values())


def test_pages_and_module_groups():
    """The editor's pages in grouped sidebar entries (the tab bar hidden; names still work), and the module list in
    two groups -- in this data pack, then not linked -- that a module moves between when ticked (2026-11-25)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        e = PackEditor(_new_pack(Path(tmp)).folder)
        nav = e.tabs.nav
        rows = [nav.item(r) for r in range(nav.count())]
        headings = [i.text() for i in rows if i.data(e.tabs.PAGE) is None]
        assert headings == ["SEE THE PACK", "SET UP", "WHAT'S EXTRACTED", "REVIEW"]
        assert e.tabs.tabBar().isHidden() and e.tabs.count() == sum(i.data(e.tabs.PAGE) is not None for i in rows)
        modules_item = next(i for i in rows if i.text().strip() == "Modules")
        nav.setCurrentItem(modules_item)                                 # the sidebar picks the page ...
        assert e.tabs.tabText(e.tabs.currentIndex()) == "Modules" and e.tabs.title.text() == "Modules"
        e.tabs.setCurrentIndex(e.tab_index("Columns"))                    # ... and follows code that does
        assert nav.currentItem().text().strip() == "Columns" and "by category" in e.tabs.about.text()
        assert e.tabs.tabText(e.tabs.count() - 1).startswith("Check")

        t = e.module_table
        order = lambda: [e._module_row_id(r) or t.item(r, 0).text() for r in range(t.rowCount())]   # noqa: E731
        groups = lambda: (order()[:order().index("NOT LINKED")], order()[order().index("NOT LINKED") + 1:])  # noqa
        linked, unlinked = groups()
        assert linked[:3] == ["IN THIS DATA PACK", "rows", "paper_details"] and "kinetics" in unlinked
        row = next(r for r in range(t.rowCount()) if e._module_row_id(r) == "kinetics")
        t.item(row, 0).setCheckState(Qt.CheckState.Checked)
        linked, unlinked = groups()
        assert "kinetics" in linked and "kinetics" not in unlinked
        row = next(r for r in range(t.rowCount()) if e._module_row_id(r) == "kinetics")
        t.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        assert "kinetics" in groups()[1]
        assert e._chosen_modules() == ["sample_time"]                     # headings are never modules

        # the Map: one heading row with its controls, the sidebar hidden for more room and back on leaving it
        e.tabs.setCurrentIndex(e.tab_index("Map"))
        assert e.map_bar.isVisibleTo(e) or not e.isVisible()
        assert e.tabs.title.toolTip() and not e.tabs.about.isVisibleTo(e.tabs.about.parentWidget())
        e.sidebar_btn.setChecked(True)
        assert e.tabs.nav.isHidden()
        e.tabs.setCurrentIndex(e.tab_index("Columns"))
        assert not e.tabs.nav.isHidden() and not e.sidebar_btn.isChecked()
        # it fits a laptop screen (2026-11-26: it opened past the edge): no page forces the window's size, and a window
        # asked to be larger than the screen is fitted to it and centred
        hint = e.minimumSizeHint()
        assert hint.width() < 1100 and hint.height() < 700, hint
        from PySide6.QtWidgets import QWidget
        from parameter_extractor.gui.widgets import fit_to_screen
        big = QWidget()
        fit_to_screen(big, 10000, 10000)
        area = big.screen().availableGeometry()
        assert big.width() <= area.width() and big.height() <= area.height() and area.contains(big.geometry().center())


def test_modules_tab():
    """The editor's Modules tab: tick to link, what a module brings along, steps shown as the module's, saved as a
    reference; the app's own packs read-only."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    e = PackEditor(packs.BUILTIN_DIR / "prebiotic_chemistry")
    assert "Analysis methods" not in [e.tabs.tabText(i) for i in range(e.tabs.count())]
    assert not e.builtin_boxes["chemistry"].isEnabled() and "Solution chemistry module" in e.builtin_boxes["chemistry"].text()
    core_row = next(r for r in range(e.module_table.rowCount()) if e._module_row_id(r))
    assert not e.module_table.item(core_row, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        e = PackEditor(pack.folder)
        t = e.module_table
        row = lambda mid: next(r for r in range(t.rowCount()) if e._module_row_id(r) == mid)   # noqa: E731 (rows move)
        compounds = e.tab_index("Compounds")
        assert not e.tabs.isTabEnabled(compounds)
        t.item(row("peptides_oligomers"), 0).setCheckState(Qt.CheckState.Checked)
        assert t.item(row("solution_chemistry"), 1).text().startswith("brought along by")
        assert e.tabs.isTabEnabled(compounds) and e.builtin_boxes["chemistry"].isChecked()
        assert "Peptides and oligomers module" in e.module_stages_note.text()   # its linkage step (2026-11-09)
        t.item(row("kinetics"), 0).setCheckState(Qt.CheckState.Checked)
        assert "Kinetics module" in e.module_stages_note.text()
        t.item(row("kinetics"), 0).setCheckState(Qt.CheckState.Unchecked)
        t.setCurrentCell(row("analysis"), 0)
        assert e.analysis_stack.currentIndex() == 0                          # not linked: no vocabulary
        assert e.vocab_box.parent() is not None                              # shown on the module's page
        t.item(row("analysis"), 0).setCheckState(Qt.CheckState.Checked)
        assert e.analysis_stack.currentIndex() == 1 and e.tech_table.rowCount() > 20
        assert not e._vocab_editable()                                        # the module's: read-only here
        assert e.save()
        own = json.loads((pack.folder / "pack.json").read_text())
        assert own["modules"] == ["analysis", "peptides_oligomers", "sample_time"]      # sample_time: a new pack's
        assert own.get("builtin_stages", []) == [] and own.get("postprocess", []) == []



def test_peptides_and_oligomers_module():
    """2026-11-09: 'Peptide and oligomer totals' became 'Peptides and oligomers' (the old id still works): the chemistry
    step's naming rules for peptides / oligomers come from it, and compound setup fills in every length of a series."""
    import json as _json
    from parameter_extractor import compound_setup, modules, names
    from parameter_extractor.stages.prompt_loader import load_prompt
    assert [m.id for m in modules.resolve(["product_totals"])] == ["solution_chemistry", "peptides_oligomers"]
    assert modules.unknown(["product_totals"]) == []
    mod = modules.available()["peptides_oligomers"]
    assert mod.manifest.compound_series and mod.manifest.prompt_rules["chemistry"]
    assert names.homopolymer("Gly13") == ("peptide", "Gly", 13) and names.homopolymer("Gly-Ala") is None
    assert names.homopolymer("10mer_A") == ("nucleotide", "A", 10) and names.homopolymer_name("peptide", "Gly", 5) == "(Gly)5"
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        pack_modules.add_modules(pack.folder, ["solution_chemistry"])
        try:
            packs.activate("modules_test")
            assert "Peptides: name a peptide" not in load_prompt("chemistry", PAPER_TEXT="", STRUCTURE_PLAN_JSON="")
            pack_modules.add_modules(pack.folder, ["peptides_oligomers"])
            packs.activate("modules_test")
            text = load_prompt("chemistry", PAPER_TEXT="", STRUCTURE_PLAN_JSON="")
            assert "Peptides: name a peptide" in text and "{{MODULE_RULES}}" not in text
            rule = mod.manifest.prompt_rules["chemistry"][1]                    # switched off for this pack
            m = _json.loads((pack.folder / "pack.json").read_text())
            m["module_settings"] = {"peptides_oligomers": {"prompt_rules_off": [rule]}}
            (pack.folder / "pack.json").write_text(_json.dumps(m))
            packs.activate("prebiotic_chemistry")                               # (written behind the pack's back)
            packs.activate("modules_test")
            assert rule not in load_prompt("chemistry", PAPER_TEXT="", STRUCTURE_PLAN_JSON="")
        finally:
            packs.activate("prebiotic_chemistry")
        # the series: Gly2, Gly3 and Gly13 surveyed -> (Gly)4 ... (Gly)12 too, as products in % yield
        surveys = [{"paper": "p", "item": "p", "error": "", "survey": {"field": "x", "row_unit": "r", "set_unit": "s",
                    "notes": "", "variables": [], "compounds": [
                        {"name": "Gly2", "full_name": "glycylglycine", "role": "product", "example": "13.96 %"},
                        {"name": "Gly3", "full_name": "triglycine", "role": "product", "example": "10.4 %"},
                        {"name": "Gly13", "full_name": "", "role": "product", "example": "0.11 %"},
                        {"name": "GG", "full_name": "diglycine", "role": "starting", "example": "3.7 mM"}]}}]
        (pack.folder / "drafted_surveys.json").write_text(_json.dumps(surveys))
        from parameter_extractor.pack_editing import PackDraft
        plan = compound_setup.find_compounds(PackDraft.load(pack.folder), None)
        by = {c.name: c for c in plan.compounds}
        assert all(f"(Gly){n}" in by for n in range(4, 13)), sorted(by)
        assert by["(Gly)7"].roles == {"sampled"} and by["(Gly)7"].measures == {"%yield"}    # what all members share
        assert "Filled in 9 length(s)" in plan.note

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
