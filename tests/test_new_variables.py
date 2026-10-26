"""
Offline tests for variables beyond the template: held out of the CSV until
accepted, the review decisions (new column / existing column / don't add),
the local registry remembering them for later runs, and the targeted term
search. No API calls.

Run with: python tests/test_new_variables.py
"""
import csv
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, pipeline
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.ingestion.new_variables import (VariableDecision, collect_new_variables,
                                                         group_new_variables)
from parameter_extractor.pipeline import extract, finish
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.schemas.chemistry import SoluteEntry
from parameter_extractor.schemas.figures import SpeciesAmount
from parameter_extractor.schemas.methodology import OtherParameter
from parameter_extractor.schemas.variables import TermFinding, TermSearch
from test_figures import _figure, _meta_and_method
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send

SET1 = "Na+ 3.33 mol dm-3, 81 C"


def _add_extras(ex):
    """Mix variables the template doesn't (and does) know into a real extraction."""
    first_sample = ex.structure.experiment_sets[0].samples[0].sample_label
    common = dict(phase="aq", quote="q", source="Table 1", confidence="high", conversion_note=None)
    ex.chemistry.solutes += [
        SoluteEntry(name="Na2HPO4", in_controlled_vocab=True, role="initial", set_label=SET1,
                    concentration_value=0.1, concentration_unit_raw="mol dm-3", concentration_mM=100.0,
                    **common),                               # has a template column
        SoluteEntry(name="RbCl", in_controlled_vocab=False, role="initial", set_label=SET1,
                    concentration_value=0.2, concentration_unit_raw="mol dm-3", concentration_mM=200.0,
                    **common),                               # doesn't
        SoluteEntry(name="4peptide_Gly", in_controlled_vocab=True, role="sampled", set_label=SET1,
                    sample_label=first_sample, concentration_value=0.012, concentration_unit_raw="% (Gly)4",
                    **common),
        SoluteEntry(name="Foo", in_controlled_vocab=False, role="sampled", set_label=SET1,
                    sample_label=first_sample, concentration_value=1.5, concentration_unit_raw="%",
                    **common),
    ]
    ex.methodology.other_parameters.append(OtherParameter(
        name="stirring rate", value="300 rpm", quote="stirred at 300 rpm", source="Experimental",
        confidence="high"))


def _run(tmp: Path, registry_path: Path, review=None, terms=(), search=None):
    config = RunConfig.from_settings(api_key="replay", output_dir=tmp, registry_path=registry_path,
                                     focus_terms=list(terms))
    with patch.object(api_client, "_send", _replay_send), \
            patch.object(pipeline, "run_term_search", lambda ctx, t, *a: search):
        ex = extract(PDF, config)
        _add_extras(ex)
        return finish(ex, review=review)


def _csv(result):
    with open(result.csv_path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def test_without_review_nothing_new_is_written():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), Path(tmp) / "registry.json")
        header, rows = _csv(result)
        assert not any("RbCl" in c or "Foo" in c or "UNRECOGNIZED" in c or "stirring" in c for c in header)
        assert rows[0]["initial_Na2HPO4_aq_mM"] == "100.0"                # known columns: written
        assert rows[0]["sampled_4peptide_Gly_%yield"] == "0.012"
        record = json.loads((result.run_dir / "new_variables.json").read_text())
        assert {(v["kind"], v["name"]) for v in record["left_out"]} == {
            ("species", "RbCl"), ("species", "Foo"), ("parameter", "stirring rate")}
        assert record["accepted"] == []
        assert len([f for f in result.paper_flags if f.kind == "new_variable"]) == 3
        assert not (Path(tmp) / "registry.json").exists()                 # nothing decided, nothing saved


def test_review_decisions_and_registry_memory():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    seen = {}

    def review(groups, unfound, registry):
        seen["groups"] = [(g.kind, g.alias_name, g.proposed_column, len(g.values)) for g in groups]
        stirring = next(g for g in groups if g.name == "stirring rate")
        stirring.values[0].value_text = "300"                                # user edits the value
        return [VariableDecision("initial RbCl", "species", "new_column", "initial_RbCl_aq_mM"),
                VariableDecision("stirring rate", "parameter", "new_column", "stirring_rate_rpm"),
                VariableDecision("sampled Foo %", "species", "existing_column", "sampled_DKP_Gly_%yield")]

    with tempfile.TemporaryDirectory() as tmp:
        reg_path = Path(tmp) / "registry.json"
        result = _run(Path(tmp), reg_path, review=review)
        assert ("species", "initial RbCl", "initial_RbCl_aq_mM", 1) in seen["groups"]
        assert ("parameter", "stirring rate", "stirring_rate_rpm", 1) in seen["groups"]   # unit suffix (category format)

        header, rows = _csv(result)
        assert header.index("initial_RbCl_aq_mM") > header.index("sampled_DKP_Gly_%yield")   # after template block
        set1 = [r for r in rows if r["set_id"] == "001001"]
        assert all(r["initial_RbCl_aq_mM"] == "200.0" for r in set1)
        assert all(r["initial_RbCl_aq_mM"] == "" for r in rows if r["set_id"] != "001001")
        assert all(r["stirring_rate_rpm"] == "300.0" for r in rows)         # paper-wide: every row; numeric
        # merged into an existing column -- the template's DKP_Gly column, written in the cyclic naming
        assert rows[0]["sampled_cyclo_Gly-Gly_%yield"] == "1.5" and rows[0]["sampled_DKP_Gly_%yield"] == ""
        assert result.new_variables == [] and len(result.accepted_variables) == 3

        saved = json.loads(reg_path.read_text())
        assert set(saved["columns"]) == {"initial_RbCl_aq_mM", "stirring_rate_rpm"}
        assert saved["aliases"]["species:sampled foo %"] == "sampled_DKP_Gly_%yield"

        # second run: the registry recognises all three; the review isn't even called
        seen.clear()
        result2 = _run(Path(tmp), reg_path, review=lambda *a: seen.setdefault("called", []) or [])
        assert "called" not in seen
        header2, rows2 = _csv(result2)
        assert rows2[0]["initial_RbCl_aq_mM"] == "200.0" and rows2[0]["sampled_DKP_Gly_%yield"] == "1.5"
        assert rows2[0]["stirring_rate_rpm"] == "300.0"                      # the paper's "300 rpm", read into the rpm column
        assert all("earlier review" in a["how"] for a in result2.accepted_variables)


def test_term_search_findings_and_not_found_terms():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    search = TermSearch(findings=[
        TermFinding(term="reaction volume", found=True, name="reaction volume", value="1 cm3",
                    column="solvent_volume_mL", set_label="", quote="vials (2 cm3) containing reaction "
                    "solution (1 cm3)", source="Experimental", confidence="high"),
        TermFinding(term="flowthrough recirculation time", found=False, name="", value="", column="",
                    set_label="", quote="", source="", confidence="low"),
    ])
    seen = {}

    def review(groups, unfound, registry):
        seen["unfound"] = unfound
        vol = next(g for g in groups if g.name == "reaction volume")
        seen["proposed"] = vol.proposed_column
        # no manual edit: "1 cm3" is converted into the mL column automatically
        return [VariableDecision("reaction volume", "parameter", "existing_column", "solvent_volume_mL")]

    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), Path(tmp) / "r.json", review=review,
                      terms=["reaction volume", "flowthrough recirculation time"], search=search)
        assert seen["unfound"] == ["flowthrough recirculation time"]
        assert seen["proposed"] == "solvent_volume_mL"                       # model's column suggestion kept
        header, rows = _csv(result)
        assert all(r["solvent_volume_mL"] == "1.0" for r in rows)          # "1 cm3" -> 1 mL automatically
        obs = [o for o in csv.DictReader(open(result.observations_path)) if o["column"] == "solvent_volume_mL"]
        assert "read from '1 cm3'" in obs[0]["source"]
        assert result.unfound_terms == ["flowthrough recirculation time"]
        assert any(f.kind == "term_not_found" for f in result.paper_flags)
        summary = json.loads((result.run_dir / "run_summary.json").read_text())
        assert summary["searched_terms"] == ["reaction volume", "flowthrough recirculation time"]


def test_figure_columns_and_species_outside_the_template():
    meta, meth = _meta_and_method()
    fig = _figure(y_col="my_custom_rate_per_h")
    fig.series[0].initial_species.append(SpeciesAmount(name="Foo", concentration_mM=5))
    rows, problems, new_vars = build_figure_rows([fig], meta, meth, "001", 14, 43)
    assert problems == [] and len(rows) == 2
    assert rows[0].duration_hr == 15.0 and "my_custom_rate_per_h" not in rows[0].extra
    assert "initial_Foo_aq_mM" not in rows[0].species_mM and rows[0].species_mM["initial_NaCl_aq_mM"] == 3000
    groups = group_new_variables(new_vars)
    assert [(g.kind, g.name, len(g.values)) for g in groups] == [
        ("species", "Foo", 1), ("figure_axis", "my_custom_rate_per_h", 2)]           # sorted by category
    assert groups[1].values[0].row_ids == ["001014001"] and groups[0].values[0].row_ids == ["001014001", "001014002"]

    # once accepted, the same hand-typed column is recognised
    with tempfile.TemporaryDirectory() as tmp:
        reg = VariableRegistry(Path(tmp) / "r.json")
        reg.add_column("my_custom_rate_per_h", "figure_axis")
        rows, _, new_vars = build_figure_rows([fig], meta, meth, "001", 14, 43, registry=reg)
        assert rows[0].extra["my_custom_rate_per_h"] == 0.6 and [v.kind for v in new_vars] == ["species"]


def test_eder1994_has_no_new_variables():
    """Hand-curated paper: everything it reports already has a template column."""
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    _, meth = _meta_and_method()
    chem = ChemistryExtraction.model_validate_json((REPLAY_DIR / "chemistry.output.json").read_text())
    assert collect_new_variables(meth, chem) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All new-variable tests passed.")
