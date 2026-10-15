"""
Deterministic clean-up of the chemistry step's output before rows are built:

  - species names matched onto the controlled vocabulary (names.py):
    "sodium chloride" -> NaCl, "diglycine" -> 2peptide_Gly, "Ca2+" -> Ca+2
  - names the rules don't know looked up on PubChem (pubchem.py, optional):
    the same compound (same CID) as a template species, as a species the user
    accepted in an earlier review, or as another name used in this paper gets
    that name -- "2'-CMP" and "cytidine 2'-monophosphate" become one variable.
    Underscored names ("ribose_1,2-cyclic_phosphate") are written with spaces.
  - every concentration recomputed from the value and unit AS PRINTED
    (units.py): a missing mM value is filled in when the unit is unambiguous,
    and if the model's own mM disagrees with the arithmetic, the recomputed
    value is used and the discrepancy flagged.

Each change is written into the entry's conversion_note, which ends up in the
value's provenance (hover text / observations.csv). Running it twice is
harmless.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

from parameter_extractor.names import match_species, vocabulary
from parameter_extractor.pubchem import query_name, template_species_cids
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.units import canonical_unit, convert

RELATIVE_TOLERANCE = 0.01


@dataclass
class NormalizationNote:
    kind: str          # "name_matched", "unit_filled", "unit_corrected"
    message: str
    quote: str = ""
    source: str = ""


def _append_note(entry, text: str) -> None:
    entry.conversion_note = f"{entry.conversion_note}; {text}" if entry.conversion_note else text


def _rename(s, canonical: str, how: str, notes: List[NormalizationNote]) -> None:
    original = s.name
    s.name = canonical
    _append_note(s, f"name matched: '{original}' -> {canonical} ({how})")
    notes.append(NormalizationNote("name_matched", f"'{original}' -> {canonical} ({how})",
                                   s.quote or "", s.source or ""))


def _identify(chemistry: ChemistryExtraction, pubchem, registry, notes: List[NormalizationNote],
              rule_matched: set) -> None:
    """PubChem pass over the names the rules didn't match (`rule_matched`: ids of entries they did)."""
    vocab = set(vocabulary())
    template_cids = template_species_cids()
    seen_in_paper = {}                            # CID -> first name used for it in this paper
    for s in chemistry.solutes:
        if s.name in vocab or id(s) in rule_matched:     # the rules' names (e.g. 14peptide_Gly) stand
            continue
        cleaned = query_name(s.name)
        if cleaned != s.name:
            s.name = cleaned                      # cosmetic: no note needed
        found = pubchem.lookup(s.name) if pubchem else None
        if found is None:
            continue
        s.pubchem_cid, s.pubchem_title = found.cid, found.title
        how = f"same compound on PubChem, CID {found.cid}"
        if found.cid in template_cids:
            _rename(s, template_cids[found.cid], how, notes)
        elif registry is not None and (known := registry.species_for_cid(found.cid)) and known != s.name:
            _rename(s, known, how + ", accepted in an earlier review", notes)
        elif seen_in_paper.setdefault(found.cid, s.name) != s.name:
            _rename(s, seen_in_paper[found.cid], how, notes)


def _rename_ratio_species(chemistry: ChemistryExtraction, original) -> None:
    """Molar ratios name species as the model first wrote them: give them the
    names their solute entries ended up with."""
    final = {}
    for entry, name in original:
        final.setdefault(" ".join(name.lower().split()), entry.name)
    for r in chemistry.molar_ratios:
        for field in ("species", "reference_species"):
            name = getattr(r, field)
            renamed = final.get(" ".join(name.lower().split()))
            if renamed is None:
                matched = match_species(name)
                renamed = matched[0] if matched else query_name(name)
            setattr(r, field, renamed)


def normalize_chemistry(chemistry: ChemistryExtraction, pubchem=None, registry=None) -> List[NormalizationNote]:
    """`pubchem`: a pubchem.PubChem (None = no lookups); `registry`: for species
    the user accepted earlier."""
    notes: List[NormalizationNote] = []
    original = [(s, s.name) for s in chemistry.solutes]
    rule_matched = set()
    for s in chemistry.solutes:
        matched = match_species(s.name)
        if matched:
            rule_matched.add(id(s))
            if matched[0] != s.name:
                _rename(s, matched[0], matched[1], notes)
    _identify(chemistry, pubchem, registry, notes, rule_matched)
    _rename_ratio_species(chemistry, original)
    for s in chemistry.solutes:
        unit = canonical_unit(s.concentration_unit_raw) if s.concentration_unit_raw else None
        if s.concentration_value is None or unit is None:
            continue
        computed = convert(s.concentration_value, unit, "mM")
        if computed is None:                       # not a concentration unit (e.g. %, mass)
            continue
        computed = float(f"{computed:.10g}")
        printed = f"{s.concentration_value:g} {s.concentration_unit_raw}"
        if s.concentration_mM is None:
            s.concentration_mM = computed
            _append_note(s, f"mM computed by the pipeline from {printed}")
            notes.append(NormalizationNote("unit_filled", f"{s.name}: {printed} -> {computed:g} mM",
                                           s.quote or "", s.source or ""))
        elif abs(s.concentration_mM - computed) > RELATIVE_TOLERANCE * max(abs(computed), 1e-12):
            model_value = s.concentration_mM
            s.concentration_mM = computed
            _append_note(s, f"mM corrected by the pipeline: {printed} = {computed:g} mM "
                            f"(the model had {model_value:g} mM)")
            notes.append(NormalizationNote(
                "unit_corrected",
                f"{s.name}{' (set ' + repr(s.set_label) + ')' if s.set_label else ''}: printed as {printed}, "
                f"which is {computed:g} mM -- the extraction had {model_value:g} mM. The recomputed value "
                f"was used; please check.", s.quote or "", s.source or ""))
    return notes
