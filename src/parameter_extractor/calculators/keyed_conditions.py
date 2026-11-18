"""
Conditions the paper gives for a STARTING SOLUTION, applied to every row with that starting composition (Mickey,
2026-11-17: mitsuzawa2004 prints the starting pH per starting material -- '100 mM G (6.1)', '3.7 mM GG (5.7)' -- in a
rate-constant table, while its result rows come from figures; a condition stated somewhere other than the rows'
own table never reached them).

A step whose spec sets `by_starting_solution` may answer a row of values with `for` naming the starting solution
('glycine 100 mM; diglycine 3.7 mM') instead of a set (stages/optional.py). Here, after every row exists -- table,
text and digitized figure rows alike:

- each part of `for` is a compound and its amount; the compound is matched to its starting column with the app's
  exact rules (the registry's synonyms, then names.match_species -- never fuzzy) and the amount converted to mM;
- a row matches when its starting compounds, among those any `for` of the step names, are exactly that solution's,
  each within 1 % (a 'glycine 100 mM' value doesn't go to a row that also starts with diglycine when another `for`
  names diglycine);
- a matching row gets the value when it has none of its own (a row's own value always wins); two solutions giving
  one row different values fill nothing and are flagged;
- one `for_solution` flag per step lists what was applied where, and any solution that matched no row or couldn't
  be read (its values are then not written: the user sees them in the flag).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value, species_column
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.validation.plausibility_checks import Flag

_STARTING = re.compile(r"^initial_.+_(?:aq|gas|s)_mM$")
_AMOUNT = (r"[~≈]?\s*(?:\d[\d.,]*\s*(?:[×x*]\s*10\s*\^?\s*[-−–]?\s*\d+)?|10\s*\^\s*[-−–]?\s*\d+)"
           r"\s*[A-Za-zµμ/]{1,8}(?:\s*/\s*[A-Za-z]{1,3})?")
_AMOUNT_AT_END = re.compile(rf"^(?P<name>.*?\S)[\s,:]+(?P<amount>{_AMOUNT})\s*$")
_AMOUNT_AT_START = re.compile(rf"^(?P<amount>{_AMOUNT})\s+(?P<name>.+)$")
_BRACKETED_AMOUNT = re.compile(r"\(\s*([~≈]?\s*\d[^()]*)\)\s*$")       # 'Gly (0.1 M)' -> 'Gly 0.1 M'


def _column(name: str, registry) -> Optional[str]:
    """A compound's starting-concentration column: the registry's synonyms first, then the exact name rules."""
    name = name.strip(" ,;:")
    if name.startswith("(") and name.endswith(")"):
        name = name[1:-1].strip()
    if not name:
        return None
    if registry is not None:
        col = registry.column_for("species", f"initial {name}")
        if col and _STARTING.match(col):
            return col
    from parameter_extractor.names import match_species
    found = match_species(name)
    return species_column("initial", found[0]) if found else None


def _mM(amount: str) -> Optional[float]:
    from parameter_extractor.units import convert, parse_quantity
    q = parse_quantity(amount.replace(",", "").strip())
    if q is None:
        return None
    value, unit = q
    return value if unit == "mM" else convert(value, unit, "mM")


def parse_solution(text: str, registry=None) -> Tuple[Dict[str, float], List[str]]:
    """({starting column: mM}, [parts that couldn't be read]) for 'glycine 100 mM; diglycine 3.7 mM'."""
    key: Dict[str, float] = {}
    bad: List[str] = []
    for part in [p.strip() for p in re.split(r"[;+]", text or "") if p.strip()]:
        part = _BRACKETED_AMOUNT.sub(r" \1", part).strip()
        first = (_AMOUNT_AT_START, _AMOUNT_AT_END) if re.match(r"[~≈]?\s*\d", part) else (_AMOUNT_AT_END,)
        m = next((x for x in (pat.match(part) for pat in first) if x), None)
        col = _column(m.group("name"), registry) if m else None
        mm = _mM(m.group("amount")) if m else None
        if col is None or mm is None:
            bad.append(part)
        else:
            key[col] = mm
    return key, bad


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.01 * max(abs(a), abs(b))


def _composition(record: dict, columns) -> Dict[str, float]:
    out = {}
    for c in columns:
        v = record.get(c)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            out[c] = float(v)
    return out


def _matches(composition: Dict[str, float], key: Dict[str, float]) -> bool:
    return set(composition) == set(key) and all(_close(composition[c], key[c]) for c in key)


def apply_keyed_conditions(rows: List[ExtractedRow], optional_list, registry=None) -> List[Flag]:
    """Fill rows from the steps' values for starting solutions (module text); returns the flags. In place."""
    from parameter_extractor.stages.optional import stage_values
    flags: List[Flag] = []
    for spec, result in optional_list:
        keyed = list(getattr(result, "keyed_parameters", []) or []) if spec.by_starting_solution else []
        if not keyed:
            continue
        solutions: Dict[str, Dict[str, float]] = {}
        unread: List[str] = []
        for text, _item in keyed:
            if text not in solutions and text not in unread:
                key, bad = parse_solution(text, registry)
                if bad or not key:
                    unread.append(text)
                else:
                    solutions[text] = key
        named = sorted({c for key in solutions.values() for c in key})
        records = {r.full_id: row_to_template_dict(r) for r in rows}
        matched = {text: [r for r in rows if _matches(_composition(records[r.full_id], named), key)]
                   for text, key in solutions.items()}
        # (row, column) -> [(value, CellSource, solution)]
        offers: Dict[Tuple[str, str], list] = {}
        for text, item in keyed:
            if text not in solutions or getattr(item, "basis", "stated") == "assumed":
                continue
            for column, v in stage_values(spec, item)[0].items():
                src = CellSource(origin=f"{spec.origin_label} (for the starting solution '{text}')", quote=v.quote,
                                 source=v.source + (f" [{v.note}]" if v.note else ""), confidence=v.confidence)
                for r in matched[text]:
                    offers.setdefault((r.full_id, column), []).append((v.value, src, text))
        by_id = {r.full_id: r for r in rows}
        applied: Dict[str, List[str]] = {}
        conflicts = []
        for (fid, column), options in offers.items():
            values = {str(o[0]) for o in options}
            if len(values) > 1:
                conflicts.append(f"{fid} {column}: " + "; ".join(f"{o[0]} (for '{o[2]}')" for o in options))
                continue
            if records[fid].get(column) not in (None, ""):
                continue                                    # the row's own value wins
            value, src, text = options[0]
            set_row_value(by_id[fid], column, value, src)
            applied.setdefault(text, []).append(f"{fid} {column}")
        lines = [f"- '{t}': {len({x.split()[0] for x in v})} row(s) ({', '.join(sorted({x.split()[1] for x in v}))})"
                 for t, v in applied.items()]
        lines += [f"- '{t}': no row starts with this solution -- its values aren't written" for t in solutions
                  if not matched[t]]
        lines += [f"- '{t}': its compounds or amounts couldn't be read -- its values aren't written" for t in unread]
        lines += [f"- conflicting values, not written: {c}" for c in conflicts]
        if lines:
            flags.append(Flag("for_solution", f"{spec.label}: values the paper gives for a starting solution, applied "
                                              f"to the rows with that starting composition:\n" + "\n".join(lines)))
    return flags
