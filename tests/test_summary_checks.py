"""
A Paper summary row holding reactants of different experiments (calculators/summary_checks.py, Mickey 2026-11-18:
Kawamura2009's row had Ala and Asp side by side; papers that DO use several amino acids together usually say so).
No API calls.

Run with: python tests/test_summary_checks.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.calculators.summary_checks import compound_class, summary_mixed_flags  # noqa: E402
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow  # noqa: E402


def _row(set_type="Paper summary", **quoted):
    values = {c: v for c, (v, _q) in quoted.items()}
    prov = {c: CellSource(origin="chemistry", quote=q, source="Methods") for c, (_v, q) in quoted.items()}
    return ExtractedRow(full_id="002001001", set_id="002001", sample_id="001", set_type=set_type, entry_number=1,
                        paper_title="t", authors=[], year_published=2009, journal_published="j",
                        experiment_type="Batch", solution_type="Wet", species_mM=values, provenance=prov)


def test_classes_by_the_exact_name_rules():
    assert [compound_class(n) for n in ("Ala", "Gly-Gly", "cyclo_Gly-Gly", "(Gly)4", "AMP", "NaCl", "EDC")] == \
        ["amino acid", "peptide", "peptide", "peptide", "nucleotide", "", ""]


def test_alternatives_and_separate_statements_are_flagged():
    # Kawamura2009: 'Asp, Glu, or Ala' -- alternatives
    row = _row(initial_Asp_aq_mM=(10.0, "0.01 M Asp, Glu, or Ala 0.02 M EDC"),
               initial_Ala_aq_mM=(5.0, "[(Ala)4] = 0.001 M, [Ala] = 0.005 M"),
               initial_EDC_aq_mM=(20.0, "0.01 M Asp, Glu, or Ala 0.02 M EDC"))
    flags = summary_mixed_flags([row], "Paper summary")["002001001"]
    assert len(flags) == 1 and flags[0].kind == "summary_mixed"
    assert "initial_Asp_aq_mM" in flags[0].message and "initial_Ala_aq_mM" in flags[0].message
    assert "EDC" not in flags[0].message                                    # a condensing agent: not a reactant class
    # two sentences that don't name each other
    row = _row(initial_Gly_aq_mM=(100.0, "glycine (0.1 M) was heated"), initial_Ala_aq_mM=(50.0, "alanine 50 mM"))
    assert summary_mixed_flags([row], "Paper summary")


def test_compounds_the_paper_uses_together_are_not_flagged():
    row = _row(initial_Gly_aq_mM=(5.0, "a mixture of glycine and alanine (5 mM each)"),
               initial_Ala_aq_mM=(5.0, "a mixture of glycine and alanine (5 mM each)"))
    assert summary_mixed_flags([row], "Paper summary") == {}
    row = _row(initial_Gly_aq_mM=(5.0, "Gly (5 mM) with Ala"), initial_Ala_aq_mM=(5.0, "5 mM Ala"))
    assert summary_mixed_flags([row], "Paper summary") == {}
    # only Paper summary rows are checked; one amino acid with salts is never flagged
    row = _row("Independent", initial_Gly_aq_mM=(1.0, "glycine"), initial_Ala_aq_mM=(1.0, "alanine"))
    assert summary_mixed_flags([row], "Paper summary") == {}
    row = _row(initial_Gly_aq_mM=(1.0, "glycine"), initial_NaCl_aq_mM=(500.0, "NaCl"), initial_MgCl2_aq_mM=(5.0, "Mg"))
    assert summary_mixed_flags([row], "Paper summary") == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All summary-row tests passed.")
