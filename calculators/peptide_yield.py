"""
Peptide %yield <-> concentration (mM) conversion.

POLO_variable_mapping.csv marks every `sampled_<n>peptide_<AA>_%yield` column
as `status: no_analogue_calculated` -- it is NOT an ontology fact to extract
directly, it's derived from the ontology-tracked concentration. Many older
papers report the inverse of what we want (yield %, not concentration), so
this module needs to go both directions.

Yield convention used here: percent of the INITIAL MONOMER (not initial
limiting reagent in general) that ended up incorporated into the n-mer,
accounting for n monomer units per n-mer. This matches how eder1994 reports
"% (Gly)2" and "% (Gly)3" relative to the 1.0 mol/dm3 initial glycine.
Confirm this convention holds before reusing it on a different paper --
yield definitions vary across the literature and this is exactly the kind of
assumption that should be stated explicitly, not silently inherited.
"""


def peptide_mM_from_yield_pct(yield_pct: float, initial_monomer_mM: float, n_mer: int) -> float:
    if n_mer < 2:
        raise ValueError("n_mer must be >= 2 (a monomer isn't a peptide)")
    return (yield_pct / 100.0) * initial_monomer_mM / n_mer


def yield_pct_from_peptide_mM(peptide_mM: float, initial_monomer_mM: float, n_mer: int) -> float:
    if initial_monomer_mM == 0:
        raise ValueError("initial_monomer_mM must be nonzero")
    return (peptide_mM * n_mer / initial_monomer_mM) * 100.0
