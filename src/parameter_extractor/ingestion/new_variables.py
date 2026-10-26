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


@dataclass
class VariableDecision:
    alias_name: str
    kind: str
    action: Action = "ignore"
    column: str = ""
    remember: bool = True          # save to the local registry so later runs don't ask again


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
        found.append(NewVariable(
            kind="species", name=s.name, alias_name=species_alias_name(s),
            proposed_column=proposed_column_for_solute(s), role=s.role,
            value=value if not isinstance(value, str) else None,
            value_text=value if isinstance(value, str) else None,
            unit="%" if pct else ("mM" if s.concentration_mM is not None else s.concentration_unit_raw),
            set_label=s.set_label, sample_label=s.sample_label, quote=s.quote, source=_from_solute(s).source,
            confidence=s.confidence, origin="calculated" if s.derived else "chemistry",
            row_ids=rows_for(s.set_label, s.sample_label), pubchem_cid=s.pubchem_cid,
            pubchem_title=s.pubchem_title, category=categories.for_source("species", s.role) or ""))
    for sol in chemistry.added_solutions:
        # the one variable for each solution volume (methodology repeats are dropped,
        # see ingestion/duplicates.py); the mixture calculations use the same records
        name = f"volume added: {sol.solution}"
        found.append(NewVariable(
            kind="parameter", name=name, alias_name=name,
            proposed_column=f"added_{column_safe_name(sol.solution)}_volume_uL", value_text=sol.volume,
            set_label=sol.set_label or None, quote=sol.quote, source=sol.source, confidence="high",
            origin="chemistry", row_ids=rows_for(sol.set_label or None, None),
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
        targets = spec.target_sets(structure) if structure else []
        for v in result.parameters:
            if v.basis == "assumed":
                # in the parameter's unit (or its text, for a text parameter), for its sample if it names one
                converted, _ = stage_values(spec, v)
                value = converted[v.parameter].value if v.parameter in converted else v.value
                sample = getattr(v, "sample_label", "") or None
                for label in ([v.set_label] if v.set_label else targets):
                    found.append(_assumed(v.parameter, value, label, v.quote, v.source, v.confidence,
                                          spec.origin_label, rows_for, sample))
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


def _categorised(v: NewVariable, category: str, keep_column: bool = False) -> NewVariable:
    """A parameter's category (the model's choice if it's one the model may assign, else a guess
    from its value) and its value in that category's format: a quantity is parsed into number +
    unit, and the proposed column gets the unit's suffix ('reaction time' -> reaction_time_hr);
    a value that doesn't fit gets a format note. Nothing is dropped or shortened."""
    ids = {c.id for c in categories.assignable()}
    v.category = category if category in ids else categories.guess(v.value_text or "")
    number, unit, v.format_note = categories.check_format(categories.by_id(v.category), v.value_text)
    if number is not None:
        v.value, v.unit = number, unit
        suffix = categories.unit_suffix(unit)
        if suffix and not keep_column and v.proposed_column and not v.proposed_column.endswith(suffix):
            v.proposed_column += suffix
    return v


def _assumed(column, value, set_label, quote, source, confidence, origin, rows_for,
             sample_label=None) -> NewVariable:
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    return NewVariable(
        kind="assumed_value", category=categories.ASSUMED.id, name=column,
        alias_name=f"{column} @ {sample_label or set_label}",
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
    for v in new_vars:
        key = (v.kind, v.alias_name or v.name)
        if key not in groups:
            groups[key] = VariableGroup(kind=v.kind, name=v.name, alias_name=key[1],
                                        proposed_column=v.proposed_column or "", values=[],
                                        category=v.category)
        groups[key].values.append(v)
    order = {c.id: i for i, c in enumerate(categories.categories())}
    return sorted(groups.values(), key=lambda g: order.get(g.category, len(order)))


def _kind_category(kind: str) -> str:
    """For values collected without a category (figure columns, older records)."""
    return {"figure_axis": categories.FIGURE.id, "assumed_value": categories.ASSUMED.id}.get(kind, "") \
        or categories.for_source(kind) or ""


def stored_value(v: NewVariable, column: str):
    """(value as it will be written into `column`, note). Converted to the column's
    unit when the column has one ("1 cm3" -> 1 for a _mL column, "45 min" -> 0.75 for
    _hr); left as-is with note 'not converted' when that can't be done safely."""
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
    conversion = to_column_unit(raw, v.unit, column_unit)
    if conversion is None:
        return raw, f"not converted to {column_unit}"
    return conversion.value, conversion.note


def write_values(rows: List[ExtractedRow], column: str, values: List[NewVariable]) -> Tuple[int, List[str]]:
    """Write each value into `column` (converted to its unit) on the rows it applies
    to. Returns (cells written, problems: values that couldn't be converted)."""
    by_id = {r.full_id: r for r in rows}
    n, problems = 0, []
    for v in values:
        value, note = stored_value(v, column)
        if value in (None, ""):
            continue
        if note.startswith("not converted"):
            problems.append(f"'{v.name}' value '{value}' was written to {column} as text: {note}.")
        source = CellSource(origin=f"{v.origin} (new variable '{v.name}')", quote=v.quote or "",
                            source=(v.source or "") + (f" [{note}]" if note else ""), confidence=v.confidence)
        for rid in v.row_ids:
            if rid in by_id:
                set_row_value(by_id[rid], column, value, source)
                n += 1
    return n, problems


def apply_decisions(rows: List[ExtractedRow], groups: List[VariableGroup],
                    decisions: List[VariableDecision], registry: VariableRegistry) -> List[VariableGroup]:
    """Write accepted variables into the rows and remember them in the registry.
    Returns the groups left out (not accepted)."""
    by_key = {(d.kind, d.alias_name): d for d in decisions}
    left_out = []
    apply_decisions.problems = []
    for g in groups:
        d = by_key.get((g.kind, g.alias_name))
        if d is None or d.action == "ignore" or not d.column.strip():
            left_out.append(g)
            continue
        column = d.column.strip()
        _, problems = write_values(rows, column, g.values)
        apply_decisions.problems += problems
        if d.remember and g.kind != "assumed_value":     # a guess is decided per paper, never remembered
            if d.action == "new_column":
                registry.add_column(column, g.kind, note=f"accepted for '{g.name}'")
            registry.add_alias(g.kind, g.alias_name, column)
            cid = next((v.pubchem_cid for v in g.values if v.pubchem_cid), 0)
            if g.kind == "species" and cid:
                registry.remember_species_id(cid, g.name)
    return left_out
