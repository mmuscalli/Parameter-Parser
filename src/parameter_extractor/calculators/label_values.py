"""
What a row's own label states (Mickey, 2026-11-12: Cleaves2008's '150 C, 20 min' row had 100 C; replaces a
temperature-only check -- one rule for every quantity a label gives, not one per parameter).

The row plan names each set and row ('0.1 M glycine, 20 min, 2400 psi'; '150 C, 20 min'; 't = 15 min';
'[Gly]0 = 3e-4 M'). Local, no model:
- `label_quantities(label)`: the quantities in a label, read with the app's unit table (units.py), each with its kind
  (dimension: temperature, time, pressure, concentration, ..., or pH) and, for a concentration, the compound it names
  ('0.1 M glycine', '[Gly]0 = 3e-4 M'). Other words after a quantity ('24 h wet-dry cycles') may change what it is:
  skipped. A kind given twice in one label ('25/300 C', two temperatures) is skipped --
  ambiguous.
- A row's quantities come from its sample label, then its set label for kinds the sample label doesn't give.
- `fill_from_labels` (before the fill-in rules): a kind none of the row's columns holds is written into the column the
  data pack names for it (pack.json `label_columns`, e.g. {"temperature": "initial_temperature_C", "time":
  "duration_hr"}), converted to that column's unit -- the explicit statement first. Concentrations go only to the
  named compound's existing starting-concentration column.
- The columns a quantity is compared with: the pack's label column for its kind and the columns column_pairs relate
  to it (not a quench temperature or an analysis setting); a pack without label_columns: every column of the kind.
- `label_mismatches` (after everything): a row whose columns of a kind all disagree with its label (2%, or 0.5 in the
  column's unit) -- one conflicting_values flag per set, whatever filled the value.
Rows not in the row plan (digitized figure rows) have no plan label and are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource
from parameter_extractor.validation.plausibility_checks import Flag

TOLERANCE = 0.02            # labels round ('2400 psi' = 165.47 bar, the row may say 165)


@dataclass
class LabelQuantity:
    kind: str               # a units.py dimension, or "pH"
    text: str               # as written in the label ('20 min')
    value: float            # in `unit`
    unit: str               # canonical unit ('min'); 'pH' for pH
    name: str = ""          # the compound a concentration names


def _segments(label: str) -> List[str]:
    return [s.strip() for s in re.split(r"[,;()]", label or "") if s.strip()]


def label_quantities(label: str) -> List[LabelQuantity]:
    """The quantities a row label states (module text)."""
    from parameter_extractor.units import dimension_of, parse_quantity
    found: List[LabelQuantity] = []
    for seg in _segments(label):
        m = re.fullmatch(r"pH\s*=?\s*(\d+(?:\.\d+)?)", seg, re.IGNORECASE)
        if m:
            found.append(LabelQuantity("pH", seg, float(m.group(1)), "pH"))
            continue
        name, text = "", seg
        m = re.fullmatch(r"(.+?)\s*=\s*(.+)", seg)                  # 't = 15 min', '[Gly]0 = 3e-4 M'
        if m:
            name, text = m.group(1).strip(), m.group(2).strip()
        q, tail = parse_quantity(text), False
        if q is None:                                               # '0.1 M glycine': quantity, then a name
            words = text.split()
            # a tail with another number is a list ('100 °C and 200 °C'), not a name: skipped
            for k in range(min(4, len(words) - 1), 0, -1):
                if any(re.search(r"\d", w) for w in words[k:]):
                    break
                q = parse_quantity(" ".join(words[:k]))
                if q is not None:
                    name, text, tail = " ".join(words[k:]), " ".join(words[:k]), True
                    break
        if q is None:
            continue
        kind = dimension_of(q[1])
        # words after a quantity can change what it is ('24 h wet-dry cycles': one cycle, not the duration): kept
        # only for a concentration they name the compound of
        if tail and not (kind == "concentration" and _compound(name)):
            continue
        if kind:
            found.append(LabelQuantity(kind, text, q[0], q[1], _compound(name) if kind == "concentration" else ""))
    counts: Dict[str, int] = {}
    for lq in found:
        counts[lq.kind] = counts.get(lq.kind, 0) + 1
    # one kind twice: ambiguous -- except concentrations of different compounds
    return [lq for lq in found if counts[lq.kind] == 1 or (lq.kind == "concentration" and lq.name)]


def _compound(name: str) -> str:
    """The compound a label names ('glycine', '[Gly]0', 'Gly') as the app's name ('Gly'); '' if none."""
    from parameter_extractor.names import match_species
    name = re.sub(r"^\[(.+?)\]\s*0?$", r"\1", (name or "").strip())   # '[Gly]0' -> 'Gly'
    hit = match_species(name) if name else None
    return hit[0] if hit else ""


def _row_labels(row, structure) -> Tuple[str, str]:
    """(sample label, set label) of a row from the row plan; ('', '') when the row isn't in it."""
    plan = structure.experiment_sets if structure is not None else []
    n, k = row.set_id[-3:], row.sample_id
    if not (n.isdigit() and k.isdigit()) or not 0 < int(n) <= len(plan):
        return "", ""
    s = plan[int(n) - 1]
    sample = s.samples[int(k) - 1].sample_label if 0 < int(k) <= len(s.samples) else ""
    return sample or "", s.set_label or ""


def _row_quantities(row, structure) -> List[Tuple[LabelQuantity, str]]:
    """(quantity, the label it's from): the sample label's, then the set label's for kinds the sample label lacks."""
    sample, set_label = _row_labels(row, structure)
    own = label_quantities(sample)
    kinds = {(q.kind, q.name) for q in own}
    return [(q, sample) for q in own] + [(q, set_label) for q in label_quantities(set_label)
                                         if (q.kind, q.name) not in kinds]


def _condition_columns(label_columns: Optional[dict], pairs) -> Dict[str, set]:
    """Per kind, the columns a label's quantity describes: the pack's label column and the columns paired with it
    (column_pairs: sampled_temperature_C with initial_temperature_C) -- not every column of that kind (a quench
    temperature, an analysis setting)."""
    out: Dict[str, set] = {}
    for kind, column in (label_columns or {}).items():
        group = {column}
        for pair in pairs or ():
            if column in pair:
                group |= set(pair)
        out[kind] = group
    return out


def _columns_of(record: dict, q: LabelQuantity, conditions: Optional[Dict[str, set]] = None) -> List[str]:
    """The row's columns that hold this kind of quantity: the pack's condition columns for it when it names them,
    else every column of the kind (a concentration: its compound's starting columns)."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import dimension_of
    if q.kind == "concentration":
        return [c for c in record
                if q.name and re.match(rf"^(?:initial|stock)_{re.escape(q.name)}_(?:aq|gas|s)_mM$", c)]
    if conditions and q.kind in conditions:
        return [c for c in record if c in conditions[q.kind]]
    out = []
    for column in record:
        if column.startswith("analysis_") or \
                re.search(r"_(?:err_plus|err_minus|range|alt\d|mode\d|prior\w*|log10|ln)(?:_|$)", column):
            continue
        unit = unit_for_column(column)
        if (q.kind == "pH" and unit == "pH") or (q.kind != "pH" and unit and dimension_of(unit) == q.kind):
            out.append(column)
    return out


def _in_column_unit(q: LabelQuantity, column: str) -> Optional[float]:
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import to_column_unit
    if q.kind == "pH":
        return q.value
    conv = to_column_unit(q.text, None, unit_for_column(column))
    return conv.value if conv is not None else None


def _agrees(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE * max(abs(a), abs(b)), 0.5 if max(abs(a), abs(b)) >= 10 else 0.0) or a == b


def _number(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fill_from_labels(rows, structure, label_columns: Optional[dict], pairs=()) -> List[Flag]:
    """Write each label quantity no column of its row holds into the pack's column for its kind (module text)."""
    if not label_columns:
        return []
    conditions = _condition_columns(label_columns, pairs)
    filled: Dict[str, list] = {}
    for r in rows:
        record = row_to_template_dict(r)
        for q, label in _row_quantities(r, structure):
            target = label_columns.get(q.kind) if q.kind != "concentration" else None
            if not target or any(_number(record.get(c)) is not None for c in _columns_of(record, q, conditions)):
                continue
            value = _in_column_unit(q, target)
            if value is None:
                continue
            set_row_value(r, target, round(value, 6), CellSource(
                origin="row label", source=f"the row plan's label '{label}'", confidence="medium"))
            record[target] = value
            filled.setdefault(r.set_id, []).append((r.full_id, target, q.text))
    return [Flag("derived_value",
                 f"{len(items)} value(s) taken from the rows' own labels in the row plan (set {sid}): "
                 + "; ".join(f"{fid} {col} = {text}" for fid, col, text in items[:8])
                 + (" ..." if len(items) > 8 else "") + ".")
            for sid, items in filled.items()]


def label_mismatches(rows, structure, label_columns: Optional[dict] = None, pairs=()) -> List[Flag]:
    """A row whose columns of a kind all disagree with what its label states -- one flag per set."""
    conditions = _condition_columns(label_columns, pairs)
    wrong: Dict[str, list] = {}
    for r in rows:
        record = row_to_template_dict(r)
        for q, label in _row_quantities(r, structure):
            values = [(c, _number(record.get(c))) for c in _columns_of(record, q, conditions)]
            values = [(c, v) for c, v in values if v is not None]
            if not values:
                continue
            expected = {c: _in_column_unit(q, c) for c, _v in values}
            if any(expected[c] is not None and _agrees(v, expected[c]) for c, v in values):
                continue
            if all(expected[c] is None for c, _v in values):
                continue
            c, v = values[0]
            wrong.setdefault(r.set_id, []).append((r.full_id, label, q.text, c, v))
    return [Flag("conflicting_values",
                 f"Values that differ from their rows' own labels in the row plan (set {sid}): "
                 + "; ".join(f"{fid} '{label}' says {text}, but {col} = {v:g}" for fid, label, text, col, v in
                             items[:8])
                 + (" ..." if len(items) > 8 else "") + ". Check them against the paper.")
            for sid, items in wrong.items()]
