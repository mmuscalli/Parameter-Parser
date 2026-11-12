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
import math
import re
from typing import Dict, List, Optional, Tuple

from parameter_extractor.ingestion.data_location import COLUMN as DATA_LOCATION, location
from parameter_extractor.ingestion.flatten_to_template import log_base, with_average, with_log
from parameter_extractor.digitizing.calibration import is_categorical, pixel_to_data, pixel_to_y, rounded
from parameter_extractor.ingestion.flatten_to_template import (
    FIELD_TO_TEMPLATE, UNRECOGNIZED_SUFFIX, resolve_template_column, set_row_value, current_column_name,
    species_column, canonical_compound_column)
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


def _has_value(row: ExtractedRow, column: str) -> bool:
    field = _FIELD_FOR_COLUMN.get(column, column)
    if field in ExtractedRow.model_fields and field not in _ID_FIELDS:
        return getattr(row, field) not in (None, "")
    return column in row.extra or column in row.species_mM


def _series_name(label: str) -> str:
    """A series' label without the marker the digitizer appends ('kaolinite [blue bar]' -> 'kaolinite')."""
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", label or "").strip()


def axis_column_from_label(label: str, average: bool = False) -> str:
    """A column name from an axis label no column fits: 'Length (nt)' -> 'length_nt',
    'Relative RNA concentration' -> 'relative_RNA_concentration' (case kept for acronyms). An
    averaged axis loses its 'avg.'/'mean' words: '_avg' is added to the name instead."""
    text = re.sub(r"[()\[\]{}]", " ", label).replace("%", " pct ")
    words = [w if (w.isupper() and len(w) > 1) else w.lower() for w in re.findall(r"[A-Za-z0-9]+", text)]
    if average:
        words = [w for w in words if w.lower() not in ("avg", "average", "averaged", "mean")]
    return "_".join(words)[:60].strip("_") or "figure_value"


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


def convert_condition(condition: SeriesCondition, registry=None) -> Tuple[str, object, str]:
    """(column, value to write, problem). The value is converted to the column's unit
    ("22.2 MPa" -> 222 for initial_pressure_bar); text columns keep the text, unless the column has a data
    type (value_types.py: replicates '3' / 'triplicate' -> 3). `problem` is '' when the value can be written."""
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
        from parameter_extractor.value_types import TYPES, coerce, column_type
        kind = column_type(column, registry)
        value, problem = coerce(raw, kind)
        if problem:
            return column, raw, f"{column} holds {TYPES[kind].lower()}s: {problem}"
        return column, value, ""                                 # a text column, e.g. headspace_gas_name
    # '72 hr (3 days)': the value with a restatement in brackets -> the value
    raw = re.sub(r"\s*\([^()]*\)\s*$", "", raw).strip() or raw
    # ambient conditions by the paper's convention (calculators/ambient.py): 25 °C, 1 bar
    if unit in ("°C", "K") and re.fullmatch(r"(?i)(ambient|room)(\s+temperature)?|r\.?\s?t\.?", raw):
        raw = "25 °C"
    elif unit == "bar" and re.fullmatch(r"(?i)(ambient|atmospheric)(\s+pressure)?", raw):
        raw = "1 bar"
    if unit == "pH":
        try:
            return column, float(raw), ""
        except ValueError:
            from parameter_extractor.ingestion.flatten_to_template import with_range
            from parameter_extractor.units import format_range, parse_range
            rng = parse_range(raw)                       # 'pH 6-7' -> initial_pH_range = '6:7'
            if rng and not rng[2]:
                return with_range(column), format_range(rng[0], rng[1]), ""
            return column, raw, f"'{raw}' isn't a number"
    converted = to_column_unit(raw, None, unit)
    if converted is None:
        from parameter_extractor.ingestion.flatten_to_template import with_range
        from parameter_extractor.units import parse_range, range_to_column_unit
        rng = parse_range(raw)        # '5-6 mg' -> solid_material_mass_range_g = '0.005:0.006'
        if rng and (in_unit := range_to_column_unit(*rng, unit)):
            return with_range(column), in_unit[0], ""
        return column, raw, f"'{raw}' can't be converted to {unit} (the unit of {column})"
    return column, converted.value, ""


# a paper-wide value that says something was absent ('none', 'no buffer', 'not stirred')
_ABSENT = re.compile(r"^\s*(none|no|not\b.*|without\b.*|n/?a|absent|0|no\s+\w+.*|unbuffered|not used)\s*\.?\s*$",
                     re.IGNORECASE)
_GENERIC_WORDS = {"initial", "sampled", "total", "name", "type", "used", "agent"}


def contradicts_absence(column: str, value, source, texts: List[str]) -> str:
    """The word in a figure's caption or series that contradicts a paper-wide 'none' for this column
    (Riggi2023: pH_buffer 'none' from "pH buffers were intentionally excluded from these experiments", but
    Fig. A2 shows 'pH-buffered control experiments'); '' when nothing does. The column's own words (4+
    letters, generic ones left out) are looked for as word stems: 'buffer' in 'pH-buffered'."""
    if not isinstance(value, str) or not _ABSENT.match(value):
        return ""
    stems = [w[:5].lower() for w in re.split(r"[_\W]+", column) if len(w) >= 4 and w.lower() not in _GENERIC_WORDS]
    for text in texts:
        words = re.findall(r"[A-Za-z][\w-]*", text or "")
        for i, word in enumerate(words):
            low = word.lower()
            negated = re.match(r"^(no|non|un)", low) or (i and words[i - 1].lower() in ("no", "without", "not", "non"))
            if any(stem in low for stem in stems) and not negated:
                return word
    return ""


def _error_bar(pt, y: float, to_data, axis) -> dict:
    """{'_err_plus': +e, '_err_minus': -e} from a point's marked error-bar ends, in the axis's values (after its
    multiplier); {} when the point has none."""
    out = {}
    for end, suffix, sign in ((getattr(pt, "err_hi_py", None), "_err_plus", 1), (getattr(pt, "err_lo_py", None),
                                                                                "_err_minus", -1)):
        if end is None:
            continue
        try:
            _, y_end = to_data(type(pt)(px=pt.px, py=end))
        except Exception:
            continue
        e = round(abs(y_end - y) * axis.multiplier, 6)
        if e:
            out[suffix] = sign * e
    return out


def build_figure_rows(
    figures: List[DigitizedFigure],
    metadata: PaperMetadata,
    methodology: Methodology,
    paper_prefix: str,
    first_set_index: int,
    first_entry_number: int,
    registry=None,
    paper_wide: Optional[dict] = None,
    abbreviations: Optional[dict] = None,
) -> Tuple[List[ExtractedRow], List[str], List[NewVariable]]:
    """Returns (rows, problems, new_variables). A series is left out, with a
    reason in `problems`, if its panel isn't calibrated or neither axis has a
    column. A paper-wide 'none' is not copied onto a figure whose caption or series mention the thing (a
    `figure_problem` says so). `paper_wide`: {column: (value, CellSource)} -- the conditions steps' values for the whole paper
    (controls, solid mass, ...), written where the series doesn't give its own."""
    from parameter_extractor.ingestion.flatten_to_template import base_registry
    registry = registry or base_registry()
    rows: List[ExtractedRow] = []
    problems: List[str] = []
    contradicted: set = set()          # (figure, column) already reported
    new_vars: List[NewVariable] = []
    set_idx, entry = first_set_index, first_entry_number

    for fig in figures:
        fig_start, fig_vars_start, fig_set, fig_entry = len(rows), len(new_vars), set_idx, entry
        problems += [f"{fig.figure_id}: concentration {n}" for n in getattr(fig, "plan_notes", []) or []]
        # the suggestions' starting concentrations for series that list none (Cleaves2008 Fig. 2: '10^-1 M' wasn't
        # read when the figure was digitized, so its series had no glycine) -- a series' own composition is kept
        if fig.plan is not None and fig.plan.concentrations and any(not s.initial_species for s in fig.series):
            from parameter_extractor.digitizing.auto_figure import fill_concentrations
            bare = [s.model_copy(deep=True) if not s.initial_species else None for s in fig.series]
            problems += [f"{fig.figure_id}: concentration {p}" for p in
                         fill_concentrations([s for s in bare if s is not None], fig.plan.concentrations,
                                             fig.panels)]
            fig = fig.model_copy(update={"series": [b if b is not None else s for b, s in zip(bare, fig.series)]})
        row_meta: Dict[str, tuple] = {}         # full_id -> (panel group, x value, x column, series label, point)
        for series in fig.series:
            if not series.points:
                continue
            if not 0 <= series.panel < len(fig.panels):        # its coordinate system is gone: skipped, not an error
                problems.append(f"{fig.figure_id} series '{series.label}': its coordinate system no longer exists "
                                f"-- left out.")
                continue
            panel = fig.panels[series.panel]
            # bars of categories: no numeric x axis -- only y is calibrated, and x has no column
            categorical = is_categorical(panel)
            if not panel.y_cal.complete() or not (categorical or panel.x_cal.complete()):
                problems.append(f"{fig.figure_id} series '{series.label}': axes not calibrated -- left out.")
                continue
            if not (panel.x.column or panel.y.column or series.y_column
                    or (panel.y.store and (panel.y.label or panel.y.new_column))
                    or (not categorical and panel.x.store and (panel.x.label or panel.x.new_column))):
                problems.append(f"{fig.figure_id} series '{series.label}': neither axis is assigned "
                                f"to a column -- left out.")
                continue

            set_id = f"{paper_prefix}{set_idx:03d}"
            set_idx += 1
            set_type = "Time Series" if "duration_hr" in (panel.x.column, panel.y.column) else "Independent"
            if getattr(panel.y, "average", False) or getattr(panel.x, "average", False):
                set_type = "Average"           # averaged values without the individual runs (Riggi2023's bars)
            where = f"{fig.figure_id}, series '{series.label}'"
            species, held_species, species_sources = {}, [], {}
            for sp in series.initial_species:
                if sp.concentration_mM is None or not sp.name:
                    continue
                from parameter_extractor.names import match_species, preferred_name
                if abbreviations:                  # the paper's one name for it, as in the chemistry
                    sp = sp.model_copy(update={"name": preferred_name(sp.name, abbreviations)})
                matched = match_species(sp.name)
                if matched and matched[0] != sp.name:
                    sp = sp.model_copy(update={"name": matched[0]})
                from parameter_extractor.names import compact_repeats
                if compact_repeats(sp.name) != sp.name:
                    sp = sp.model_copy(update={"name": compact_repeats(sp.name)})
                own = species_column("initial", sp.name)
                col = (registry.alias_for("species", f"initial {sp.name}")
                       or (own if registry.is_known_column(own) else None))
                if col is None:
                    held_species.append(NewVariable(
                        kind="species", name=sp.name, alias_name=f"initial {sp.name}",
                        proposed_column=resolve_template_column(sp.name, "initial").removesuffix(UNRECOGNIZED_SUFFIX),
                        role="initial", value=sp.concentration_mM, unit="mM", set_label=where,
                        source=where, origin=fig.figure_id))
                else:
                    species[col] = sp.concentration_mM
                    if sp.basis == "indirect" or sp.source:
                        species_sources[col] = ("indirect: " if sp.basis == "indirect" else "") + sp.source
            series_row_ids = []
            known_conditions, held_conditions = [], []
            for cond in series.conditions:
                column, value, problem = convert_condition(cond, registry)
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

            to_data = (lambda p: (p.px, pixel_to_y(panel, p.px, p.py))) if categorical else \
                (lambda p: pixel_to_data(panel, p.px, p.py))
            points = sorted(series.points, key=lambda p: to_data(p)[0])
            # a point far outside its axes' calibrated range: the series likely reads against the wrong coordinate
            # system (Cleaves2008: panel B's points read with panel A's axes -> 475 C on a 100-250 C axis)
            far = []
            for axis_name, cal in (("x", panel.x_cal), ("y", panel.y_cal)):
                if axis_name == "x" and categorical or not cal.complete() or cal.log:
                    continue
                lo, hi = sorted((cal.p1.value, cal.p2.value))
                span = hi - lo
                k = 0 if axis_name == "x" else 1
                if span > 0 and any(not (lo - 0.6 * span <= to_data(p)[k] <= hi + 0.6 * span) for p in points):
                    far.append(axis_name)
            if far:
                problems.append(f"{fig.figure_id} series '{series.label}': point(s) read far outside the "
                                f"{' and '.join(far)} axis range of coordinate system '{panel.name}' -- check the "
                                f"series' 'Read against' setting and the calibration markers.")
            for sample_idx, pt in enumerate(points, start=1):
                x, y = to_data(pt)
                fields = {
                    "initial_temperature_C": series.initial_temperature_C
                    if series.initial_temperature_C is not None else methodology.initial_temperature_C.value,
                    "sampled_temperature_C": series.initial_temperature_C
                    if series.initial_temperature_C is not None else methodology.sampled_temperature_C.value,
                }
                row_species, extra = dict(species), {}
                conditions = CellSource(origin=f"{fig.figure_id} series conditions", source=where)
                prov = {col: (conditions.model_copy(update={"source": f"{where}; {species_sources[col]}"})
                              if col in species_sources else conditions) for col in species}
                if series.initial_temperature_C is not None:
                    prov["initial_temperature_C"] = prov["sampled_temperature_C"] = conditions
                if series.initial_pH is not None:
                    extra["initial_pH"] = series.initial_pH
                    prov["initial_pH"] = conditions
                y_axis = panel.y.model_copy(update={"column": series.y_column}) if series.y_column else panel.y
                # an axis no column fits (mizuuchi2019's 'Relative RNA concentration', 'Length (nt)'):
                # a column named after its label, reviewed as a new variable like any other
                if not y_axis.column and y_axis.store and (y_axis.new_column or y_axis.label):
                    y_axis = y_axis.model_copy(update={"column": y_axis.new_column
                                                       or axis_column_from_label(y_axis.label, y_axis.average)})
                # the template's old DKP_<AA> names follow the cyclic naming (cyclo_<AA>-<AA>)
                x_axis = panel.x.model_copy(update={"column": canonical_compound_column(panel.x.column)}) \
                    if panel.x.column else panel.x
                if not x_axis.column and x_axis.store and (x_axis.new_column or x_axis.label) and not categorical:
                    x_axis = x_axis.model_copy(update={"column": x_axis.new_column
                                                       or axis_column_from_label(x_axis.label, x_axis.average)})
                if y_axis.column:
                    y_axis = y_axis.model_copy(update={"column": canonical_compound_column(y_axis.column)})
                # averaged values go in '<name>_avg_<unit>' columns
                if getattr(y_axis, "average", False) and y_axis.column:
                    y_axis = y_axis.model_copy(update={"column": with_average(y_axis.column)})
                if getattr(x_axis, "average", False) and x_axis.column:
                    x_axis = x_axis.model_copy(update={"column": with_average(x_axis.column)})
                # plotted LOGARITHMS ('Log % yield', Cleaves2008 Fig. 2) go in their own '<name>_log10_<unit>' column,
                # as plotted; a unit multiplier becomes an offset (log10 of mol dm-3 -> of mM: + 3)
                offsets = {}
                for name in ("x", "y"):
                    ax = y_axis if name == "y" else x_axis
                    base = log_base(ax)
                    if base and ax.column:
                        offsets[name] = (math.log10(ax.multiplier) if base == "log10" else math.log(ax.multiplier)) \
                            if ax.multiplier > 0 else 0.0
                        ax = ax.model_copy(update={"column": with_log(ax.column, base), "multiplier": 1.0})
                        if name == "y":
                            y_axis = ax
                        else:
                            x_axis = ax
                # a category axis has no number: its value is the series' category (below)
                errors = _error_bar(pt, y, to_data, y_axis)
                x_stored = None
                for axis, value in ([(y_axis, y)] if categorical else [(x_axis, x), (y_axis, y)]):
                    offset = offsets.get("y" if axis is y_axis else "x", 0.0)
                    value = round(rounded(value, getattr(axis, "decimals", None)) * axis.multiplier + offset, 6)
                    if axis is x_axis:
                        x_stored = value
                    read = CellSource(origin=f"{fig.figure_id} (digitized)", confidence=DIGITIZED,
                                      source=f"{where}, point {sample_idx} (page {fig.page_label or fig.page}), read off axis "
                                             f"'{axis.label}'"
                                             + (f" x {axis.multiplier:g}" if axis.multiplier != 1 else ""))
                    point_errors = errors if axis is y_axis else {}
                    if _assign(fields, row_species, extra, axis.column, value, registry, prov, read):
                        resolved = (registry.alias_for("figure_axis", axis.column) or axis.column) if axis.column \
                            else None
                        if not resolved:
                            continue
                        for suffix, e in point_errors.items():       # the error bar, beside its value
                            _assign(fields, row_species, extra, resolved + suffix, e, registry, prov,
                                    read.model_copy(update={"source": read.source + ", error bar"}))
                    else:
                        new_vars.append(NewVariable(
                            kind="figure_axis", name=axis.column, alias_name=axis.column,
                            proposed_column=axis.column, value=value,
                            set_label=where, sample_label=f"point {sample_idx}", source=where,
                            quote=f"axis '{axis.label}'", origin=fig.figure_id,
                            row_ids=[f"{set_id}{sample_idx:03d}"],
                            err_plus=point_errors.get("_err_plus", 0.0), err_minus=point_errors.get("_err_minus", 0.0)))

                if categorical and x_axis.column and not any(c.column == x_axis.column for c in series.conditions):
                    # the category goes in the x axis's column (Riggi2023: solid_material_name = 'kaolinite')
                    category = _series_name(series.label)
                    read = CellSource(origin=f"{fig.figure_id} (digitized)", source=f"{where}: the bar's category")
                    if not _assign(fields, row_species, extra, x_axis.column, category, registry, prov, read):
                        new_vars.append(NewVariable(
                            kind="figure_axis", name=x_axis.column, alias_name=x_axis.column,
                            proposed_column=x_axis.column, value_text=category, set_label=where,
                            sample_label=f"point {sample_idx}", source=where, quote=f"axis '{x_axis.label}'",
                            origin=fig.figure_id, row_ids=[f"{set_id}{sample_idx:03d}"]))

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
                    source_notes=f"digitized from {fig.figure_id} (page {fig.page_label or fig.page}), series "
                                 f"'{series.label}', point {sample_idx}"
                                 + (f"; {series.notes}" if series.notes else ""),
                    extraction_confidence=DIGITIZED,
                    original_data_reference=fig.data_source or None,
                )
                extra[DATA_LOCATION] = location(fig.figure_id)
                prov[DATA_LOCATION] = CellSource(origin=f"{fig.figure_id} (digitized)", source=where)
                if fig.data_source:
                    prov["original_data_reference"] = CellSource(
                        origin=f"{fig.figure_id} (reproduces another publication's data)", source=where)
                row.update(fields)   # axis/series values win over paper-wide defaults
                row_obj = ExtractedRow(**row)
                own = {c for c, _, _ in known_conditions}
                for column, (value, source) in (paper_wide or {}).items():
                    if _has_value(row_obj, column) or column in own:
                        continue                # the series' own value is written below
                    said = contradicts_absence(column, value, source, [fig.caption, series.label, series.notes or ""])
                    if said:
                        if (fig.figure_id, column) not in contradicted:
                            contradicted.add((fig.figure_id, column))
                            problems.append(
                                f"{fig.figure_id}: {column} left empty on its rows -- the paper's conditions say "
                                f"'{value}' for its experiments, but this figure mentions it ('{said}'). Fill in "
                                f"the figure's value (the series' conditions) if the paper gives one.")
                        continue
                    set_row_value(row_obj, column, value, source)
                # the series' other conditions (pressure, flow rate, ...), also over paper-wide defaults
                for column, value, note in known_conditions:
                    set_row_value(row_obj, column, value, CellSource(
                        origin=f"{fig.figure_id} series conditions",
                        source=f"{where}" + (f"; {note}" if note else "")))
                rows.append(row_obj)
                if not categorical:
                    from parameter_extractor.digitizing.auto_figure import panel_sides
                    row_meta[row_obj.full_id] = (panel_sides(panel.name or "")[2] or str(series.panel), x_stored,
                                                 x_axis.column, series.label, sample_idx, panel)
                entry += 1
            for v in held_species + held_conditions:
                v.row_ids = list(series_row_ids)
            new_vars += held_species + held_conditions
        if getattr(fig, "rows_by_x", False) and row_meta:
            merged, id_map, set_idx, entry = _merge_rows_by_x(
                fig, rows[fig_start:], row_meta, paper_prefix, fig_set, fig_entry, problems)
            rows[fig_start:] = merged
            for v in new_vars[fig_vars_start:]:
                v.row_ids = list(dict.fromkeys(id_map.get(r, r) for r in v.row_ids))
    return rows, list(dict.fromkeys(problems)), new_vars


_MERGED_FIELDS = ("duration_hr", "initial_temperature_C", "sampled_temperature_C", "initial_pressure_bar",
                  "vessel_material", "solvent_name", "analysis_method", "headspace_gas")


def _merge_rows_by_x(fig, fig_rows, meta, paper_prefix, first_set, first_entry, problems):
    """One row per x value (Mickey, 2026-11-12, Cleaves2008 Fig. 2: each temperature its own experiment, the series
    its products): the points of one coordinate system (with its other y axis) within 2% of the x axis's range become
    one row -- its x their average, each series' value in its own column; one experiment set per coordinate system,
    rows numbered by x. Two series writing different values into one column: the first kept, a problem reported.
    Returns (rows, {old id: new id}, next set index, next entry number)."""
    groups: Dict[str, list] = {}
    for r in fig_rows:
        if r.full_id in meta:
            groups.setdefault(meta[r.full_id][0], []).append(r)
    kept = [r for r in fig_rows if r.full_id not in meta]          # (category charts: unchanged)
    out, id_map, set_idx, entry = [], {}, first_set, first_entry
    for group, members in groups.items():
        members.sort(key=lambda r: meta[r.full_id][1] if meta[r.full_id][1] is not None else float("inf"))
        panel = meta[members[0].full_id][5]
        span = abs((panel.x_cal.p2.value or 0) - (panel.x_cal.p1.value or 0)) if panel.x_cal.complete() else 0
        tol = 0.02 * span if span else 1e-9
        clusters: List[list] = []
        for r in members:
            x = meta[r.full_id][1]
            if clusters and x is not None and meta[clusters[-1][-1].full_id][1] is not None \
                    and abs(x - meta[clusters[-1][-1].full_id][1]) <= tol:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        set_id = f"{paper_prefix}{set_idx:03d}"
        set_idx += 1
        for k, cluster in enumerate(clusters, start=1):
            first = cluster[0]
            xs = [meta[r.full_id][1] for r in cluster if meta[r.full_id][1] is not None]
            x_col = meta[first.full_id][2]
            row = first.model_copy(deep=True)
            for other in cluster[1:]:
                for name in _MERGED_FIELDS:
                    if getattr(row, name) is None and getattr(other, name) is not None:
                        setattr(row, name, getattr(other, name))
                for store in ("species_mM", "extra"):
                    mine, theirs = getattr(row, store), getattr(other, store)
                    for column, value in theirs.items():
                        if column not in mine:
                            mine[column] = value
                            if column in other.provenance:
                                row.provenance[column] = other.provenance[column]
                        elif mine[column] != value and column != x_col and column != DATA_LOCATION:
                            a, b = meta[first.full_id][3], meta[other.full_id][3]
                            at = f"{fig.figure_id} {group} at {x_col} = {meta[first.full_id][1]:g}"
                            problems.append(
                                f"{at}: series '{a}' has two points here ({column}: {mine[column]} and {value}) -- "
                                f"the first kept. Check the series' points." if a == b else
                                f"{at}: {column} is given by two series ('{a}': {mine[column]}, '{b}': {value}) -- "
                                f"the first kept. Give each series its own column ('Read against').")
            if xs and x_col:
                mean = round(sum(xs) / len(xs), 6)
                if x_col in ExtractedRow.model_fields:
                    setattr(row, x_col, mean)
                elif x_col in row.species_mM:
                    row.species_mM[x_col] = mean
                else:
                    row.extra[x_col] = mean
            sample_id = f"{k:03d}"
            for r in cluster:
                id_map[r.full_id] = f"{set_id}{sample_id}"
            parts = "; ".join(f"series '{meta[r.full_id][3]}' point {meta[r.full_id][4]}" for r in cluster)
            row.full_id, row.set_id, row.sample_id, row.entry_number = f"{set_id}{sample_id}", set_id, sample_id, entry
            row.set_type = "Time Series" if x_col == "duration_hr" else "Independent"
            row.source_notes = (f"digitized from {fig.figure_id} (page {fig.page_label or fig.page}), {group}"
                                + (f" at {x_col} = {xs[0] if len(xs) == 1 else round(sum(xs) / len(xs), 6):g}"
                                   if xs and x_col else "")
                                + f", one row per x value: {parts}")
            out.append(row)
            entry += 1
    new_sets: Dict[str, str] = {}
    for r in kept:                                                   # renumbered after the merged sets, set by set
        if r.set_id not in new_sets:
            new_sets[r.set_id] = f"{paper_prefix}{set_idx:03d}"
            set_idx += 1
        set_id = new_sets[r.set_id]
        id_map[r.full_id] = f"{set_id}{r.sample_id}"
        r.full_id, r.set_id, r.entry_number = f"{set_id}{r.sample_id}", set_id, entry
        entry += 1
        out.append(r)
    return out, id_map, set_idx, entry
