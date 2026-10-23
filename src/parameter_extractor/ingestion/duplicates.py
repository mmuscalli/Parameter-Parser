"""
One quantity, one variable: drop "other parameters" that only repeat amounts
the chemistry step already records.

The methodology step lists open-ended conditions, and sometimes includes the
volumes and concentrations of the solutions combined (kim2019: "nucleobase
solution volume 20 µL" next to the chemistry step's added solution "nucleobase
solution, 20 µL"). Two variables for the same amount invite double counting
("20 µL" twice reads like 40 µL), so the chemistry record is the one kept --
it's what the mixture calculations use. (Mickey, 2026-10-15.)

Only exact repeats go: an other-parameter is dropped when it contains at least
one volume or concentration and EVERY volume/concentration in it matches one
recorded with the chemistry for the same set (or paper-wide). Anything with an
extra quantity (a redissolution volume, a total volume) is kept. Dropped items
are reported, not lost.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from parameter_extractor.calculators.mixing import solutions_for
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.methodology import Methodology, OtherParameter
from parameter_extractor.units import convert, parse_quantity

TOLERANCE = 0.01
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mol\s*dm[-−–]?3|mol\s*/\s*L|mol\s*L[-−–]1|[µμu]M|mM|M|"
                     r"[µμu][Ll]|m[Ll]|cm3|cm³|dm3|L)(?![A-Za-z0-9])")


@dataclass
class DroppedParameter:
    parameter: OtherParameter
    matches: str            # what it repeats, for the report


def amounts(text: str) -> List[Tuple[str, float, str]]:
    """Every volume ('volume', µL) and concentration ('concentration', mM) in a text."""
    found = []
    for m in _AMOUNT.finditer(text or ""):
        q = parse_quantity(f"{m.group(1)} {m.group(2)}")
        if q is None:
            continue
        for kind, unit in (("volume", "µL"), ("concentration", "mM")):
            value = convert(q[0], q[1], unit)
            if value is not None:
                found.append((kind, value, m.group(0)))
                break
    return found


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b), 1e-12)


def _volume_match(value: float, chemistry: ChemistryExtraction, set_label: Optional[str]):
    sols = solutions_for(chemistry, set_label) if set_label else chemistry.added_solutions
    for sol in sols:
        q = parse_quantity(sol.volume)
        v = convert(q[0], q[1], "µL") if q else None
        if v is not None and _close(v, value):
            return sol
    return None


def _concentration_match(value: float, chemistry: ChemistryExtraction, set_label: Optional[str],
                         text: str, solutions: set):
    """A recorded starting concentration equal to `value` -- of a species the parameter is
    about: named in its text, or added in a solution whose volume it also gives. (Equal
    numbers alone aren't enough: kim2019's CaCl2 and ribose phosphate are both 15 mM.)"""
    low = text.lower()
    for s in chemistry.solutes:
        if (s.derived and not s.calculated_from) or s.concentration_mM is None or s.role != "initial":
            continue
        if set_label and s.set_label not in (set_label, None):
            continue
        linked = (s.name.lower() in low or (s.pubchem_title and s.pubchem_title.lower() in low)
                  or (s.stock_solution and " ".join(s.stock_solution.lower().split()) in solutions))
        if linked and _close(s.concentration_mM, value):
            return s
    return None


def drop_repeated_amounts(methodology: Methodology, chemistry: ChemistryExtraction) -> List[DroppedParameter]:
    """Removes the repeats from methodology.other_parameters; returns what was removed."""
    kept, dropped = [], []
    for p in methodology.other_parameters:
        found, label, matches = amounts(p.value), p.set_label or None, []
        sols = [_volume_match(v, chemistry, label) for kind, v, _ in found if kind == "volume"]
        matches += [f"'{sol.solution}' {sol.volume}" if sol else None for sol in sols]
        linked = {" ".join(sol.solution.lower().split()) for sol in sols if sol}
        for kind, v, _ in found:
            if kind == "concentration":
                s = _concentration_match(v, chemistry, label, f"{p.name} {p.value}", linked)
                matches.append(f"{s.name} {s.concentration_value:g} {s.concentration_unit_raw}" if s else None)
        if found and all(matches):
            dropped.append(DroppedParameter(p, "; ".join(dict.fromkeys(matches))))
        else:
            kept.append(p)
    methodology.other_parameters = kept
    return dropped
