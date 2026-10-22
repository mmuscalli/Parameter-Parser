You are recording HOW an astronomy paper obtained the planet and stellar
parameters it reports: the models it fit, the data in each, and the priors and
assumptions behind them. Don't extract the parameter values themselves (other
steps do that). Report only what the paper states.

One `FitModel` per model or solution that produced reported values, e.g. an
RV-only Keplerian fit, a joint RV + astrometry fit, a joint SED + RV + transit
fit, a stellar SED or isochrone fit, a spectroscopic analysis giving Teff,
log g and [Fe/H]. If the same procedure is applied to many systems, it can be
ONE model listing all of their rows and stars.

For each model:
- `rows`: the exact `sample_label`s from the structure plan whose PLANET
  values come from this model. A planet can have several rows, one per
  solution (label in [brackets]); give each solution its own model.
- `stars`: the exact `set_label`s whose STELLAR values (Teff, mass, radius,
  age, ...) come from this model. A stellar-only model has `rows` [].
- `datasets`: every kind of data that went into THIS model, with the
  facility/telescope, instrument and filters/bands as printed -- e.g. radial
  velocity from "OAO 1.88 m / HIDES"; SED photometry in "Tycho BT, VT; 2MASS
  J, H, Ks; WISE W1-W4"; astrometry from "Hipparcos; Gaia EDR3"; a parallax
  used as a prior. Spectra used only to derive stellar parameters belong to
  the stellar model.
- `joint` / `joint_description`: were the datasets fit SIMULTANEOUSLY in one
  model (linked parameters), or analysed separately and combined? Say which
  data were linked.
- `star_and_planets_joint`: true ONLY if a stellar model (an SED fit,
  stellar evolution isochrones / tracks, stellar atmosphere models) and the
  planet models have their sampled parameters LINKED WITHIN ONE LIKELIHOOD,
  so that all of them influence one another self-consistently -- e.g. the
  transit data help constrain the stellar density (mass and radius) while
  the SED and isochrones constrain the star. The classic case is a joint
  SED + isochrone + RV + transit fit (e.g. with EXOFASTv2). NOT joint: using
  stellar parameters derived beforehand (from spectra, an earlier paper, a
  separate SED or isochrone fit) as fixed inputs or as priors, even if the
  planet fit then samples them -- record those under `priors` /
  `assumptions` instead, and list that separate stellar analysis as its own
  model (with `rows` []).
- `software`: fitting codes, samplers and models with versions as printed
  (e.g. "EXOFASTv2", "RadVel 1.4", "emcee", "MIST" "v1.2" as stellar
  evolution models, "NextGen" as stellar atmosphere models). If EXOFAST is
  used, write EXOFAST's version exactly as the paper gives it (EXOFAST,
  EXOFASTv2); leave `version` '' if the paper doesn't say.
- `priors`: EVERY prior stated for the model -- shape (gaussian, uniform,
  log-uniform, truncated gaussian, fixed), its numbers as printed (`center`
  and `width` for a gaussian or the fixed value; `lower`/`upper` for bounds),
  the unit they're printed in, and `as_printed`. Name the parameter by its
  NASA Exoplanet Archive column when there is one: pl_orbper, pl_orbeccen,
  pl_orblper, pl_rvamp, pl_orbtper, pl_tranmid, pl_ratror, pl_imppar,
  pl_orbincl, st_teff, st_met, st_logg, st_mass, st_rad, st_age, st_dens,
  sy_plx, sy_dist, ... (the parameter lists of the other steps use the same
  names); otherwise the paper's own name (e.g. "RV jitter (HIDES)", "RV
  offset", "limb darkening u1 (TESS)", "dilution", "extinction A_V").
  `target`: the row or star it applies to, '' for every object in the model.
  Priors are often in a table of "priors" or in the text of the fitting
  section; a parameter "fixed to" a value is a `fixed` prior.
- `assumptions`: key, especially simplifying, assumptions behind the
  reported values, each with its quote -- e.g. a circular orbit (e fixed to
  0), a non-grazing transit, no stellar activity signal, a linear trend from
  an unseen companion, coplanar orbits, M sin i reported because the
  inclination is unknown, stellar parameters taken from an earlier paper.
- `quote` and every assumption `quote`: the paper's own words, copied exactly --
  the shortest span that shows it (at most 20 words). `source`: exact table /
  section and paragraph.

If the paper doesn't describe how some values were obtained, leave them out
rather than guessing; say so in `notes`.

Return a FitModels object.

---
STRUCTURE PLAN:

{{STRUCTURE_PLAN_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
