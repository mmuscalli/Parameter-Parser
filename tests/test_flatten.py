"""
Offline regression tests for row building, from issues found on truman2024:
starting concentrations that differ per SAMPLE (not per set), and per-set
overrides other than temperature (e.g. pH). No API calls.

Run with: python tests/test_flatten.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.ingestion.flatten_to_template import (build_rows, column_safe_name,
                                                                proposed_column_for_solute, row_to_template_dict)
from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
from parameter_extractor.schemas.methodology import Methodology, SetOverride
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.structure_plan import StructurePlan
from test_pipeline_offline import REPLAY_DIR

L = lambda cls, n: cls.model_validate_json((REPLAY_DIR / f"{n}.output.json").read_text())


def test_per_sample_initial_concentrations_and_ph_override():
    meta, structure = L(PaperMetadata, "metadata"), L(StructurePlan, "structure_planner")
    meth, chem = L(Methodology, "methodology"), L(ChemistryExtraction, "chemistry")
    s1 = structure.experiment_sets[0]
    # a starting concentration that differs per sample in set 1 (as Gly did in truman2024's
    # Table 2); Ala, because eder1994 gives Gly paper-wide, which would (rightly) trigger the
    # "paper-wide AND per-set" ambiguity rule instead
    for i, sample in enumerate(s1.samples):
        chem.solutes.append(SoluteEntry(
            name="Ala", in_controlled_vocab=True, phase="aq", role="initial", set_label=s1.set_label,
            sample_label=sample.sample_label, concentration_value=10.0 ** (i - 4),
            concentration_unit_raw="mol dm-3", concentration_mM=1000 * 10.0 ** (i - 4),
            quote="q", source="Table 2", confidence="high"))
    meth.per_set_overrides.append(SetOverride(set_label=s1.set_label, field_name="initial_pH", value=9.8))

    rows = build_rows(meta, structure, meth, chem, "001")
    set1 = [row_to_template_dict(r) for r in rows if r.set_id == "001001"]
    assert [round(d["initial_Ala_mM"], 6) for d in set1] == [0.1, 1.0, 10.0][:len(set1)]
    assert all(d["initial_pH"] == 9.8 for d in set1)
    others = [row_to_template_dict(r) for r in rows if r.set_id == "001002"]
    assert all("initial_Ala_mM" not in d and "initial_pH" not in d for d in others)   # untouched
    assert all(d["initial_Gly_mM"] == 1000.0 for d in set1 + others)
    assert rows[0].provenance["initial_Ala_mM"].source == "Table 2"
    assert rows[0].provenance["initial_pH"].origin == "methodology (per set)"


def test_unlabelled_differing_initial_values_are_left_out_and_flagged():
    """truman2024: four different starting Gly values for one set, no sample labels.
    Picking any one would put wrong values on most rows."""
    from parameter_extractor.validation.plausibility_checks import check_extraction
    meta, structure = L(PaperMetadata, "metadata"), L(StructurePlan, "structure_planner")
    meth, chem = L(Methodology, "methodology"), L(ChemistryExtraction, "chemistry")
    s1 = structure.experiment_sets[0]
    for v in (0.1, 1.0, 10.0):
        chem.solutes.append(SoluteEntry(
            name="Ala", in_controlled_vocab=True, phase="aq", role="initial", set_label=s1.set_label,
            concentration_value=v / 1000, concentration_unit_raw="mol dm-3", concentration_mM=v,
            quote="q", source="Table 2", confidence="high"))
    rows = build_rows(meta, structure, meth, chem, "001")
    assert all("initial_Ala_mM" not in row_to_template_dict(r) for r in rows)
    flags = [f for f in check_extraction(meth, chem) if f.kind == "conflicting_values"]
    assert len(flags) == 1 and "Ala" in flags[0].message


def test_proposed_column_names_are_csv_safe():
    """kim2019's species have spaces and commas ("ribose 1,2-cyclic phosphate")."""
    assert column_safe_name(" ribose 1,2-cyclic phosphate ") == "ribose_1_2-cyclic_phosphate"
    e = SoluteEntry(name="cytidine 2'-phosphate", in_controlled_vocab=False, phase="aq", role="sampled",
                    concentration_value=1.7, concentration_unit_raw="%", quote="q", source="Table 1",
                    confidence="high")
    assert proposed_column_for_solute(e) == "sampled_cytidine_2'-phosphate_%yield"
    e.name, e.role, e.concentration_unit_raw = "ribose 1,2-cyclic phosphate", "initial", "mM"
    assert proposed_column_for_solute(e) == "initial_ribose_1_2-cyclic_phosphate_aq_mM"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All flatten tests passed.")
