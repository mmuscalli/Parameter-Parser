"""
Digitized figures -> template rows.

Each digitized series becomes its own set, numbered after the sets that came
from text and tables; each clicked point becomes one sample row. The x and
y values go into the columns the user (or the model's suggestion) assigned to
the axes, after the axis multiplier; the series' conditions fill the initial
composition, temperature, pH and any other condition columns (pressure, flow
rate, ...: converted from the value as printed, see convert_condition). Paper-wide fields (metadata, methodology)
are filled the same way as for table rows.

Rows are marked extraction_confidence="digitized" and their source_notes say
which figure and series they came from: the values are approximate readings
of a plot, not numbers printed in the paper.

An axis column or a series species that isn't a template column (typed in by
hand in the digitizer) is a new variable: its values are held out of the CSV
and returned as NewVariable records, like any other unaccepted variable.
"""
from __future__ import annotations
from typing import List, Optional, Tuple

from parameter_extractor.digitizing.calibration import pixel_to_data
from parameter_extractor.ingestion.flatten_to_template import (
    FIELD_TO_TEMPLATE, UNRECOGNIZED_SUFFIX, _TEMPLATE_COLUMNS, resolve_template_column, set_row_value, current_column_name)
from parameter_extractor.schemas.figures import DigitizedFigure, SeriesCondition
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.schemas.variables import NewVariable

DIGITIZED = "digitized"
# Template columns whose ExtractedRow field has a different name.
_FIELD_FOR_COLUMN = {col: field for field, col in FIELD_TO_TEMPLATE.items()}
_ID_FIELDS = {"full_id", "set_id", "sample_id", "set_type", "entry_number", "paper_doi",
              "paper_title", "authors", "year_published", "journal_published",
              "species_mM", "extra", "source_notes", "extraction_confidence"}


def _assign(fields: dict, species: dict, extra: dict, column: Optional[str], value: float,
            registry, prov: Optional[dict] = None, source: Optional[CellSource] = None) -> bool:
    """Puts the value in its column; False (nothing written) if the column isn't known
    (neither a template column, one accepted earlier, nor mapped by an alias)."""
    if not column:
        return True
    column = registry.alias_for("figure_axis", column) or column
    if not registry.is_known_column(column):
        return False
    if prov is not None and source is not None:
        prov[column] = source
    field = _FIELD_FOR_COLUMN.get(column, column)
    if field in ExtractedRow.model_fields and field not in _ID_FIELDS:
        fields[field] = value
    elif column.endswith("_mM"):
        species[column] = value
    else:
        extra[column] = value
    return True


# columns that can't be set per series, and category columns with fixed values
NOT_CONDITIONS = {"full_id", "set_id", "sample_id", "set_type", "entry_number", "year_published",
                  "journal_published", "source_notes", "extraction_confidence", "original_data_reference"}
CATEGORY_VALUES = {"experiment_type": ("Batch", "Flowthrough")}


def _note(condition: SeriesCondition, value) -> str:
    return "" if str(value) == condition.value.strip() else f"from '{condition.value.strip()}'"


def convert_condition(condition: SeriesCondition) -> Tuple[str, object, str]:
    """(column, value to write, problem). The value is converted to the column's unit
    ("22.2 MPa" -> 222 for initial_pressure_bar); text columns keep the text. `problem`
    is '' when the value can be written."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import to_column_unit
    column, raw = condition.column.strip(), condition.value.strip()
    if not column or not raw:
        return column, raw, "needs both a column and a value"
    if column in NOT_CONDITIONS or column.startswith(("author", "paper_")):
        return column, raw, f"{column} identifies the paper or row; it isn't a condition"
    if column in CATEGORY_VALUES:
        match = next((v for v in CATEGORY_VALUES[column] if v.lower() == raw.lower()), None)
        if match is None:
            return column, raw, (f"{column} takes only {' or '.join(CATEGORY_VALUES[column])} "
                                 f"-- put a description in the series notes")
        return column, match, ""
    unit = unit_for_column(column)
    if not unit:
        return column, raw, ""                                   # a text column, e.g. headspace_gas_name
    if unit == "pH":
        try:
            return column, float(raw), ""
        except ValueError:
            return column, raw, f"'{raw}' isn't a number"
    converted = to_column_unit(raw, None, unit)
    if converted is None:
        return column, raw, f"'{raw}' can't be converted to {unit} (the unit of {column})"
    return column, converted.value, ""


def build_figure_rows(
    figures: List[DigitizedFigure],
    metadata: PaperMetadata,
    methodology: Methodology,
    paper_prefix: str,
    first_set_index: int,
    first_entry_number: int,
    registry=None,
) -> Tuple[List[ExtractedRow], List[str], List[NewVariable]]:
    """Returns (rows, problems, new_variables). A series is left out, with a
    reason in `problems`, if its panel isn't calibrated or neither axis has a
    column."""
    from parameter_extractor.ingestion.flatten_to_template import base_registry
    registry = registry or base_registry()
    rows: List[ExtractedRow] = []
    problems: List[str] = []
    new_vars: List[NewVariable] = []
    set_idx, entry = first_set_index, first_entry_number

    for fig in figures:
        for series in fig.series:
            if not series.points:
                continue
            panel = fig.panels[series.panel]
            if not (panel.x_cal.complete() and panel.y_cal.complete()):
                problems.append(f"{fig.figure_id} series '{series.label}': axes not calibrated -- left out.")
                continue
            if not (panel.x.column or panel.y.column or series.y_column):
                problems.append(f"{fig.figure_id} series '{series.label}': neither axis is assigned "
                                f"to a column -- left out.")
                continue

            set_id = f"{paper_prefix}{set_idx:03d}"
            set_idx += 1
            set_type = "Time Series" if "duration_hr" in (panel.x.column, panel.y.column) else "Independent"
            where = f"{fig.figure_id}, series '{series.label}'"
            species, held_species = {}, []
            for sp in series.initial_species:
                if sp.concentration_mM is None or not sp.name:
                    continue
                from parameter_extractor.names import match_species
                matched = match_species(sp.name)
                if matched and matched[0] != sp.name:
                    sp = sp.model_copy(update={"name": matched[0]})
                candidates = (f"initial_{sp.name}_aq_mM", f"initial_{sp.name}_mM")
                col = (registry.alias_for("species", f"initial {sp.name}")
                       or next((c for c in candidates if registry.is_known_column(c)), None))
                if col is None:
                    held_species.append(NewVariable(
                        kind="species", name=sp.name, alias_name=f"initial {sp.name}",
                        proposed_column=resolve_template_column(sp.name, "initial").removesuffix(UNRECOGNIZED_SUFFIX),
                        role="initial", value=sp.concentration_mM, unit="mM", set_label=where,
                        source=where, origin=fig.figure_id))
                else:
                    species[col] = sp.concentration_mM
            series_row_ids = []
            known_conditions, held_conditions = [], []
            for cond in series.conditions:
                column, value, problem = convert_condition(cond)
                if problem:
                    problems.append(f"{where}: condition {column or '?'} = '{cond.value}' left out -- {problem}.")
                elif registry.is_known_column(column):
                    note = cond.source + (f", {value_note}" if (value_note := _note(cond, value)) else "")
                    known_conditions.append((column, value, note.strip(", ")))
                else:                                   # a new column: the user decides in the review
                    held_conditions.append(NewVariable(
                        kind="parameter", name=column, alias_name=column, proposed_column=column,
                        value_text=cond.value, set_label=where, source=f"{where}; {cond.source}".strip("; "),
                        origin=fig.figure_id))

            points = sorted(series.points, key=lambda p: pixel_to_data(panel, p.px, p.py)[0])
            for sample_idx, pt in enumerate(points, start=1):
                x, y = pixel_to_data(panel, pt.px, pt.py)
                fields = {
                    "initial_temperature_C": series.initial_temperature_C
                    if series.initial_temperature_C is not None else methodology.initial_temperature_C.value,
                    "sampled_temperature_C": series.initial_temperature_C
                    if series.initial_temperature_C is not None else methodology.sampled_temperature_C.value,
                }
                row_species, extra = dict(species), {}
                conditions = CellSource(origin=f"{fig.figure_id} series conditions", source=where)
                prov = {col: conditions for col in species}
                if series.initial_temperature_C is not None:
                    prov["initial_temperature_C"] = prov["sampled_temperature_C"] = conditions
                if series.initial_pH is not None:
                    extra["initial_pH"] = series.initial_pH
                    prov["initial_pH"] = conditions
                y_axis = panel.y.model_copy(update={"column": series.y_column}) if series.y_column else panel.y
                # the template's old DKP_<AA> names follow the cyclic naming (cyclo_<AA>-<AA>)
                x_axis = panel.x.model_copy(update={"column": current_column_name(panel.x.column)}) \
                    if panel.x.column else panel.x
                if y_axis.column:
                    y_axis = y_axis.model_copy(update={"column": current_column_name(y_axis.column)})
                for axis, value in ((x_axis, x), (y_axis, y)):
                    value = round(value * axis.multiplier, 6)
                    read = CellSource(origin=f"{fig.figure_id} (digitized)", confidence=DIGITIZED,
                                      source=f"{where}, point {sample_idx} (page {fig.page}), read off axis "
                                             f"'{axis.label}'"
                                             + (f" x {axis.multiplier:g}" if axis.multiplier != 1 else ""))
                    if not _assign(fields, row_species, extra, axis.column, value, registry, prov, read):
                        new_vars.append(NewVariable(
                            kind="figure_axis", name=axis.column, alias_name=axis.column,
                            proposed_column=axis.column, value=value,
                            set_label=where, sample_label=f"point {sample_idx}", source=where,
                            quote=f"axis '{axis.label}'", origin=fig.figure_id,
                            row_ids=[f"{set_id}{sample_idx:03d}"]))

                sample_id = f"{sample_idx:03d}"
                series_row_ids.append(f"{set_id}{sample_id}")
                row = dict(
                    provenance=prov,
                    full_id=f"{set_id}{sample_id}", set_id=set_id, sample_id=sample_id,
                    set_type=set_type, entry_number=entry,
                    paper_doi=metadata.paper_doi, paper_title=metadata.paper_title,
                    authors=metadata.authors, year_published=metadata.year_published,
                    journal_published=metadata.journal_published,
                    experiment_type=methodology.experiment_type.value or "",
                    solution_type=methodology.solution_type.value or "",
                    vessel_material=methodology.vessel_material.value,
                    solvent_name=methodology.solvent_name.value,
                    analysis_method=methodology.analysis_method.value,
                    headspace_gas=methodology.headspace_gas.value,
                    initial_pressure_bar=methodology.initial_pressure_bar.value,
                    species_mM=row_species, extra=extra,
                    source_notes=f"digitized from {fig.figure_id} (page {fig.page}), series "
                                 f"'{series.label}', point {sample_idx}"
                                 + (f"; {series.notes}" if series.notes else ""),
                    extraction_confidence=DIGITIZED,
                    original_data_reference=fig.data_source or None,
                )
                if fig.data_source:
                    prov["original_data_reference"] = CellSource(
                        origin=f"{fig.figure_id} (reproduces another publication's data)", source=where)
                row.update(fields)   # axis/series values win over paper-wide defaults
                row_obj = ExtractedRow(**row)
                # the series' other conditions (pressure, flow rate, ...), also over paper-wide defaults
                for column, value, note in known_conditions:
                    set_row_value(row_obj, column, value, CellSource(
                        origin=f"{fig.figure_id} series conditions",
                        source=f"{where}" + (f"; {note}" if note else "")))
                rows.append(row_obj)
                entry += 1
            for v in held_species + held_conditions:
                v.row_ids = list(series_row_ids)
            new_vars += held_species + held_conditions
    return rows, problems, new_vars
