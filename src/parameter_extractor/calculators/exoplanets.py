"""
Post-processing for the exoplanet pack (packs/exoplanets): fills the columns the
NASA Exoplanet Archive derives from the reported ones, the same way it does.

  row_labels         hostname = the set (host star), pl_name = the sample (planet;
                     a "[solution]" suffix -- one row per fit -- goes to pl_fitlabel),
                     pl_letter = the planet's letter
  exoplanet_masses   Earth-unit twins of Jupiter-unit masses and radii (and their
                     uncertainties), and the "best mass" columns pl_bmass*: the true
                     mass when the paper gives one, else M sin i, with pl_bmassprov
                     saying which -- the archive's factors (units.py)
  companion_masses   flags companions above the archive's 30 M_J limit for planets
                     (brown dwarfs, stars -- e.g. teng2023's HD 5608 B, 121 M_J): kept,
                     but the archive won't list them
  reference_names    pl_refname = this paper in the archive's style ("Teng et al.
                     2023") on every row; st_refname where this paper gave stellar
                     values; disc_refname where it reported the discovery

Every value written here is marked as calculated in its provenance.
"""
from __future__ import annotations
import re
from typing import List

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.units import _ASTRO

M_J_IN_M_E = _ASTRO["M_J"][1]
R_J_IN_R_E = _ASTRO["R_J"][1]
_SUFFIXES = ("", "err1", "err2")


def _calc(source: str) -> CellSource:
    return CellSource(origin="calculated", source=source)


def row_labels(rows: List[ExtractedRow], structure, paper_prefix: str) -> None:
    labels = {}
    for set_idx, pset in enumerate(structure.experiment_sets, start=1):
        for sample_idx, sample in enumerate(pset.samples, start=1):
            labels[f"{paper_prefix}{set_idx:03d}{sample_idx:03d}"] = (pset.set_label, sample.sample_label)
    src = CellSource(origin="structure", source="the paper's names for the system and planet")
    from parameter_extractor.calculators.exoplanet_fits import split_solution
    for row in rows:
        if row.full_id not in labels:
            continue
        host, label = labels[row.full_id]
        planet, solution = split_solution(label)       # "HD 14067 b [joint fit]": one row per solution
        set_row_value(row, "hostname", host, src)
        set_row_value(row, "pl_name", planet, src)
        if solution:                                    # the fitting-model stage may name it more fully
            set_row_value(row, "pl_fitlabel", solution, src)
        m = re.search(r"\s([a-z])$", planet.strip())
        if m:
            set_row_value(row, "pl_letter", m.group(1), src)


def exoplanet_masses(rows: List[ExtractedRow]) -> None:
    for row in rows:
        d = row_to_template_dict(row)
        for j_col, e_col, factor, unit in (("pl_msinij", "pl_msinie", M_J_IN_M_E, "M_J"),
                                           ("pl_massj", "pl_masse", M_J_IN_M_E, "M_J"),
                                           ("pl_radj", "pl_rade", R_J_IN_R_E, "R_J")):
            for suffix in _SUFFIXES:
                value = d.get(j_col + suffix)
                if isinstance(value, (int, float)) and d.get(e_col + suffix) in (None, ""):
                    set_row_value(row, e_col + suffix, float(f"{value * factor:.10g}"),
                                  _calc(f"{j_col + suffix} x {factor:g} ({unit} -> Earth units)"))
            lim = d.get(j_col + "lim")
            if lim not in (None, "") and d.get(e_col + "lim") in (None, ""):
                set_row_value(row, e_col + "lim", lim, _calc(f"same as {j_col}lim"))
        d = row_to_template_dict(row)
        best, prov = (("pl_massj", "pl_masse"), "Mass") if d.get("pl_massj") not in (None, "") else \
                     (("pl_msinij", "pl_msinie"), "Msini") if d.get("pl_msinij") not in (None, "") else (None, None)
        if best is None:
            continue
        for src_col, dst_col in ((best[0], "pl_bmassj"), (best[1], "pl_bmasse")):
            for suffix in _SUFFIXES + ("lim",):
                value = d.get(src_col + suffix)
                if value not in (None, ""):
                    set_row_value(row, dst_col + suffix, value, _calc(f"best mass: {src_col + suffix}"))
        set_row_value(row, "pl_bmassprov", prov, _calc("best mass is the true mass" if prov == "Mass"
                                                       else "best mass is M sin i (no true mass given)"))


ARCHIVE_MASS_LIMIT_MJ = 30.0         # the archive's inclusion limit (mass or M sin i)
HYDROGEN_BURNING_MJ = 75.0


def companion_masses(rows: List[ExtractedRow]) -> List[str]:
    """Messages for companions too heavy to be planets in the archive's sense."""
    out = []
    for row in rows:
        d = row_to_template_dict(row)
        mass = d.get("pl_bmassj")
        if not isinstance(mass, (int, float)) or mass <= ARCHIVE_MASS_LIMIT_MJ:
            continue
        kind = "a low-mass star" if mass > HYDROGEN_BURNING_MJ else "a brown dwarf"
        out.append(f"{d.get('pl_name') or row.full_id}: mass {mass:g} M_J is above the NASA Exoplanet Archive's "
                   f"{ARCHIVE_MASS_LIMIT_MJ:g} M_J limit for planets -- probably {kind}; it's kept in the CSV, "
                   f"but the archive won't list it. Remove the row if it shouldn't be in the dataset.")
    return out


def reference_name(authors: List[str], year) -> str:
    """The archive's style: 'Teng 2023', 'Teng & Sato 2023', 'Teng et al. 2023'."""
    surnames = [_surname(a) for a in authors if a and a.strip()]
    if not surnames or not year:
        return ""
    if len(surnames) == 1:
        return f"{surnames[0]} {year}"
    if len(surnames) == 2:
        return f"{surnames[0]} & {surnames[1]} {year}"
    return f"{surnames[0]} et al. {year}"


def _surname(name: str) -> str:
    if "," in name:                                   # "Teng, H.-Y."
        return name.split(",")[0].strip().title()
    name = re.sub(r"[*†‡∗]|\d+$", "", name).strip()
    parts = [p for p in name.split() if not re.fullmatch(r"(?:[A-Z]\.?-?)+", p)]   # drop initials
    last = parts[-1] if parts else name.split()[-1]
    return last.title() if last.isupper() else last


def reference_names(rows: List[ExtractedRow], metadata) -> str:
    ref = reference_name(list(metadata.authors or []), metadata.year_published)
    if not ref:
        return ""
    src = _calc(f"this paper ({ref})")
    for row in rows:
        d = row_to_template_dict(row)
        set_row_value(row, "pl_refname", ref, src)
        if any(k.startswith("st_") and k != "st_refname" and v not in (None, "") for k, v in d.items()):
            set_row_value(row, "st_refname", ref, src)
        if any(d.get(k) not in (None, "") for k in ("discoverymethod", "disc_year", "disc_facility")):
            set_row_value(row, "disc_refname", ref, src)
    return ref
