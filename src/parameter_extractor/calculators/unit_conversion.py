"""Unambiguous unit conversions only. Anything requiring an assumed molecular
weight or compound identity should be flagged by the extraction stage
(see schemas/chemistry.py: `conversion_note`) rather than silently computed
here -- that's a judgment call, not a pure conversion.
"""


def molar_to_mM(value_mol_per_dm3: float) -> float:
    """1 mol/dm3 == 1 mol/L == 1000 mmol/L == 1000 mM. Exact, no assumptions."""
    return value_mol_per_dm3 * 1000.0


def mM_to_molar(value_mM: float) -> float:
    return value_mM / 1000.0
