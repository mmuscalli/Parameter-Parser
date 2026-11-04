"""
Species name matching: map the names papers (and the model) use onto the
controlled vocabulary's names, so the same chemical always lands in the same
column -- "sodium chloride" / "NaCl(aq)" -> NaCl, "glycine" -> Gly,
"diglycine" / "(Gly)2" / "Gly2" -> Gly-Gly, "tetraglycine" -> (Gly)4, "Ca2+" -> Ca+2,
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


COMPACT_RUN = 4        # a run of this many of one residue is written '(Gly)4' (Mickey, 2026-11-04)


def peptide_name(codes: List[str]) -> str:
    """A peptide's name (Mickey, 2026-11-04; replaces '<n>peptide_<AA>'): its sequence, N- to C-terminus, in
    three-letter codes joined by '-' -- 'Gly-Gly', 'Gly-Gly-Gly', 'Gly-Ala-Ala' -- with a run of 4 or more of one
    residue written '(Gly)n': '(Gly)4', '(Gly)10', 'Gly-(Ala)4'. A peptide is then a compound like any other: its
    columns are '<role>_<name>_<phase>_<unit>' and it can be shown under a PubChem synonym (compound_names.py)."""
    parts, i = [], 0
    while i < len(codes):
        j = i
        while j < len(codes) and codes[j] == codes[i]:
            j += 1
        n = j - i
        parts += [f"({codes[i]}){n}"] if n >= COMPACT_RUN else [codes[i]] * n
        i = j
    return "-".join(parts)


def peptide_length(name: str) -> Optional[int]:
    """Residues in a peptide named by the convention ('Gly-Gly' 2, '(Gly)10' 10, 'cyclo_Gly-Gly' 2), else None."""
    codes = peptide_codes(name.removeprefix("cyclo_"))
    return len(codes) if codes else None


def cyclic_name(codes: List[str]) -> str:
    """Cyclic peptides, homo- or heteromeric (Mickey, 2026-10-15): 'cyclo_' + the sequence,
    residues as given ('cyclo_Gly-Gly' = the glycine diketopiperazine, 'cyclo_Val-Gly')."""
    return "cyclo_" + peptide_name(codes)


def _aa_code(text: str) -> Optional[str]:
    t = re.sub(r"^(?:dl|l|d)-", "", text.strip().lower())
    return next((c for c, full in AMINO_ACIDS.items() if t in (c.lower(), full)), None)


def cyclic_codes(name: str) -> Optional[List[str]]:
    """Residues of a cyclic peptide: 'cyclo(Gly-Ala)', 'c(Gly-Gly)', 'cyclo-Gly-Ala',
    'DKP_Gly' (the old template name), 'glycine diketopiperazine', 'Ala-DKP', 'alanine anhydride',
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
    'GlyAlaAla', 'H-Gly-L-Ala-OH', 'glycylalanylalanine', 'glycyl-alanine', '(Gly)4', 'Gly-(Ala)4'.
    None if it isn't one (or has a single residue)."""
    t = _STEREO.sub("", name.strip())
    t = re.sub(r"^H-|-OH$", "", t)
    t = re.sub(rf"\(({_AA_CODE})\)(\d{{1,3}})", lambda m: "-".join([m.group(1)] * int(m.group(2))), t)
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


# ---- nucleic-acid oligomers (Mickey, 2026-11-03; the counterpart of the peptide convention) ----
# '<n>mer_<nucleotide>': n = chain length, the nucleotide by its base letter (RNA A C G U; DNA dA dC dG dT):
# '4mer_A' (adenylate tetramer, (pA)4), '43mer_U', '12mer_dT'; a mixed oligomer by its letters as the paper gives
# them -- a sequence, or a composition when the order wasn't determined -- '3mer_AAU', '3mer_dATG'.
NUCLEOTIDE_LETTERS = {"A": "adenylate", "C": "cytidylate", "G": "guanylate", "U": "uridylate", "T": "thymidylate"}
_BASE = r"(?:d[ACGT]|[ACGU])"
_NT_WORDS = {"adenylate": "A", "adenylic acid": "A", "adenosine": "A", "cytidylate": "C", "cytidylic acid": "C",
             "cytidine": "C", "guanylate": "G", "guanylic acid": "G", "guanosine": "G", "uridylate": "U",
             "uridylic acid": "U", "uridine": "U", "thymidylate": "dT", "thymidylic acid": "dT", "thymidine": "dT",
             "deoxyadenylate": "dA", "deoxyadenosine": "dA", "deoxycytidylate": "dC", "deoxycytidine": "dC",
             "deoxyguanylate": "dG", "deoxyguanosine": "dG"}
_MER_WORDS = {"monomer": 1, "dimer": 2, "trimer": 3, "tetramer": 4, "pentamer": 5, "hexamer": 6, "heptamer": 7,
              "octamer": 8, "nonamer": 9, "decamer": 10, "undecamer": 11, "dodecamer": 12}


def oligonucleotide_name(n: int, letters: str) -> str:
    """'4mer_A', '3mer_AAU', '12mer_dT', '3mer_dATG' (see above)."""
    return f"{n}mer_{letters}"


def _letters(text: str) -> Optional[str]:
    """'A', 'dT', 'AAU' or 'dATG' when `text` is a base letter / letters, else None."""
    t = text.strip()
    if re.fullmatch(_BASE, t):
        return t
    if re.fullmatch(r"[ACGU]{2,}", t):
        return t
    if re.fullmatch(r"d[ACGT]{2,}", t):
        return t
    return None


def oligonucleotide_match(name: str) -> Optional[str]:
    """The convention's name for an oligonucleotide written another way: '(pA)4', '(Ap)3', '(dT)12', 'A 4-mer',
    '4-mer of A', 'oligo(A) 10-mer', '10-mer (G)', 'U43', 'adenylate tetramer', 'tetraadenylate', '3mer_AAU'.
    None otherwise (also for poly(A) of no stated length, and for linkage-specific isomers like pA3'pA)."""
    t = re.sub(r"\s+", " ", name.strip())
    m = re.fullmatch(rf"(\d{{1,3}})mer_(d?[ACGTU]+)", t)
    if m and _letters(m.group(2)):
        return t
    m = re.fullmatch(rf"\(\s*p?({_BASE})p?\s*\)\s*_?(\d{{1,3}})", t)                     # (pA)4, (Ap)3, (dT)12
    if m:
        return oligonucleotide_name(int(m.group(2)), m.group(1))
    m = re.fullmatch(rf"(?:oligo\s*\(\s*)?(d?[ACGTU]+)(?:\s*\))?[\s_-]*(\d{{1,3}})\s*-?\s*mers?", t, re.IGNORECASE) or \
        re.fullmatch(rf"(\d{{1,3}})\s*-?\s*mers?\s*(?:of\s+|\(\s*)?(?:oligo\s*\(\s*)?(d?[ACGTU]+)\s*\)?\)?", t)
    if m:
        a, b = m.groups()
        letters, n = (a, b) if not a.isdigit() else (b, a)
        if _letters(letters):
            return oligonucleotide_name(int(n), letters)
    m = re.fullmatch(r"([ACGU])(\d{2,3})", t)                       # 'U43' (Song 2024: U43 by MS)
    if m:
        return oligonucleotide_name(int(m.group(2)), m.group(1))
    low = t.lower()
    m = re.fullmatch(r"(?:oligo)?([a-z ]+?)\s+(" + "|".join(_MER_WORDS) + r")", low)    # adenylate tetramer
    if m and m.group(1).strip() in _NT_WORDS:
        return oligonucleotide_name(_MER_WORDS[m.group(2)], _NT_WORDS[m.group(1).strip()])
    m = re.fullmatch(r"(di|tri|tetra|penta|hexa|hepta|octa|nona|deca)([a-z ]+)", low)   # tetraadenylate
    if m and m.group(2).strip() in _NT_WORDS and m.group(2).strip().endswith(("ate", "ic acid")):
        return oligonucleotide_name(_OLIGO_PREFIX[m.group(1)], _NT_WORDS[m.group(2).strip()])
    return None


def vocabulary() -> Tuple[str, ...]:
    from parameter_extractor.packs import current
    return tuple(current().species_names)


def _salt_formula(cation: str, anion: str) -> List[str]:
    """Plausible formulas for a named salt, e.g. ('Ca', 'Cl') -> ['CaCl', 'CaCl2', 'CaCl3']."""
    return [f"{cation}{anion}", f"{cation}{anion}2", f"{cation}{anion}3"]


def _oligomer(n: int, aa: str) -> str:
    return peptide_name([aa] * n)


def match_species(name: str, vocab: Optional[Tuple[str, ...]] = None) -> Optional[Tuple[str, str]]:
    """(canonical name, how it was matched), or None if no rule applies. Returns the
    canonical form even when it isn't in the vocabulary for peptides (e.g.
    '(Gly)14'), so new variables still get consistent names."""
    vocab = vocab or vocabulary()
    vocab_set = set(vocab)
    if not name:
        return None
    raw = name.strip()
    cyclic = cyclic_codes(raw)                    # before the exact match: the template's DKP_Gly too
    if cyclic:
        return cyclic_name(cyclic), "cyclic peptide"
    oligo = oligonucleotide_match(raw)            # nucleic-acid oligomers: '(pA)4' -> '4mer_A'
    if oligo:
        return oligo, "exact" if oligo == raw else "oligonucleotide"
    m = re.fullmatch(r"(\d+)peptide_([A-Z][a-z]{2})", raw)   # the old convention ('3peptide_Gly', before 2026-11-04)
    if m and int(m.group(1)) >= 2 and m.group(2) in AMINO_ACIDS:
        return _oligomer(int(m.group(1)), m.group(2)), "peptide name (old naming)"
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


# ---- one name per species within a paper (Mickey, 2026-11-02, Riggi2023: the chemistry step wrote
# "adenosine 5'-phosphorimidazolide (ImpA)", the figure suggestions "ImpA" -- two variables for one molecule) ----

_DEFINED = re.compile(r"^(?P<full>.+?)\s*\(\s*(?P<abbr>[A-Za-z][A-Za-z0-9'′+\-]{0,11})\s*\)\s*$")
_GLUE = r"(?:\(cid:\d+\)|[^A-Za-z0-9])*"       # anything between a name's words in the PDF text (primes, '(cid:48)')


def _is_abbreviation(abbr: str, full: str) -> bool:
    letters = re.sub(r"[^a-z]", "", abbr.lower())
    return (any(c.isupper() for c in abbr) and len(abbr) < len(full) and " " not in abbr
            and not re.fullmatch(r"[IVX]+", abbr)        # a roman-numeral compound label isn't one
            # its letters come from the name: '200 mM d-ribose (Wako)' names the supplier (hirakawa2025)
            and all(c in full.lower() for c in letters))


def abbreviations_in(text: str, names) -> dict:
    """{full name (lower case): abbreviation} for species names the paper itself defines as
    'full name (ABBR)' -- in the name as given, or in the paper's text."""
    found = {}
    for name in names:
        m = _DEFINED.match(name or "")
        if m and _is_abbreviation(m.group("abbr"), m.group("full")):
            found[m.group("full").strip().lower()] = m.group("abbr")
            continue
        words = re.findall(r"[A-Za-z0-9]+", name or "")
        if len(words) < 2 or not text:           # a one-word name is an abbreviation or plain name already
            continue
        pattern = _GLUE.join(map(re.escape, words)) + r"\s*\(\s*([A-Za-z][A-Za-z0-9'′+\-]{0,11})\s*\)"
        hit = re.search(pattern, text, re.IGNORECASE)
        if hit and _is_abbreviation(hit.group(1), name):
            found[name.strip().lower()] = hit.group(1)
    return found


def preferred_name(name: str, abbreviations: dict) -> str:
    """The one name a species goes by in this paper: the abbreviation the paper defines for it ('ImpA'),
    unless only the full name is a vocabulary species (then that)."""
    m = _DEFINED.match(name or "")
    full = (m.group("full") if m and _is_abbreviation(m.group("abbr"), m.group("full")) else name or "").strip()
    abbr = abbreviations.get(full.lower())
    if not abbr:
        return name
    if match_species(full) and not match_species(abbr):
        return match_species(full)[0]
    return abbr
