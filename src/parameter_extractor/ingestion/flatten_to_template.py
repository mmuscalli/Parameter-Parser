"""
Combine StructurePlan + Methodology + ChemistryExtraction (+ calculators) into
one ExtractedRow per planned sample, and flatten a list of ExtractedRow into
the wide, PaperDataTemplate-shaped CSV your existing pipeline expects -- with
the template's own column names (e.g. paper_DOI, author1..7,
sampled_2peptide_Gly_%yield) and column order.

This is the one place that's allowed to know about the wide template's column
names -- every stage upstream of this deliberately stays schema-narrow.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import List, Optional

from parameter_extractor.config import settings
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.common import CONFIDENCE_ORDER, confidence_below
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.calculators.peptide_yield import peptide_mM_from_yield_pct

_VOCAB_PATH = Path(__file__).resolve().parent.parent / "schemas" / "template_vocab.json"
_TEMPLATE_COLUMNS_ORDERED = json.loads(_VOCAB_PATH.read_text())["all_columns"] if _VOCAB_PATH.exists() else []
_TEMPLATE_COLUMNS = set(_TEMPLATE_COLUMNS_ORDERED)


UNRECOGNIZED_SUFFIX = "__UNRECOGNIZED_COLUMN"


def resolve_template_column(species_name: str, role: str) -> str:
    """
    The real template is NOT uniform: salts/ions use '<role>_<name>_aq_mM'
    (e.g. initial_NaCl_aq_mM) while amino acids/peptides use '<role>_<name>_mM'
    with no '_aq_' infix (e.g. initial_Gly_mM, sampled_2peptide_Gly_mM) --
    confirmed against PaperDataTemplate.xlsx's own headers, not guessed. Try
    the real column name patterns in order; if neither exists yet, fall back
    to the _aq_mM form and mark it so a human can decide whether it's a new
    column or a naming mismatch, rather than silently writing a column the
    template will never recognize.
    """
    aq_form = f"{role}_{species_name}_aq_mM"
    plain_form = f"{role}_{species_name}_mM"
    if aq_form in _TEMPLATE_COLUMNS:
        return aq_form
    if plain_form in _TEMPLATE_COLUMNS:
        return plain_form
    return f"{aq_form}{UNRECOGNIZED_SUFFIX}"


def is_percent(entry) -> bool:
    return "%" in (entry.concentration_unit_raw or "")


_BASE_REGISTRY = None


def base_registry():
    """Template columns only (no local additions)."""
    global _BASE_REGISTRY
    if _BASE_REGISTRY is None:
        from parameter_extractor.registry import VariableRegistry
        _BASE_REGISTRY = VariableRegistry(None)
    return _BASE_REGISTRY


def species_alias_name(entry) -> str:
    """How the registry remembers a species value: role and % vs concentration
    matter ("initial RbCl" and "sampled RbCl %" are different variables)."""
    return f"{entry.role} {entry.name}" + (" %" if entry.role == "sampled" and is_percent(entry) else "")


def column_for_solute(entry, registry=None) -> Optional[str]:
    """The column an extracted value belongs in -- a template column, or one the
    user accepted earlier (local registry: column or alias) -- or None, making
    it a new variable that stays out of the CSV until the user accepts it (see
    ingestion/new_variables.py). Percent yields go to sampled_<name>_%yield."""
    registry = registry or base_registry()
    alias = registry.column_for("species", species_alias_name(entry))
    if alias:
        return alias
    if entry.role == "sampled" and is_percent(entry):
        candidates = (f"sampled_{entry.name}_%yield", f"sampled_{entry.name}_aq_%yield")
    else:
        candidates = (f"{entry.role}_{entry.name}_aq_mM", f"{entry.role}_{entry.name}_mM")
    return next((c for c in candidates if registry.is_known_column(c)), None)


def set_row_value(row: ExtractedRow, column: str, value) -> None:
    """Write a value into any column of a row: a dedicated field if the row has
    one, a concentration column, or `extra` (other template / accepted columns)."""
    field = _FIELD_FOR_TEMPLATE.get(column, column)
    if field in ExtractedRow.model_fields and field not in _NOT_VALUE_FIELDS:
        setattr(row, field, value)
    elif column.endswith("_mM") and isinstance(value, (int, float)):
        row.species_mM[column] = value
    else:
        row.extra[column] = value


_NOT_VALUE_FIELDS = {"full_id", "set_id", "sample_id", "set_type", "entry_number", "paper_doi",
                     "paper_title", "authors", "year_published", "journal_published",
                     "species_mM", "extra", "source_notes", "extraction_confidence"}


def proposed_column_for_solute(entry) -> str:
    """What the column would be called if this new variable were accepted."""
    if entry.role == "sampled" and is_percent(entry):
        return f"sampled_{entry.name}_%yield"
    return resolve_template_column(entry.name, entry.role).removesuffix(UNRECOGNIZED_SUFFIX)


def _solute_value(entry) -> Optional[float]:
    return entry.concentration_value if is_percent(entry) else entry.concentration_mM


def _lowest_confidence(entries) -> Optional[str]:
    levels = [s.confidence for s in entries]
    return min(levels, key=CONFIDENCE_ORDER.index) if levels else None




def build_rows(
    metadata: PaperMetadata,
    structure: StructurePlan,
    methodology: Methodology,
    chemistry: ChemistryExtraction,
    paper_prefix: str,
    drop_below: Optional[str] = settings.CONFIDENCE_DROP_BELOW,
    registry=None,
) -> List[ExtractedRow]:
    """`drop_below`: values whose confidence ranks below this are left blank
    (None = keep everything). They're still reported by the plausibility checks."""
    rows: List[ExtractedRow] = []

    def _kept(confidence: Optional[str]) -> bool:
        return not confidence_below(confidence, drop_below)

    def _method_value(field):
        """A paper-wide methodology value, unless it's below the drop threshold."""
        return field.value if _kept(field.confidence) else None

    # species constant across the whole paper (set_label is None) -- minus any
    # that also appear per-set, which are left out and flagged instead (see
    # ChemistryExtraction.ambiguous_paper_wide_species)
    ambiguous = chemistry.ambiguous_paper_wide_species()
    constant_species = {
        s.name: s for s in chemistry.solutes
        if s.set_label is None and s.role == "initial" and s.name not in ambiguous
        and _kept(s.confidence)
    }

    entry_number = 0
    for set_idx, pset in enumerate(structure.experiment_sets, start=1):
        set_id = f"{paper_prefix}{set_idx:03d}"
        set_species = {
            s.name: s for s in chemistry.solutes
            if s.set_label == pset.set_label and s.role == "initial" and _kept(s.confidence)
        }
        merged_species = {**constant_species, **set_species}
        species_mM = {
            col: s.concentration_mM for s in merged_species.values()
            if s.concentration_mM is not None and (col := column_for_solute(s, registry))
        }

        sampled_for_set = [
            s for s in chemistry.solutes
            if s.set_label == pset.set_label and s.role == "sampled"
        ]

        override = methodology.overrides_for(pset.set_label)

        for sample_idx, sample in enumerate(pset.samples, start=1):
            entry_number += 1
            sample_id = f"{sample_idx:03d}"
            full_id = f"{set_id}{sample_id}"

            sampled_here = [s for s in sampled_for_set if s.sample_label == sample.sample_label]
            sampled_kept = [s for s in sampled_here if _kept(s.confidence)]
            sampled_mM, extra, yield_fields = {}, {}, {}
            for s in sampled_kept:
                col, value = column_for_solute(s, registry), _solute_value(s)
                if col is None or value is None:
                    continue
                if col in _FIELD_FOR_TEMPLATE:          # e.g. the Gly 2-/3-peptide % yields
                    yield_fields[_FIELD_FOR_TEMPLATE[col]] = value
                elif col.endswith("_mM"):
                    sampled_mM[col] = value
                else:
                    extra[col] = value

            rows.append(ExtractedRow(
                full_id=full_id, set_id=set_id, sample_id=sample_id,
                set_type=pset.set_type, entry_number=entry_number,
                paper_doi=metadata.paper_doi, paper_title=metadata.paper_title,
                authors=metadata.authors, year_published=metadata.year_published,
                journal_published=metadata.journal_published,
                experiment_type=_method_value(methodology.experiment_type) or "",
                solution_type=_method_value(methodology.solution_type) or "",
                duration_hr=sample.duration_hr,
                vessel_material=_method_value(methodology.vessel_material),
                solvent_name=_method_value(methodology.solvent_name),
                analysis_method=_method_value(methodology.analysis_method),
                headspace_gas=_method_value(methodology.headspace_gas),
                initial_temperature_C=override.get(
                    "initial_temperature_C", _method_value(methodology.initial_temperature_C)),
                initial_pressure_bar=_method_value(methodology.initial_pressure_bar),
                sampled_temperature_C=override.get(
                    "sampled_temperature_C", _method_value(methodology.sampled_temperature_C)),
                species_mM={**species_mM, **sampled_mM},
                extra=extra,
                **yield_fields,
                # lowest confidence among this row's MEASURED values, including any
                # dropped by drop_below, so check_row still flags them
                extraction_confidence=_lowest_confidence(sampled_here),
                source_notes=f"set: {pset.varying_condition_summary}; sample source: {sample.source}",
            ))

    return rows


# ExtractedRow field -> template column, where the names differ (Python field
# names can't contain '%'). Every other field already uses the template's name.
FIELD_TO_TEMPLATE = {
    "paper_doi": "paper_DOI",
    "headspace_gas": "headspace_gas_name",
    "sampled_2peptide_Gly_pct_yield": "sampled_2peptide_Gly_%yield",
    "sampled_3peptide_Gly_pct_yield": "sampled_3peptide_Gly_%yield",
}
_FIELD_FOR_TEMPLATE = {col: field for field, col in FIELD_TO_TEMPLATE.items()}
MAX_AUTHOR_COLUMNS = 7          # template has author1..author7
def row_to_template_dict(row: ExtractedRow) -> dict:
    """{template column: value} for one row, using the template's own names."""
    data = row.model_dump(exclude={"species_mM", "extra", "authors"})
    out = {FIELD_TO_TEMPLATE.get(k, k): v for k, v in data.items()}
    authors = list(row.authors)
    if len(authors) > MAX_AUTHOR_COLUMNS:   # keep the template's 7 columns: overflow joins the last
        authors = authors[:MAX_AUTHOR_COLUMNS - 1] + ["; ".join(authors[MAX_AUTHOR_COLUMNS - 1:])]
    for i, name in enumerate(authors, start=1):
        out[f"author{i}"] = name
    out.update(row.species_mM)
    out.update(row.extra)
    return out


# Not template columns: our provenance, always last.
PROVENANCE_COLUMNS = ["yield_below_threshold_note", "source_notes", "extraction_confidence"]


def ordered_columns(present: set) -> List[str]:
    """ALL of PaperDataTemplate's columns, in its exact order (empty ones too),
    so the rows can be pasted straight into the template. Columns the template
    doesn't have (e.g. a species with no template column yet) come after that
    block, then our provenance columns."""
    extras = sorted(c for c in present if c not in _TEMPLATE_COLUMNS and c not in PROVENANCE_COLUMNS)
    return list(_TEMPLATE_COLUMNS_ORDERED) + extras + PROVENANCE_COLUMNS


def write_template_csv(records: List[dict], out_path: Path) -> None:
    present = {k for r in records for k, v in r.items() if v not in (None, "")}
    header = ordered_columns(present)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in records:
            writer.writerow(["" if r.get(c) is None else r.get(c) for c in header])


def write_csv(rows: List[ExtractedRow], out_path: Path) -> None:
    """The dataset CSV, with PaperDataTemplate.xlsx's column names and order."""
    write_template_csv([row_to_template_dict(r) for r in rows], out_path)
