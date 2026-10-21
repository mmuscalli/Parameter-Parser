"""
How an exoplanet paper obtained the values it reports: its fitting models
(exoplanet pack, stage `fit_models`; asked for by an exoplanet subject-matter
expert, 2026-10-21).

One FitModel per model/solution the paper uses to produce reported values -- a
joint RV + transit fit, a stellar SED fit, an RV-only Keplerian fit, ... Each
says which rows (planet solutions) and which host stars it produced values for,
which data went in (kind, facility, instrument, filters), whether they were fit
jointly (and whether the star was modelled together with the planets), the
software and stellar/atmosphere models, the priors and the key assumptions.
calculators/exoplanet_fits.py turns this into NEA-style columns per row.

Flat on purpose (structured-output grammar size): no Optional fields; numbers
of priors are strings as printed ('' = not given), parsed locally.
"""
from __future__ import annotations
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field

from parameter_extractor.schemas.common import Confidence

DataKind = Literal["radial velocity", "transit photometry", "SED photometry", "spectroscopy", "astrometry",
                   "imaging", "secondary eclipse", "phase curve", "transit timing", "parallax",
                   "asteroseismology", "other"]
def _require_all(schema: dict) -> None:
    schema["required"] = list(schema.get("properties", {}))


class _Strict(BaseModel):
    """Every field required in the schema sent to the model (a skipped field invites the model
    to say it in a free-text field instead, and ramble -- aa57186-25); defaults still apply
    when validating older answers."""
    model_config = ConfigDict(json_schema_extra=_require_all)


PriorShape = Literal["gaussian", "uniform", "log-uniform", "truncated gaussian", "fixed", "other"]


class FitDataset(_Strict):
    kind: DataKind
    facility: str = Field(description="Observatory / telescope / mission as printed, e.g. 'OAO 1.88 m', 'TESS', "
                                      "'Gaia DR3'; '' if not stated.")
    instrument: str = Field(description="Instrument as printed, e.g. 'HIDES', 'HARPS'; '' if not stated.")
    bands: str = Field(description="Filters / photometric bands / wavelength range as printed, e.g. "
                                   "'2MASS J, H, Ks; WISE W1-W3', 'TESS band', 'I2 cell 500-620 nm'; '' if none.")
    note: str = Field(default="", description="Dates, number of points etc. if useful; '' otherwise.")


class FitSoftware(_Strict):
    name: str = Field(description="As printed, e.g. 'EXOFASTv2', 'RadVel', 'juliet', 'emcee', 'MIST', 'isoclassify'.")
    version: str = Field(description="Version as printed ('v1.2', '2'); '' if not stated.")
    role: Literal["fitting code", "sampler", "stellar evolution models", "stellar atmosphere models",
                  "limb darkening", "other"]


class FitPrior(_Strict):
    parameter: str = Field(description="The archive column the prior is on if one matches (e.g. 'pl_orbeccen', "
                                       "'st_teff', 'pl_orbper'), else the paper's name for the parameter "
                                       "(e.g. 'RV jitter (HIDES)', 'limb darkening u1').")
    target: str = Field(description="Exact sample_label of the row (planet solution) or set_label of the star "
                                    "the prior is for; '' if it applies to every object in this model.")
    shape: PriorShape
    center: str = Field(description="Gaussian mean, or the fixed value; '' if not applicable. Numbers as printed.")
    width: str = Field(description="Gaussian standard deviation; '' if not applicable.")
    lower: str = Field(description="Lower bound (uniform, log-uniform, truncation); '' if none.")
    upper: str = Field(description="Upper bound; '' if none.")
    unit: str = Field(description="Unit the numbers are printed in; '' if dimensionless or already the "
                                  "archive column's unit.")
    as_printed: str = Field(description="The prior exactly as printed, e.g. 'N(4874, 100) K', 'U(0, 1)'.")
    source: str = Field(description="Table/section where it's stated.")


class FitAssumption(_Strict):
    text: str = Field(description="The assumption in a few words, e.g. 'circular orbit (e fixed to 0)', "
                                  "'transit is not grazing', 'no RV jitter between instruments'.")
    parameter: str = Field(default="", description="Archive column it concerns, e.g. 'pl_orbeccen'; '' if none.")
    quote: str = Field(description="Copied word for word from the paper.")
    source: str


class FitModel(_Strict):
    label: str = Field(description="Short name for the model as the paper calls it, e.g. 'RV-only Keplerian fit "
                                   "(Table 3)', 'joint RV + astrometry fit (Table 4)', 'SED fit'.")
    rows: List[str] = Field(description="Exact sample_labels (planet solutions) whose planet values come from "
                                        "this model; [] if it only gives stellar values.")
    stars: List[str] = Field(description="Exact set_labels of host stars whose stellar values come from this "
                                         "model; [] if it gives no stellar values.")
    datasets: List[FitDataset] = Field(description="Every kind of data that went into THIS model.")
    joint: bool = Field(description="True if the datasets were fit simultaneously in one model.")
    joint_description: str = Field(description="Which data were linked/fit jointly and how, in a few words, "
                                                "e.g. 'RV + TESS transits + SED fit simultaneously'; '' if not joint.")
    star_and_planets_joint: bool = Field(description="True only if a stellar model (SED, isochrones / tracks, "
                                                     "atmosphere models) and the planet models have their sampled "
                                                     "parameters linked within ONE likelihood. Earlier stellar "
                                                     "results used as priors or fixed inputs are NOT joint.")
    software: List[FitSoftware]
    priors: List[FitPrior] = Field(description="Every prior the paper states for this model.")
    assumptions: List[FitAssumption] = Field(description="Key, especially simplifying, assumptions.")
    quote: str = Field(description="A sentence from the paper describing the model, word for word.")
    source: str
    confidence: Confidence


class FitModels(_Strict):
    models: List[FitModel] = Field(default_factory=list)
    notes: str = Field(default="", description="Anything about the modelling that didn't fit above.")
