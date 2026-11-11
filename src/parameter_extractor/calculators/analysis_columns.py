"""
The analysis step's answer -> columns (Mickey, 2026-11-07): each technique's settings go in
analysis_<technique>_<setting>[_<unit>] (analysis_vocab.py), on the rows of the set the technique was used for
(every row, figure rows included, when it was used throughout). Values are converted to the setting's unit.

A column the pack's vocabulary defines -- or one the user accepted in an earlier review -- is written directly.
Anything else (a technique or setting the vocabulary lacks) becomes a new variable in the review, category
Analysis, with its column already in the format. Nothing is dropped: several values of one setting for the same
rows are kept together ('260; 280'), a value whose unit couldn't be converted is reviewed as text, and each case
is flagged (kind 'analysis', GUI group "Analysis methods").
"""
from __future__ import annotations
from collections import OrderedDict
import re
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

from parameter_extractor import analysis_vocab as av
from parameter_extractor.ingestion.flatten_to_template import set_row_value
from parameter_extractor.schemas.analysis import AnalysisResult
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.schemas.variables import NewVariable

ORIGIN = "analysis"
CATEGORY = "analysis"
_METRES = {"m", "metre", "meter", "metres", "meters"}


def _number(x: float):
    return int(x) if float(x).is_integer() else x


def convert(value: float, printed: str, target: str) -> Tuple[Optional[float], str]:
    """(value in the target unit, note) -- None when the printed unit can't be put in the target's.
    No unit printed: taken as the target's, with a note."""
    from parameter_extractor.units import canonical_unit, convert as convert_units, _tidy
    printed = (printed or "").strip()
    if not printed:
        return value, f"no unit printed; taken as {target}"
    if target == "m":                                 # GC column lengths in metres ('m' alone reads as molar)
        if printed.lower() in _METRES:
            return value, ""
        mm = convert_units(value, canonical_unit(printed) or "", "mm")
        return (None, "") if mm is None else (_tidy(mm / 1000), f"converted from '{value:g} {printed}'")
    unit = canonical_unit(printed)
    if unit == "M" and printed.lower() in _METRES:      # '30 m' of something with a length unit
        unit = None
    if unit is None:
        return None, ""
    out = convert_units(value, unit, target)
    if out is None:
        return None, ""
    return _tidy(out), ("" if unit == target else f"converted from '{value:g} {printed}'")


# one number, optionally followed by its unit, and nothing else
_NUMBER_AS_TEXT = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*([^\d\s;,][^;,]{0,20})?\s*$")


def _value(setting, spec: Optional[av.Setting]):
    """(value, column unit, is_range, note, problem) for one setting."""
    from parameter_extractor.units import canonical_unit, format_range
    from parameter_extractor.value_types import whole_number
    text = (setting.text or "").strip()
    has_number = bool(setting.value) or bool(setting.unit)
    printed = (setting.unit or "").strip()
    if spec is not None and not spec.unit:            # a text (or whole-number) setting
        if spec.integer:
            n = whole_number(text) if text else (int(setting.value) if float(setting.value).is_integer() else None)
            if n is None:
                return (text or f"{setting.value:g}"), "", False, "", "isn't one whole number -- kept as printed"
            return n, "", False, "", ""
        if not text and has_number:
            text = f"{setting.value:g} {printed}".strip()
        return text, "", False, "", ""
    m = _NUMBER_AS_TEXT.match(text) if not has_number and spec is not None and spec.unit else None
    if m:       # a number setting answered in the text field ('200', '0.35 mL/min'; qwen3.8:27b, 2026-11-10)
        setting = SimpleNamespace(value=float(m.group(1).replace(",", ".")), unit=(m.group(2) or "").strip(),
                                  high=0.0)
        has_number, printed = True, setting.unit
    if not has_number:                                # a number setting answered in text, or an unknown text one
        return text, "", False, "", ("given as text" if spec is not None and text else "")
    target = spec.unit if spec is not None else (canonical_unit(printed) or "")
    hi = setting.high if setting.high and setting.high > setting.value else 0.0
    if spec is None and not target:                   # unknown setting, unit not one we convert: keep as printed
        shown = f"{setting.value:g}" + (f"-{hi:g}" if hi else "") + (f" {printed}" if printed else "")
        return shown, "", False, "", ""
    lo, note = convert(setting.value, printed, target)
    if lo is None:
        shown = f"{setting.value:g}" + (f"-{hi:g}" if hi else "") + f" {printed}"
        return shown, "", False, "", f"'{printed}' can't be put in {target}"
    if hi:
        up, _ = convert(hi, printed, target)
        return format_range(lo, up), target, True, note, ""
    return _number(lo), target, False, note, ""


def apply_analysis(rows: List[ExtractedRow], result: Optional[AnalysisResult], registry,
                   rows_for: Callable[[Optional[str], Optional[str]], List[str]], pack=None
                   ) -> Tuple[List[NewVariable], List[Tuple[str, str]]]:
    """Writes the known settings into the rows; returns (new variables for the review, [(flag kind, message)])."""
    if result is None or not result.methods:
        return [], []
    vocab = av.vocabulary(pack)
    by_id = {r.full_id: r for r in rows}
    all_ids = [r.full_id for r in rows]
    # (column, row) -> [(value, CellSource)] so several values of one setting are kept together
    cells: Dict[Tuple[str, str], List[Tuple[object, CellSource]]] = OrderedDict()
    new_vars: List[NewVariable] = []
    flags: List[Tuple[str, str]] = []
    summary: Dict[str, List[str]] = OrderedDict()
    for m in result.methods:
        tech = (vocab.technique(m.technique) or vocab.technique(m.name)) if vocab else None
        tech_name = tech.name if tech else av.token(m.technique or m.name)
        if not tech_name:
            continue
        targets = rows_for(m.set_label or None, m.sample_label or None) if m.set_label else all_ids
        where = f" ({m.set_label}{', ' + m.sample_label if m.sample_label else ''})" if m.set_label else ""
        recorded = summary.setdefault(tech_name + where, [])
        if not tech:
            flags.append(("analysis", f"'{m.name or m.technique}' isn't in the analysis vocabulary: its settings are "
                                      f"offered in the review as {tech_name} columns."))
        for s in m.settings:
            spec = vocab.setting(tech, s.setting) if vocab else None
            name = spec.name if spec else av.token(s.setting)
            if not name:
                continue
            value, unit, is_range, note, problem = _value(s, spec)
            if value in (None, ""):
                continue
            col = av.column(tech_name, name, unit, is_range)   # a number setting that came as text: no unit
            if problem:
                flags.append(("analysis", f"{tech_name} {name} = '{value}': {problem}" +
                              (" -- offered in the review as text." if spec and spec.unit else ".")))
            src = CellSource(origin=ORIGIN, quote=s.quote, source=s.source or m.source, confidence=s.confidence)
            if note:
                src.source = f"{src.source}; {note}" if src.source else note
            known = registry.is_known_column(col) and not (problem and spec and spec.unit)
            recorded.append(name if known else f"{name} (review)")
            if known:
                for rid in targets:
                    cells.setdefault((col, rid), []).append((value, src))
                continue
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            new_vars.append(NewVariable(
                kind="parameter", name=f"{tech_name} {name}", alias_name=f"{tech_name} {name}",
                proposed_column=col, value=value if numeric else None, value_text=None if numeric else str(value),
                unit=unit or None, set_label=m.set_label or None, sample_label=m.sample_label or None,
                quote=s.quote, source=s.source or m.source, confidence=s.confidence, origin=ORIGIN,
                row_ids=list(targets), category=CATEGORY))
    several = OrderedDict()
    for (col, rid), found in cells.items():
        distinct = list(OrderedDict((str(v), (v, src)) for v, src in found).values())
        if len(distinct) == 1:
            value, src = distinct[0]
        else:                                          # two detection wavelengths, two columns used: both kept
            value = "; ".join(str(v) for v, _ in distinct)
            src = distinct[0][1].model_copy(update={"source": "; ".join(s.source for _, s in distinct if s.source)})
            several.setdefault(col, value)
        if rid in by_id:
            set_row_value(by_id[rid], col, value, src)
    for col, value in several.items():
        flags.append(("analysis", f"{col} has several values for the same rows: '{value}' (kept together)."))
    for tech, names in summary.items():
        if names:
            flags.insert(0, ("analysis", f"{tech}: {len(names)} setting{'s' if len(names) != 1 else ''} recorded -- "
                                         f"{', '.join(names)}."))
    return new_vars, flags
