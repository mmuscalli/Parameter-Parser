"""
Offline tests for one name per species within a paper (names.abbreviations_in / preferred_name), calculated
values that repeat a stated one, and stock concentrations as solution preparation (Mickey, 2026-11-02,
Riggi2023: ImpA under three names and three identical values). No API calls.

Run with: python tests/test_species_names.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs


def test_the_papers_abbreviation_is_the_name():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.names import abbreviations_in, preferred_name
    text = ("Activated nucleotides, adenosine 5(cid:48)-phosphorimidazolide (ImpA), were used. A 15 mM ImpA stock "
            "was prepared. Compound (II) and sodium chloride (aq) were added.")
    names = ["adenosine 5'-phosphorimidazolide", "ImpA", "glycine (Gly)", "compound (II)", "NaCl (aq)"]
    abbreviations = abbreviations_in(text, names)
    assert abbreviations == {"adenosine 5'-phosphorimidazolide": "ImpA", "glycine": "Gly"}
    assert preferred_name("adenosine 5'-phosphorimidazolide", abbreviations) == "ImpA"      # from the text
    assert preferred_name("adenosine 5'-phosphorimidazolide (ImpA)", abbreviations) == "ImpA"
    assert preferred_name("glycine (Gly)", abbreviations) == "Gly"
    assert preferred_name("compound (II)", abbreviations) == "compound (II)"        # a label, not an abbreviation
    assert preferred_name("NaCl (aq)", abbreviations) == "NaCl (aq)"


def test_chemistry_and_review_use_one_name_and_one_value():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.calculators.mixing import derive_mixture_concentrations
    from parameter_extractor.ingestion.new_variables import group_new_variables
    from parameter_extractor.ingestion.normalize import normalize_chemistry
    from parameter_extractor.schemas.chemistry import AddedSolution, ChemistryExtraction, SoluteEntry
    from parameter_extractor.schemas.variables import NewVariable
    stock = SoluteEntry(name="adenosine 5'-phosphorimidazolide (ImpA)", role="initial", phase="aq",
                        concentration_value=15, concentration_unit_raw="mM", concentration_basis="stock",
                        stock_solution="ImpA stock", quote="A stock solution of 15 mM ImpA", source="Methods",
                        confidence="high")
    chem = ChemistryExtraction(solutes=[stock], added_solutions=[AddedSolution(
        solution="ImpA stock", volume="100 µL", quote="100 µL was added", source="Methods")])
    normalize_chemistry(chem, abbreviations={"adenosine 5'-phosphorimidazolide": "ImpA"})
    derive_mixture_concentrations(chem, [""])
    assert {(s.name, s.concentration_basis, s.derived) for s in chem.solutes} == {("ImpA", "stock", False),
                                                                                ("ImpA", "mixture", True)}
    # the review: the calculated 15 mM is left out where the digitized series state 15 mM for the same rows
    rows = ["001001001", "001002001"]
    figure = [NewVariable(kind="species", name="ImpA", alias_name="initial ImpA", proposed_column="initial_ImpA_aq_mM",
                          role="initial", value=15.0, unit="mM", origin="Fig. 2", row_ids=[r]) for r in rows]
    calculated = NewVariable(kind="species", name="ImpA", alias_name="initial ImpA", proposed_column="initial_ImpA_aq_mM",
                             role="initial", value=15.0, unit="mM", origin="calculated", row_ids=rows)
    [group] = group_new_variables(figure + [calculated])
    assert [v.origin for v in group.values] == ["Fig. 2", "Fig. 2"]
    different = calculated.model_copy(update={"value": 10.0})            # a different number stays (both shown)
    [group] = group_new_variables(figure + [different])
    assert len(group.values) == 3


def test_stock_concentrations_are_solution_preparation():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor import variable_categories as vc
    assert vc.for_source("species", "stock") == "solution_prep"
    assert vc.for_source("species", "initial") == "starting_species"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All species-name tests passed.")
