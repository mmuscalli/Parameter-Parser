"""
Values whose variable has no column yet ("new variables"), and what happens to
them.

Sources: species with no known column (chemistry), the methodology step's
open-ended `other_parameters`, the targeted term search, and hand-typed figure
columns (ingestion/figure_rows.py). Each value becomes a NewVariable carrying
the rows it applies to.

  - If the user's local registry already knows the variable (an alias from an
    earlier review), the value is written straight into its column.
  - Otherwise it's pending: shown in the "Review new variables" screen, and
    written only if the user accepts it (as a new column, or into an existing
    one). Values not accepted stay out of the CSV but are kept in
    new_variables.json.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from parameter_extractor.ingestion.flatten_to_template import (
    DETECTED, _from_solute, _solute_value, column_for_solute, column_safe_name, proposed_column_for_solute, set_row_value, species_alias_name)
from parameter_extractor.registry import VariableRegistry, suggest_column_name
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.variables import NewVariable, TermSearch
from parameter_extractor import variable_categories as categories

Action = Literal["ignore", "new_column", "existing_column"]


@dataclass
class VariableGroup:
    """All values of one new variable, as shown in one line of the review screen."""
    kind: str
    name: str
    alias_name: str
    proposed_column: str
    values: List[NewVariable]
    category: str = ""             # variable_categories.py id: the review groups lines by it

    def __post_init__(self):
        self.category = self.category or _kind_category(self.kind)

    @property
    def sources(self) -> Dict[str, int]:
        """Where the line's values come from, in order: {'Table 1': 4, 'Fig. 3': 8}."""
        out: Dict[str, int] = {}
        for v in self.values:
            label = source_label(v)
            out[label] = out.get(label, 0) + 1
        return out

    @property
    def merged(self) -> bool:
        """Values of one compound from a table (or the text) AND a figure, shown as one line (2026-11-04)."""
        return any(v.kind == "figure_axis" for v in self.values) and any(v.kind != "figure_axis" for v in self.values)


_TABLE_IN_SOURCE = re.compile(r"\b(?:SI\s+)?Table\.?\s*(?:S|A|ED)?[IVXLC\d]+\b", re.IGNORECASE)


def source_label(v: NewVariable) -> str:
    """'Fig. 3' for a value read off a figure, the table for a table value ('Table 1'), else 'text'."""
    if v.kind == "figure_axis" or (v.origin or "").startswith("Fig"):
        return v.origin or "figure"
    m = _TABLE_IN_SOURCE.search(v.source or "")
    return re.sub(r"\s+", " ", m.group(0)).replace("Table.", "Table") if m else "text"


@dataclass
class VariableDecision:
    alias_name: str
    kind: str
    action: Action = "ignore"
    column: str = ""
    remember: bool = True          # save to the local registry so later runs don't ask again
    value_type: str = ""           # value_types.TYPES; '' = the column's own (or any)


def row_index(structure: StructurePlan, rows: List[ExtractedRow], paper_prefix: str):
    """(set_label -> row ids, (set_label, sample_label) -> row id, all text/table row ids),
    following build_rows' numbering."""
    by_set: Dict[str, List[str]] = {}
    by_sample: Dict[Tuple[str, str], str] = {}
    for set_idx, pset in enumerate(structure.experiment_sets, start=1):
        set_id = f"{paper_prefix}{set_idx:03d}"
        for sample_idx, sample in enumerate(pset.samples, start=1):
            rid = f"{set_id}{sample_idx:03d}"
            by_set.setdefault(pset.set_label, []).append(rid)
            by_sample[(pset.set_label, sample.sample_label)] = rid
    return by_set, by_sample, [r.full_id for r in rows]


def _rows_for(set_label, sample_label, index) -> List[str]:
    by_set, by_sample, all_ids = index
    if set_label is None:
        return list(all_ids)
    if sample_label is not None and (set_label, sample_label) in by_sample:
        return [by_sample[(set_label, sample_label)]]
    return list(by_set.get(set_label, []))


def collect_new_variables(
    methodology: Methodology, chemistry: ChemistryExtraction,
    registry: Optional[VariableRegistry] = None, index=None,
    term_search: Optional[TermSearch] = None, wet_dry=None, structure=None, optional=None,
) -> List[NewVariable]:
    """Every value without a known column (species) or not yet mapped by the user
    (parameters, search findings). `index` (from row_index) fills row_ids."""
    registry = registry or VariableRegistry(None)
    rows_for = (lambda s, smp: _rows_for(s, smp, index)) if index else (lambda s, smp: [])
    found: List[NewVariable] = []
    for s in chemistry.solutes:
        if column_for_solute(s, registry) is not None:
            continue
        pct = "%" in (s.concentration_unit_raw or "")
        value = _solute_value(s)
        if value in (None, ""):
            continue                 # no amount stated: flagged (concentration_not_stated), nothing to review
        found.append(NewVariable(
            kind="species", name=s.name, alias_name=species_alias_name(s),
            proposed_column=proposed_column_for_solute(s), role=s.role,
            value=value if not isinstance(value, str) else None,
            value_text=value if isinstance(value, str) else None,
            unit=("mM/h" if getattr(s, "measure", "") == "rate" else "%" if pct
                  else "mM" if s.concentration_mM is not None else s.concentration_unit_raw),
            set_label=s.set_label, sample_label=s.sample_label, quote=s.quote, source=_from_solute(s).source,
            confidence=s.confidence, origin="calculated" if s.derived else "chemistry",
            row_ids=rows_for(s.set_label, s.sample_label), pubchem_cid=s.pubchem_cid,
            pubchem_title=s.pubchem_title, pubchem_synonyms=list(getattr(s, "pubchem_synonyms", []) or []),
            **_errors(s),
            # a stock solution's concentration is how the solution was prepared (Mickey, 2026-11-02)
            category=categories.for_source("species", "calculated" if getattr(s, "calculated", False) else
                                            "stock" if s.concentration_basis == "stock" else s.role) or ""))
    for sol in chemistry.added_solutions:
        # the one variable for each solution volume (methodology repeats are dropped,
        # see ingestion/duplicates.py); the mixture calculations use the same records
        name = f"volume added: {sol.solution}"
        found.append(NewVariable(
            kind="parameter", name=name, alias_name=name,
            proposed_column=f"added_{column_safe_name(sol.solution)}_volume_uL", value_text=sol.volume,
            set_label=sol.set_label or None, sample_label=getattr(sol, "sample_label", "") or None, quote=sol.quote,
            source=sol.source, confidence="high", origin="chemistry",
            row_ids=rows_for(sol.set_label or None, getattr(sol, "sample_label", "") or None),
            category=categories.for_source("added_solution") or ""))
    for p in methodology.other_parameters:
        found.append(_categorised(NewVariable(
            kind="parameter", name=p.name, alias_name=p.name,
            proposed_column=suggest_column_name("parameter", p.name), value_text=p.value,
            set_label=p.set_label or None, sample_label=p.sample_label or None, quote=p.quote,
            source=p.source, confidence=p.confidence, origin="methodology",
            row_ids=rows_for(p.set_label or None, p.sample_label or None)), p.category))
    # values the model marked "assumed" (not stated in the paper): never written
    # automatically -- offered in the review, where the user decides
    for o in methodology.per_set_overrides:
        if o.basis == "assumed":
            found.append(_assumed(o.field_name, o.value, o.set_label, o.quote, o.source, o.confidence,
                                  "methodology", rows_for))
    from parameter_extractor.stages.optional import optional_results, stage_values
    for spec, result in optional_results(optional, wet_dry):
        for v in result.parameters:
            if v.basis == "assumed":
                # in the parameter's unit (or its text, for a text parameter), for its sample if it names one
                converted, _ = stage_values(spec, v)
                value = converted[v.parameter].value if v.parameter in converted else v.value
                sample = getattr(v, "sample_label", "") or None
                if v.set_label:
                    found.append(_assumed(v.parameter, value, v.set_label, v.quote, v.source, v.confidence,
                                          spec.origin_label, rows_for, sample))
                    continue
                # paper-wide: ONE review line for the rows of every set the step applies to (kim2017:
                # 'polypropylene' for the Eppendorf tubes was 8 lines and 8 flags, one per set)
                targets = spec.target_sets(structure) if structure else []
                one = _assumed(v.parameter, value, targets[0] if len(targets) == 1 else None, v.quote, v.source,
                               v.confidence, spec.origin_label, rows_for, sample)
                if len(targets) > 1:
                    one.row_ids = [rid for t in targets for rid in rows_for(t, sample)]
                found.append(one)
    for f in (term_search.findings if term_search else []):
        if not f.found:
            continue
        name = f.name or f.term
        known = registry.is_known_column(f.column)
        found.append(_categorised(NewVariable(
            kind="parameter", name=name, alias_name=name,
            proposed_column=f.column if known else suggest_column_name("parameter", name),
            value_text=f.value, set_label=f.set_label or None, quote=f.quote, source=f.source,
            confidence=f.confidence, origin=f"search: {f.term}", row_ids=rows_for(f.set_label or None, None)),
            "", keep_column=known))
    return found


def _printed_range(text):
    """(low, high, canonical unit) for a value printed as a range with a known unit, else None."""
    from parameter_extractor.units import canonical_unit, parse_range
    found = parse_range(text) if text else None
    unit = canonical_unit(found[2]) if found and found[2] else None
    return (found[0], found[1], unit) if unit else None


def _categorised(v: NewVariable, category: str, keep_column: bool = False) -> NewVariable:
    """A parameter's category (the model's choice if it's one the model may assign, else a guess
    from its value) and its value in that category's format: a quantity is parsed into number +
    unit, and the proposed column gets the unit's suffix ('reaction time' -> reaction_time_hr);
    a value that doesn't fit gets a format note. Nothing is dropped or shortened."""
    ids = {c.id for c in categories.assignable()}
    v.category = category if category in ids else categories.guess(v.value_text or "")
    number, unit, v.format_note = categories.check_format(categories.by_id(v.category), v.value_text)
    rng = _printed_range(v.value_text) if number is None else None
    if rng and categories.by_id(v.category) and categories.by_id(v.category).value_type in ("number", "any"):
        # a range ('10-200 s'): kept, as 'low:high' in '<name>_range_<unit>' (Mickey, 2026-10-31)
        from parameter_extractor.ingestion.flatten_to_template import with_range
        v.unit, v.format_note = rng[2], ""
        suffix = categories.unit_suffix(rng[2])
        if v.proposed_column and not keep_column:
            base = v.proposed_column
            if suffix and not base.endswith(suffix):
                base += suffix
            v.proposed_column = with_range(base)
        return v
    if number is not None:
        v.value, v.unit = number, unit
        suffix = categories.unit_suffix(unit)
        if suffix and not keep_column and v.proposed_column and not v.proposed_column.endswith(suffix):
            v.proposed_column += suffix
    if v.proposed_column and not keep_column and v.kind == "parameter":
        # the app's naming conventions, as for drafted and suggested parameters (conventions.py): 'final pH' ->
        # sampled_pH, 'reaction temperature' -> initial_temperature_C (then an existing column, accepted directly)
        from parameter_extractor.conventions import canonical
        numeric = v.value is not None or bool(re.search(r"\d", v.value_text or ""))       # '8.5' for a pH: a number
        conv = canonical(v.proposed_column, v.unit or "", "number" if numeric else "text", v.value_text or "")
        if conv is not None and conv.column:          # (a row column like duration_hr: left as proposed, reviewed)
            v.proposed_column = conv.column
    return v


def _assumed(column, value, set_label, quote, source, confidence, origin, rows_for,
             sample_label=None) -> NewVariable:
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    return NewVariable(
        kind="assumed_value", category=categories.ASSUMED.id, name=column,
        alias_name=f"{column} @ {sample_label or set_label or 'whole paper'}",
        proposed_column=column, value=value if numeric else None, value_text=None if numeric else str(value),
        set_label=set_label, sample_label=sample_label, quote=quote, source=source, confidence=confidence,
        origin=f"{origin} (assumed)", row_ids=rows_for(set_label, sample_label))


def split_known(new_vars: List[NewVariable], registry: VariableRegistry):
    """(already mapped by the registry -> [(column, value)], still pending).
    Only explicit aliases count here: a parameter isn't written to a column
    just because the model suggested one -- the user decides that once."""
    known, pending = [], []
    for v in new_vars:
        column = None if v.kind == "assumed_value" else registry.alias_for(v.kind, v.alias_name or v.name)
        if column:
            known.append((column, v))
        else:
            pending.append(v)
    return known, pending


def group_new_variables(new_vars: List[NewVariable]) -> List[VariableGroup]:
    """One group per variable (kind + alias name), sorted by category (the pack's order), first-seen
    order within one."""
    groups: Dict[Tuple[str, str], VariableGroup] = {}
    from parameter_extractor.ingestion.flatten_to_template import without_range
    for v in new_vars:
        alias = v.alias_name or v.name
        if v.proposed_column and without_range(v.proposed_column) != v.proposed_column and not alias.endswith(" range"):
            alias += " range"            # a range ('6-13 nt') gets its own '_range_' column, not the single values'
        key = (v.kind, alias)
        if key not in groups:
            groups[key] = VariableGroup(kind=v.kind, name=v.name, alias_name=key[1],
                                        proposed_column=v.proposed_column or "", values=[],
                                        category=v.category)
        groups[key].values.append(v)
    for g in groups.values():
        g.values = _without_repeated_calculations(g.values)
    _merge_figure_axes_into_compounds(groups)
    order = {c.id: i for i, c in enumerate(categories.categories())}
    return sorted(groups.values(), key=lambda g: order.get(g.category, len(order)))


def _merge_figure_axes_into_compounds(groups: Dict[Tuple[str, str], "VariableGroup"]) -> None:
    """A compound read off a figure axis and the same compound from a table / the text propose ONE column
    (flatten_to_template.canonical_compound_column): their values go on one review line, decided together
    (Mickey, 2026-11-04 -- accepting one and rejecting the other left the column half filled in this paper and
    filled automatically in later ones)."""
    by_column = {}
    for key, g in groups.items():
        if g.kind == "species" and action_is_species_column(g.proposed_column):
            by_column.setdefault(g.proposed_column, key)
    for key in [k for k, g in groups.items() if g.kind == "figure_axis"]:
        target = by_column.get(groups[key].proposed_column)
        if target is not None:
            groups[target].values += groups.pop(key).values


def _without_repeated_calculations(values: List[NewVariable]) -> List[NewVariable]:
    """A calculated value (a mixture concentration from a stock) is left out where the paper states the same
    value for the same rows (Riggi2023: ImpA 15 mM stated on the digitized series, and 15 mM calculated from
    its 15 mM stock) -- one value, the paper's (Mickey, 2026-11-02)."""
    stated = [v for v in values if v.origin != "calculated" and v.value is not None]

    def repeated(v: NewVariable) -> bool:
        if v.origin != "calculated" or v.value is None or not v.row_ids:
            return False
        same = [s for s in stated if abs(s.value - v.value) <= 0.01 * max(abs(v.value), 1e-12)]
        return set(v.row_ids) <= {r for s in same for r in s.row_ids}
    kept = [v for v in values if not repeated(v)]
    return kept or values


def _kind_category(kind: str) -> str:
    """For values collected without a category (figure columns, older records)."""
    return {"figure_axis": categories.FIGURE.id, "assumed_value": categories.ASSUMED.id}.get(kind, "") \
        or categories.for_source(kind) or ""


def stored_value(v: NewVariable, column: str, value_type: str = ""):
    """(value as it will be written into `column`, note). Converted to the column's
    unit when the column has one ("1 cm3" -> 1 for a _mL column, "45 min" -> 0.75 for
    _hr); left as-is with note 'not converted' when that can't be done safely. With a data type
    (value_types.py), the value is also converted to it ('triplicate' -> 3 for a whole number); one that
    can't be is not stored (note 'not stored: ...')."""
    value, note = _in_column_unit(v, column)
    # a value that couldn't be put in the column's unit is written as text and flagged, as before
    is_range = isinstance(value, str) and re.fullmatch(r"[-\d.eE+]+:[-\d.eE+]+", value)   # 'low:high', a range column
    if value_type and value_type != "any" and value not in (None, "") and not note.startswith("not converted") \
            and not (is_range and value_type == "number"):
        from parameter_extractor.value_types import TYPES, coerce
        typed, problem = coerce(value, value_type)
        if problem:
            return value, f"not stored: {column} holds {TYPES[value_type].lower()}s -- {problem}"
        if typed != value and not note:
            note = f"read from '{_shown(value)}'" if isinstance(value, str) else ""
        return typed, note
    return value, note


def _shown(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _in_column_unit(v: NewVariable, column: str):
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import to_column_unit
    raw = v.value if v.value is not None else v.value_text
    if v.value is not None and v.unit and v.value_text:
        raw = v.value_text                   # parsed from the printed text: convert that (the note says so)
    column_unit = unit_for_column(column)
    if not column_unit and v.value is not None and v.unit and v.value_text:
        return v.value_text, ""              # a column with no unit keeps the unit with the value
    if raw in (None, "", DETECTED) or not column_unit or column_unit == "pH":
        return raw, ""                       # 'detected' is meant as text
    if isinstance(raw, (int, float)) and v.unit == column_unit:
        return raw, ""                       # already in the column's unit (the analysis step converts its own)
    rng = _printed_range(v.value_text) if v.value is None else None
    formatted = re.fullmatch(r"([-\d.eE+]+):([-\d.eE+]+)", str(raw)) if v.value is None else None
    if formatted and not rng:            # already 'low:high' (the chemistry step's ranges: % / ratio as printed)
        rng = (float(formatted.group(1)), float(formatted.group(2)), v.unit or column_unit)
    if rng:                              # a range: 'low:high' in the column's unit
        from parameter_extractor.units import range_to_column_unit
        converted = range_to_column_unit(rng[0], rng[1], rng[2], column_unit)
        return (converted if converted else (v.value_text, f"not converted to {column_unit}"))
    from parameter_extractor.units import is_difference
    conversion = to_column_unit(raw, v.unit, column_unit, difference=is_difference(column) or is_difference(v.name))
    if conversion is None:
        return raw, f"not converted to {column_unit}"
    return conversion.value, conversion.note


def _errors(s) -> dict:
    """A species value's uncertainty in the unit of the value offered for review (mM, or % as printed)."""
    from parameter_extractor.ingestion.flatten_to_template import error_cells
    cells = error_cells(s, "x")
    return {"err_plus": cells.get("x_err_plus", 0.0), "err_minus": cells.get("x_err_minus", 0.0)}


def write_values(rows: List[ExtractedRow], column: str, values: List[NewVariable],
                 value_type: str = "") -> Tuple[int, List[str]]:
    """Write each value into `column` (converted to its unit, and to its data type when it has one) on the
    rows it applies to. Returns (cells written, problems: values that couldn't be converted)."""
    by_id = {r.full_id: r for r in rows}
    n, problems = 0, []
    for v in values:
        value, note = stored_value(v, column, value_type)
        if value in (None, ""):
            continue
        if note.startswith("not stored"):
            problems.append(f"'{v.name}' value '{_shown(value)}' left out of {column}: {note[len('not stored: '):]}.")
            continue
        if note.startswith("not converted"):
            problems.append(f"'{v.name}' value '{value}' was written to {column} as text: {note}.")
        source = CellSource(origin=f"{v.origin} (new variable '{v.name}')", quote=v.quote or "",
                            source=(v.source or "") + (f" [{note}]" if note else ""), confidence=v.confidence)
        errors = {}
        if (v.err_plus or v.err_minus) and isinstance(value, (int, float)) and isinstance(v.value, (int, float)) \
                and v.value:                     # the uncertainty, converted like the value (2026-11-03)
            factor = value / v.value
            from parameter_extractor.units import _tidy
            errors = {column + suffix: _tidy(e * factor) for suffix, e in (("_err_plus", v.err_plus),
                                                                          ("_err_minus", v.err_minus)) if e}
        for rid in v.row_ids:
            if rid in by_id:
                set_row_value(by_id[rid], column, value, source)
                for col, e in errors.items():
                    set_row_value(by_id[rid], col, e, source)
                n += 1
    return n, problems


def action_is_species_column(column: str) -> bool:
    """A starting / measured / stock species column (its compound can get an active name)."""
    return bool(re.match(r"(initial|sampled|stock|calculated)_", column or ""))


def apply_decisions(rows: List[ExtractedRow], groups: List[VariableGroup],
                    decisions: List[VariableDecision], registry: VariableRegistry) -> List[VariableGroup]:
    """Write accepted variables into the rows and remember them in the registry.
    Returns the groups left out (not accepted)."""
    by_key = {(d.kind, d.alias_name): d for d in decisions}
    left_out = []
    apply_decisions.problems = []
    for g in groups:
        d = by_key.get((g.kind, g.alias_name))
        if d is None or d.action == "ignore" or not d.column.strip() or not any(v.include for v in g.values):
            left_out.append(g)                # (every value unticked: as good as not added)
            continue
        column = d.column.strip()
        from parameter_extractor.value_types import column_type
        value_type = d.value_type or column_type(column, registry)
        excluded = [v for v in g.values if not v.include]
        if excluded:                         # values unticked in the review: kept as left out (new_variables.json)
            left_out.append(VariableGroup(kind=g.kind, name=g.name, alias_name=g.alias_name,
                                          proposed_column=g.proposed_column, values=excluded, category=g.category))
        _, problems = write_values(rows, column, [v for v in g.values if v.include], value_type)
        apply_decisions.problems += problems
        if d.remember and g.kind != "assumed_value":     # a guess is decided per paper, never remembered
            if d.action == "new_column":
                registry.add_column(column, g.kind, note=f"accepted for '{g.name}'", category=g.category,
                                    value_type=d.value_type)
            elif d.value_type:
                registry.set_column_type(column, d.value_type)      # only the columns the user added
            registry.add_alias(g.kind, g.alias_name, column)
            cid = next((v.pubchem_cid for v in g.values if v.pubchem_cid), 0)
            if g.kind == "species" and cid:
                registry.remember_species_id(cid, g.name)
            if g.kind == "species" and action_is_species_column(column):
                synonyms = next((v.pubchem_synonyms for v in g.values if v.pubchem_synonyms), [])
                registry.remember_compound(g.name, cid, synonyms)
    return left_out
