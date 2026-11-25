"""
Building a data pack's columns in the app's own formats (Mickey, 2026-11-24: the user builds variables from the
categories, compounds and units the app already has, instead of typing column names).

- Compounds: names or formulas as the user types them ('glycine', 'NaCl', 'mgcl2', 'Gly-Gly') are identified --
  the app's name rules first (names.match_species: 'glycine' -> Gly), then PubChem (its free name lookup: CID,
  title, synonyms). A compound the pack already has under the same CID keeps the pack's name. Its columns are
  built in the one compound format, `<role>_<name>_<phase>_<measure>` (flatten_to_template.species_column), for
  the roles, phase and measures chosen; the compound, its PubChem identity and its columns go to the pack (written
  directly from then on: vocabulary-defined columns).
- Other values: a name, a kind (number / text) and a unit give the column name with the app's unit suffix
  (pack_drafting.column_for: 'reaction temperature' in K -> reaction_temperature_C, stored in °C) or the
  conventional column when there is one (conventions.canonical: a temperature is initial_temperature_C). It can be
  added as a parameter of one of the pack's own steps -- then the model is asked for it, and a focused search can
  look for it.

Nothing here talks to the model; PubChem only through pubchem.PubChem (cached).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from parameter_extractor.ingestion.flatten_to_template import PHASE_CODES, SPECIES_MEASURES, species_column

# what each role and measure means, as the builder offers them
ROLES = {"initial": "starting (in the reaction at the start)", "sampled": "measured (a product or what is left)",
         "stock": "stock solution (before mixing)", "calculated": "calculated or modelled by the paper"}
PHASES = {"aq": "dissolved", "gas": "gas", "solid": "solid"}
MEASURES = {"mM": "concentration (mM)", "%yield": "yield (%)", "%recovered": "recovered (%)", "ratio": "ratio",
            "rate_mM_hr": "rate of change (mM/h)"}
assert set(MEASURES) == set(SPECIES_MEASURES)


@dataclass
class CompoundMatch:
    entered: str                       # as the user typed it
    name: str                          # the name the columns use (editable)
    cid: int = 0
    title: str = ""                    # PubChem's title
    synonyms: List[str] = field(default_factory=list)
    how: str = ""                      # how it was identified
    known: bool = False                # the pack already has it


def identify(texts: Sequence[str], pubchem=None, pack_compounds: Sequence[dict] = ()) -> List[CompoundMatch]:
    """Each entered name / formula identified: the app's rules, then PubChem (`pubchem`: a pubchem.PubChem, None =
    no lookups). `pack_compounds`: the pack's [{name, cid}] -- the same CID keeps the pack's name."""
    from parameter_extractor.compound_setup import formula_case
    from parameter_extractor.names import match_species
    from parameter_extractor.pubchem import query_name
    by_cid = {int(c.get("cid") or 0): c["name"] for c in pack_compounds if c.get("cid")}
    have = {c["name"].lower() for c in pack_compounds}
    out: List[CompoundMatch] = []
    for raw in texts:
        text = " ".join((raw or "").split())
        if not text or any(m.entered.lower() == text.lower() for m in out):
            continue
        name, how = text, ""
        ruled = match_species(text)
        if ruled:
            name, how = ruled[0], f"the app's name rules ({ruled[1]})"
        elif " " not in text and (fixed := formula_case(text)) and fixed != text:
            name, how = fixed, "a formula, element case restored"
        m = CompoundMatch(entered=text, name=query_name(name) if not ruled else name, how=how)
        hit = None
        if pubchem is not None:
            try:
                hit = pubchem.lookup(text) or (pubchem.lookup(name) if name != text else None)
            except Exception as e:                         # no internet: the rules' answer stands
                m.how = (m.how + "; " if m.how else "") + f"PubChem not reached ({type(e).__name__})"
        if hit is not None:
            m.cid, m.title = hit.cid, hit.title
            try:
                m.synonyms = list(pubchem.synonyms(hit.cid))[:40]
            except Exception:
                m.synonyms = []
            if hit.cid in by_cid:
                m.name, m.how = by_cid[hit.cid], f"this data pack's {by_cid[hit.cid]} (same PubChem CID {hit.cid})"
            else:
                m.how = (m.how + "; " if m.how else "") + f"PubChem CID {hit.cid}"
        elif not m.how:
            m.how = "not identified: kept as typed" + ("" if pubchem is not None else " (no PubChem lookup)")
        m.known = m.name.lower() in have
        out.append(m)
    return out


def compound_columns(name: str, roles: Sequence[str], phase: str = "aq", measures: Sequence[str] = ("mM",)) -> List[str]:
    """The compound's columns for these roles and measures. A yield or recovery is of a product (sampled) only; a
    stock solution and a starting composition are concentrations."""
    out = []
    for role in roles:
        for measure in measures:
            if measure.startswith("%") and role not in ("sampled", "calculated"):
                continue
            if role in ("initial", "stock") and measure not in ("mM",):
                continue
            out.append(species_column(role, name, phase, measure))
    return list(dict.fromkeys(out))


# ---- other values ---------------------------------------------------------------------------------------------------

def units_by_quantity() -> Dict[str, List[str]]:
    """{quantity (units.py dimension): [canonical units]} the unit table knows, for the unit choice."""
    from parameter_extractor.units import _UNITS
    out: Dict[str, List[str]] = {}
    for unit, (dimension, _factor) in _UNITS.items():
        out.setdefault(dimension, []).append(unit)
    return {k: v for k, v in sorted(out.items())}


@dataclass
class BuiltValue:
    column: str
    unit: str                          # the unit values are stored in ('' for text)
    kind: str                          # number | text
    description: str
    note: str = ""                     # e.g. 'the conventional column for a temperature'


def value_column(name: str, unit: str = "", kind: str = "number", description: str = "",
                 system: str = "lab") -> BuiltValue:
    """The column for a value the user describes: the conventional one when the app has it, else the name with
    the app's unit suffix (pack_drafting.column_for)."""
    from parameter_extractor.conventions import canonical
    from parameter_extractor.pack_drafting import column_for
    column, stored = column_for(name, unit, kind, system)
    conv = canonical(column, unit, kind, description) if system != "astronomy" else None
    if conv is not None and conv.column:
        conv_kind = conv.kind or kind
        return BuiltValue(conv.column, conv.unit if conv_kind != "text" else "", conv_kind,
                          description or conv.reason, f"the app's column for it: {conv.reason}")
    if conv is not None:                                   # a quantity the app records elsewhere (a row column)
        return BuiltValue(column, stored if kind != "text" else "", kind, description or " ".join(name.split()),
                          f"the app already records this elsewhere: {conv.reason}")
    note = f"stored in {stored}" if stored and stored != unit else ""
    return BuiltValue(column, stored if kind != "text" else "", kind, description or " ".join(name.split()), note)


def parameter_entry(v: BuiltValue, uncertainties: bool = False) -> dict:
    """A step parameter as the pack's stages/*.json write it."""
    entry = {"column": v.column, "description": v.description or v.column.replace("_", " ")}
    if v.kind == "text":
        entry["kind"] = "text"
    elif v.unit:
        entry["unit"] = v.unit
    if uncertainties and v.kind != "text":
        entry["uncertainties"] = True
    return entry


def valid_column(column: str) -> Optional[str]:
    """Why a column name can't be used ('' / None = fine)."""
    if not column:
        return "empty"
    if re.search(r"\s", column):
        return "has spaces"
    if column in ("full_id", "set_id", "sample_id"):
        return "is a row identifier"
    return None


__all__ = ["ROLES", "PHASES", "MEASURES", "PHASE_CODES", "CompoundMatch", "identify", "compound_columns",
           "units_by_quantity", "BuiltValue", "value_column", "parameter_entry", "valid_column"]
