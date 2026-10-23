"""
Combine StructurePlan + Methodology + ChemistryExtraction (+ calculators) into
one ExtractedRow per planned sample, and flatten a list of ExtractedRow into
the wide, PaperDataTemplate-shaped CSV your existing pipeline expects -- with
the template's own column names (e.g. paper_DOI, author_list,
sampled_2peptide_Gly_%yield) and column order.

This is the one place that's allowed to know about the wide template's column
names -- every stage upstream of this deliberately stays schema-narrow.
"""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path
from typing import List, Optional

from parameter_extractor.config import settings
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.common import CONFIDENCE_ORDER, confidence_below
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.calculators.peptide_yield import peptide_mM_from_yield_pct

def template_columns() -> List[str]:
    """The active domain pack's columns, in template order (packs/)."""
    from parameter_extractor.packs import current
    return current().template_columns


def _template_set() -> set:
    from parameter_extractor.packs import current
    pack = current()
    if getattr(pack, "_column_set", None) is None:
        pack._column_set = set(pack.template_columns)
    return pack._column_set


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
    if aq_form in _template_set():
        return aq_form
    if plain_form in _template_set():
        return plain_form
    return f"{aq_form}{UNRECOGNIZED_SUFFIX}"


def is_percent(entry) -> bool:
    return "%" in (entry.concentration_unit_raw or "")


_BASE_REGISTRY: dict = {}


def base_registry():
    """The active pack's template columns only (no local additions)."""
    from parameter_extractor.packs import current
    from parameter_extractor.registry import VariableRegistry
    pack_id = current().id
    if pack_id not in _BASE_REGISTRY:
        _BASE_REGISTRY[pack_id] = VariableRegistry(None)
    return _BASE_REGISTRY[pack_id]


def species_alias_name(entry) -> str:
    """How the registry remembers a species value: role and % vs concentration
    matter ("initial RbCl" and "sampled RbCl %" are different variables)."""
    return f"{_column_role(entry)} {entry.name}" + (" %" if entry.role == "sampled" and is_percent(entry) else "")


def _column_role(entry) -> str:
    """Column prefix: initial / sampled, or stock for a stock-solution concentration
    (stock_<name>_aq_mM -- not a template column; known wherever the species'
    initial column is, see VariableRegistry.is_known_column)."""
    return "stock" if getattr(entry, "concentration_basis", "mixture") == "stock" else entry.role


_TOTAL_PEPTIDES = re.compile(r"\btotal\b.*\bpeptides?\b", re.IGNORECASE)


def column_for_solute(entry, registry=None) -> Optional[str]:
    """The column an extracted value belongs in -- a template column, or one the
    user accepted earlier (local registry: column or alias) -- or None, making
    it a new variable that stays out of the CSV until the user accepts it (see
    ingestion/new_variables.py). Percent yields go to sampled_<name>_%yield."""
    registry = registry or base_registry()
    alias = registry.column_for("species", species_alias_name(entry))
    if alias:
        return alias
    if entry.role == "sampled" and is_percent(entry) and _TOTAL_PEPTIDES.search(entry.name):
        return "total_sampled_peptides_yield"      # "Total Gly in peptides", "total peptide yield"
    if _column_role(entry) == "stock":         # follows wherever the starting concentration was mapped
        initial = registry.column_for("species", f"initial {entry.name}")
        if initial and initial.startswith("initial_") and registry.is_known_column("stock_" + initial[8:]):
            return "stock_" + initial[8:]
    if entry.role == "sampled" and is_percent(entry):
        candidates = (f"sampled_{entry.name}_%yield", f"sampled_{entry.name}_aq_%yield")
    else:
        role = _column_role(entry)
        candidates = (f"{role}_{entry.name}_aq_mM", f"{role}_{entry.name}_mM")
    return next((c for c in candidates if registry.is_known_column(c)), None)


_OLD_DKP = re.compile(r"(initial|sampled)_DKP_([A-Z][a-z]{2})_(mM|%yield)")


def current_column_name(column: str) -> str:
    """The template's DKP_<AA> columns follow the cyclic naming now:
    sampled_DKP_Gly_%yield -> sampled_cyclo_Gly-Gly_%yield (e.g. chosen as a figure axis)."""
    m = _OLD_DKP.fullmatch(column)
    return f"{m.group(1)}_cyclo_{m.group(2)}-{m.group(2)}_{m.group(3)}" if m else column


def set_row_value(row: ExtractedRow, column: str, value, source: Optional[CellSource] = None) -> None:
    """Write a value into any column of a row: a dedicated field if the row has
    one, a concentration column, or `extra` (other template / accepted columns)."""
    column = current_column_name(column)
    if source is not None:
        row.provenance[column] = source
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


def column_safe_name(name: str) -> str:
    """A species name usable inside a column name: whitespace/commas/quotes -> '_'
    ("cytidine 2'-phosphate" -> "cytidine_2'-phosphate"); primes etc. are kept,
    since they matter chemically (2'- vs 5'-phosphate)."""
    return re.sub(r'[\s,;"]+', "_", name.strip()).strip("_")


def is_peptide_column(column: str) -> bool:
    from parameter_extractor.registry import is_peptide_column as check
    return check(column)


def proposed_column_for_solute(entry) -> str:
    """What the column would be called if this new variable were accepted."""
    name = column_safe_name(entry.name)
    if entry.role == "sampled" and is_percent(entry):
        return f"sampled_{name}_%yield"
    if _column_role(entry) != "stock" and is_peptide_column(f"{entry.role}_{name}_mM"):
        return f"{entry.role}_{name}_mM"           # peptides: no _aq_ infix, as in the template
    if _column_role(entry) == "stock":
        initial = resolve_template_column(name, "initial").removesuffix(UNRECOGNIZED_SUFFIX)
        return "stock_" + initial.removeprefix("initial_")
    return resolve_template_column(name, entry.role).removesuffix(UNRECOGNIZED_SUFFIX)


def _solute_value(entry) -> Optional[float]:
    return entry.concentration_value if is_percent(entry) else entry.concentration_mM


def _lowest_confidence(entries) -> Optional[str]:
    levels = [s.confidence for s in entries]
    return min(levels, key=CONFIDENCE_ORDER.index) if levels else None




def _from_extracted(field, origin: str = "methodology") -> CellSource:
    return CellSource(origin=origin, quote=field.quote or "", source=field.source or "",
                      confidence=field.confidence)


def _from_solute(s) -> CellSource:
    source = s.source or ""
    if s.conversion_note:
        source = f"{source} [{s.conversion_note}]" if source else s.conversion_note
    return CellSource(origin="calculated" if s.derived else "chemistry", quote=s.quote or "", source=source,
                      confidence=s.confidence)


_METHOD_COLUMNS = {   # template column -> Methodology field
    "experiment_type": "experiment_type", "solution_type": "solution_type",
    "vessel_material": "vessel_material", "solvent_name": "solvent_name",
    "analysis_method": "analysis_method", "headspace_gas_name": "headspace_gas",
    "initial_pressure_bar": "initial_pressure_bar", "initial_temperature_C": "initial_temperature_C",
    "sampled_temperature_C": "sampled_temperature_C",
}


def build_rows(
    metadata: PaperMetadata,
    structure: StructurePlan,
    methodology: Methodology,
    chemistry: ChemistryExtraction,
    paper_prefix: str,
    drop_below: Optional[str] = settings.CONFIDENCE_DROP_BELOW,
    registry=None,
    wet_dry=None,
    optional=None,
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
        s.variable: s for s in chemistry.solutes
        if s.set_label is None and s.role == "initial" and s.variable not in ambiguous
        and _kept(s.confidence)
    }

    # optional stages' values per set (stages/optional.py: '' = every set the stage concerns,
    # set-specific wins; assumed values never written -- offered in the review)
    from parameter_extractor.stages.optional import optional_results, optional_values
    stage_values = [(spec, optional_values(spec, result, structure))
                    for spec, result in optional_results(optional, wet_dry)]

    entry_number = 0
    for set_idx, pset in enumerate(structure.experiment_sets, start=1):
        set_id = f"{paper_prefix}{set_idx:03d}"
        # initial species for the whole set; ones with a sample_label (a starting
        # concentration that differs per sample, e.g. truman2024's Table 2) are applied
        # per sample below -- keying them by name here would let the last one win
        conflicting = {name for (label, name) in chemistry.conflicting_set_species() if label == pset.set_label}
        set_species = {
            s.variable: s for s in chemistry.solutes
            if s.set_label == pset.set_label and s.role == "initial" and _kept(s.confidence)
            and not s.sample_label and s.variable not in conflicting
        }
        per_sample_initial = [
            s for s in chemistry.solutes
            if s.set_label == pset.set_label and s.role == "initial" and _kept(s.confidence)
            and s.sample_label
        ]
        merged_species = {**constant_species, **set_species}
        species_mM, species_prov = {}, {}
        for s in merged_species.values():
            if s.concentration_mM is not None and (col := column_for_solute(s, registry)):
                species_mM[col] = s.concentration_mM
                species_prov[col] = _from_solute(s)

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
            sampled_mM, extra, yield_fields, prov = {}, {}, {}, dict(species_prov)
            row_species = dict(species_mM)
            for s in per_sample_initial:
                if (s.sample_label == sample.sample_label and s.concentration_mM is not None
                        and (col := column_for_solute(s, registry))):
                    row_species[col] = s.concentration_mM
                    prov[col] = _from_solute(s)
            for s in sampled_kept:
                col, value = column_for_solute(s, registry), _solute_value(s)
                if col is None or value is None:
                    continue
                prov[col] = _from_solute(s)
                if col in _FIELD_FOR_TEMPLATE:          # e.g. the Gly 2-/3-peptide % yields
                    yield_fields[_FIELD_FOR_TEMPLATE[col]] = value
                elif col.endswith("_mM"):
                    sampled_mM[col] = value
                else:
                    extra[col] = value

            meta_src = CellSource(origin="metadata", source=metadata.source)
            for col in ("paper_DOI", "paper_title", "year_published", "journal_published"):
                prov[col] = meta_src
            if metadata.authors:
                prov["author_list"] = meta_src
            if metadata.doi_source == "crossref_api":
                prov["paper_DOI"] = CellSource(origin="CrossRef", source=metadata.doi_note or "",
                                               quote=metadata.doi_match_title or "")
            for col, fname in _METHOD_COLUMNS.items():
                prov[col] = _from_extracted(getattr(methodology, fname))
            if "initial_pH" in override:            # no dedicated field: template column via extra
                extra["initial_pH"] = override["initial_pH"]
            elif _method_value(methodology.initial_pH) is not None:
                extra["initial_pH"] = _method_value(methodology.initial_pH)
                prov["initial_pH"] = _from_extracted(methodology.initial_pH)
            for fname, o in methodology.override_details(pset.set_label).items():
                prov[fname] = CellSource(
                    origin="methodology (per set)" + (", derived" if o.basis == "derived" else ""),
                    source=o.source or pset.source_table_or_section,
                    quote=o.quote,       # never the set summary: that's the model's wording, not the paper's
                    confidence=o.confidence)
            structure_src = CellSource(origin="structure", source=sample.source)
            prov["set_type"] = CellSource(origin="structure", source=pset.source_table_or_section)
            prov["duration_hr"] = structure_src
            for spec, values in stage_values:
                # whole-set values first, so a value for this sample (row) wins
                for (label, sample_label, param), v in sorted(values.items(), key=lambda kv: bool(kv[0][1])):
                    if (label == pset.set_label and sample_label in ("", sample.sample_label)
                            and _kept(v.confidence)):
                        extra[param] = v.value
                        prov[param] = CellSource(origin=spec.origin_label + (", derived" if v.basis == "derived" else ""),
                                                 quote=v.quote, confidence=v.confidence,
                                                 source=v.source + (f" [{v.note}]" if v.note else ""))
            if pset.data_source:
                prov["original_data_reference"] = CellSource(
                    origin="structure (data reproduced from another publication)",
                    source=pset.source_table_or_section)

            rows.append(ExtractedRow(
                provenance=prov,
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
                initial_pressure_bar=override.get("initial_pressure_bar",
                                                  _method_value(methodology.initial_pressure_bar)),
                sampled_temperature_C=override.get(
                    "sampled_temperature_C", _method_value(methodology.sampled_temperature_C)),
                species_mM={**row_species, **sampled_mM},
                extra=extra,
                **yield_fields,
                # lowest confidence among this row's MEASURED values, including any
                # dropped by drop_below, so check_row still flags them
                extraction_confidence=_lowest_confidence(sampled_here),
                source_notes=f"set: {pset.varying_condition_summary}; sample source: {sample.source}",
                original_data_reference=pset.data_source or None,
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
# every author in one column (Mickey, 2026-10-22; was author1..author7): "; " between names, so
# the list splits cleanly and a name can be searched for
AUTHOR_SEPARATOR = "; "
def row_to_template_dict(row: ExtractedRow) -> dict:
    """{template column: value} for one row, using the template's own names."""
    data = row.model_dump(exclude={"species_mM", "extra", "authors", "provenance"})
    out = {FIELD_TO_TEMPLATE.get(k, k): v for k, v in data.items()}
    authors = [a.replace(AUTHOR_SEPARATOR, ", ").strip() for a in row.authors if a and a.strip()]
    if authors:
        out["author_list"] = AUTHOR_SEPARATOR.join(authors)
    out.update(row.species_mM)
    out.update(row.extra)
    return out


# Not template columns: our provenance, always last (the optional one only when filled).
PROVENANCE_COLUMNS = ["yield_below_threshold_note", "source_notes", "extraction_confidence"]
OPTIONAL_PROVENANCE_COLUMNS = ["original_data_reference"]


def ordered_columns(present: set) -> List[str]:
    """ALL of PaperDataTemplate's columns, in its exact order (empty ones too),
    so the rows can be pasted straight into the template. After that block:
    the app's standard columns that are filled (schemas/standard_columns.json,
    in their order), then any other columns (accepted in review), then our
    provenance columns."""
    from parameter_extractor.registry import standard_columns
    provenance = set(PROVENANCE_COLUMNS) | set(OPTIONAL_PROVENANCE_COLUMNS)
    standard = [c for c in standard_columns() if c in present]
    extras = sorted(c for c in present
                    if c not in _template_set() and c not in provenance and c not in standard)
    optional = [c for c in OPTIONAL_PROVENANCE_COLUMNS if c in present]
    return template_columns() + standard + extras + PROVENANCE_COLUMNS + optional


def write_template_csv(records: List[dict], out_path: Path) -> None:
    present = {k for r in records for k, v in r.items() if v not in (None, "")}
    header = ordered_columns(present)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in records:
            writer.writerow(["" if r.get(c) is None else r.get(c) for c in header])


def write_csv(rows: List[ExtractedRow], out_path: Path) -> None:
    """The dataset CSV, with PaperDataTemplate.xlsx's column names and order --
    generated from the long-format record (ingestion/observations.py), the
    run's canonical data."""
    from parameter_extractor.ingestion.observations import observations_to_records, rows_to_observations
    write_template_csv(observations_to_records(rows_to_observations(rows)), out_path)
