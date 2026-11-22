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
    """'primer_concentration_um' -> 'primer_concentration'; 'gas_flow_rate_ml_per_min' -> 'gas_flow_rate'. A word
    after 'log' is the quantity, not a unit: 'stellar_log_g' (surface gravity) keeps its g (2026-11-20)."""
    tokens = [t for t in base.split("_") if t]
    while len(tokens) > 1 and tokens[-1].lower() in UNIT_WORDS and tokens[-2].lower() != "log":
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


# ---- the research area's units (Mickey, 2026-11-20) ------------------------------------------------------------------
# Everything above is the lab-chemistry datasets' convention: °C, hours, mM, bar, initial_ / sampled_ columns. A
# research area whose papers report astronomy units keeps the units of its field instead: the accuracy evaluation's
# drafted exoplanet pack (Phase 1) had been given stellar temperatures in °C and orbital periods in hours, although the
# design asked for K and days. The field is read from the units the design and the surveys give, locally: units only
# the astronomy table knows (planet and star masses and radii, au, parsecs, solar luminosities, Earth fluxes) and
# Julian dates. Units both fields use (K, days, degrees, %, km/s) don't decide it.
LAB, ASTRONOMY = "lab", "astronomy"
UNIT_SYSTEMS = (LAB, ASTRONOMY)
_ASTRONOMY_SIGNS = {"mass", "length", "distance", "luminosity", "flux"}
ASTRONOMY_MIN, ASTRONOMY_SHARE = 3, 0.2


def julian_date(unit: str) -> bool:
    from parameter_extractor.units import _JD_OFFSET, _JD_PLAIN
    u = (unit or "").strip()
    return bool(u) and bool(_JD_PLAIN.match(u) or _JD_OFFSET.match(u))


def astronomy_unit(unit: str) -> bool:
    """A unit only astronomy uses: in the astronomy table, of a dimension the chemistry table has no unit for, or a
    Julian date ('M_J', 'R_sun', 'au', 'pc', 'L_sun', 'S_E', 'BJD-2457000'; not 'K', 'd', 'deg', '%')."""
    from parameter_extractor.units import _ASTRO, _LOG_OF, astro_unit, canonical_unit
    u = (unit or "").strip()
    m = _LOG_OF.match(u)
    if m:
        u = m.group(1)
    if julian_date(u):
        return True
    a = astro_unit(u) if u else None
    return bool(a) and not canonical_unit(u) and _ASTRO[a][0] in _ASTRONOMY_SIGNS


def unit_system(units) -> str:
    """ASTRONOMY when at least ASTRONOMY_MIN of the numeric values' units, and ASTRONOMY_SHARE of them, are astronomy
    units; else LAB."""
    given = [u for u in units if (u or "").strip() and (u or "").strip().lower() not in ("none", "-", "unitless")]
    astro = sum(astronomy_unit(u) for u in given)
    return ASTRONOMY if astro >= ASTRONOMY_MIN and astro >= ASTRONOMY_SHARE * len(given) else LAB


def astronomy_column(base: str, unit: str):
    """(column, stored unit) in astronomy's conventions, or None for a unit the astronomy table doesn't know: the
    unit as the field writes it (the astronomy table's spelling) ends the name -- 'orbital_period' + 'd' ->
    ('orbital_period_d', 'd'), 'planet_mass' + 'M_earth' -> ('planet_mass_M_E', 'M_E'), a Julian date with an offset
    stored as the full date ('BJD-2457000' -> '_BJD', 'BJD'), 'log(L_sun)' -> '_log_L_sun'."""
    from parameter_extractor.units import _LOG_OF, astro_unit, unit_slug
    u = (unit or "").strip()
    if julian_date(u):
        stored = re.split(r"\s*[-−–]\s*", u)[0].strip()
        stored = re.sub(r"\s+", "_", stored) or "BJD"
    else:
        m = _LOG_OF.match(u)
        inner = astro_unit(m.group(1)) if m else None
        if m and inner:
            stored = f"log({inner})"
        else:
            stored = astro_unit(u) if u else None
            if not stored:
                return None
    suffix = "_" + unit_slug(stored)
    if base.lower().endswith(suffix.lower()):
        base = base[: -len(suffix)]
    return base + suffix, stored


# ---- the Exoplanet Archive's names for an astronomy design's parameters (2026-11-21) --------------------------------
# A pack drafted for exoplanet papers named its own columns ('orbital_period_d', 'stellar_mass_M_sun'), so it had none
# of the built-in exoplanet pack's logic: fit models, Earth / Jupiter masses, the archive check and fill. Drafting now
# recognises the quantities that pack records (pack_drafting._built_in_base) by the words in a column's name: every
# word set of an entry must be there (first entry that matches wins; planet before stellar where both could).
_ARCHIVE_WORDS = [
    ("pl_ratdor", [{"scaled", "semi"}, {"a", "rstar"}]),         # before the semi-major axis itself
    ("pl_orbper", [{"orbital", "period"}]), ("pl_orbsmax", [{"semi", "major"}, {"semimajor"}]),
    ("pl_orbeccen", [{"eccentricity"}]), ("pl_orbincl", [{"inclination"}]), ("pl_imppar", [{"impact", "parameter"}]),
    ("pl_orblper", [{"periastron"}, {"periapsis"}, {"omega"}]), ("pl_rvamp", [{"semi", "amplitude"}, {"rv", "amplitude"}]),
    ("pl_tranmid", [{"conjunction"}, {"transit", "mid"}, {"transit", "midpoint"}, {"transit", "epoch"}]),
    ("pl_trandur", [{"transit", "duration"}]), ("pl_trandep", [{"transit", "depth"}]),
    ("pl_ratror", [{"radius", "ratio"}]),
    ("pl_massj", [{"planet", "mass"}, {"planetary", "mass"}, {"minimum", "mass"}]),
    ("pl_radj", [{"planet", "radius"}, {"planetary", "radius"}]), ("pl_dens", [{"planet", "density"}]),
    ("pl_eqt", [{"equilibrium", "temperature"}]), ("pl_insol", [{"insolation"}, {"irradiation"}]),
    ("st_teff", [{"stellar", "effective", "temperature"}, {"host", "effective", "temperature"}, {"st", "teff"}]),
    ("st_logg", [{"stellar", "log", "g"}, {"surface", "gravity"}]), ("st_met", [{"metallicity"}]),
    ("st_mass", [{"stellar", "mass"}, {"host", "mass"}]), ("st_rad", [{"stellar", "radius"}, {"host", "radius"}]),
    ("st_lum", [{"stellar", "luminosity"}, {"host", "luminosity"}]), ("st_dens", [{"stellar", "density"}]),
    ("st_age", [{"stellar", "age"}, {"host", "age"}]), ("st_rotp", [{"rotation", "period"}]),
    ("st_vsin", [{"vsini"}, {"v", "sin", "i"}, {"projected", "rotational"}]), ("st_spectype", [{"spectral", "type"}]),
    ("st_radv", [{"systemic", "velocity"}, {"radial", "velocity", "systemic"}]),
    ("sy_dist", [{"stellar", "distance"}, {"system", "distance"}, {"distance", "pc"}]), ("sy_plx", [{"parallax"}]),
    ("discoverymethod", [{"detection", "method"}, {"discovery", "method"}]),
    ("disc_facility", [{"discovery", "facility"}]), ("disc_year", [{"discovery", "year"}]),
]


def archive_column(column: str) -> str:
    """The Exoplanet Archive column a drafted astronomy parameter stands for ('orbital_period_d' -> 'pl_orbper'), or
    '' when it names none (a companion's own temperature, a microlensing lens distance)."""
    words = set(re.split(r"[_\W]+", (column or "").lower())) - {""}
    if words & {"companion", "lens", "source", "einstein", "halpha", "accretion"}:
        return ""                   # another object's quantity or a method's own one, not the planet's or its host's
    for archive, alternatives in _ARCHIVE_WORDS:
        if any(alt <= words for alt in alternatives):
            if "ratio" in words and archive not in ("pl_ratror", "pl_ratdor"):
                return ""           # a mass ratio isn't a mass ('planet_mass_ratio', 'mass_ratio_to_host')
            return archive
    return ""
