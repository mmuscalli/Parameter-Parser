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
    _solute_value, column_for_solute, proposed_column_for_solute, set_row_value, species_alias_name)
from parameter_extractor.registry import VariableRegistry, suggest_column_name
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.variables import NewVariable, TermSearch

Action = Literal["ignore", "new_column", "existing_column"]


@dataclass
class VariableGroup:
    """All values of one new variable, as shown in one line of the review screen."""
    kind: str
    name: str
    alias_name: str
    proposed_column: str
    values: List[NewVariable]


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
    term_search: Optional[TermSearch] = None,
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
        found.append(NewVariable(
            kind="species", name=s.name, alias_name=species_alias_name(s),
            proposed_column=proposed_column_for_solute(s), role=s.role, value=_solute_value(s),
            unit="%" if pct else ("mM" if s.concentration_mM is not None else s.concentration_unit_raw),
            set_label=s.set_label, sample_label=s.sample_label, quote=s.quote, source=s.source,
            confidence=s.confidence, origin="chemistry", row_ids=rows_for(s.set_label, s.sample_label)))
    for p in methodology.other_parameters:
        found.append(NewVariable(
            kind="parameter", name=p.name, alias_name=p.name,
            proposed_column=suggest_column_name("parameter", p.name), value_text=p.value,
            set_label=p.set_label or None, quote=p.quote, source=p.source, confidence=p.confidence,
            origin="methodology", row_ids=rows_for(p.set_label or None, None)))
    for f in (term_search.findings if term_search else []):
        if not f.found:
            continue
        name = f.name or f.term
        found.append(NewVariable(
            kind="parameter", name=name, alias_name=name,
            proposed_column=f.column if registry.is_known_column(f.column) else suggest_column_name("parameter", name),
            value_text=f.value, set_label=f.set_label or None, quote=f.quote, source=f.source,
            confidence=f.confidence, origin=f"search: {f.term}", row_ids=rows_for(f.set_label or None, None)))
    return found


def split_known(new_vars: List[NewVariable], registry: VariableRegistry):
    """(already mapped by the registry -> [(column, value)], still pending).
    Only explicit aliases count here: a parameter isn't written to a column
    just because the model suggested one -- the user decides that once."""
    known, pending = [], []
    for v in new_vars:
        column = registry.alias_for(v.kind, v.alias_name or v.name)
        if column:
            known.append((column, v))
        else:
            pending.append(v)
    return known, pending


def group_new_variables(new_vars: List[NewVariable]) -> List[VariableGroup]:
    """One group per variable (kind + alias name), in first-seen order."""
    groups: Dict[Tuple[str, str], VariableGroup] = {}
    for v in new_vars:
        key = (v.kind, v.alias_name or v.name)
        if key not in groups:
            groups[key] = VariableGroup(kind=v.kind, name=v.name, alias_name=key[1],
                                        proposed_column=v.proposed_column or "", values=[])
        groups[key].values.append(v)
    return list(groups.values())


def write_values(rows: List[ExtractedRow], column: str, values: List[NewVariable]) -> int:
    """Write each value into `column` on the rows it applies to. Returns cells written."""
    by_id = {r.full_id: r for r in rows}
    n = 0
    for v in values:
        value = v.value if v.value is not None else v.value_text
        if value in (None, ""):
            continue
        source = CellSource(origin=f"{v.origin} (new variable '{v.name}')", quote=v.quote or "",
                            source=v.source or "", confidence=v.confidence)
        for rid in v.row_ids:
            if rid in by_id:
                set_row_value(by_id[rid], column, value, source)
                n += 1
    return n


def apply_decisions(rows: List[ExtractedRow], groups: List[VariableGroup],
                    decisions: List[VariableDecision], registry: VariableRegistry) -> List[VariableGroup]:
    """Write accepted variables into the rows and remember them in the registry.
    Returns the groups left out (not accepted)."""
    by_key = {(d.kind, d.alias_name): d for d in decisions}
    left_out = []
    for g in groups:
        d = by_key.get((g.kind, g.alias_name))
        if d is None or d.action == "ignore" or not d.column.strip():
            left_out.append(g)
            continue
        column = d.column.strip()
        write_values(rows, column, g.values)
        if d.remember:
            if d.action == "new_column":
                registry.add_column(column, g.kind, note=f"accepted for '{g.name}'")
            registry.add_alias(g.kind, g.alias_name, column)
    return left_out
