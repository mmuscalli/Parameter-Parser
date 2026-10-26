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


# words that describe software rather than name it ('the RadVel package', 'emcee sampler v3.0')
_SOFTWARE_WORDS = {"the", "a", "an", "and", "with", "using", "via", "by", "of", "for", "in", "code", "codes", "package",
                   "packages", "software", "sampler", "samplers", "fitting", "fit", "fits", "tool", "toolkit", "python",
                   "library", "modelling", "modeling", "model", "models", "mcmc", "version", "algorithm", "routine"}


def drop_recorded_software(methodology: Methodology, fit_models) -> List[DroppedParameter]:
    """Exoplanets (2026-10-27): the fitting-models step writes the modelling software into its own
    columns (pl_fitsoftware, st_fitsoftware, ...). A suggested data-reduction item that ONLY names
    software recorded there (+ descriptive words and versions) is a repeat and is dropped; one naming
    anything else (a reduction pipeline, a step like sigma clipping) is kept."""
    names = {s.name.strip().lower() for m in (fit_models.models if fit_models else []) for s in m.software
             if s.name.strip()}
    if not names:
        return []
    kept, dropped = [], []
    for p in methodology.other_parameters:
        text = f" {p.value.lower()} "
        hits = [n for n in sorted(names, key=len, reverse=True) if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)]
        for n in hits:
            text = re.sub(rf"(?<![\w-]){re.escape(n)}(?![\w-])", " ", text)
        rest = [w for w in re.findall(r"[a-z][a-z'-]*", text) if w not in _SOFTWARE_WORDS and not re.fullmatch(r"v", w)]
        if p.category == "data_reduction" and hits and not rest:
            dropped.append(DroppedParameter(p, ", ".join(hits)))
        else:
            kept.append(p)
    methodology.other_parameters = kept
    return dropped


_NUMBER_IN_TEXT = re.compile(r"(?<![\w.])[-+−]?\d+(?:[.,]\d+)?(?![\w.]*\d)")


def _numbers(text: str) -> List[float]:
    out = []
    for m in _NUMBER_IN_TEXT.finditer(text or ""):
        try:
            out.append(abs(float(m.group().replace("−", "-").replace(",", "."))))
        except ValueError:
            pass
    return out


_SUFFIX_PARTS = re.compile(r"(?:_?(?:alt|mode)\d+)?(?:_?(?:err1|err2|err_plus|err_minus|lim|method|desc))?$")
_UNIT_WORDS = {"d", "day", "days", "h", "hr", "hrs", "hour", "hours", "min", "s", "sec", "yr", "yrs", "year", "years",
               "k", "c", "m", "km", "ms", "s-1", "mm", "ml", "ul", "bar", "mpa", "dex", "deg", "ppm", "ppt", "au",
               "r_sun", "m_sun", "r_e", "m_e", "r_j", "m_j", "pc", "mag", "kms", "about", "approximately", "of", "and"}


def _parameter(column: str) -> str:
    """The parameter a column belongs to: st_rotpalt1err1 -> st_rotp, initial_pressure_bar_err_plus -> ..."""
    return _SUFFIX_PARTS.sub("", column)


def drop_repeated_values(methodology: Methodology, rows, rows_for) -> List[DroppedParameter]:
    """One quantity, one variable (2026-10-27, nielsen2019: a suggested 'rotation period from activity
    indicators = 42.5 ± 3.4 days' next to st_rotpalt1 = 42.5, err 3.4 from the stellar step). A
    suggestion is dropped only when its value is just numbers (+ units, at most 2 other words) that
    are ALL values of ONE parameter on its rows (the value and its uncertainties / other estimates),
    with at least one distinctive number (not a whole number below 10, not a year; a lone number needs
    3 significant digits). A value that also says how ('additional Keplerian with a prior on 42.5 d')
    or numbers spread over unrelated columns (faisal's '10-200 s' vs 10 mM and 200 bar) are kept.
    `rows_for(set_label, sample_label)` -> row ids."""
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    from parameter_extractor.ingestion.observations import ROW_KEYS
    by_id = {r.full_id: r for r in rows}
    kept, dropped = [], []
    for p in methodology.other_parameters:
        numbers = _numbers(p.value)
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z_'-]*", p.value) if w.lower() not in _UNIT_WORDS]
        distinctive = [n for n in numbers if not (n == int(n) and (n < 10 or 1900 <= n <= 2100))]
        if len(numbers) == 1 and len(f"{numbers[0]:g}".replace(".", "").lstrip("0")) < 3:
            distinctive = []                 # one short number ('r ~ 0.49') could match by chance
        match = ""
        if numbers and distinctive and len(words) <= 2:
            columns = {}                     # value -> columns holding it on the item's rows
            for rid in rows_for(p.set_label or None, p.sample_label or None):
                if rid in by_id:
                    for column, v in row_to_template_dict(by_id[rid]).items():
                        if column not in ROW_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                            columns.setdefault(abs(float(v)), set()).add(column)
            per_number = [{c for v, cs in columns.items() if abs(v - n) <= 1e-6 * max(1.0, n) for c in cs}
                          for n in numbers]
            shared = set.intersection(*[{_parameter(c) for c in cs} for cs in per_number]) if all(per_number) else set()
            if shared:
                base = sorted(shared)[0]
                match = ", ".join(f"{min(c for c in cs if _parameter(c) == base)} = {n:g}"
                                  for n, cs in zip(numbers, per_number))
        if match:
            dropped.append(DroppedParameter(p, match))
        else:
            kept.append(p)
    methodology.other_parameters = kept
    return dropped
