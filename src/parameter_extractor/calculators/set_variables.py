"""
What distinguishes the rows of a set, and what a set's rows should share (Mickey, 2026-11-17: row and set notation
should be legible -- which variable a set varies was only in `source_notes`; and the starting conditions of a set's
rows should be robust: a value reported for one row of a set usually holds for the others).

Local, no model, after every row is assembled (table, text and digitized figure rows alike):

1. `set_independent_variable` / `set_independent_value` (Row block, next to the ids): the starting-condition
   columns whose values differ between the rows of a set -- `duration_hr` for a time series, `initial_NaCl_aq_mM` for
   rows that raise the NaCl concentration, 'initial_temperature_C; duration_hr' when both change, a compound some rows
   have and others don't -- and each row's value of them, in the same order ('not given' where the row has none). Read from the rows themselves, so it is right whatever the set was called. A set
   of one row, or one whose rows don't differ in any starting condition (replicates), gets ''.
2. `set_gap` flags: a minority of a set's rows with NO value for a starting compound that the set's other rows all
   give with ONE value (a reagent stated once for a series, or a control run without it). Nothing is filled: which it is needs the
   paper (Mickey: assumed values are flagged and offered, never written). Not flagged: a substitution, where every
   row without it has another compound the rows with it lack (H2S in some runs, CH3SH in the others). Methods and conditions (pH, pressure ...)
   are filled within a set by calculators/shared_values.py's group rule; compounds aren't, because a control row
   without the reagent is common.
"""
from __future__ import annotations

import re
from typing import Dict, List

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.validation.plausibility_checks import Flag

VARIABLE, VALUE = "set_independent_variable", "set_independent_value"
NOT_GIVEN = "not given"
# starting conditions of a row: what was set before the experiment (not what was measured from it)
_CONDITION = re.compile(r"^(?:initial_|stock_)|^(?:duration_hr|cycle_number|cycle_duration_hr|flow_rate_mL_min|"
                        r"residence_time_hr|loading_volume_mL|solvent_volume_mL|solid_material_name|"
                        r"solid_material_mass_g|headspace_gas_name|wet_phase_.+|dry_phase_.+)$")
_NOT = re.compile(r"_(?:err_plus|err_minus|lim)$|_range(?:_|$)|_avg(?:_|$)")
_COMPOUND = re.compile(r"^(?:initial|stock)_.+_(?:aq|gas|s)_[A-Za-z%]+$")
_TIME_FIRST = ("duration_hr", "cycle_number", "residence_time_hr")


def _empty(v) -> bool:
    return v is None or v == "" or (isinstance(v, float) and v != v)


def _key(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 6)
    return str(v).strip().lower()


def _shown(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return f"{v:g}" if isinstance(v, float) else str(v)


def _sets(rows: List[ExtractedRow]) -> Dict[str, List[ExtractedRow]]:
    out: Dict[str, List[ExtractedRow]] = {}
    for r in rows:
        out.setdefault(r.set_id, []).append(r)
    return out


def add_set_variables(rows: List[ExtractedRow]) -> None:
    """Writes set_independent_variable / set_independent_value on every row, in place."""
    for members in _sets(rows).values():
        records = [row_to_template_dict(r) for r in members]
        columns: List[str] = []
        if len(members) > 1:
            seen = list(dict.fromkeys(c for rec in records for c in rec
                                      if _CONDITION.match(c) and not _NOT.search(c)))
            for c in seen:
                values = {_key(rec.get(c)) for rec in records if not _empty(rec.get(c))}
                given = sum(not _empty(rec.get(c)) for rec in records)
                # different values, or a compound some rows have and others don't (H2S in some runs, CH3SH in the
                # others; with and without Na2HPO4)
                if len(values) > 1 or (_COMPOUND.match(c) and 0 < given < len(records)):
                    columns.append(c)
            # time first, then the other conditions, then compounds
            columns.sort(key=lambda c: (c not in _TIME_FIRST, bool(_COMPOUND.match(c)), seen.index(c)))
        src = CellSource(origin="set structure", source="the starting conditions that differ between the rows of "
                                                         "this set")
        for r, rec in zip(members, records):
            set_row_value(r, VARIABLE, "; ".join(columns), src)
            set_row_value(r, VALUE, "; ".join(NOT_GIVEN if _empty(rec.get(c)) else _shown(rec.get(c)) for c in columns),
                          src)


def set_gap_flags(rows: List[ExtractedRow]) -> List[Flag]:
    """One flag per set and compound: rows without a starting compound the set's other rows (2 or more) all give
    with one value. Rows reproduced from another paper are left out (they keep that paper's own reporting)."""
    flags: List[Flag] = []
    for set_id, members in _sets(rows).items():
        members = [r for r in members if not r.original_data_reference]
        if len(members) < 3:
            continue
        records = {r.full_id: row_to_template_dict(r) for r in members}
        compounds = list(dict.fromkeys(c for rec in records.values() for c in rec
                                       if _COMPOUND.match(c) and not _empty(rec.get(c))))
        for c in compounds:
            have = [r for r in members if not _empty(records[r.full_id].get(c))]
            missing = [r for r in members if _empty(records[r.full_id].get(c))]
            values = {_key(records[r.full_id][c]) for r in have}
            # a gap: most rows of the set give it with one value and a minority don't (a reagent used in 2 of 20
            # screening entries isn't missing from the other 18)
            if len(have) < 2 or not missing or len(values) != 1 or len(missing) >= len(have):
                continue
            # a substitution, not a gap: every row without it has another compound the rows with it lack
            # (Huber1998: H2S in some runs, CH3SH in the others)
            if all(any(_COMPOUND.match(d) and d != c and not _empty(records[r.full_id].get(d))
                       and all(_empty(records[h.full_id].get(d)) for h in have) for d in records[r.full_id])
                   for r in missing):
                continue
            value = _shown(records[have[0].full_id][c])
            flags.append(Flag(
                "set_gap",
                f"Set {set_id}: {len(missing)} row(s) have no {c}, which the set's other {len(have)} row(s) all give as "
                f"{value}. A control without it, or a value the paper states once for the whole series? Enter it on "
                f"those rows if the paper says so. Rows: {', '.join(r.full_id for r in missing)}.",
                source=f"set {set_id}"))
    return flags
