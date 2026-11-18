"""
A 'Paper summary' row holding reactants of different experiments (Mickey, 2026-11-18: Kawamura2009's summary row had
alanine 5 mM and aspartic acid 10 mM -- reactants of separate experiments, each stated once for the paper -- side by
side; "flag the problematic cells ... be careful: some papers do use several amino acids together, and the paper will
likely say so").

Only on a Paper summary row (pipeline.SUMMARY_SET): its starting compounds of one class -- amino acids, peptides,
nucleotides (the app's exact name rules; salts, buffers and condensing agents are left out: several of them together
is normal) -- when two or more are on the row. They are taken as used TOGETHER when the paper says so where it gives
them: one quote names both ("glycine and alanine (5 mM each)", "a mixture of Gly and Ala"), or the two share their
quote -- unless that quote lists them as alternatives ("0.01 M Asp, Glu, or Ala": Kawamura2009). A compound whose quote names none of the class's others is flagged on its cell (`summary_mixed`): it
was probably stated for a different experiment. Nothing is removed.
"""
from __future__ import annotations

import re
from typing import Dict, List

from parameter_extractor.schemas.row_schema import ExtractedRow
from parameter_extractor.validation.plausibility_checks import Flag

_START = re.compile(r"^initial_(.+)_(?:aq|s|gas)_mM$")


def compound_class(name: str) -> str:
    """'amino acid', 'peptide', 'nucleotide' or '' -- by the app's exact name rules, never fuzzy."""
    from parameter_extractor.names import AMINO_ACIDS, cyclic_codes, nucleotide_match, peptide_codes
    if name in AMINO_ACIDS:
        return "amino acid"
    if cyclic_codes(name) or (peptide_codes(name) and "-" in name) or re.fullmatch(r"\([A-Z][a-z]{2}\)\d+", name):
        return "peptide"
    if nucleotide_match(name):
        return "nucleotide"
    return ""


def _aliases(name: str) -> List[str]:
    """How a paper may write the compound: its code and, for an amino acid, its full name."""
    from parameter_extractor.names import AMINO_ACIDS
    out = [name, name.replace("_", " ").replace("cyclo ", "cyclo(")]
    if name in AMINO_ACIDS:
        out.append(AMINO_ACIDS[name])
    return [a for a in out if a]


def _mentions(quote: str, name: str) -> bool:
    text = (quote or "").lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(a.lower())}(?![a-z0-9])", text) for a in _aliases(name))


# a quote naming both as ALTERNATIVES ("0.01 M Asp, Glu, or Ala", Kawamura2009) says they were NOT used together
_ALTERNATIVES = re.compile(r"\b(?:or|either|instead of|alternatively|nor)\b", re.IGNORECASE)


def _used_together(quote_a: str, quote_b: str, name_a: str, name_b: str) -> bool:
    """The paper says the two were used together: a quote naming both ('glycine and alanine, 5 mM each'), or the
    same quote for both -- unless that quote lists them as alternatives ('Asp, Glu, or Ala')."""
    for q in {quote_a, quote_b}:
        if q and _mentions(q, name_a) and _mentions(q, name_b):
            return not _ALTERNATIVES.search(q)
    if _norm(quote_a) and _norm(quote_a) == _norm(quote_b):
        return not _ALTERNATIVES.search(quote_a)
    return False


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def summary_mixed_flags(rows: List[ExtractedRow], summary_set_type: str) -> Dict[str, List[Flag]]:
    """{full_id: [flags]} for Paper summary rows (module text)."""
    out: Dict[str, List[Flag]] = {}
    for r in rows:
        if r.set_type != summary_set_type:
            continue
        values = {**r.species_mM, **{c: v for c, v in r.extra.items() if isinstance(v, (int, float))}}
        by_class: Dict[str, list] = {}
        for column, v in values.items():
            m = _START.match(column)
            if m and v not in (None, "") and compound_class(m.group(1)):
                by_class.setdefault(compound_class(m.group(1)), []).append((column, m.group(1)))
        for cls, members in by_class.items():
            if len(members) < 2:
                continue
            quotes = {c: (r.provenance.get(c).quote if r.provenance.get(c) else "") for c, _n in members}
            apart = []
            for column, name in members:
                others = [(c, n) for c, n in members if c != column]
                together = any(_used_together(quotes[column], quotes[c], name, n) for c, n in others)
                if not together:
                    apart.append((column, name))
            if apart:
                listing = ", ".join(f"{c} ({values[c]:g})" for c, _n in apart)
                out.setdefault(r.full_id, []).append(Flag(
                    "summary_mixed",
                    f"This Paper summary row has {len(members)} starting {cls}s, and the paper gives {listing} "
                    f"separately or as alternatives, not as one mixture: probably reactants of different "
                    f"experiments. "
                    f"Check them against the paper; keep the ones used together, or digitize the figures for one row "
                    f"per experiment."))
    return out
