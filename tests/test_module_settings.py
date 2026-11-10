"""
Module settings (module_settings.py, 2026-11-09): a data pack's own changes to the modules it links -- steps,
values, calculations, rules and instrument families on/off, a value stored in another unit (its column renamed),
trigger words, table images, extra rules -- applied when the pack loads, while the module stays shared; the check's
findings; the paper flow (pack_overview.py); one paper run end to end with a renamed column. No API calls.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import csv
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
from parameter_extractor import analysis_vocab, api_client, module_settings as ms, pack_modules, packs
from parameter_extractor.stages.optional import load_specs


def _pack(tmp: Path, modules, settings=None, pack_id="settings_test"):
    pack = packs.create_pack(pack_id, "Settings test", base=tmp)
    pack_modules.add_modules(pack.folder, modules)
    if settings is not None:
        m = json.loads((pack.folder / "pack.json").read_text())
        m["module_settings"] = settings
        (pack.folder / "pack.json").write_text(json.dumps(m))
    return packs.Pack(pack.folder)


def test_unit_choices():
    choices = dict(ms.unit_choices("half_life_hr", "h"))
    assert choices["h"] == "half_life_hr" and choices["min"] == "half_life_min"
    assert dict(ms.unit_choices("initial_pressure_bar", "bar"))["GPa"] == "initial_pressure_GPa"
    assert dict(ms.unit_choices("wet_phase_temperature_C", "°C"))["K"] == "wet_phase_temperature_K"
    assert ms.unit_choices("kinetic_model", "") == []
    assert ms.base_name("activation_energy_kJ_mol") == "activation_energy"


def test_settings_change_the_pack_not_the_module():
    rule = pack_modules.module_store.available()["wet_dry"].manifest.row_rules[1]
    settings = {
        "kinetics": {"steps": {"kinetics": {"keywords": ["half-life"], "table_images": False,
                                            "extra_rules": ["Report half_life_hr for hydrolysis only."]}},
                     "parameters": {"half_life_hr": {"unit": "min"}, "kinetic_model": {"off": True},
                                    "activation_energy_kJ_mol": {"description": "Ea of the hydrolysis"}}},
        "peptides_oligomers": {"calculations_off": ["oligomer_totals"]},
        "solution_chemistry": {"stage_rules_off": [pack_modules.CHEMISTRY_RULE],
                               "parameters": {"solvent_volume_mL": {"unit": "uL"}}},
        "analysis": {"families_off": ["nmr", "maldi"]},
        "wet_dry": {"row_rules_off": [rule], "steps": {"wet_dry": {"off": True}}}}
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = _pack(Path(tmp), ["kinetics", "peptides_oligomers", "analysis", "wet_dry"], settings)
        specs = load_specs(pack)
        kin = specs["kinetics"]
        cols = {p.column: p for p in kin.parameters}
        assert "half_life_min" in cols and cols["half_life_min"].unit == "min" and "half_life_hr" not in cols
        assert "kinetic_model" not in cols and cols["activation_energy_kJ_mol"].description == "Ea of the hydrolysis"
        assert kin.trigger.keywords == ["half-life"] and kin.table_images is False
        assert kin.rules[-1] == "Report half_life_min for hydrolysis only."            # renamed in the text too
        assert "wet_dry" not in specs                                                     # switched off
        assert "oligomer_totals" not in pack.manifest.postprocess and "peptide_totals" in pack.manifest.postprocess
        assert rule not in pack.prompt_rules("structure_planner")
        own = next(s for s in specs.values() if s.name not in ("kinetics",))
        assert pack_modules.CHEMISTRY_RULE not in own.rules
        # a fixed column keeps its unit (the amounts calculation reads it in mL)
        assert "solvent_volume_mL" in {p.column for p in own.parameters}
        vocab = analysis_vocab.vocabulary(pack)
        assert "nmr" not in vocab.families and "liquid_chromatography" in vocab.families
        # the module itself (and another pack linking it) is unchanged
        other = _pack(Path(tmp), ["kinetics", "analysis"], pack_id="plain_test")   # the same modules, no settings
        assert "half_life_hr" in {p.column for p in load_specs(other)["kinetics"].parameters}
        assert "nmr" in analysis_vocab.vocabulary(other).families
        # the check: the fixed unit is reported, nothing is an error
        from parameter_extractor.pack_editing import PackDraft, check
        d = PackDraft.load(pack.folder)
        found = [p for p in check(d) if p.where == "Module settings"]
        assert any("keeps its unit" in p.message for p in found), found
        assert not [p for p in found if p.level == "error"]
        assert "half_life_min" in d.module_columns() and "kinetic_model" not in d.module_columns()
        assert "oligomer_totals" not in d.effective_calculations()


def test_check_reports_bad_settings():
    from parameter_extractor.pack_editing import PackDraft, check
    bad = {"kinetics": {"parameters": {"half_life_hr": {"unit": "kg"}, "nope": {"off": True}},
                        "steps": {"kinetics": {"keywords": []}, "other": {"off": True}}},
           "exoplanet_fits": {"calculations_off": ["x"]}}
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = _pack(Path(tmp), ["kinetics"], bad)
        messages = {p.level + ": " + p.message for p in check(PackDraft.load(pack.folder))
                    if p.where == "Module settings"}
        assert any(m.startswith("error:") and "can't be stored in kg" in m for m in messages), messages
        assert any("no parameter 'nope'" in m for m in messages)
        assert any("never runs" in m for m in messages)
        assert any("no step 'other'" in m for m in messages)
        assert any("doesn't link" in m for m in messages)


def test_cleaned_keeps_only_changes():
    s = ms.ModuleSettings(steps={"k": ms.StepSetting(), "w": ms.StepSetting(keywords=[])},
                          parameters={"a": ms.ParameterSetting(), "b": ms.ParameterSetting(unit="min")})
    assert ms.cleaned(s) == {"steps": {"w": {"keywords": []}}, "parameters": {"b": {"unit": "min"}}}
    assert ms.is_default(ms.ModuleSettings())


def test_paper_flow():
    from parameter_extractor import pack_overview as po
    flow = po.paper_flow(packs.available()["prebiotic_chemistry"])
    requests = {s.name: s for s in flow if s.kind == "request"}
    mods = pf.module_ids("prebiotic_chemistry")
    # one request per step the pack and its linked modules have (taken from the pack: links can change)
    expected = {"structure_planner", "metadata", "experimental_conditions"} | set(pf.module_step_names("prebiotic_chemistry"))
    expected |= {s for s, m in (("chemistry", "solution_chemistry"), ("analysis", "analysis")) if m in mods}
    assert expected <= set(requests)
    assert requests["experimental_conditions"].source == po.PACK and requests["experimental_conditions"].always
    if "kinetics" in mods:
        assert requests["kinetics"].source == "the Kinetics module" and not requests["kinetics"].always
    local = {s.name: s.source for s in flow if s.kind == "local"}
    assert local["results_check"] == po.PACK
    if "solution_chemistry" in mods:
        assert requests["chemistry"].source == "the Solution chemistry module"
        assert local["amounts"] == "the Solution chemistry module"
    always = sum(1 for r in requests.values() if r.always)
    assert po.summary(flow).startswith(f"{always} model requests for every paper, up to {len(requests) - always} more")
    assert "Requests to the AI model" in po.as_html(flow)


def test_a_paper_runs_with_module_settings():
    """kinetics triggered by the pack's own trigger word, half-lives stored in minutes (converted from hours)."""
    from test_pipeline_offline import PDF, REPLAY_DIR
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}")
        return
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import run_pipeline
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    settings = {"kinetics": {"steps": {"kinetics": {"keywords": ["glycine"]}},
                             "parameters": {"half_life_hr": {"unit": "min"}}}}
    meta = PaperMetadata.model_validate_json((REPLAY_DIR / "metadata.output.json").read_text())
    seen = {}
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        _pack(Path(tmp), ["kinetics"], settings)

        def send(ctx, *, model, system_prompt, content, response_model, **kw):
            name = response_model.__name__
            system = system_prompt if isinstance(system_prompt, str) else system_prompt[0]["text"]
            seen[name] = system + (content if isinstance(content, str) else content[-1]["text"])
            if name == "StructurePlan":
                out = response_model.model_validate({"kind": "experimental", "n_rows": 1, "sets": [
                    {"set": "Run A", "type": "Independent", "varies": "", "src": "Table 1",
                     "samples": [{"label": "A", "hr": 1, "src": "Table 1"}]}]})
            elif name == "PaperMetadata":
                out = meta
            elif name == "KineticsResults":
                out = response_model.model_validate({"parameters": [dict(
                    set_label="Run A", sample_label="A", parameter="half_life_min", value=2.0, unit="h",
                    quote="q", source="Table 1", confidence="high")]})
            else:
                out = response_model.model_validate({"parameters": []})
            return SimpleNamespace(id="fake", stop_reason="end_turn", parsed_output=out,
                                   content=[SimpleNamespace(type="text", text=out.model_dump_json())],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        try:
            with patch.object(api_client, "_send", send):
                result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp) / "out",
                                                                   pack="settings_test", registry_path=None))
            assert "KineticsResults" in seen and "half_life_min" in seen["KineticsResults"]
            with open(result.csv_path) as f:
                rows = list(csv.DictReader(f))
            assert rows[0]["half_life_min"] == "120.0" and "half_life_hr" not in rows[0]
        finally:
            packs.activate("prebiotic_chemistry")


def test_modules_tab_settings():
    """One Modules tab (2026-11-09): tick to link; a linked module's page holds this pack's settings for it."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = _pack(Path(tmp), ["kinetics"])
        e = PackEditor(pack.folder)
        names = [e.tabs.tabText(i) for i in range(e.tabs.count())]
        assert names[0] == "Overview" and "Modules" in names and "Module settings" not in names and names[-1] == "Check"
        assert "Kinetics" in e.overview.toPlainText()
        t = e.module_table
        rows = {t.item(r, 0).data(Qt.ItemDataRole.UserRole): r for r in range(t.rowCount())}
        t.setCurrentCell(rows["wet_dry"], 0)                       # not linked: no settings yet
        assert e.module_settings_tab._shown != "wet_dry"
        t.setCurrentCell(rows["kinetics"], 0)
        table = e.module_settings_tab.values_table
        for r in range(table.rowCount()):
            if table.item(r, 1).text() == "half_life_hr":
                combo = table.cellWidget(r, 2).findChild(QComboBox)
                combo.setCurrentIndex(combo.findData("min"))
                assert table.item(r, 1).text() == "half_life_min"
            if table.item(r, 1).text() == "kinetic_model":
                table.cellWidget(r, 0).findChild(QCheckBox).setChecked(False)
        assert t.item(rows["kinetics"], 1).text() == "linked • changed"
        t.setCurrentCell(rows["analysis"], 0)                      # moving away keeps the edits
        t.setCurrentCell(rows["kinetics"], 0)
        assert e.save()
        saved = json.loads((pack.folder / "pack.json").read_text())["module_settings"]
        assert saved == {"kinetics": {"parameters": {"half_life_hr": {"unit": "min"}, "kinetic_model": {"off": True}}}}
        assert "half_life_min" in {p.column for p in load_specs(packs.Pack(pack.folder))["kinetics"].parameters}
        e._reset_module("kinetics")
        assert t.item(rows["kinetics"], 1).text() == "linked"
        assert e.save() and "module_settings" not in json.loads((pack.folder / "pack.json").read_text())
        # settings of a module the pack no longer links aren't kept
        e2 = PackEditor(pack.folder)
        e2.module_settings_tab.settings["kinetics"] = ms.ModuleSettings(calculations_off=["x"])
        rows = {e2.module_table.item(r, 0).data(Qt.ItemDataRole.UserRole): r for r in range(e2.module_table.rowCount())}
        e2.module_table.item(rows["kinetics"], 0).setCheckState(Qt.CheckState.Unchecked)
        assert e2.save() and "module_settings" not in json.loads((pack.folder / "pack.json").read_text())


def test_data_packs_window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    from parameter_extractor import local_models
    from parameter_extractor.gui import main_window
    from parameter_extractor.gui.packs_window import DataPacksWindow
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)), \
            patch.object(local_models, "default_path", lambda: Path(tmp) / "local.json"):
        w = main_window.MainWindow()
        win = DataPacksWindow(w)
        labels = [win.pack_list.item(i).text() for i in range(win.pack_list.count())]
        assert any(l.startswith("Prebiotic chemistry") for l in labels)
        row = next(i for i, l in enumerate(labels) if l.startswith("Exoplanets"))
        win.pack_list.setCurrentRow(row)
        text = win.pack_view.toPlainText()
        assert "What happens to each paper" in text and "model requests for every paper" in text
        assert not win.remove_btn.isEnabled()                                    # the app's own
        win._use()
        assert w.pack_combo.currentData() == "exoplanets"
        win.tabs.setCurrentIndex(1)
        mods = [win.module_list.item(i).text() for i in range(win.module_list.count())]
        linked = pack_modules.module_store.available()[pf.module_ids("prebiotic_chemistry")[0]].label
        assert linked in mods                                   # a module Prebiotic links (whichever comes first)
        win.module_list.setCurrentRow(mods.index(linked))
        assert "Prebiotic chemistry" in win.module_view.toPlainText()             # linked by
        w.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
