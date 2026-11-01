"""
Ambient conditions (Mickey, 2026-11-01, Riggi2023: "Experiments were conducted at ambient temperature and
pressure"): where a paper SAYS its experiments ran at ambient / room temperature, initial_temperature_C (and
sampled_temperature_C) is 25 °C; ambient / atmospheric pressure is initial_pressure_bar 1 -- unless the paper
gives a value for those experiments elsewhere. Marked derived, with one `assumed_default` flag each.

The conditions step is told so (experimental_conditions.json); this is the safety net for answers that still
put the statement among the open-ended `other` conditions (Riggi's 'temperature conditions: ambient temperature
and pressure') or mark it 'assumed'. Runs on the step's answer before anything reads it (pipeline.extract_steps).
"""
from __future__ import annotations
import re
from typing import List, Optional, get_args

AMBIENT_T = re.compile(r"\b(?:ambient|room)[\s-]+temperatures?\b|\br\.\s?t\.|\(RT\)|\bat RT\b", re.IGNORECASE)
AMBIENT_P = re.compile(r"\bambient[\s-]+(?:temperature\s+and\s+)?pressures?\b|\batmospheric[\s-]+pressures?\b"
                       r"|\b(?:ambient|room)\s+conditions\b", re.IGNORECASE)
CONVENTIONS = {   # parameter -> (value, unit, note, what the paper's words must say)
    "initial_temperature_C": (25.0, "°C", "ambient temperature = 25 °C", AMBIENT_T),
    "sampled_temperature_C": (25.0, "°C", "ambient temperature = 25 °C", AMBIENT_T),
    "initial_pressure_bar": (1.0, "bar", "ambient pressure = 1 bar", AMBIENT_P),
}


def _ambient_words(item) -> str:
    return " ".join(str(getattr(item, f, "") or "") for f in ("quote", "note", "text", "value", "name"))


def apply_ambient(spec, result) -> List[str]:
    """Fill ambient temperature / pressure into the stage's answer (in place); one message per convention used."""
    if result is None or not any(p.column in CONVENTIONS for p in spec.parameters):
        return []
    Item, _ = spec.models()
    rows = list(getattr(result, "rows", []))
    items = [v for r in rows for v in r.values] + list(getattr(result, "legacy_parameters", []))
    columns = {p.column for p in spec.parameters}
    used = {}

    # an ambient value the model marked 'assumed' (the old rule) is the convention: derived, written
    for row in rows:
        for v in row.values:
            conv = CONVENTIONS.get(v.parameter)
            if conv and v.basis == "assumed" and conv[3].search(_ambient_words(v)):
                v.basis, v.note = "derived", v.note or conv[2]

    # ambient conditions left among `other`: become the parameters, where the answer has none for those experiments
    given = {(r.set_label, getattr(r, "sample_label", ""), v.parameter) for r in rows for v in r.values}
    given |= {(v.set_label, getattr(v, "sample_label", ""), v.parameter) for v in getattr(result, "legacy_parameters", [])}
    kept_other = []
    for o in list(getattr(result, "other", []) or []):
        words = f"{o.name} {o.value}"
        added = False
        for column, (value, unit, note, pattern) in CONVENTIONS.items():
            if column not in columns or not pattern.search(words):
                continue
            where = (o.set_label or "", getattr(o, "sample_label", "") or "")
            if (*where, column) in given or ("", "", column) in given:
                added = True                         # stated already: the `other` entry is just a repeat
                continue
            row = _row(result, *where)
            row.values.append(Item.model_validate({
                "col": column, "v": value, "u": unit, "b": "derived", "q": o.quote, "src": o.source,
                "c": o.confidence, "n": note}))
            given.add((*where, column))
            added = True
        # an entry that only said 'ambient temperature and pressure' is now in the parameters
        if not (added and re.fullmatch(r"[\w\s,/&-]*", o.value or "")
                and not re.sub(r"(?i)ambient|room|atmospheric|temperatures?|pressures?|conditions|and|[,/&\s-]", "",
                               o.value or "")):
            kept_other.append(o)
    if hasattr(result, "other"):
        result.other = kept_other

    for row in getattr(result, "rows", []):
        for v in row.values:
            conv = CONVENTIONS.get(v.parameter)
            if conv and v.basis != "assumed" and abs(float(v.value) - conv[0]) < 1e-9 and \
                    conv[3].search(_ambient_words(v)):
                used.setdefault(conv[2], (v.quote, set()))[1].add(row.set_label or "every experiment")
    return [f"{note[0].upper() + note[1:]} by convention, where the paper says the experiments ran at ambient conditions "
            f"(\"{quote[:120]}\"; {', '.join(sorted(where))}). Correct it if the paper gives the actual value."
            for note, (quote, where) in used.items()]


def _row(result, set_label: str, sample_label: str):
    """The answer's row for (set, sample), added if missing."""
    for r in result.rows:
        if r.set_label == set_label and getattr(r, "sample_label", "") == sample_label:
            return r
    Row = get_args(type(result).model_fields["rows"].annotation)[0]
    data = {"set": set_label, "values": []}
    if "sample_label" in Row.model_fields:
        data["sample"] = sample_label
    row = Row.model_validate(data)
    result.rows.append(row)
    return row
