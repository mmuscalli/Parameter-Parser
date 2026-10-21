"""
The exoplanet pack's fitting-model columns: how each row's values were obtained
(stage `fit_models`, schemas/fit_models.py), as columns named in the NASA
Exoplanet Archive's style -- prefix pl_/st_ for the object they describe, then
"fit", lower case, flags ending in _flag, no underscores inside a name
(an exoplanet subject-matter expert's request, 2026-10-21).

Planet side (the model(s) that produced this row's planet values):
  pl_fitlabel          the paper's name(s) for the model, '; '-separated
  pl_fitdata           kinds of data in the model ('radial velocity; transit photometry')
  pl_fit<kind>_flag    1/0 per kind of data, like the archive's rv_flag / tran_flag
  pl_fit<kind>inst     facility / instrument (bands) used for that kind
  pl_fitjoint_flag     1 if the data were fit simultaneously
  pl_fitjointdesc      which data were linked, as the paper describes it
  pl_fitstjoint_flag   1 if a model constraining the STAR (SED, isochrones) was fit
                       simultaneously with the planets
  pl_fitsoftware       fitting code, samplers, models ('EXOFASTv2; MIST v1.2')
  pl_fitexofastver     1 or 2 when EXOFAST was used (version as stated)
  pl_fitassump         key assumptions ('circular orbit (e fixed to 0); ...')
  pl_fitpriors         every prior of the model as printed, incl. parameters the
                       archive has no column for (jitter, limb darkening)
Star side: the same for the model(s) that produced the host star's values --
  st_fitlabel, st_fitdata, st_fitbands (photometric bands / filters), st_fitinst,
  st_fitsoftware, st_fitmodels (stellar evolution / atmosphere models with
  versions), st_fitexofastver, st_fitjoint_flag, st_fitassump, st_fitpriors.
Priors on archive parameters, per parameter <col>:
  <col>priortype (gaussian / uniform / log-uniform / truncated gaussian / fixed /
  other), <col>priorcen (mean or fixed value), <col>priorwid (standard
  deviation), <col>priorlo / <col>priorhi (bounds) -- in the column's unit.

Everything here is copied or converted from what the model read in the paper;
nothing is inferred. Problems (unknown row labels, unconvertible prior units,
EXOFAST without a version) are returned as messages for flags.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

from parameter_extractor.ingestion.flatten_to_template import set_row_value
from parameter_extractor.schemas.fit_models import FitModel, FitModels
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow

# data kind -> column word (the archive's own where it has one: rv, tran, ast, ima, ttv)
KIND_WORD = {"radial velocity": "rv", "transit photometry": "tran", "astrometry": "ast", "imaging": "ima",
             "transit timing": "ttv", "SED photometry": "sed", "spectroscopy": "spec",
             "secondary eclipse": "occ", "phase curve": "phase", "parallax": "plx",
             "asteroseismology": "astero", "other": "other"}
PRIOR_SUFFIXES = ("priortype", "priorcen", "priorwid", "priorlo", "priorhi")
STELLAR_MODEL_ROLES = ("stellar evolution models", "stellar atmosphere models")

PLANET_COLUMNS = [
    ("pl_fitlabel", "Fitting model(s) that produced this row's planet values, as the paper names them"),
    ("pl_fitdata", "Kinds of data in the planet model(s)"),
    *[(f"pl_fit{w}_flag", f"1 if {k} data were in the planet model(s), else 0") for k, w in KIND_WORD.items()],
    *[(f"pl_fit{w}inst", f"Facility / instrument (bands) of the {k} data in the planet model(s)")
      for k, w in KIND_WORD.items()],
    ("pl_fitjoint_flag", "1 if the planet model's data were fit simultaneously"),
    ("pl_fitjointdesc", "Which data were fit jointly, as the paper describes it"),
    ("pl_fitstjoint_flag", "1 if a model constraining the star (SED, isochrones) was fit simultaneously with the planets"),
    ("pl_fitsoftware", "Software and models used for the planet values"),
    ("pl_fitexofastver", "EXOFAST version (1 or 2) if EXOFAST produced the planet values"),
    ("pl_fitassump", "Key assumptions behind the planet values"),
    ("pl_fitpriors", "Priors of the planet model(s), as printed"),
]
STELLAR_COLUMNS = [
    ("st_fitlabel", "Model(s) that produced the host star's values, as the paper names them"),
    ("st_fitdata", "Kinds of data in the stellar model(s)"),
    ("st_fitbands", "Photometric bands / filters used for the star"),
    ("st_fitinst", "Facilities / instruments of the stellar data"),
    ("st_fitsoftware", "Software used for the stellar values"),
    ("st_fitmodels", "Stellar evolution / atmosphere models (with versions)"),
    ("st_fitexofastver", "EXOFAST version (1 or 2) if EXOFAST produced the stellar values"),
    ("st_fitjoint_flag", "1 if the star was fit simultaneously with the planets"),
    ("st_fitassump", "Key assumptions behind the stellar values"),
    ("st_fitpriors", "Priors of the stellar model(s), as printed"),
]


def _parameter_units() -> Dict[str, str]:
    """Archive column -> its unit, from the pack's stage specs (numeric parameters)."""
    from parameter_extractor.stages.optional import load_specs
    return {p.column: p.unit for spec in load_specs().values() for p in spec.parameters if p.kind == "number"}


def fit_columns() -> List[Tuple[str, str]]:
    """(column, description) of every fitting-model column, in output order."""
    priors = [(c + s, f"Prior on {c}: {s[5:]}") for c in _parameter_units() for s in PRIOR_SUFFIXES]
    return PLANET_COLUMNS + STELLAR_COLUMNS + priors


def exofast_version(software) -> Tuple[Optional[int], bool]:
    """(version, used): EXOFASTv2 / 'EXOFAST' + version '2' -> 2; EXOFAST with no version -> (None, True)."""
    for s in software:
        text = f"{s.name} {s.version}"
        if "exofast" not in text.lower():
            continue
        m = re.search(r"exofast\s*(?:v(?:ersion)?\s*)?([12])\b|\bv?([12])(?:\.\d+)*\b", text, re.IGNORECASE)
        return (int(m.group(1) or m.group(2)) if m else None), True
    return None, False


def _software_text(software, roles=None) -> str:
    """'EXOFASTv2; MIST v1.2 (stellar evolution models)'; with `roles`, only those, no role names."""
    parts = []
    for s in software:
        if roles is not None and s.role not in roles:
            continue
        name = f"{s.name} {s.version}".strip()
        parts.append(name if roles is not None or s.role == "fitting code" else f"{name} ({s.role})")
    return "; ".join(parts)


def _dataset_text(d) -> str:
    where = " / ".join(x for x in (d.facility.strip(), d.instrument.strip()) if x)
    return where + (f" ({d.bands.strip()})" if d.bands.strip() else "") if where else d.bands.strip()


def _join(values) -> str:
    out = []
    for v in values:
        for part in str(v).split("; "):
            if part and part not in out:
                out.append(part)
    return "; ".join(out)


def _number(text: str) -> Optional[float]:
    text = (text or "").strip().replace("−", "-").replace("–", "-")
    try:
        return float(text)
    except ValueError:
        from parameter_extractor.units import parse_quantity
        try:
            q = parse_quantity(text)
            return q[0] if q else None
        except Exception:
            return None


def _prior_text(p) -> str:
    printed = p.as_printed.strip() or f"{p.shape} {p.center or ''} {p.width or ''} [{p.lower}, {p.upper}]"
    return f"{p.parameter}: {printed}"


def _prior_columns(p, column_unit: str) -> Tuple[Dict[str, object], str]:
    """{<col>priortype: ..., <col>priorcen: ...} in the column's unit, and a problem if any."""
    from parameter_extractor.units import convert_printed
    out: Dict[str, object] = {p.parameter + "priortype": p.shape}
    for suffix, text, is_error in (("priorcen", p.center, False), ("priorwid", p.width, True),
                                   ("priorlo", p.lower, False), ("priorhi", p.upper, False)):
        if not (text or "").strip():
            continue
        value = _number(text)
        if value is None:
            return {}, f"prior on {p.parameter} ('{p.as_printed}'): '{text}' isn't a number"
        converted, note = convert_printed(value, p.unit.strip(), column_unit, is_error=is_error)
        if converted is None:
            return {}, f"prior on {p.parameter} ('{p.as_printed}'): {note}"
        out[p.parameter + suffix] = converted
    return out, ""


def _source(model: FitModel, what: str) -> CellSource:
    return CellSource(origin="fitting models", quote=model.quote, confidence=model.confidence,
                      source=f"{model.source} -- {what}, model '{model.label}'".strip(" -"))


def prior_side(prior, model: FitModel) -> str:
    """'st' for a prior on the star, 'pl' for one on a planet or the system; a parameter the
    archive has no column for goes with the model's planets, else its star."""
    if prior.parameter.startswith("st_"):
        return "st"
    if prior.parameter.startswith(("pl_", "sy_")):
        return "pl"
    return "pl" if model.rows else "st"


def apply_fit_models(rows: List[ExtractedRow], fits: Optional[FitModels], structure,
                     paper_prefix: str) -> List[str]:
    """Write the fitting-model columns into the rows; return problems for flags."""
    if fits is None:
        return []
    labels = {}                                   # full_id -> (set_label, sample_label)
    samples, stars = set(), set()
    for set_idx, pset in enumerate(structure.experiment_sets, start=1):
        stars.add(pset.set_label)
        for sample_idx, smp in enumerate(pset.samples, start=1):
            samples.add(smp.sample_label)
            labels[f"{paper_prefix}{set_idx:03d}{sample_idx:03d}"] = (pset.set_label, smp.sample_label)
    units = _parameter_units()
    problems: List[str] = []
    for m in fits.models:
        for label in m.rows:
            if label not in samples:
                problems.append(f"Fitting model '{m.label}' names a planet row '{label}' that isn't in the "
                                f"structure plan; its description wasn't attached to any row.")
        for label in m.stars:
            if label not in stars:
                problems.append(f"Fitting model '{m.label}' names a star '{label}' that isn't in the "
                                f"structure plan.")
        version, used = exofast_version(m.software)
        if used and version is None:
            problems.append(f"Fitting model '{m.label}' uses EXOFAST, but the paper doesn't say which version "
                            f"(1 or 2); pl_fitexofastver / st_fitexofastver left empty.")
    for row in rows:
        if row.full_id not in labels:
            continue                              # e.g. a digitized figure's rows
        star, sample = labels[row.full_id]
        planet_models = [m for m in fits.models if sample in m.rows]
        # a stellar-only model describes the star on all its rows; a model that also produced
        # planet values (a joint star + planet fit) only on the rows of its own solution
        star_models = [m for m in fits.models if star in m.stars and (not m.rows or sample in m.rows)]
        if planet_models:
            _write_side(row, planet_models, "pl", sample, star, units, problems)
        if star_models:
            _write_side(row, star_models, "st", sample, star, units, problems)
    return problems


def _write_side(row, models: List[FitModel], side: str, sample: str, star: str,
                units: Dict[str, str], problems: List[str]) -> None:
    first = models[0]
    put = lambda col, value, what: set_row_value(row, col, value, _source(first, what)) \
        if value not in (None, "") else None
    put(f"{side}_fitlabel", _join(m.label for m in models), "model name")
    data = [d for m in models for d in m.datasets]
    put(f"{side}_fitdata", _join(d.kind for d in data), "kinds of data")
    version = next((v for v, _ in (exofast_version(m.software) for m in models) if v), None)
    put(f"{side}_fitexofastver", version, "EXOFAST version")
    put(f"{side}_fitassump", _join(a.text for m in models for a in m.assumptions), "assumptions")
    if side == "pl":
        for kind, word in KIND_WORD.items():
            of_kind = [d for d in data if d.kind == kind]
            put(f"pl_fit{word}_flag", 1 if of_kind else 0, f"{kind} data in the model")
            put(f"pl_fit{word}inst", _join(_dataset_text(d) for d in of_kind), f"{kind} data")
        put("pl_fitjoint_flag", 1 if any(m.joint for m in models) else 0, "joint fit")
        put("pl_fitjointdesc", _join(m.joint_description for m in models), "joint fit")
        put("pl_fitstjoint_flag", 1 if any(m.star_and_planets_joint for m in models) else 0, "star fit jointly")
        put("pl_fitsoftware", _join(_software_text(m.software) for m in models), "software")
    else:
        put("st_fitbands", _join(d.bands for d in data if d.bands.strip()), "bands")
        put("st_fitinst", _join(" / ".join(x for x in (d.facility, d.instrument) if x.strip()) for d in data),
            "instruments")
        put("st_fitsoftware", _join(_software_text([s for s in m.software if s.role not in STELLAR_MODEL_ROLES])
                                    for m in models), "software")
        put("st_fitmodels", _join(_software_text(m.software, STELLAR_MODEL_ROLES) for m in models),
            "stellar models")
        put("st_fitjoint_flag", 1 if any(m.star_and_planets_joint and m.rows for m in models) else 0,
            "star fit jointly")
    # priors: this side's archive parameters structured, all of this side's priors as text
    texts = []
    for m in models:
        for p in m.priors:
            if p.target.strip() not in ("", sample, star) or prior_side(p, m) != side:
                continue
            texts.append(_prior_text(p))
            if p.parameter in units:
                columns, problem = _prior_columns(p, units[p.parameter])
                message = f"Fitting model '{m.label}': {problem}; kept as text only."
                if problem and message not in problems:          # once, not once per row
                    problems.append(message)
                for col, value in columns.items():
                    set_row_value(row, col, value, _source(m, f"prior as printed: {p.as_printed}"))
    put(f"{side}_fitpriors", _join(texts), "priors as printed")


def split_solution(label: str) -> Tuple[str, str]:
    """'HD 14067 b [joint RV + astrometry fit]' -> ('HD 14067 b', 'joint RV + astrometry fit')."""
    m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", label or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else ((label or "").strip(), "")


def model_flags(rows: List[ExtractedRow], fits: FitModels) -> list:
    """Models the model itself wasn't sure of, and rows no model was linked to (one flag)."""
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    from parameter_extractor.validation.plausibility_checks import Flag
    flags = [Flag("low_confidence", f"Fitting model '{m.label}' was read with {m.confidence} confidence -- "
                                    f"check its data, priors and assumptions.", quote=m.quote or None,
                  source=m.source or None)
             for m in fits.models if m.confidence != "high"]
    for m in fits.models:
        # joint star + planet fit (expert, 2026-10-21): a stellar model and the planet models with their
        # sampled parameters linked in ONE likelihood; earlier stellar results used as priors are not.
        # The model's answer is kept; a claim its own listing doesn't support is flagged, both ways.
        stellar_model = (any(d.kind == "SED photometry" for d in m.datasets)
                         or any(s.role in STELLAR_MODEL_ROLES for s in m.software))
        if m.star_and_planets_joint and not (m.rows and m.stars and stellar_model):
            missing = [what for what, ok in (("planet rows", m.rows), ("stars", m.stars),
                                             ("a stellar model (SED data or isochrones / atmosphere models)",
                                              stellar_model)) if not ok]
            flags.append(Flag("fit_model", f"Fitting model '{m.label}' is marked as a joint star + planet fit, but "
                                           f"lists no {' / no '.join(missing)} -- a joint fit links a stellar "
                                           f"model's and the planets' parameters in one likelihood; stellar values "
                                           f"used only as priors don't count. Check pl_fitstjoint_flag.",
                              quote=m.quote or None, source=m.source or None))
        elif not m.star_and_planets_joint and m.rows and m.stars and stellar_model and m.joint:
            flags.append(Flag("fit_model", f"Fitting model '{m.label}' produced both planet and stellar values and "
                                           f"includes a stellar model, but isn't marked as a joint star + planet "
                                           f"fit -- check whether their parameters were linked in one likelihood "
                                           f"(pl_fitstjoint_flag = 0).", quote=m.quote or None,
                              source=m.source or None))
        if not m.rows and not m.stars:                 # e.g. a spectroscopic analysis that only fed priors
            kinds = ", ".join(sorted({d.kind for d in m.datasets})) or "no data listed"
            flags.append(Flag("fit_model", f"Fitting model '{m.label}' ({kinds}) produced no row's reported values "
                                           f"directly (e.g. it supplied priors), so it isn't in the CSV -- it's kept "
                                           f"in fit_models.output.json.", quote=m.quote or None,
                              source=m.source or None))
    unlinked = [row_to_template_dict(r).get("pl_name") or r.full_id for r in rows
                if not row_to_template_dict(r).get("pl_fitdata")]
    if unlinked and fits.models:
        flags.append(Flag("fit_model", f"No fitting model was linked to {len(unlinked)} row(s): "
                                       f"{', '.join(unlinked)} -- how their planet values were obtained isn't recorded."))
    elif not fits.models:
        flags.append(Flag("fit_model", "No fitting models were found in the paper"
                                       + (f": {fits.notes}" if fits.notes else ".")))
    return flags
