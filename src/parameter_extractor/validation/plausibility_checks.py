"""
Cheap, always-on sanity checks -- these don't require a gold-standard answer
key, just physical/chemical plausibility and the model's own confidence.
Distinct from gold_standard_eval.py (which DOES require a known-correct answer
and is toggled off until that exists). Returns Flag objects; never raises or
silently corrects a value.

Flags are structured (kind / message / quote / source) rather than bare
strings so a front end can group, sort and highlight them; `message` alone is
still a complete human-readable sentence.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Dict, List, Literal, Optional

from parameter_extractor.config import settings
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.common import confidence_below
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.row_schema import ExtractedRow

FlagKind = Literal["out_of_range", "low_confidence", "ambiguous_paper_wide_species",
                   "possible_duplicate", "figure_problem", "new_variable",
                   "term_not_found", "cited_data", "conflicting_values",
                   "assumed_value", "unit_conversion", "derived_value", "lookup_unavailable"]


@dataclass
class Flag:
    kind: FlagKind
    message: str
    quote: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def __str__(self) -> str:
        return self.message


_METHOD_FIELDS = (
    "experiment_type", "solution_type", "vessel_material", "solvent_name", "analysis_method",
    "headspace_gas", "initial_pressure_bar", "initial_temperature_C", "sampled_temperature_C",
    "initial_pH",
)


def _drop_suffix(confidence, drop_below) -> str:
    if confidence_below(confidence, drop_below):
        return f" -- left BLANK in the CSV (values below '{drop_below}' are dropped)"
    return ""


def check_row(
    row: ExtractedRow,
    flag_below: Optional[str] = settings.CONFIDENCE_FLAG_BELOW,
    drop_below: Optional[str] = settings.CONFIDENCE_DROP_BELOW,
) -> List[Flag]:
    flags: List[Flag] = []
    out_of_range = lambda msg: flags.append(Flag("out_of_range", msg))

    if row.initial_temperature_C is not None and not (-20 <= row.initial_temperature_C <= 400):
        out_of_range(f"initial_temperature_C={row.initial_temperature_C} is outside a plausible "
                     f"range for an aqueous-phase prebiotic experiment -- check extraction.")

    if row.sampled_temperature_C is not None and not (-20 <= row.sampled_temperature_C <= 400):
        out_of_range(f"sampled_temperature_C={row.sampled_temperature_C} is outside a plausible range.")

    if row.initial_pressure_bar is not None and row.initial_pressure_bar < 0:
        out_of_range("initial_pressure_bar is negative -- not physically possible.")

    for pct_field in ("sampled_2peptide_Gly_pct_yield", "sampled_3peptide_Gly_pct_yield"):
        val = getattr(row, pct_field)
        if val is not None and not (0 <= val <= 100):
            out_of_range(f"{pct_field}={val} is outside 0-100%.")

    for name, conc in row.species_mM.items():
        if conc is not None and conc < 0:
            out_of_range(f"{name}={conc} mM is negative -- not physically possible.")

    if row.duration_hr is not None and row.duration_hr < 0:
        out_of_range("duration_hr is negative.")

    if row.extraction_confidence and confidence_below(row.extraction_confidence, flag_below):
        flags.append(Flag("low_confidence",
                          f"lowest confidence among this row's measured values is "
                          f"'{row.extraction_confidence}' -- verify against the paper"
                          f"{_drop_suffix(row.extraction_confidence, drop_below)}."))

    return flags


def check_extraction(
    methodology: Methodology,
    chemistry: ChemistryExtraction,
    flag_below: Optional[str] = settings.CONFIDENCE_FLAG_BELOW,
    drop_below: Optional[str] = settings.CONFIDENCE_DROP_BELOW,
    wet_dry=None,
) -> List[Flag]:
    """Paper-level flags: problems with values that apply to many rows at once
    (paper-wide methodology, initial compositions), reported once here rather
    than repeated on every row they affect."""
    flags: List[Flag] = []

    for name in sorted(chemistry.ambiguous_paper_wide_species()):
        for s in chemistry.solutes:
            if s.variable == name and s.role == "initial" and s.set_label is None:
                flags.append(Flag(
                    "ambiguous_paper_wide_species",
                    f"{name} = {s.concentration_value} {s.concentration_unit_raw} was extracted "
                    f"as paper-wide (no set_label), but {name} is also given for specific sets "
                    f"-- most likely a set-specific value missing its set_label. NOT applied to "
                    f"any row; assign it to the right set by hand.",
                    quote=s.quote, source=s.source))

    for label, name in sorted(chemistry.conflicting_set_species()):
        values = sorted({s.concentration_value for s in chemistry.solutes
                         if s.role == "initial" and s.set_label == label and s.variable == name and not s.sample_label},
                        key=lambda v: (v is None, v))
        flags.append(Flag(
            "conflicting_values",
            f"{name} in set '{label}' was extracted with several different starting values "
            f"({', '.join(str(v) for v in values)}) and nothing saying which sample each belongs to. "
            f"NOT written to any row; enter them by hand."))

    for field in _METHOD_FIELDS:
        f = getattr(methodology, field)
        if f.value is not None and confidence_below(f.confidence, flag_below):
            flags.append(Flag(
                "low_confidence",
                f"methodology.{field} = {f.value!r} has confidence '{f.confidence}' "
                f"(applies to every row){_drop_suffix(f.confidence, drop_below)}.",
                quote=f.quote or None, source=f.source or None))

    # per-set and cycling values (assumed ones are reported separately: never written)
    per_set = [(o.field_name, o.value, o.set_label, o.confidence, o.basis, o.quote, o.source)
               for o in methodology.per_set_overrides]
    per_set += [(c.parameter, c.value, c.set_label or "every cycling set", c.confidence, c.basis, c.quote,
                 c.source) for c in (wet_dry.parameters if wet_dry else [])]
    for name, value, label, confidence, basis, quote, source in per_set:
        if basis != "assumed" and confidence_below(confidence, flag_below):
            flags.append(Flag(
                "low_confidence",
                f"{name} = {value:g} for set '{label}' has confidence '{confidence}'"
                + (" (derived from stated values)" if basis == "derived" else "")
                + f"{_drop_suffix(confidence, drop_below)}.", quote=quote or None, source=source or None))

    for s in chemistry.solutes:
        if s.role == "initial" and confidence_below(s.confidence, flag_below):
            where = f"set {s.set_label!r}" if s.set_label else "every set"
            flags.append(Flag(
                "low_confidence",
                f"initial {s.name} = {s.concentration_value} {s.concentration_unit_raw} "
                f"({where}) has confidence '{s.confidence}'{_drop_suffix(s.confidence, drop_below)}.",
                quote=s.quote, source=s.source))

    return flags


def flags_to_json(paper_flags: List[Flag], row_flags: Dict[str, List[Flag]]) -> dict:
    """The plausibility_flags.json layout."""
    return {
        "paper_level": [f.to_dict() for f in paper_flags],
        "rows": {row_id: [f.to_dict() for f in fs] for row_id, fs in row_flags.items()},
    }
