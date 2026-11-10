"""
Fixes from the 'Organics in target' test set (2026-11-09: five impact / shock / delivery papers, a drafted data pack vs the
prebiotic pack, in developer handoff mode): units the app didn't know or misread, compound values that were dropped or
put in the wrong column, temperature differences, limits without a limit column, citations read as table captions, the
table-grid rule sent when grids are off, PubChem and Greek letters, and drafting a data pack in handoff mode.
No API, no network.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from parameter_extractor import packs

PAPERS = ROOT.parent / "Paper Files" / "Paper Lists"
EDER = PAPERS / "Initial Easy Papers" / "Eder1994" / "eder1994.pdf"
KIM = PAPERS / "Kim2019" / "kim2019.pdf"


def test_units():
    from parameter_extractor.units import (convert_printed, parse_quantity, parse_range, to_column_unit, unit_slug)
    # the same unit spelled three ways (16 of mckay1997's values were left out as 'can't be converted')
    assert unit_slug("molecules per joule") == unit_slug("molecules J-1") == unit_slug("molecules/J") == "molecules_per_J"
    assert convert_printed(5e17, "molecules per joule", "molecules/J") == (5e17, "")
    assert unit_slug("g cm-3") == "g_per_cm3"
    # new units: GPa, velocities, joules, densities
    assert parse_quantity("7 GPa") == (7.0, "GPa") and to_column_unit(7, "GPa", "bar").value == 70000
    assert parse_quantity("0.9 km/s") == (0.9, "km/s") and parse_quantity("1 km/sec") == (1.0, "km/s")
    assert parse_quantity("0.2 J") == (0.2, "J")
    assert convert_printed(1.75, "g cm-3", "g/cm**3") == (1.75, "")
    # approximate values are the stated values; wt% is a %
    assert parse_quantity("~0.9 km/s") == (0.9, "km/s") and parse_quantity("about 100 ns") == (100.0, "ns")
    assert parse_quantity("2 × 10−5 wt%") == (2e-05, "%")
    # thousands separators ('1,000 rpm' was 1 rpm, '12,000 K' 12 K); a decimal comma stays one
    assert parse_quantity("1,000 r.p.m.") == (1000.0, "rpm") and parse_quantity("12,000 K") == (12000.0, "K")
    assert parse_quantity("2,5 mM") == (2.5, "mM") and parse_range("1,000-2,000 rpm") == (1000.0, 2000.0, "rpm")
    from parameter_extractor.value_types import coerce, whole_number
    assert coerce("1,000", "number") == (1000.0, "") and coerce("2,5", "number") == (2.5, "")
    assert whole_number("1,000 runs") == 1000


def test_temperature_differences_have_no_offset():
    from parameter_extractor.units import convert_printed, is_difference, to_column_unit
    assert is_difference("temperature_increase_C") and is_difference("temperature rise") and is_difference("ΔT")
    assert not is_difference("initial_temperature_C") and not is_difference("post-shock_temperature_C")
    assert to_column_unit(5600, "K", "°C", difference=True).value == 5600       # burchell2020: a rise of 5600 K
    assert to_column_unit(5600, "K", "°C").value == 5326.85
    assert convert_printed(5600, "K", "°C", is_error=True)[0] == 5600


def test_column_units_from_names():
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import canonical_unit
    from parameter_extractor.variable_categories import unit_suffix
    assert [unit_for_column(c) for c in ("peak_shock_pressure_GPa", "impact_velocity_km_per_s", "shock_duration_us",
                                         "energy_input_J", "product_amount_nmol", "density_g_per_cm3")] == \
        ["GPa", "km/s", "µs", "J", "nmol", "g/cm3"]
    assert unit_for_column("pl_orbper") == "" and unit_for_column("x_status") == ""     # no unit made up
    assert unit_for_column("production_efficiency_molecules_per_J") == ""               # a rate per joule, not J
    # a suggestion's column is named after its unit, so it reads back in it (numbers stay numbers)
    assert [unit_suffix(canonical_unit(u)) for u in ("km/s", "µs", "kV", "J", "GPa", "h")] == \
        ["_km_per_s", "_us", "_kV", "_J", "_bar", "_hr"]
    from parameter_extractor.pack_drafting import column_for
    assert column_for("shock_duration", "µs") == ("shock_duration_us", "µs")      # was _hr: 0.7 µs = 1.9e-10 h
    assert column_for("product_amount", "nmol") == ("product_amount_nmol", "nmol")


def test_compound_values_in_other_units_are_kept():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import (_solute_value, column_for_solute,
                                                                   proposed_column_for_solute, species_alias_name)
    from parameter_extractor.schemas.chemistry import SoluteEntry
    e = lambda **kw: SoluteEntry(**{"name": "HCN", "role": "sampled", "phase": "gas", "quote": "q", "source": "s",
                                    "confidence": "high", **kw})
    # mckay1997's Table 2 in molecules per joule: was dropped without a trace
    per_j = e(concentration_value=5e17, concentration_unit_raw="molecules per joule")
    assert proposed_column_for_solute(per_j) == "sampled_HCN_gas_molecules_per_J" and _solute_value(per_j) == 5e17
    assert species_alias_name(per_j) == "sampled HCN (molecules per joule)"
    # a starting gas composition in %: was proposed as initial_H2O_gas_mM = 42
    pct = e(name="H2O", role="initial", concentration_value=42, concentration_unit_raw="%")
    assert proposed_column_for_solute(pct) == "initial_H2O_gas_pct" and species_alias_name(pct) == "initial H2O %"
    # a concentration unit is still converted to mM (normalize_chemistry), not kept as printed
    mm = e(name="Gly", role="sampled", phase="aq", concentration_value=1.2, concentration_unit_raw="mM")
    assert proposed_column_for_solute(mm) == "sampled_Gly_aq_mM" and column_for_solute(mm) == "sampled_Gly_aq_mM"
    # an amount without a reaction volume keeps its unit
    amount = e(name="FeCl2", role="initial", phase="aq", concentration_value=0.4, concentration_unit_raw="mmol")
    assert proposed_column_for_solute(amount) == "initial_FeCl2_aq_mmol"


def test_a_limit_without_a_limit_column_is_flagged():
    from parameter_extractor.stages.optional import StageSpec, stage_values
    spec = StageSpec.model_validate({"name": "c", "label": "Conditions", "trigger": {"always": True}, "intro": "x",
                                     "parameters": [{"column": "peak_temperature_C", "unit": "°C", "description": "T"},
                                                    {"column": "yield_pct", "unit": "%", "description": "y",
                                                     "uncertainties": True}]})     # (the stage asks for limits)
    Item = spec.models()[0]
    item = Item.model_validate({"col": "peak_temperature_C", "v": 10000, "u": "K", "lim": "lower", "q": "in excess of "
                                "10,000 K", "src": "p. 1", "c": "high", "set": ""})
    values, problems = stage_values(spec, item)
    assert abs(values["peak_temperature_C"].value - 9726.85) < 1e-6
    assert "lower limit" in values["peak_temperature_C"].note and problems and "lower limit" in problems[0]


def test_citations_are_not_table_captions():
    from parameter_extractor.ingestion.pdf_parser import TABLE_CAPTION_RE as R
    assert not R.search("Table 3 for product yields.")                  # 'See Supplementary\nTable 3 for ...'
    assert not R.search("Table 1 shows the results of the reaction")
    assert R.search("Table 1                              or more). Fig. 1 gives")   # a caption beside the other column
    assert R.search("Table 1. Abundances of the biogenic elements") and R.search("Table 2")


def test_table_grid_rule_only_with_grids():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.stages import chemistry_extractor as ch
    from parameter_extractor.stages.optional import for_run, load_specs
    vocab = packs.current().vocab["species_names"]
    paper = "PAPER\n\n\nwith blank lines\n\n\n"
    on, off = ch.prompt_text(paper, "PLAN", vocab), ch.prompt_text(paper, "PLAN", vocab, grids=False)
    assert "TABLE GRIDS" in on and "TABLES IN \"TABLE GRIDS\"" not in off and paper in off     # the paper untouched
    spec = load_specs()["experimental_conditions"]
    assert "TABLE GRIDS" in for_run(spec).prompt_text("P", "PLAN")
    lean = for_run(spec, grids=False)
    assert "TABLE GRIDS" not in lean.prompt_text("P", "PLAN") and "grids" not in lean.models()[1].model_fields


def test_greek_letters_spelled_out_for_pubchem():
    from parameter_extractor.pubchem import query_name
    assert query_name("α-aminobutyric acid") == "alpha-aminobutyric acid"      # PubChem's answer was GABA
    assert query_name("β-alanine") == "beta-alanine"


def test_a_code_with_an_unfound_full_name_is_not_looked_up():
    from parameter_extractor.compound_setup import _Resolver
    from parameter_extractor.pubchem import Compound, PubChem
    drug = Compound(59291641, "1-(4-(5-(3-(2-Methylpyridin-3-yloxy)...", "")
    with tempfile.TemporaryDirectory() as tmp:
        pc = PubChem(Path(tmp) / "pc.json", fetch=lambda n: drug if n == "HKG" else None)
        pc._synonyms = {"59291641": ["HKG"]}                                  # PubChem lists 'HKG' for the drug
        r = _Resolver(pc)
        assert r.resolve("HKG", "hydroxyketoglutarate", trusted=True)[1] == 0   # kept, no wrong CID
        assert r.resolve("HKG", "", trusted=True)[1] == 59291641                # (no full name: as before)


def test_drafting_in_handoff_mode():
    if not (EDER.is_file() and KIM.is_file()):
        print(f"SKIP: needs {EDER} and {KIM}")
        return
    from test_pack_drafting import PROPOSAL, _survey
    from parameter_extractor import dev_features, pack_drafting
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.errors import AnswersNeededError
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"), \
            patch.dict(os.environ, {dev_features.ENV_VAR: "1"}):
        cfg = RunConfig(api_key="", output_dir=Path(tmp) / "out", handoff_dir=Path(tmp) / "handoff",
                        rasterize_table_pages=False)
        draft = lambda: pack_drafting.draft_pack([EDER, KIM], "handoff_draft", "Peptide synthesis", "", cfg)
        for round_, expect in enumerate(([("pack_survey", 2)], [("pack_synthesis", 1)])):
            try:
                draft()
                raise AssertionError("expected requests")
            except AnswersNeededError as e:
                keys = list(e.keys)
                assert [(k.rsplit("-", 1)[0], len(keys)) for k in keys[:1]] == expect[:1], keys
                for key in keys:
                    folder = next(Path(tmp, "handoff").glob(f"*/requests/{key}.md")).parent.parent
                    answer = _survey(1) if key.startswith("pack_survey") else PROPOSAL
                    (folder / "answers" / f"{key}.json").write_text(json.dumps(answer.model_dump()))
        r = draft()
        assert r.pack.id == "handoff_draft" and r.cost_usd == 0 and (r.pack.folder / "stages").is_dir()


def test_a_figures_only_paper_skips_its_steps_when_no_figures_are_digitized():
    """run_pipeline (no figure review, no automatic digitizing): a paper whose rows would only come from figures pays
    for planning the rows and nothing else (takeuchi2020 / burchell2020 cost $0.14 each for no rows)."""
    if not EDER.is_file():
        print(f"SKIP: needs {EDER}")
        return
    import shutil
    from parameter_extractor import api_client
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import run_pipeline
    from test_pipeline_offline import make_replay
    with tempfile.TemporaryDirectory() as tmp:
        rec = Path(tmp) / "rec"
        shutil.copytree(ROOT / "runs" / "reference" / "eder1994", rec)
        plan = json.loads((rec / "structure_planner.output.json").read_text())
        plan.update(experiment_sets=[], total_planned_rows=0)
        (rec / "structure_planner.output.json").write_text(json.dumps(plan))
        replay, stages = make_replay(rec), []

        def send(ctx, **kw):
            stages.append(api_client._streamed.stage)
            return replay(ctx, **kw)
        with patch.object(api_client, "_send", send):
            result = run_pipeline(EDER, RunConfig(api_key="replay", output_dir=Path(tmp) / "out", registry_path=None))
        packs.activate("prebiotic_chemistry")
        assert sorted(stages) == ["metadata", "structure_planner"], stages
        flags = json.loads((result.run_dir / "plausibility_flags.json").read_text())["paper_level"]
        assert any(f["kind"] == "no_results" and "digitize" in f["message"] for f in flags)


def test_range_and_average_markers_go_before_any_unit():
    """Held-out round: '_range' had gone after units the app learned this round ('crater_diameters_um_range')."""
    from parameter_extractor.ingestion.flatten_to_template import with_average, with_range, without_range
    assert with_range("crater_diameters_um") == "crater_diameters_range_um"
    assert with_range("particle_speed_km_per_s") == "particle_speed_range_km_per_s"
    assert with_range("capture_efficiency_pct") == "capture_efficiency_range_pct"
    assert with_average("sampled_Gly_aq_mM") == "sampled_Gly_aq_avg_mM" and with_range("x_name") == "x_name_range"
    c = with_range("carbon_delivery_rate_kg_per_yr", "kg/yr")         # a stage parameter's own unit (not converted)
    assert c == "carbon_delivery_rate_range_kg_per_yr" and without_range(c) == "carbon_delivery_rate_kg_per_yr"
    from parameter_extractor.units import parse_range, to_column_unit
    assert parse_range("30–100 mTorr") == (30.0, 100.0, "mTorr") and abs(to_column_unit(100, "mTorr", "bar").value - 1.33322e-4) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
