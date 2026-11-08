"""
Constructed-parameter groups (Mickey, 2026-11-08): a step whose columns are BUILT from a vocabulary -- compound
columns '<role>_<compound>_<phase>_<measure>' from the compound vocabulary, analysis columns
'analysis_<technique>_<setting>_<unit>' from the analysis vocabulary -- shows that vocabulary's items in the main
window's Parameters panel, so a run can be narrowed to some of them:

  ScopeGroup(step, label, description, items=[ScopeItem(key, label, tip)])

RunConfig.scopes {step: [keys]} holds a narrowed choice (a step missing = everything). The step is then told to
extract only those items (its prompt) and the app drops anything else it returns (a model slip), with one flag. All
items unticked = the step is switched off (RunConfig.optional_stages[step] = 'off').

The same shape is meant for future vocabulary-based steps, including user-defined vocabularies: a pack's
vocabulary file -> a ScopeGroup -> a scope the step honours.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ScopeItem:
    key: str                  # what RunConfig.scopes holds (a compound's default name, an instrument family id)
    label: str                # what the user sees (a compound's active name, the family's label)
    tip: str = ""             # hover text
    detail: str = ""          # the panel's "What it is" column ('' = nothing to add beyond the name)


@dataclass
class ScopeGroup:
    step: str                 # the step it narrows ('chemistry', 'analysis')
    label: str
    description: str
    items: List[ScopeItem] = field(default_factory=list)


def compound_group(pack, registry=None) -> Optional[ScopeGroup]:
    """The chemistry step's compounds: the pack's vocabulary species and the compounds accepted in reviews, shown
    by their active names (compound_names.py)."""
    if not pack.uses("chemistry"):
        return None
    from parameter_extractor.compound_names import CompoundNames
    names = CompoundNames(registry, pack)
    keys = list(dict.fromkeys(list(pack.vocab.get("species_names", [])) + list(names.compounds)))
    items = []
    for key in keys:
        c = names.compounds.get(key)
        shown = c.shown if c else key
        tip = f"Columns: <role>_{c.shown if c else key}_<phase>_<measure>" + (f" (default name {key})"
                                                                             if c and c.active else "")
        items.append(ScopeItem(key, shown, tip, f"default name {key}" if c and c.active else ""))
    items.sort(key=lambda i: i.label.lower())
    return ScopeGroup("chemistry", "Chemical compounds",
                      "Solution chemistry: starting concentrations and product yields of these compounds. Untick "
                      "compounds to extract only the others; untick all to skip the step.", items)


def analysis_group(pack) -> Optional[ScopeGroup]:
    """The analysis step's instrument families (analysis_vocab.json): a family unticked = its techniques left out."""
    if not pack.uses("analysis"):
        return None
    from parameter_extractor.analysis_vocab import vocabulary
    vocab = vocabulary(pack)
    if vocab is None:
        return None
    items = []
    for fid, (label, settings) in vocab.families.items():
        if fid == "general":
            continue                       # settings every technique has, not a family of instruments
        techs = [t.name for t in vocab.techniques if fid in t.families]
        listing = f"{len(techs)} techniques: {', '.join(techs[:12])}" + (" ..." if len(techs) > 12 else "")
        items.append(ScopeItem(fid, label, listing, listing))
    return ScopeGroup("analysis", "Analysis methods",
                      "Analytical techniques and their instrument settings, by instrument family. Untick families "
                      "to record only the others; untick all to skip the step.", items)


def groups(pack, registry=None) -> List[ScopeGroup]:
    return [g for g in (compound_group(pack, registry), analysis_group(pack)) if g is not None]


# ---- applying a scope ---------------------------------------------------------------------------------------

def compound_rule(scope: Optional[List[str]]) -> str:
    """The chemistry prompt's rule for a narrowed run ('' when every compound is wanted)."""
    if not scope:
        return ""
    return ("\nSCOPE OF THIS RUN: extract ONLY these compounds (as starting species, stock solutions or products): "
            + "; ".join(scope) + ". Leave out every other species -- but still list the solutions combined (`added_"
            "solutions`) and stated molar ratios that involve them, so their concentrations can be calculated.\n")


def filter_compounds(chemistry, scope: Optional[List[str]]) -> List[str]:
    """Drops species outside the run's compound scope (after names were normalised); returns the names left out."""
    if not scope:
        return []
    wanted = {s.lower() for s in scope}
    kept, dropped = [], []
    for s in chemistry.solutes:
        (kept if (s.name or "").lower() in wanted else dropped).append(s)
    chemistry.solutes = kept
    return sorted({s.name for s in dropped})


def analysis_rule(scope: Optional[List[str]], vocab) -> str:
    if not scope or vocab is None:
        return ""
    labels = [vocab.families[f][0] for f in scope if f in vocab.families]
    return ("\nSCOPE OF THIS RUN: record ONLY techniques of these instrument families: " + "; ".join(labels)
            + ". Leave out every other technique.\n")


def filter_analysis(result, scope: Optional[List[str]], vocab) -> List[str]:
    """Drops techniques outside the run's instrument families (unknown techniques too); returns their names."""
    if not scope or result is None or vocab is None:
        return []
    wanted, kept, dropped = set(scope), [], []
    for m in result.methods:
        tech = vocab.technique(m.technique) or vocab.technique(m.name)
        (kept if tech is not None and wanted & set(tech.families) else dropped).append(m)
    result.methods = kept
    return [m.technique or m.name for m in dropped]
