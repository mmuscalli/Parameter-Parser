"""
The 2026-11-08 audit (Mickey: improvements made in one search path must reach the others): the naming conventions in a
normal run's review suggestions, PubChem's answer for a code corroborated before a normal run uses it, species names
that aren't compounds flagged in a normal run, the user's accepted columns not suggested again as additions.
No API, no network.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.pubchem import Compound, PubChem


def test_review_suggestions_follow_the_naming_conventions():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.new_variables import NewVariable, _categorised
    v = _categorised(NewVariable(kind="parameter", name="final pH", alias_name="final pH", proposed_column="final_pH", origin="t",
                                 value_text="8.5"), "conditions")
    assert v.proposed_column == "sampled_pH"
    t = _categorised(NewVariable(kind="parameter", name="reaction temperature", alias_name="reaction temperature", origin="t",
                                 proposed_column="reaction_temperature", value_text="80 °C"), "conditions")
    assert t.proposed_column == "initial_temperature_C"
    other = _categorised(NewVariable(kind="parameter", name="lamp power", alias_name="lamp power", origin="t",
                                     proposed_column="lamp_power", value_text="15 W"), "conditions")
    assert other.proposed_column.startswith("lamp_power")                  # no convention: unchanged


def test_codes_need_corroboration_in_a_normal_run():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.normalize import normalize_chemistry
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    fake = {"impa": Compound(15778, "Isopropyl methylphosphonate", ""),          # PubChem's wrong first hit
            "rcp": Compound(449097, "CP-640186", ""),
            "ribose 1,2-cyclic phosphate": Compound(449097, "CP-640186", "")}    # corroborates RCP (same CID)
    with tempfile.TemporaryDirectory() as tmp:
        pc = PubChem(Path(tmp) / "pc.json", fetch=lambda n: fake.get(n.lower()))
        pc._synonyms = {"15778": ["IMPA"], "449097": ["something else"]}        # no network: synonyms cached
        entry = lambda n: SoluteEntry(name=n, in_controlled_vocab=False, phase="aq", role="initial",
                                      concentration_value=1, concentration_unit_raw="mM", concentration_mM=1,
                                      quote="q", source="Methods", confidence="high")
        chem = ChemistryExtraction(paper_id="p", solutes=[entry("ImpA"), entry("RCP"),
                                                          entry("ribose 1,2-cyclic phosphate")])
        normalize_chemistry(chem, pubchem=pc)
        impa, rcp, full = chem.solutes
        assert impa.pubchem_cid in (0, None) and "not used" in (impa.conversion_note or "")
        assert rcp.pubchem_cid == 449097                                       # the paper's full name confirms it


def test_names_that_are_not_compounds_are_flagged_not_dropped():
    from parameter_extractor.pipeline import _not_a_compound_flags
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    entry = lambda n: SoluteEntry(name=n, in_controlled_vocab=False, phase="aq", role="initial",
                                  concentration_value=1, concentration_unit_raw="mM", concentration_mM=1,
                                  quote="q", source="Methods", confidence="high")
    chem = ChemistryExtraction(paper_id="p", solutes=[entry("MgCl2"), entry("phosphate buffer"), entry("DNase I")])
    flags = _not_a_compound_flags(chem)
    assert len(flags) == 1 and "phosphate buffer" in flags[0].message and "MgCl2" not in flags[0].message
    assert len(chem.solutes) == 3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
