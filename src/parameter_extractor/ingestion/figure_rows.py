"""
Digitized figures -> template rows.

Each digitized series becomes its own set, numbered after the sets that came
from text and tables; each clicked point becomes one sample row. The x and
y values go into the columns the user (or the model's suggestion) assigned to
the axes, after the axis multiplier; the series' conditions fill the initial
composition, temperature and pH. Paper-wide fields (metadata, methodology)
are filled the same way as for table rows.

Rows are marked extraction_confidence="digitized" and their source_notes say
which figure and series they came from: the values are approximate readings
of a plot, not numbers printed in the paper.
"""
from __future__ import annotations
from typing import List, Optional, Tuple

from parameter_extractor.digitizing.calibration import pixel_to_data
from parameter_extractor.ingestion.flatten_to_template import FIELD_TO_TEMPLATE, resolve_template_column
from parameter_extractor.schemas.figures import DigitizedFigure
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import ExtractedRow

DIGITIZED = "digitized"
# Template columns whose ExtractedRow field has a different name.
_FIELD_FOR_COLUMN = {col: field for field, col in FIELD_TO_TEMPLATE.items()}
_ID_FIELDS = {"full_id", "set_id", "sample_id", "set_type", "entry_number", "paper_doi",
              "paper_title", "authors", "year_published", "journal_published",
              "species_mM", "extra", "source_notes", "extraction_confidence"}


def _assign(fields: dict, species: dict, extra: dict, column: Optional[str], value: float) -> None:
    if not column:
        return
    field = _FIELD_FOR_COLUMN.get(column, column)
    if field in ExtractedRow.model_fields and field not in _ID_FIELDS:
        fields[field] = value
    elif column.endswith("_mM"):
        species[column] = value
    else:
        extra[column] = value


def build_figure_rows(
    figures: List[DigitizedFigure],
    metadata: PaperMetadata,
    methodology: Methodology,
    paper_prefix: str,
    first_set_index: int,
    first_entry_number: int,
) -> Tuple[List[ExtractedRow], List[str]]:
    """Returns (rows, problems). A series is left out, with a reason in
    `problems`, if its panel isn't calibrated or neither axis has a column."""
    rows: List[ExtractedRow] = []
    problems: List[str] = []
    set_idx, entry = first_set_index, first_entry_number

    for fig in figures:
        for series in fig.series:
            if not series.points:
                continue
            panel = fig.panels[series.panel]
            if not (panel.x_cal.complete() and panel.y_cal.complete()):
                problems.append(f"{fig.figure_id} series '{series.label}': axes not calibrated -- left out.")
                continue
            if not (panel.x.column or panel.y.column):
                problems.append(f"{fig.figure_id} series '{series.label}': neither axis is assigned "
                                f"to a column -- left out.")
                continue

            set_id = f"{paper_prefix}{set_idx:03d}"
            set_idx += 1
            set_type = "Time Series" if "duration_hr" in (panel.x.column, panel.y.column) else "Independent"
            species = {resolve_template_column(s.name, "initial"): s.concentration_mM
                       for s in series.initial_species if s.concentration_mM is not None}

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
                if series.initial_pH is not None:
                    extra["initial_pH"] = series.initial_pH
                _assign(fields, row_species, extra, panel.x.column, round(x * panel.x.multiplier, 6))
                _assign(fields, row_species, extra, panel.y.column, round(y * panel.y.multiplier, 6))

                sample_id = f"{sample_idx:03d}"
                row = dict(
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
                )
                row.update(fields)   # axis/series values win over paper-wide defaults
                rows.append(ExtractedRow(**row))
                entry += 1
    return rows, problems
