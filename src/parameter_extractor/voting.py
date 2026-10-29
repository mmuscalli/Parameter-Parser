"""
Several passes and a vote (Mickey, 2026-10-29): a cheaper alternative to Standard for packs whose steps
need it. With RunConfig.passes = 2 or 3, the extraction steps after the structure plan (chemistry and
the pack's stage specs) are each run that many times on the same structure, and every value is decided
by vote:

  - values are matched across passes by WHAT they are (set, sample, column / species, role, basis,
    mode, method) and compared by their value converted to the column's unit (text: case-insensitive);
  - the most common value among the passes that GIVE one wins (a pass that left it out doesn't vote
    for "nothing": measured on faisal2005, Economy passes dropped whole blocks at random -- the
    temperatures in one pass, the NH4+ column in another); a tie goes to the earliest pass;
  - every disagreement is kept for one grouped flag per step and column: values that differ between
    passes, and values only some passes found.

Why (5 eder1994 + 3 faisal2005 live Economy passes): systematic misses are the same in every pass and
need fixes, not votes; random dropouts were 10-15 points on faisal and a vote over 2-3 passes recovered
them (74-84% -> 89.5%). The structure plan, metadata, term search and fitting models run once.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, List, Tuple

MAX_PASSES = 3


@dataclass
class Disagreement:
    step: str                          # stage label
    what: str                          # column or species
    where: str                         # set / sample
    winner: str                        # the value kept
    counts: Dict[str, int]             # value shown -> passes that gave it
    passes: int                        # passes run
    present_in: int                    # passes that gave any value

    @property
    def kind(self) -> str:
        return "differ" if len(self.counts) > 1 else "missing"


@dataclass
class VoteResult:
    disagreements: List[Disagreement] = field(default_factory=list)


def vote_items(passes: List[list], key: Callable, signature: Callable, shown: Callable,
               step: str, what: Callable, where: Callable,
               prefer: Callable = lambda item: True) -> Tuple[list, List[Disagreement]]:
    """The winning item for every key any pass gave, in first-seen order (pass 1's order first), and
    the disagreements. Among the passes giving the winning value, the first `prefer`red one's item is
    kept (e.g. the one that also gives the unit)."""
    order: List[Hashable] = []
    by_key: Dict[Hashable, List[list]] = {}
    for p, items in enumerate(passes):
        for item in items:
            k = key(item)
            if k not in by_key:
                by_key[k] = [[] for _ in passes]
                order.append(k)
            by_key[k][p].append(item)
    winners, notes = [], []
    for k in order:
        per_pass = by_key[k]
        voting = [items for items in per_pass if items]
        firsts = [items[0] for items in voting]                        # one vote per pass
        counts = Counter(signature(i) for i in firsts)
        best = max(counts.values())
        win_sig = next(signature(i) for i in firsts if counts[signature(i)] == best)   # tie: earliest pass
        agreeing = [n for n, i in enumerate(firsts) if signature(i) == win_sig]
        index = next((n for n in agreeing if prefer(firsts[n])), agreeing[0])
        chosen = firsts[index]
        # that pass's other items for the same key too (a second value it gave -> the usual conflict flag)
        winners += voting[index]
        if len(counts) > 1 or len(firsts) < len(passes):
            shown_counts = Counter()
            for i in firsts:
                shown_counts[shown(i)] += 1
            notes.append(Disagreement(step=step, what=what(chosen), where=where(chosen), winner=shown(chosen),
                                      counts=dict(shown_counts), passes=len(passes), present_in=len(firsts)))
    return winners, notes


# ---- the pack's stage specs (stages/optional.py) ---------------------------------------------------------

def vote_stage(spec, results: list) -> Tuple[object, dict, List[Disagreement]]:
    """(voted Result, its answer as a dict -- saved as <stage>.output.json and loadable by replays --,
    disagreements)."""
    from parameter_extractor.stages.optional import stage_values

    def sig(item):
        converted, _ = stage_values(spec, item)
        v = converted.get(item.parameter)
        if v is None:
            return ("raw", item.value, (getattr(item, "text", "") or "").strip().lower(), (item.unit or "").strip())
        value = v.value
        return ("t", value.strip().lower()) if isinstance(value, str) else ("n", round(float(value), 6))

    def shown(item):
        text = (getattr(item, "text", "") or "").strip()
        return text if text else f"{item.value:g}" + (f" {item.unit}" if item.unit else "")

    key = lambda i: (i.set_label, getattr(i, "sample_label", ""), i.parameter, getattr(i, "mode", ""),
                     getattr(i, "method", ""))
    where = lambda i: " / ".join(x for x in (i.set_label, getattr(i, "sample_label", "")) if x) or "whole paper"
    winners, notes = vote_items([r.parameters for r in results], key, sig, shown, spec.label,
                                lambda i: i.parameter, where, prefer=lambda i: bool(i.unit))
    other = next((r.other for r in results if getattr(r, "other", None)), [])
    data = {"parameters": [w.model_dump(by_alias=True) for w in winners],
            "notes": " | ".join(dict.fromkeys(r.notes for r in results if r.notes)),
            **({"other": [_without_empty_category(o.model_dump(by_alias=True)) for o in other]}
               if hasattr(results[0], "other") else {})}
    _, Result = spec.models()
    return Result.model_validate(data), data, notes


def _without_empty_category(item: dict) -> dict:
    """An item recorded before categories has cat '' (the default, never validated): leave it out so
    the voted answer reloads."""
    if not item.get("cat"):
        item.pop("cat", None)
    return item


# ---- chemistry ------------------------------------------------------------------------------------------

def _species(name: str) -> str:
    """One name per species across passes ('Gly-Gly', 'glycylglycine' -> '2peptide_Gly')."""
    from parameter_extractor.names import match_species
    matched = match_species(name or "")
    return matched[0] if matched else (name or "").strip().lower()


def vote_chemistry(results: list) -> Tuple[object, dict, List[Disagreement]]:
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    step = "Solution chemistry"
    solutes, notes = vote_items(
        [r.solutes for r in results],
        key=lambda s: (_species(s.name), s.role, s.set_label or "", s.sample_label or "",
                       s.concentration_basis, (s.stock_solution or "").strip().lower()),
        # the number as printed (a pass that left the unit out still agrees -- faisal2005 pass 3); the
        # unit, when different, shows up in the flag
        signature=lambda s: (None if s.concentration_value is None else round(float(s.concentration_value), 6),
                             s.detection),
        prefer=lambda s: bool(s.concentration_unit_raw),
        shown=lambda s: s.detection or (f"{s.concentration_value:g} {s.concentration_unit_raw or ''}".strip()
                                        if s.concentration_value is not None else "no value"),
        step=step, what=lambda s: f"{s.name} ({s.role})",
        where=lambda s: " / ".join(x for x in (s.set_label, s.sample_label) if x) or "whole paper")
    added, n2 = vote_items(
        [r.added_solutions for r in results], key=lambda a: (a.solution.strip().lower(), a.set_label),
        signature=lambda a: a.volume.replace(" ", "").lower(), shown=lambda a: a.volume, step=step,
        what=lambda a: f"volume added: {a.solution}", where=lambda a: a.set_label or "whole paper")
    ratios, n3 = vote_items(
        [r.molar_ratios for r in results],
        key=lambda m: (m.set_label, m.species.strip().lower(), m.reference_species.strip().lower()),
        signature=lambda m: round(m.species_parts / m.reference_parts, 6) if m.reference_parts else None,
        shown=lambda m: m.ratio_text, step=step, what=lambda m: f"ratio {m.species} : {m.reference_species}",
        where=lambda m: m.set_label or "whole paper")
    totals, n4 = vote_items(
        [r.mixture_totals for r in results],
        key=lambda t: (t.set_label, t.sample_label, tuple(sorted(p.name.strip().lower() for p in t.parts))),
        signature=lambda t: t.total.replace(" ", "").lower(), shown=lambda t: t.total, step=step,
        what=lambda t: "total of " + " + ".join(p.name for p in t.parts),
        where=lambda t: " / ".join(x for x in (t.set_label, t.sample_label) if x) or "whole paper")
    unmapped = list(dict.fromkeys(n for r in results for n in r.unmapped_species))
    voted = ChemistryExtraction(paper_id=results[0].paper_id, solutes=solutes, unmapped_species=unmapped,
                                added_solutions=added, molar_ratios=ratios, mixture_totals=totals)
    data = json_ready(voted)
    return voted, data, notes + n2 + n3 + n4


def json_ready(model) -> dict:
    import json
    return json.loads(model.model_dump_json())


# ---- flags ----------------------------------------------------------------------------------------------

def disagreement_flags(notes: List[Disagreement]) -> List[str]:
    """One message per step and column/species: how many places the passes disagreed, with examples."""
    grouped: Dict[Tuple[str, str, str], List[Disagreement]] = {}
    for d in notes:
        grouped.setdefault((d.step, d.what, d.kind), []).append(d)
    out = []
    for (step, what, kind), ds in grouped.items():
        n = ds[0].passes
        examples = "; ".join(
            f"{d.where}: " + (f"kept {d.winner} ({d.counts.get(d.winner, 0)} of {n}; others "
                              + ", ".join(f"{v} x{c}" for v, c in d.counts.items() if v != d.winner) + ")"
                              if kind == "differ" else f"{d.winner}, found by {d.present_in} of {n} passes")
            for d in ds[:3]) + (f"; ... ({len(ds) - 3} more)" if len(ds) > 3 else "")
        head = (f"{step}: {what} differs between passes in {len(ds)} place(s) -- the most common value was kept"
                if kind == "differ" else
                f"{step}: {what} was found by only some of the {n} passes in {len(ds)} place(s) -- kept")
        out.append(f"{head}. {examples}.")
    return out
