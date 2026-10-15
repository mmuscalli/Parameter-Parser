"""
Offline tests for stock -> mixture concentrations (calculators/mixing.py),
PubChem name identity (pubchem.py + normalize, with a fake PubChem -- no
network), and the cost estimates (pricing.py). No API calls.

Run with: python tests/test_mixing_pubchem.py
"""
import json
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.calculators.mixing import derive_mixture_concentrations
from parameter_extractor.ingestion.flatten_to_template import build_rows, row_to_template_dict
from parameter_extractor.ingestion.new_variables import (
    VariableDecision, apply_decisions, collect_new_variables, group_new_variables)
from parameter_extractor.ingestion.normalize import normalize_chemistry
from parameter_extractor.pricing import format_usd, request_cost
from parameter_extractor.pubchem import Compound, PubChem
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.schemas.chemistry import AddedSolution, ChemistryExtraction, SoluteEntry
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.structure_plan import StructurePlan
from test_pipeline_offline import REPLAY_DIR

L = lambda cls, n: cls.model_validate_json((REPLAY_DIR / f"{n}.output.json").read_text())


def _no_methods():
    meth = L(Methodology, "methodology")
    meth.other_parameters = []
    return meth


def _entry(name, mM, **kw):
    return SoluteEntry(name=name, in_controlled_vocab=False, phase="aq", role=kw.pop("role", "initial"),
                       concentration_value=mM, concentration_unit_raw="mM", concentration_mM=mM,
                       quote="q", source="Methods", confidence="high", **kw)


def _kim_like():
    """kim2019's recipe: 5 µL 15 mM ribose phosphate + 20 µL nucleobase + 8 µL 15 mM CaCl2."""
    return ChemistryExtraction(paper_id="p", solutes=[
        _entry("ribose 1,2-cyclic phosphate", 15, concentration_basis="stock", stock_solution="ribose stock"),
        _entry("cytosine", 3.75, concentration_basis="stock", stock_solution="Nucleobase solution"),
        _entry("CaCl2", 15, concentration_basis="stock", stock_solution="CaCl2 solution"),
    ], added_solutions=[
        AddedSolution(solution="ribose stock", volume="5 µL"),
        AddedSolution(solution="nucleobase solution", volume="20 µl"),
        AddedSolution(solution="CaCl2 solution", volume="0.008 mL"),
    ])


def test_mixture_concentrations_are_calculated_and_marked():
    chem = _kim_like()
    notes = derive_mixture_concentrations(chem, ["s1"])
    derived = {s.name: s for s in chem.solutes if s.derived}
    assert derived["ribose 1,2-cyclic phosphate"].concentration_mM == 2.273       # 15 x 5 / 33
    assert derived["cytosine"].concentration_mM == 2.273                          # 3.75 x 20 / 33
    assert derived["CaCl2"].concentration_mM == 3.636                             # 15 x 8 / 33
    assert all(s.concentration_basis == "mixture" for s in derived.values())
    assert "15 mM x 8 µL / 33 µL total" in derived["CaCl2"].conversion_note
    assert [n.kind for n in notes] == ["derived"] * 3
    assert len(chem.solutes) == 6
    derive_mixture_concentrations(chem, ["s1"])                                   # idempotent
    assert len(chem.solutes) == 6


def test_mixture_not_calculated_without_every_volume():
    chem = _kim_like()
    chem.added_solutions[1].volume = "a few drops"
    notes = derive_mixture_concentrations(chem, ["s1"])
    assert not any(s.derived for s in chem.solutes)
    assert all(n.kind == "not_derived" for n in notes) and "a few drops" in notes[0].message
    chem = _kim_like()                                     # paper states the mixture value itself
    chem.solutes.append(_entry("CaCl2", 3.6))
    derive_mixture_concentrations(chem, ["s1"])
    assert sorted(s.name for s in chem.solutes if s.derived) == ["cytosine", "ribose 1,2-cyclic phosphate"]


def test_stock_and_mixture_both_reach_the_csv():
    meta, structure = L(PaperMetadata, "metadata"), L(StructurePlan, "structure_planner")
    meth, chem = L(Methodology, "methodology"), L(ChemistryExtraction, "chemistry")
    label = structure.experiment_sets[0].set_label
    chem.solutes.append(_entry("KCl", 100, set_label=label, concentration_basis="stock", stock_solution="KCl"))
    chem.added_solutions = [AddedSolution(solution="KCl", volume="10 µL", set_label=label),
                            AddedSolution(solution="water", volume="40 µL", set_label=label)]
    derive_mixture_concentrations(chem, [s.set_label for s in structure.experiment_sets])
    rows = build_rows(meta, structure, meth, chem, "001")
    d = row_to_template_dict(rows[0])
    assert d["initial_KCl_aq_mM"] == 20.0 and d["stock_KCl_aq_mM"] == 100.0
    assert rows[0].provenance["initial_KCl_aq_mM"].origin == "calculated"
    assert rows[0].provenance["stock_KCl_aq_mM"].origin == "chemistry"
    assert "stock_KCl_aq_mM" not in row_to_template_dict(rows[-1])                # other sets untouched


def test_unknown_species_stock_goes_to_review_with_its_own_column():
    chem = _kim_like()
    derive_mixture_concentrations(chem, ["s1"])
    new = collect_new_variables(_no_methods(), chem, VariableRegistry(None))
    by_alias = {v.alias_name: v for v in new}
    assert by_alias["stock cytosine"].proposed_column == "stock_cytosine_aq_mM"
    assert by_alias["initial cytosine"].proposed_column == "initial_cytosine_aq_mM"
    assert by_alias["initial cytosine"].origin == "calculated"
    assert "stock CaCl2" not in by_alias and "initial CaCl2" not in by_alias      # template species
    assert VariableRegistry(None).display_name("species:stock cytosine") == "cytosine (stock solution, before mixing)"


FAKE = {"2'-cmp": Compound(101544, "2'-Cytidylic acid", "C9H14N3O8P"),
        "cytidine 2'-monophosphate": Compound(101544, "2'-Cytidylic acid", "C9H14N3O8P"),
        "calcium dichloride": Compound(5284359, "Calcium Chloride", "CaCl2"),
        "cytosine": Compound(597, "Cytosine", "C4H5N3O")}


def _fake_pubchem(cache=None, calls=None):
    def fetch(name):
        if calls is not None:
            calls.append(name)
        return FAKE.get(name.lower())
    return PubChem(cache, fetch=fetch)


def test_pubchem_identity_matching():
    with tempfile.TemporaryDirectory() as tmp:
        cache, calls = Path(tmp) / "pc.json", []
        chem = ChemistryExtraction(paper_id="p", solutes=[
            _entry("2'-CMP", 1, role="sampled"), _entry("cytidine_2'-monophosphate", 2, role="sampled"),
            _entry("calcium dichloride", 15), _entry("ribose_1,2-cyclic_phosphate", 15),
            _entry("Gly14", 1)])
        pc = _fake_pubchem(cache, calls)
        notes = normalize_chemistry(chem, pubchem=pc)
        assert [s.name for s in chem.solutes] == ["2'-CMP", "2'-CMP", "CaCl2", "ribose 1,2-cyclic phosphate",
                                                  "14peptide_Gly"]
        assert chem.solutes[1].pubchem_cid == 101544 and "CID 101544" in chem.solutes[1].conversion_note
        assert chem.solutes[3].pubchem_cid == 0                       # PubChem doesn't know it: left alone
        assert "14peptide_Gly" not in calls                           # the rules' names aren't looked up
        assert sum(n.kind == "name_matched" for n in notes) == 3
        pc.save()
        saved = json.loads(cache.read_text())["names"]
        assert saved["2'-cmp"]["cid"] == 101544 and saved["ribose 1,2-cyclic phosphate"] is None
        calls.clear()
        again = _fake_pubchem(cache, calls)                           # second run: all from the cache
        assert again.lookup("2'-CMP").cid == 101544 and again.lookup("ribose_1,2-cyclic_phosphate") is None
        assert calls == []


def test_pubchem_names_accepted_earlier_are_recognised():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        reg = VariableRegistry(path)
        chem = ChemistryExtraction(paper_id="p", solutes=[_entry("cytidine 2'-monophosphate", 2, role="sampled")])
        normalize_chemistry(chem, pubchem=_fake_pubchem(), registry=reg)
        groups = group_new_variables(collect_new_variables(_no_methods(), chem, reg))
        apply_decisions([], groups, [VariableDecision(groups[0].alias_name, "species", "new_column",
                                                      "sampled_cytidine_2'-monophosphate_aq_mM")], reg)
        reg.save()
        reg = VariableRegistry(path)
        assert reg.species_for_cid(101544) == "cytidine 2'-monophosphate"
        chem = ChemistryExtraction(paper_id="q", solutes=[_entry("2'-CMP", 3, role="sampled")])
        normalize_chemistry(chem, pubchem=_fake_pubchem(), registry=reg)    # a later paper, another name
        assert chem.solutes[0].name == "cytidine 2'-monophosphate"
        assert collect_new_variables(_no_methods(), chem, reg) == []   # goes straight in
        reg.remove_column("sampled_cytidine_2'-monophosphate_aq_mM")
        assert reg.species_for_cid(101544) is None                    # forgotten with its column


def test_pubchem_unreachable_fails_soft():
    calls = []

    def down(name):
        calls.append(name)
        raise urllib.error.URLError("no network")
    pc = PubChem(None, fetch=down)
    chem = ChemistryExtraction(paper_id="p", solutes=[_entry("cytosine", 1), _entry("uracil", 1)])
    normalize_chemistry(chem, pubchem=pc)
    assert [s.name for s in chem.solutes] == ["cytosine", "uracil"]
    assert "could not be reached" in pc.unavailable_reason and len(calls) == 1   # stops trying


def test_cost_estimates():
    assert abs(request_cost("claude-sonnet-5-5", 63_104, 12_178) - 0.248) < 1e-3
    assert request_cost("claude-haiku-5-5", 100_000, 0) == 0.01                  # at the threshold: lower tier
    assert request_cost("claude-haiku-5-5", 100_001, 0) > 0.05                   # over: higher tier
    assert request_cost("claude-opus-5-5", 1_000_000, 0) == 4.0                  # not priced as opus-5
    assert request_cost("some-other-model", 10, 10) is None
    assert format_usd(None) == "—" and format_usd(0.0123) == "$0.012" and format_usd(1.5) == "$1.50"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All mixing / PubChem / cost tests passed.")
