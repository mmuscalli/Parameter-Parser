"""
Offline tests for results named without an amount ('detected' -> text, 'not detected'
-> 0) and amounts converted to mM with the reaction volume (calculators/amounts.py,
Mickey 2026-10-23, from Chen2007). No API calls.

Run with: python tests/test_amounts.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.calculators.amounts import apply_detection, derive_from_amounts
from parameter_extractor.calculators.peptide_totals import fill_total_peptide_yield
from parameter_extractor.ingestion.flatten_to_template import (DETECTED, _solute_value, column_for_solute,
                                                               set_row_value)
from parameter_extractor.ingestion.new_variables import stored_value
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.row_schema import ExtractedRow
from parameter_extractor.schemas.variables import NewVariable
from parameter_extractor.units import convert, parse_quantity

T1, T3 = "Table 1", "Table 3"


def _sp(nm, r, v, u, **kw):
    return {"nm": nm, "r": r, "ph": "aq", "v": v, "u": u, "q": "q", "src": "s", "c": "high", **kw}


def _chem(groups):
    return ChemistryExtraction.model_validate({"groups": groups, "unmapped_species": [], "added_solutions": [],
                                               "molar_ratios": []})


def test_amount_units():
    assert parse_quantity("3.3 mmol") == (3.3, "mmol") and parse_quantity("10 µmol") == (10.0, "µmol")
    assert convert(2, "mol", "mmol") == 2000 and convert(1, "mmol", "mM") is None     # an amount isn't a concentration


def test_detected_and_not_detected():
    chem = _chem([{"set": T3, "sample": "Entry 3", "species": [
        _sp("Phe-Ala", "sampled", None, "%", det="detected"),
        _sp("Gly-Gly", "sampled", None, "%", det="not detected"),
        _sp("Ala-Ala", "sampled", None, "", det="not detected"),
        _sp("Ala", "initial", None, "mmol")]}])
    notes = apply_detection(chem)
    fa, gg, aa, ala = chem.solutes
    assert _solute_value(fa) == DETECTED and fa.concentration_value is None
    assert (gg.concentration_value, gg.concentration_mM, _solute_value(gg)) == (0.0, None, 0.0)   # 0 %
    assert aa.concentration_mM == 0.0                                                          # 0 mM
    assert _solute_value(ala) is None                                    # initial: never 'detected'
    assert [n.kind for n in notes] == ["derived", "derived"]
    assert "not detected were written as 0" in notes[0].message and "Gly-Gly (Entry 3)" in notes[0].message
    assert "'detected'" in notes[1].message and "Phe-Ala" in notes[1].message
    # into a row: text in its %yield column; the review passes it through unconverted
    row = ExtractedRow(full_id="1", set_id="1", sample_id="1", set_type="Independent", entry_number=1,
                       paper_title="t", authors=["a"], year_published=2000, journal_published="j",
                       experiment_type="Batch", solution_type="Wet")
    set_row_value(row, column_for_solute(fa) or "sampled_Phe-Ala_%yield", DETECTED)
    set_row_value(row, "sampled_2peptide_Gly_%yield", 1.5)
    filled, _ = fill_total_peptide_yield([row])
    assert filled == ["1"] and row.extra["total_sampled_peptides_yield"] == 1.5
    assert "detected without an amount, not counted: Phe-Ala" in row.provenance["total_sampled_peptides_yield"].source
    nv = NewVariable(kind="species", name="Phe2Ala", alias_name="sampled Phe2Ala %", proposed_column="c",
                     value_text=DETECTED, unit="%", origin="chemistry")
    assert stored_value(nv, "sampled_Phe2Ala_%yield") == (DETECTED, "")


def test_amounts_to_mM():
    chem = _chem([
        {"set": T1, "species": [_sp("isobutyric acid", "initial", 3, "mmol"),
                                _sp("NaCl", "initial", 0.5, "M")]},
        {"set": T1, "sample": "E1", "species": [_sp("Na2CO3", "initial", 30, "mmol")]},
        {"set": T3, "species": [_sp("Ala", "initial", 1, "mmol", mM=999)]},
        {"set": "", "species": [_sp("KCl", "initial", 2, "mmol")]}])
    volumes = {(T1, "E1"): (30.0, "Sect. 2.1"), (T1, "E2"): (50.0, "Sect. 2.2"), (T3, ""): (10.0, "Sect. 2.4")}
    notes = derive_from_amounts(chem, volumes, {T1: ["E1", "E2", "E3"], T3: ["E1"]})
    by = {(s.name, s.sample_label): s for s in chem.solutes}
    # a set-wide amount in a set with different volumes -> one entry per sample
    assert by[("isobutyric acid", "E1")].concentration_mM == 100.0
    assert by[("isobutyric acid", "E2")].concentration_mM == 60.0
    assert by[("isobutyric acid", "E3")].concentration_mM is None                         # no volume
    assert by[("Na2CO3", "E1")].concentration_mM == 1000.0
    ala = by[("Ala", None)]
    assert ala.concentration_mM == 100.0 and ala.derived and ala.calculated_from == "amount"
    assert "1 mmol in 10 mL reaction volume (Sect. 2.4)" in ala.conversion_note
    assert by[("NaCl", None)].concentration_mM is None                    # not an amount: normalize's job
    assert by[("KCl", None)].concentration_mM is None                     # paper-wide: volumes differ
    kinds = sorted(n.kind for n in notes)
    assert kinds.count("mismatch") == 1 and "had 999 mM" in next(n for n in notes if n.kind == "mismatch").message
    missing = " ".join(n.message for n in notes if n.kind == "not_derived")
    assert "for that sample: isobutyric acid (E3)" in missing and "KCl" in missing
    t1 = next(n for n in notes if n.kind == "derived" and n.message.startswith("mM calculated") and T1 in n.message)
    assert "isobutyric acid 3 mmol / 30 mL -> 100 mM (E1)" in t1.message
    # running the mixing step afterwards keeps these calculated entries
    from parameter_extractor.calculators.mixing import derive_mixture_concentrations
    derive_mixture_concentrations(chem, [T1, T3])
    assert any(s.name == "Ala" and s.concentration_mM == 100.0 for s in chem.solutes)



def test_totals_split_in_their_ratio():
    """Chen2007 Table 3: '(1:1 ratio of each component, total 1 mmol)' in 10 mL -> 0.5 mmol each = 50 mM."""
    from parameter_extractor.calculators.amounts import split_totals
    from parameter_extractor.ingestion.normalize import normalize_chemistry
    chem = ChemistryExtraction.model_validate({
        "groups": [{"set": T3, "sample": "E3", "species": [_sp("L-Alanine", "initial", None, "")]},
                   {"set": T3, "sample": "E4", "species": [_sp("Ser", "initial", 0.4, "mmol")]}],
        "unmapped_species": [], "added_solutions": [], "molar_ratios": [], "mixture_totals": [
            {"set": T3, "sample": "E1", "total": "1 mmol", "parts": [{"nm": "Ala", "n": 1}], "q": "total 1 mmol",
             "src": "Sect. 2.4"},
            {"set": T3, "sample": "E3", "total": "1 mmol", "parts": [{"nm": "alanine", "n": 1},
                                                                    {"nm": "phenylalanine", "n": 1}]},
            {"set": T3, "sample": "E4", "total": "1 mmol", "parts": [{"nm": "Ser", "n": 1}, {"nm": "Phe", "n": 3}]},
            {"set": "", "total": "30 mM", "parts": [{"nm": "Gly", "n": 1}, {"nm": "Ala", "n": 2}]},
            {"set": T1, "total": "a few mmol", "parts": [{"nm": "Gly", "n": 1}]}]})
    normalize_chemistry(chem)                            # 'alanine' -> Ala, as the species entries
    notes = split_totals(chem, [T1, T3])
    notes += derive_from_amounts(chem, {(T3, ""): (10.0, "Sect. 2.4")}, {T1: [], T3: ["E1", "E3", "E4"]})
    by = {(s.name, s.set_label, s.sample_label): s for s in chem.solutes}
    assert by[("Ala", T3, "E1")].concentration_mM == 100.0
    ala = by[("Ala", T3, "E3")]                          # the empty entry was filled, not duplicated
    assert ala.concentration_value == 0.5 and ala.concentration_mM == 50.0 and ala.derived
    assert "1/2 of the stated total 1 mmol" in ala.conversion_note and "in 10 mL" in ala.conversion_note
    assert by[("Phe", T3, "E3")].concentration_mM == 50.0
    assert by[("Ser", T3, "E4")].concentration_value == 0.4                 # stated: kept, checked
    assert by[("Phe", T3, "E4")].concentration_mM == 75.0
    assert by[("Gly", T1, None)].concentration_mM == 10.0 and by[("Ala", T1, None)].concentration_mM == 20.0
    assert sum(1 for s in chem.solutes if s.name == "Ala" and s.sample_label == "E3") == 1
    kinds = [n.kind for n in notes]
    assert kinds.count("mismatch") == 1 and "share of the total 1 mmol is 0.25 mmol" in \
        next(n.message for n in notes if n.kind == "mismatch")
    assert any(n.kind == "not_derived" and "a few mmol" in n.message for n in notes)
    assert any(n.kind == "derived" and n.message.startswith("Total 1 mmol split in the ratio Ala 1, Phe 1")
               for n in notes)

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All amount / detection tests passed.")
