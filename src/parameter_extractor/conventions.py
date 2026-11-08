"""
Column-name conventions for drafted and suggested parameters (Mickey, 2026-11-08): a model proposing columns names
them freely ('pH', 'reaction_temperature_C', 'reaction_time_hr', 'wet_dry_cycles', 'analytical_method'); the app's
datasets use one set of names for the same quantities -- the prebiotic pack's, which the curated dataset uses:
initial_pH / sampled_pH, initial_temperature_C / sampled_temperature_C, initial_pressure_bar, duration_hr (filled by
the row planner), cycle_number, cycle_duration_hr, analysis_method, solvent_name, solvent_volume_mL, solid_material_name,
headspace_gas_name, ... `canonical(column, unit, kind)` maps a column to its conventional name (or says it duplicates a
row column), from local rules only. Used when a research area is drafted, when additions are suggested, and by the
editor's 'Find compounds / tidy columns' review for packs drafted earlier. On by default; each change is listed.

Also `strip_unit_words`: a base name that repeats its unit ('primer_concentration_um' + mM, 'gas_flow_rate_ml_per_min'
+ mL/min, 'oligomer_fraction_percent' + %) loses the repeat before the unit suffix is added.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional

UNIT_WORDS = {"um", "nm", "mm", "cm", "ml", "ul", "l", "min", "mins", "s", "sec", "h", "hr", "hrs", "hours", "pct",
              "percent", "fold", "mg", "g", "kg", "mol", "mmol", "umol", "m", "mm", "c", "k", "bar", "mpa", "kpa",
              "per", "nl", "ppm", "nt", "d", "days"}
MEASURED = {"measured", "final", "sampled", "after", "end", "observed", "post"}
GENERIC_QUALIFIERS = {"reaction", "incubation", "initial", "starting", "start", "experiment", "experimental", "run",
                      "heating", "set", "solution", "mixture", "sample", "nominal", "applied", "condition", "oven",
                      "treatment", "process", "operating", "system"}


@dataclass
class Convention:
    column: str            # the conventional name; '' = the quantity is a row column filled elsewhere (drop it)
    unit: str
    reason: str
    integer: bool = False
    kind: str = ""         # 'text' when the conventional column is text


def strip_unit_words(base: str) -> str:
    """'primer_concentration_um' -> 'primer_concentration'; 'gas_flow_rate_ml_per_min' -> 'gas_flow_rate'."""
    tokens = [t for t in base.split("_") if t]
    while len(tokens) > 1 and tokens[-1].lower() in UNIT_WORDS:
        tokens.pop()
    return "_".join(tokens) or base


def _dimension(unit: str) -> str:
    from parameter_extractor.units import _UNITS, canonical_unit
    canon = canonical_unit(unit or "")
    if canon:
        return _UNITS.get(canon, ("",))[0]
    return {"h-1": "inverse_time"}.get(unit or "", "")


def _base_tokens(column: str) -> List[str]:
    from parameter_extractor.ingestion.observations import unit_for_column
    base = column
    if unit_for_column(column) and unit_for_column(column) != "pH":
        base = re.sub(r"_(?:mL_min|per_M_hr|per_hr|mM_hr|kJ_mol|[A-Za-z%]+)$", "", column)
    return [t for t in strip_unit_words(base).lower().split("_") if t]


def canonical(column: str, unit: str = "", kind: str = "number", description: str = "") -> Optional[Convention]:
    """The conventional column for a drafted one, or None when it has none (or already is it)."""
    toks = _base_tokens(column)
    words = set(toks)
    extra = words - GENERIC_QUALIFIERS - MEASURED
    dim = _dimension(unit)
    text = kind == "text"
    measured = bool(words & MEASURED)
    out: Optional[Convention] = None
    if not text and ("ph" in words) and extra <= {"ph", "value"}:
        out = Convention("sampled_pH" if measured else "initial_pH", "", "pH as the app names it (initial / sampled)")
    elif not text and dim == "temperature" and words & {"temperature", "temp"} and extra <= {"temperature", "temp"}:
        out = Convention("sampled_temperature_C" if measured else "initial_temperature_C", "°C",
                         "the temperature columns the app uses (initial / sampled)")
    elif not text and dim == "pressure" and "pressure" in words and extra <= {"pressure"}:
        out = Convention("sampled_pressure_bar" if measured else "initial_pressure_bar", "bar",
                         "the pressure columns the app uses (initial / sampled)")
    elif not text and dim == "time" and words & {"time", "duration"} and extra <= {"time", "duration", "total",
                                                                                  "reaction", "incubation"}:
        out = Convention("", "", "a sample's time is the row column duration_hr, filled when the rows are planned")
    elif "cycle" in words or "cycles" in words:
        if not text and (dim == "" or unit == "") and (words & {"number", "count", "cycles", "n"}):
            out = Convention("cycle_number", "", "the app's wet-dry cycle count", integer=True)
        elif not text and dim == "time" and words & {"duration", "length", "time", "period"} and \
                not words & {"dry", "wet", "drying", "wetting", "phase"}:
            out = Convention("cycle_duration_hr", "h", "the app's cycle length column")
    elif text and words & {"analysis", "analytical", "detection", "quantification"} and \
            words & {"method", "methods", "technique", "techniques", "instrument"}:
        out = Convention("analysis_method", "", "the app's analysis column", kind="text")
    elif text and words <= {"solvent", "name", "type", "used"} and "solvent" in words:
        out = Convention("solvent_name", "", "the app's solvent column", kind="text")
    elif not text and dim == "volume" and words & {"volume"} and extra <= {"volume", "solvent", "total", "liquid"}:
        out = Convention("solvent_volume_mL", "mL", "the app's reaction-volume column")
    elif text and words & {"mineral", "clay", "solid", "surface"} and words <= {"mineral", "clay", "solid", "surface",
                                                                               "material", "name", "type", "or",
                                                                               "catalyst", "used", "phase"}:
        out = Convention("solid_material_name", "", "the app's solid-material column", kind="text")
    elif not text and dim == "mass" and words & {"mineral", "clay", "solid"}:
        out = Convention("solid_material_mass_g", "g", "the app's solid-material mass column")
    elif text and words & {"headspace", "atmosphere", "gas"} and words <= {"headspace", "atmosphere", "gas", "name",
                                                                          "type", "composition"}:
        out = Convention("headspace_gas_name", "", "the app's headspace gas column", kind="text")
    elif text and "vessel" in words and words & {"material", "type"}:
        out = Convention("vessel_material", "", "the app's vessel column", kind="text")
    elif text and "buffer" in words and words <= {"buffer", "name", "type", "ph", "used"}:
        out = Convention("pH_buffer", "", "the app's buffer column", kind="text")
    elif not text and words & {"replicate", "replicates", "repeats"} and words <= {"replicate", "replicates",
                                                                                   "repeats", "number", "n", "count"}:
        out = Convention("replicates", "", "the app's replicate count", integer=True)
    elif not text and dim == "volume_rate" or (not text and unit in ("mL/min", "mL min-1") and
                                                words & {"flow"} and extra <= {"flow", "rate", "liquid", "pump"}):
        out = Convention("flow_rate_mL_min", "mL/min", "the app's flow-rate column")
    elif not text and words & {"longest", "max", "maximum"} and words & {"oligomer", "oligomers", "polymer"} and \
            "length" in words:
        out = Convention("max_oligomer_length_nt", "nt", "the app's longest-oligomer column")
    if out is not None and out.column == column:
        return None
    return out
