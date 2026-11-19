"""
Column names in words, for people who don't know the dataset's naming scheme (branch levels-and-facets, step 2:
"easy to understand for someone ... without experience using this specific app"): 'initial_Gly_aq_mM' ->
'Gly concentration (starting, dissolved)', 'sampled_Gly-Gly_aq_%yield' -> 'Gly-Gly yield (measured, dissolved)',
'initial_temperature_C' -> 'Initial temperature'. The unit is shown beside the value, so it is left out of the name;
the column's own name stays in the tooltip.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict

ROLES = {"initial": "starting", "sampled": "measured", "stock": "stock solution", "calculated": "calculated by the paper"}
PHASES = {"aq": "dissolved", "s": "solid", "gas": "gas", "g": "gas", "l": "liquid"}
MEASURES = {"mM": "concentration", "%yield": "yield", "%recovered": "recovered", "mmol": "amount", "umol": "amount",
            "nmol": "amount", "g": "mass", "mL": "volume", "uL": "volume", "pct": "share"}
_COMPOUND = re.compile(r"^(initial|sampled|stock|calculated)_(.+)_(aq|s|gas|g|l)_(.+)$")
# words that keep their case
_KEEP = {"pH", "DOI", "ID", "UV", "IR", "NMR", "HPLC", "MS", "GC", "LC", "pKa", "RV", "SNR"}


def readable(column: str, pack_id: str = "") -> str:
    """The column in words, without its unit: the pack's own label for it (an archive's 'Orbital Period [days]'),
    else read from the naming scheme."""
    labels = _template_labels(pack_id) if pack_id else {}
    label = labels.get(column, "")
    if label:
        return _without_brackets(label)
    derived = _derived(column, labels)
    if derived:
        return derived
    m = _COMPOUND.match(column)
    if m:
        role, name, phase, measure = m.groups()
        what = MEASURES.get(measure, measure.replace("_", " "))
        return f"{name} {what} ({ROLES[role]}, {PHASES[phase]})"
    base = _without_unit(column)
    words = [w for w in base.split("_") if w]
    if not words:
        return column
    text = " ".join(w if w in _KEEP or any(ch.isupper() for ch in w[1:]) else w.lower() for w in words)
    return text[0].upper() + text[1:] if not text.split()[0] in _KEEP else text


def _without_unit(column: str) -> str:
    from parameter_extractor.ingestion.observations import _SUFFIX_UNITS, unit_slug_suffix
    for pattern, _unit in _SUFFIX_UNITS:
        if re.search(pattern, column) and not re.search(r"(^|_)pH$", column):
            return re.sub(pattern, "", column)
    slug = unit_slug_suffix(column)
    return column[: -len(slug)] if slug else column


@lru_cache(maxsize=8)
def _descriptions(pack_id: str) -> Dict[str, str]:
    from parameter_extractor import packs
    from parameter_extractor.stages.optional import load_specs
    out: Dict[str, str] = {}
    try:
        pack = packs.available(include_template=True)[pack_id]
        for spec in load_specs(pack).values():
            for p in spec.parameters:
                if getattr(p, "description", "") and p.column not in out:
                    out[p.column] = p.description
    except Exception:                                 # noqa: BLE001 -- a description is a courtesy
        pass
    return out


def description(column: str, pack_id: str) -> str:
    """What the data pack's steps are told the column holds, when a step asks for it ('' otherwise)."""
    return _descriptions(pack_id).get(column, "")


@lru_cache(maxsize=8)
def _template_labels(pack_id: str) -> Dict[str, str]:
    """{column: label} from the pack's template file ('descriptions'), when it has them."""
    import json
    from parameter_extractor import packs
    try:
        pack = packs.available(include_template=True)[pack_id]
        data = json.loads((pack.folder / pack.manifest.template).read_text())
        return dict(data.get("descriptions") or {})
    except Exception:                                 # noqa: BLE001
        return {}


def _without_brackets(label: str) -> str:
    """'Planet Mass [Jupiter Mass] Upper Unc.' -> 'Planet Mass Upper Unc.' (the unit is shown beside the value)."""
    return re.sub(r"\s+", " ", re.sub(r"\s*\[[^\]]*\]", "", label)).strip()


# an archive column made from a labelled one ('pl_orbincl' + 'mode1err1'): its parts in words
_DERIVED = [(re.compile(r"^_?modal_flag$"), "has several solutions (modes)"),
            (re.compile(r"^mode(\d+)err1$"), "mode {0}, upper unc."), (re.compile(r"^mode(\d+)err2$"), "mode {0}, lower unc."),
            (re.compile(r"^mode(\d+)desc$"), "mode {0}, description"), (re.compile(r"^mode(\d+)$"), "mode {0}"),
            (re.compile(r"^err1$"), "upper unc."), (re.compile(r"^err2$"), "lower unc."), (re.compile(r"^lim$"), "limit flag")]


def _derived(column: str, labels: Dict[str, str]) -> str:
    bases = [b for b in labels if len(b) >= 4 and column.startswith(b) and column != b]
    if not bases:
        return ""
    base = max(bases, key=len)
    rest = column[len(base):]
    for pattern, words in _DERIVED:
        m = pattern.match(rest)
        if m:
            return f"{_without_brackets(labels[base])}, {words.format(*m.groups())}"
    return ""


def unit(column: str, pack_id: str = "") -> str:
    """The unit the pack's template label gives a column ('Orbital Period [days]' -> 'days'; a derived column its
    base's, a flag or a description none) -- for showing beside a value that has no unit of its own."""
    labels = _template_labels(pack_id) if pack_id else {}
    label = labels.get(column, "")
    if not label:
        bases = [b for b in labels if len(b) >= 4 and column.startswith(b) and column != b]
        if not bases or re.search(r"(flag|desc|lim)$", column):
            return ""
        label = labels[max(bases, key=len)]
    if re.search(r"flag\b|limit", label, re.IGNORECASE):
        return ""
    m = re.search(r"\[([^\]]+)\]", label)
    return m.group(1).strip() if m else ""
