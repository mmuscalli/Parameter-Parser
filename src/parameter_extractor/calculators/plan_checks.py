"""
Rows that lack what their row plan says varies (Mickey, 2026-11-17: Huber1998's Table 1 -- 46 runs, a pH per run, the
page image perfectly legible -- came back with no pH in 2 of 3 runs, the conditions step noting "not provided row-by-row
here"; a table read incompletely should be caught, not trusted).

Local, no model, after every row exists. The row plan names, per set, what distinguishes its rows (`varies`: "pH per
run", "temperature = 80-95 C", "elapsed time"). For each set of two or more rows and each kind of condition the
pack's label columns cover (temperature, time, pressure, pH -- `label_columns`, which drafted packs get too), when the
plan says that condition varies but the set's rows have no value for it, or the same one on every row, one
`plan_mismatch` flag names the set, its table and the column: the table was probably read incompletely. Nothing is
filled or changed.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
from parameter_extractor.validation.plausibility_checks import Flag

# A condition varies WITHIN a set only when the plan says so: several values of it (a list or a range) or a variation
# word next to it. `varies` mostly says what sets a set apart from the others ("T = 50 C", "initial pH 8"): one value
# is the set's own, never a sign of rows that differ (the first version flagged 90 sets in 21 of 56 papers for that).
_NUM = r"(?<![\w.\-/])\d+(?:\.\d+)?"
_NUMLIST = rf"{_NUM}(?:\s*(?:,|-|–|to|and|or|vs\.?)\s*\d+(?:\.\d+)?)*"
VALUES = {
    "pH": rf"\bp[HD]\b\s*[=:≈~]?\s*\(?({_NUMLIST})",
    "temperature": rf"({_NUMLIST})(?:\s*°\s*C|\s+C)\b",          # '94 C', '94 °C' -- not '14C glycine'
    "pressure": rf"({_NUMLIST})\s*(?:bar|MPa|kPa|psi|atm)\b",
    "time": rf"({_NUMLIST})\s*(?:h|hr|hrs|hours?|d|days?|min|minutes?|weeks?)\b",
}
KIND_WORDS = {
    "pH": r"\bp[HD]\b",
    "temperature": r"\btemperatures?\b|\bT\b",
    "pressure": r"\bpressures?\b",
    "time": r"\btimes?\b|\bdurations?\b|\btime points?\b|\bsampling\b",
}
_VARIATION = r"per\s+(?:run|row|entry|sample|experiment)|vary|varies|varied|varying|different|differ\w*|series|sweep|each"


def varies_evidence(kind: str, varies: str) -> str:
    """How the plan's `varies` text says the set's rows differ in this kind of condition: 'list' (several values,
    'pH 8.0, 9.0, 10.5', '1.4 vs 2.6'), 'word' ('pH per run', 'different pH'), 'range' ('pH 7.5-9.9': rows that
    differ, or one imprecise condition) or '' (not said: one value is the set's own -- 'T = 50 C', 'initial pH 8')."""
    text = varies or ""
    found = ""
    for m in re.finditer(VALUES[kind], text, re.IGNORECASE):
        part = m.group(1)
        n = len(re.findall(r"\d+(?:\.\d+)?", part))
        commas = part.count(",")
        if n >= 3 and commas or re.search(r"\b(?:and|or|vs)\b", part) and n >= 2:
            return "list"
        if n == 2 and not commas:
            found = "range"
    word = KIND_WORDS[kind]
    near = rf"(?:{_VARIATION})\W+(?:[\w/()\[\]-]+\W+){{0,12}}?(?:{word})|(?:{word})\W+(?:\w+\W+){{0,2}}?(?:{_VARIATION})"
    if re.search(near, text, re.IGNORECASE):
        return "word"
    return found


def says_varies(kind: str, varies: str) -> bool:
    return bool(varies_evidence(kind, varies))


def _values(records: List[dict], column: str) -> set:
    out = set()
    for rec in records:
        for c in [k for k in rec if k == column or k.replace("_range", "") == column]:      # its range column too
            v = rec.get(c)
            if v not in (None, "") and not (isinstance(v, float) and v != v):
                out.add(str(round(v, 6)) if isinstance(v, (int, float)) else str(v).strip())
    return out


def plan_mismatch_flags(rows, structure, label_columns: Optional[dict]) -> List[Flag]:
    if not rows or structure is None or not label_columns:
        return []
    plan = structure.experiment_sets
    by_set: Dict[int, list] = {}
    for r in rows:
        n = r.set_id[-3:]
        if n.isdigit() and 0 < int(n) <= len(plan) and not r.original_data_reference:
            by_set.setdefault(int(n), []).append(r)
    flags = []
    for n, members in sorted(by_set.items()):
        if len(members) < 2:
            continue
        pset = plan[n - 1]
        varies = pset.varying_condition_summary or ""
        records = [row_to_template_dict(r) for r in members]
        for kind, column in label_columns.items():
            evidence = varies_evidence(kind, varies) if kind in VALUES else ""
            if not evidence:
                continue
            values = _values(records, column)
            if len(values) > 1 or (evidence == "range" and values):
                continue                    # a range with one value on the rows may be one imprecise condition
            where = pset.source_table_or_section or "its source"
            state = f"the same {column} on every row ({next(iter(values))})" if values else f"no {column}"
            flags.append(Flag(
                "plan_mismatch",
                f"Set {members[0].set_id} ({pset.set_label}, {where}): the row plan says its rows differ in {kind} "
                f"('{varies}'), but its {len(members)} rows have {state}. {where} was probably read incompletely -- "
                f"check the column against the paper and enter the values per row.",
                source=where))
    return flags
