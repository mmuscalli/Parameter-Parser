"""
Species name matching: map the names papers (and the model) use onto the
controlled vocabulary's names, so the same chemical always lands in the same
column -- "sodium chloride" / "NaCl(aq)" -> NaCl, "glycine" -> Gly,
"diglycine" / "Gly-Gly" / "(Gly)2" / "Gly2" -> 2peptide_Gly, "Ca2+" -> Ca+2,
"CuCl2·2H2O" -> CuCl2, ...

Deterministic and conservative: only exact rules and a curated synonym table,
generated from the vocabulary's own naming patterns -- never fuzzy guessing.
(`closest_names` does fuzzy matching, but only to SUGGEST an existing column
in the review screen; it never maps anything by itself.) Matches are recorded
in the value's provenance.
"""
from __future__ import annotations
import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple


AMINO_ACIDS = {  # 3-letter code -> full name
    "Ala": "alanine", "Arg": "arginine", "Asn": "asparagine", "Asp": "aspartic acid", "Cys": "cysteine",
    "Gln": "glutamine", "Glu": "glutamic acid", "Gly": "glycine", "His": "histidine", "Ile": "isoleucine",
    "Leu": "leucine", "Lys": "lysine", "Met": "methionine", "Phe": "phenylalanine", "Pro": "proline",
    "Ser": "serine", "Thr": "threonine", "Trp": "tryptophan", "Tyr": "tyrosine", "Val": "valine",
}
_EXTRA_AA_NAMES = {"aspartate": "Asp", "glutamate": "Glu"}
_ONE_LETTER = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu", "G": "Gly",
               "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser",
               "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val"}
_OLIGO_PREFIX = {"di": 2, "tri": 3, "tetra": 4, "penta": 5, "hexa": 6, "hepta": 7, "octa": 8, "nona": 9,
                 "deca": 10, "undeca": 11, "dodeca": 12, "trideca": 13}
_CATIONS = {"sodium": "Na", "potassium": "K", "lithium": "Li", "caesium": "Cs", "cesium": "Cs",
            "rubidium": "Rb", "magnesium": "Mg", "calcium": "Ca", "barium": "Ba", "strontium": "Sr",
            "ammonium": "NH4", "copper(ii)": "Cu", "cupric": "Cu", "copper": "Cu", "iron(ii)": "Fe",
            "ferrous": "Fe", "iron(iii)": "Fe", "ferric": "Fe", "zinc": "Zn", "nickel": "Ni",
            "manganese": "Mn", "cadmium": "Cd", "lead": "Pb"}
_ANIONS = {"chloride": "Cl", "hydroxide": "OH", "bromide": "Br", "carbonate": "CO3",
           "bicarbonate": "HCO3", "hydrogen carbonate": "HCO3", "cyanide": "CN"}
_COMMON = {"urea": "urea", "imidazole": "imidazole", "cyanamide": "cyanamide", "glycinamide": "glycinamide",
           "edta": "EDTA", "atp": "ATP", "amp": "AMP", "ump": "UMP", "trimetaphosphate": "sodium_triMP",
           "sodium trimetaphosphate": "sodium_triMP", "stmp": "sodium_triMP", "carbonyl sulfide": "COS",
           "hydrogen sulfide": "H2S", "sulfur dioxide": "SO2", "carbon monoxide": "CO",
           "carbon disulfide": "CS2",
           # salts whose formulas the cation+anion rule can't build (subscripted anions, complexes)
           "potassium ferricyanide": "K3[Fe(CN)6]", "potassium hexacyanoferrate(iii)": "K3[Fe(CN)6]",
           "potassium ferrocyanide": "K4[Fe(CN)6]", "potassium hexacyanoferrate(ii)": "K4[Fe(CN)6]",
           "sodium carbonate": "Na2CO3", "potassium carbonate": "K2CO3", "sodium sulfite": "Na2SO3",
           "sodium hydrogensulfite": "NaHSO3", "sodium hydrogen sulfite": "NaHSO3", "sodium bisulfite": "NaHSO3"}
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻−–", "01234567890123456789+---")


# peptide residues as named inside a peptide: "glycyl", "alanyl", ... (N- to C-terminus)
_ACYL = {"Gly": "glycyl", "Ala": "alanyl", "Val": "valyl", "Leu": "leucyl", "Ile": "isoleucyl", "Ser": "seryl",
         "Thr": "threonyl", "Cys": "cysteinyl", "Met": "methionyl", "Phe": "phenylalanyl", "Tyr": "tyrosyl",
         "Trp": "tryptophyl", "His": "histidyl", "Lys": "lysyl", "Arg": "arginyl", "Pro": "prolyl",
         "Asp": "aspartyl", "Glu": "glutamyl", "Asn": "asparaginyl", "Gln": "glutaminyl"}
_AA_CODE = "(?:" + "|".join(AMINO_ACIDS) + ")"
_STEREO = re.compile(r"(?<![A-Za-z])(?:DL|L|D)-(?=[A-Z])")


def peptide_name(codes: List[str]) -> str:
    """The naming convention for peptides (Mickey, 2026-10-15): a homopolymer's order
    doesn't matter -> '<n>peptide_<AA>' ('3peptide_Gly'); a heteropolymer's does ->
    residues N- to C-terminus joined by '-' ('Gly-Ala-Ala')."""
    return _oligomer(len(codes), codes[0]) if len(set(codes)) == 1 else "-".join(codes)


def cyclic_name(codes: List[str]) -> str:
    """Cyclic peptides, homo- or heteromeric (Mickey, 2026-10-15): 'cyclo_<AA1>-<AA2>-...',
    residues as given ('cyclo_Gly-Gly' = the glycine diketopiperazine, 'cyclo_Val-Gly')."""
    return "cyclo_" + "-".join(codes)


def _aa_code(text: str) -> Optional[str]:
    t = re.sub(r"^(?:dl|l|d)-", "", text.strip().lower())
    return next((c for c, full in AMINO_ACIDS.items() if t in (c.lower(), full)), None)


def cyclic_codes(name: str) -> Optional[List[str]]:
    """Residues of a cyclic peptide: 'cyclo(Gly-Ala)', 'c(Gly-Gly)', 'cyclo-Gly-Ala',
    'DKP_Gly', 'glycine diketopiperazine', 'Ala-DKP', 'alanine anhydride',
    '2,5-diketopiperazine' / '2,5-piperazinedione' (the glycine one)."""
    t = name.strip()
    if t.startswith("cyclo_"):                   # already in the app's naming
        codes = peptide_codes(t[6:])
        return codes if codes and len(codes) >= 2 else None
    m = re.fullmatch(r"(?:cyclo|c)\s*-?\s*[(\[]\s*(.+?)\s*[)\]]", t, re.IGNORECASE) or \
        re.fullmatch(r"cyclo[-\s]+(.+)", t, re.IGNORECASE)
    if m:
        return peptide_codes(m.group(1))
    m = re.fullmatch(r"DKP_([A-Z][a-z]{2})", t)
    if m and m.group(1) in AMINO_ACIDS:
        return [m.group(1)] * 2
    low = t.lower()
    if re.fullmatch(r"(?:2,5-)?(?:diketopiperazine|piperazine-?2,5-dione|piperazinedione)", low):
        return ["Gly", "Gly"]                    # the unsubstituted DKP is cyclo(Gly-Gly)
    m = re.fullmatch(r"(.+?)[\s_-]+(?:diketopiperazine|dkp|anhydride)", low) or \
        re.fullmatch(r"(?:dkp|diketopiperazine)[\s_-]+(.+)", low)
    if m and (code := _aa_code(m.group(1))):
        return [code, code]
    return None


def peptide_codes(name: str) -> Optional[List[str]]:
    """Residue codes of a linear peptide written as a sequence: 'Gly-Ala-Ala',
    'GlyAlaAla', 'H-Gly-L-Ala-OH', 'glycylalanylalanine', 'glycyl-alanine'.
    None if it isn't one (or has a single residue)."""
    t = _STEREO.sub("", name.strip())
    t = re.sub(r"^H-|-OH$", "", t)
    if re.fullmatch(rf"{_AA_CODE}(?:-?{_AA_CODE})+", t):
        return re.findall(_AA_CODE, t)
    low = re.sub(r"(?<![a-z])(?:dl|l|d)-", "", t.lower()).replace("-", "").replace(" ", "")
    codes = []
    while low:
        for code, acyl in sorted(_ACYL.items(), key=lambda kv: -len(kv[1])):
            if low.startswith(acyl):
                codes.append(code)
                low = low[len(acyl):]
                break
        else:
            last = next((c for c, full in AMINO_ACIDS.items() if low == full.replace(" ", "")), None)
            if last and codes:
                return codes + [last]
            return None
    return None


def vocabulary() -> Tuple[str, ...]:
    from parameter_extractor.packs import current
    return tuple(current().species_names)


def _salt_formula(cation: str, anion: str) -> List[str]:
    """Plausible formulas for a named salt, e.g. ('Ca', 'Cl') -> ['CaCl', 'CaCl2', 'CaCl3']."""
    return [f"{cation}{anion}", f"{cation}{anion}2", f"{cation}{anion}3"]


def _oligomer(n: int, aa: str) -> str:
    return f"{n}peptide_{aa}"


def match_species(name: str, vocab: Optional[Tuple[str, ...]] = None) -> Optional[Tuple[str, str]]:
    """(canonical name, how it was matched), or None if no rule applies. Returns the
    canonical form even when it isn't in the vocabulary for oligopeptides (e.g.
    '14peptide_Gly'), so new variables still get consistent names."""
    vocab = vocab or vocabulary()
    vocab_set = set(vocab)
    if not name:
        return None
    raw = name.strip()
    cyclic = cyclic_codes(raw)                    # before the exact match: the template's DKP_Gly too
    if cyclic:
        return cyclic_name(cyclic), "cyclic peptide"
    m = re.fullmatch(r"(\d+)peptide_([A-Z][a-z]{2})", raw)   # the convention's own names, any length
    if m and int(m.group(1)) >= 2 and m.group(2) in AMINO_ACIDS:
        return raw, "exact" if raw in vocab_set else "peptide name"
    if raw in vocab_set:
        return raw, "exact"

    t = raw.translate(_SUBSCRIPTS)
    t = re.sub(r"\((?:aq|s|l|g)\)$", "", t).strip()               # state suffixes: NaCl(aq)
    hydrate = re.split(r"\s*[·•∙.]\s*(?:\d+\s*)?H2O$", t)[0]       # CuCl2·2H2O -> CuCl2
    for candidate in (t, hydrate, t.replace(" ", "")):
        if candidate in vocab_set:
            return candidate, "formula"
    # vocab entries that carry a hydrate (Na3PO4.12H2O): match the anhydrous name
    for v in vocab:
        if re.split(r"[.·]\s*\d*H2O$", v)[0] == hydrate and v != hydrate:
            return v, "formula (hydrate)"

    # ions: Ca2+ / Ca++ / SO4 2- / HPO4^2- -> Ca+2, SO4-2, HPO4-2 ; Cl- -> Cl-
    # (a trailing digit before the sign is tried as the charge first: "Ca2+" is Ca with charge 2)
    m = re.fullmatch(r"(.+?)\s*\^?(\d)([+-])", hydrate)
    if m:
        base, num, sign = m.group(1).replace(" ", ""), int(m.group(2)), m.group(3)
        candidate = f"{base}{sign}{num}" if num > 1 else f"{base}{sign}"
        if candidate in vocab_set:
            return candidate, "ion notation"
    m = re.fullmatch(r"([A-Z][a-z]?\d*(?:\([A-Za-z0-9]+\)\d*)?)\s*\^?(\d?)([+-]{1,3})", hydrate.replace(" ", ""))
    if m:
        base, num, signs = m.groups()
        charge = int(num) if num else len(signs)
        sign = signs[0]
        for c in (f"{base}{sign}{charge}" if charge > 1 else f"{base}{sign}", f"{base}{sign}"):
            if c in vocab_set:
                return c, "ion notation"

    low = re.sub(r"\s+", " ", hydrate.lower()).strip()
    # amino acids: "glycine", "L-alanine", "Gly", "G"
    low_aa = re.sub(r"^(?:l|d|dl)-", "", low)
    for code, full in AMINO_ACIDS.items():
        if low_aa in (full, code.lower()):
            return code, "amino acid name"
    if low_aa in _EXTRA_AA_NAMES:
        return _EXTRA_AA_NAMES[low_aa], "amino acid name"

    # oligopeptides: diglycine, (Gly)2, Gly2, Gly-Gly(-Gly), GlyGlyGly, GG, oligo(Gly)n
    m = re.fullmatch(r"(di|tri|tetra|penta|hexa|hepta|octa|nona|deca|undeca|dodeca|trideca)([a-z]+)", low_aa)
    if m:
        for code, full in AMINO_ACIDS.items():
            if m.group(2) in (full, full.replace("ine", "yl") + "ine"):
                return _oligomer(_OLIGO_PREFIX[m.group(1)], code), "oligomer name"
    compact = hydrate.replace(" ", "")
    m = re.fullmatch(r"\(?([A-Z][a-z]{2})\)?_?(\d{1,2})", compact) or re.fullmatch(r"\(([A-Z][a-z]{2})\)(\d{1,2})", compact)
    if m and m.group(1) in AMINO_ACIDS and int(m.group(2)) >= 2:
        return _oligomer(int(m.group(2)), m.group(1)), "oligomer notation"
    parts = re.findall(r"[A-Z][a-z]{2}", compact)
    if len(parts) >= 2 and len(set(parts)) == 1 and parts[0] in AMINO_ACIDS and \
            re.fullmatch(r"(?:[A-Z][a-z]{2}-?)+", compact):
        return _oligomer(len(parts), parts[0]), "oligomer notation"
    if re.fullmatch(r"([A-Z])\1+", compact) and compact[0] in _ONE_LETTER:
        return _oligomer(len(compact), _ONE_LETTER[compact[0]]), "oligomer notation"
    codes = peptide_codes(hydrate)
    if codes:                                     # Gly-Ala-Ala, glycylalanine, H-Ala-Gly-OH
        return peptide_name(codes), "peptide sequence"

    # named salts: "sodium chloride" -> NaCl, "calcium chloride" -> CaCl2
    for cname, c in _CATIONS.items():
        for aname, a in _ANIONS.items():
            if low in (f"{cname} {aname}",):
                for f in _salt_formula(c, a):
                    if f in vocab_set:
                        return f, "salt name"
    if low in _COMMON and _COMMON[low] in vocab_set:
        return _COMMON[low], "common name"
    return None


def closest_names(name: str, choices, n: int = 1, cutoff: float = 0.75) -> List[str]:
    """Fuzzy SUGGESTIONS only (for the review screen); never used to map automatically."""
    return difflib.get_close_matches(name, list(choices), n=n, cutoff=cutoff)
