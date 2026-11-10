"""
Modules drafted from sample papers (Mickey, 2026-11-09: build up the shared modules future data packs draw from).

1. The papers are surveyed like for a data pack draft (pack_drafting.survey_paper; cached -- module drafting goes
   over many papers, round after round).
2. One design request (prompts/module_synthesis.md) proposes modules: groups of values that recur across papers and
   form a topic of their own (mineral surfaces, irradiation, shock conditions ...), told what every existing module
   already records (module.json `covers` + its columns) so it doesn't propose them again.
3. Local checks (`check_proposals`), before anything is written:
   - parameters named by the app's conventions (pack_drafting.column_for / tidy_parameter);
   - a parameter an existing module records is dropped; a CORE column (a convention's column: temperature, pH,
     pressure, solvent, solid material ...) becomes a `pack_parameters` entry -- added to a pack's own first step only
     when the pack has no such column -- instead of a module step value (core conditions belong to the pack);
   - two proposals sharing a column: the larger keeps it; a module left with fewer than MIN_PARAMETERS values is
     dropped (a step costs a request per paper it runs for);
   - evidence words must appear in the sample papers' surveys and not in nearly all of them (they decide which
     drafts link the module and which papers its step runs for);
   - ids and labels must be new.
4. `write_module` -> <app data>/modules/<id>/ (module.json with `evidence` words + stages/<id>.json). Drafting links a
   user module when the papers' surveys show its evidence words (pack_modules.evidence_for).
"""
from __future__ import annotations
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from parameter_extractor import modules as module_store
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError, RunCancelledError
from parameter_extractor.pack_drafting import (ProposedCategory, ProposedStage, SurveyedPaper, _config, _prompt,
                                               _slug, _survey_all, _survey_digest, column_for, tidy_parameter)

MODULE_BUDGET = 16000
MIN_PARAMETERS = 3
GENERIC_SHARE = 0.85            # an evidence word in more than this share of the surveys says nothing about a paper


class ProposedModule(BaseModel):
    from parameter_extractor.stages.optional import ALL_REQUIRED as model_config      # every field asked for
    id: str = Field(description="snake_case, e.g. 'mineral_surfaces'.")
    label: str = Field(description="Short title, e.g. 'Mineral surfaces'.")
    description: str = Field(description="Two sentences: what the module records and for which experiments.")
    covers: str = Field(description="One sentence for designers of data packs: what the module records, so they "
                                    "don't ask for it again.")
    evidence_words: List[str] = Field(description="4-10 specific words or short phrases that papers needing the "
                                                  "module use and other papers don't ('montmorillonite', 'cation "
                                                  "exchange capacity'); its step runs for papers containing one.")
    papers: List[str] = Field(description="The sample papers (as named in the surveys) that report these values.")
    step: ProposedStage
    category: ProposedCategory
    row_rules: List[str] = Field(description="0-2 rules for planning rows that papers with this topic need, or [].")
    extends: str = Field("", description="The id of an EXISTING module this belongs to (its topic, more values of "
                                         "the same kind), or '' for a new module.")


class ModuleProposal(BaseModel):
    modules: List[ProposedModule]
    notes: str = Field(description="Topics you considered but left out, and why (one or two sentences), or ''.")


_DIMENSIONLESS = {"fold", "ratio", "dimensionless", "unitless", "none", "-", "times", "x", "×"}


def _unit_note(column: str, unit: str) -> tuple:
    """(unit to keep, note): a dimensionless word means no unit; a unit the app can't read is kept with a note (its
    values are stored as printed)."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import canonical_unit
    u = (unit or "").strip()
    if u.lower() in _DIMENSIONLESS:
        return "", ""
    if not u or canonical_unit(u) or unit_for_column(column):
        return u, ""
    return u, f"`{column}`: the app doesn't convert '{u}' -- values are kept as printed"


@dataclass
class CheckedModule:
    proposal: ProposedModule
    parameters: List[dict]                        # step parameters (column, unit, kind, description, ...)
    pack_parameters: List[dict]                   # core columns: added to a pack's first step when it lacks them
    evidence: List[str]
    papers_with_evidence: Dict[str, List[str]]
    notes: List[str] = field(default_factory=list)
    include: bool = True
    extends: str = ""                             # an existing module this is an addition to ('' = a new module)

    @property
    def id(self) -> str:
        return _slug(self.proposal.id)


@dataclass
class ModuleDraftResult:
    modules: List[CheckedModule]
    left_out: List[str]
    papers: List[SurveyedPaper]
    proposal: Optional[ModuleProposal]
    work_dir: Path
    cost_usd: float = 0.0
    written: List[Path] = field(default_factory=list)


# ---- what exists already ------------------------------------------------------------------------------------------------

def existing_brief() -> str:
    """Every available module (the app's and the user's) with what it records and its columns: the design request
    must not propose these again."""
    from parameter_extractor.pack_drafting import _module_own_columns
    lines = []
    for mod in module_store.available().values():
        cols = _module_own_columns(mod)
        lines.append(f"- {mod.label} (id {mod.id}): {mod.manifest.covers or mod.manifest.description}"
                     + (f" Columns: {', '.join(cols[:20])}" if cols else ""))
    return "\n".join(lines)


def _existing_columns() -> Dict[str, str]:
    """{column: module label} for the columns modules OWN -- not the core conditions they add to a pack only when it
    lacks them (pack_parameters): those belong to no module."""
    from parameter_extractor.pack_drafting import _module_own_columns
    out = {}
    for m in module_store.available().values():
        core = {p["column"] for p in m.manifest.pack_parameters}
        out.update({c: m.label for c in _module_own_columns(m) if c not in core})
    return out


# ---- the design request -----------------------------------------------------------------------------------------------

def propose_modules(papers: List[SurveyedPaper], config: RunConfig, work_dir: Path, area: str,
                    cancel_event: Optional[threading.Event] = None) -> tuple:
    from parameter_extractor.api_client import call_structured
    from parameter_extractor.run_context import RunContext, total_cost
    ctx = RunContext(config=config, run_dir=work_dir, total_steps=1, cancel_event=cancel_event)
    prompt = _prompt("module_synthesis", AREA=area, N_PAPERS=len(papers), EXISTING=existing_brief())
    proposal = call_structured(ctx, stage="module_synthesis", system_prompt="Design shared extraction modules from "
                               "surveys of sample papers.", user_content=f"{prompt}\n\nSURVEYS:\n{_survey_digest(papers)}",
                               response_model=ModuleProposal, max_tokens=MODULE_BUDGET)
    return proposal, total_cost(ctx.usage) or 0.0


# ---- local checks --------------------------------------------------------------------------------------------------------

def _survey_texts(papers: List[SurveyedPaper]) -> Dict[str, str]:
    from parameter_extractor.pack_modules import _texts
    return {p.name: " ".join(t for t in _texts(p.survey) if t).lower() for p in papers if p.survey}


def _word_pattern(word: str) -> re.Pattern:
    w = re.escape(word.strip().lower()).replace(r"\ ", r"[\s_-]+")
    return re.compile(rf"(?<![a-z0-9]){w}s?(?![a-z0-9])")


def evidence_hits(words: Sequence[str], texts: Dict[str, str]) -> Dict[str, List[str]]:
    """{paper: [words it uses]} for the evidence words."""
    out: Dict[str, List[str]] = {}
    for w in words:
        rx = _word_pattern(w)
        for name, text in texts.items():
            if rx.search(text):
                out.setdefault(name, []).append(w)
    return out


_CORE: Optional[set] = None


def core_columns() -> set:
    """Conditions data packs have themselves: the targets of the app's naming conventions (temperature, pH, pressure,
    solvent, volumes, solid material, flow rate, ...) and the condition columns of the app's own packs (their own steps
    and template, not compound columns). A module asking for one adds it to a pack only when the pack lacks it."""
    global _CORE
    if _CORE is None:
        import inspect
        from parameter_extractor import conventions, packs
        from parameter_extractor.stages.optional import _specs_in
        out = set(re.findall(r'Convention\("([a-z][A-Za-z0-9_]*)"', inspect.getsource(conventions)))
        out |= set(re.findall(r'"((?:initial|sampled)_[A-Za-z]+(?:_[A-Za-z]+)?)" if', inspect.getsource(conventions)))
        compound = re.compile(r"_(?:aq|gas|s)_|^(?:initial|sampled|stock|added)_.+_(?:mM|%yield|uL)$")
        for pack in packs.available().values():
            if packs.BUILTIN_DIR not in pack.folder.parents:
                continue
            for spec in _specs_in(pack.folder / "stages").values():
                out |= {p.column for p in spec.parameters}
            out |= {c for c in pack.template_columns if not compound.search(c)}
        _CORE = out
    return _CORE


def is_core_column(column: str, unit: str = "", kind: str = "", description: str = "") -> bool:
    """A condition data packs have themselves (core_columns, or a column the conventions rename to one)."""
    from parameter_extractor.conventions import canonical
    if column in core_columns():
        return True
    conv = canonical(column, unit, kind, description)
    return conv is not None and bool(conv.column) and conv.column in core_columns()


_UNIT_TALK = re.compile(r"[,;]?\s*(?:\(?\s*(?:converted|expressed|given|reported)\s+(?:to|in)\s+[^.;,)]+\)?|"
                        r"\bin\s+(?:units of\s+)?(?:GPa|MPa|kPa|Pa|bar|K|°C|km/s|m/s|µm|um|mm|nm|mg|g|kg|s|"
                        r"seconds|minutes|hours|h|mL|L|µL|kJ/mol|J/mol/K|mM|M|%)(?![\w/]))", re.IGNORECASE)


def clean_description(text: str) -> str:
    """A value's description without unit instructions ('in GPa', 'converted to seconds'): the column's unit is the
    stored one and the app converts whatever the paper prints -- a description naming another unit misleads."""
    out = _UNIT_TALK.sub("", text or "").strip()
    out = re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;])", r"\1", out))
    return out if out.endswith(".") or not out else out + "."


MIN_PRECISION = 0.5
MIN_TRIGGER_HITS = 3            # a module's step runs when its words occur this often (not a passing mention)             # an evidence word must mostly hit papers that report the module's values


def _listed(paper_names: Sequence[str], texts: Dict[str, str]) -> set:
    """The surveyed papers the designer listed (its names may be shortened)."""
    out = set()
    for n in paper_names:
        key = re.sub(r"\W+", " ", n.lower()).strip()
        for name in texts:
            full = re.sub(r"\W+", " ", name.lower()).strip()
            if key and (key in full or full in key):
                out.add(name)
    return out


def check_proposals(proposal: ModuleProposal, papers: List[SurveyedPaper], tidy: bool = True) -> tuple:
    """(checked modules, notes on what was left out)."""
    texts = _survey_texts(papers)
    taken = _existing_columns()
    existing_ids = set(module_store.available())
    existing_labels = {m.label.lower() for m in module_store.available().values()}
    extends_ids = {_slug(pm.extends) for pm in proposal.modules if pm.extends.strip()}
    left: List[str] = []
    checked: List[CheckedModule] = []
    for pm in proposal.modules:
        notes: List[str] = []
        mid = _slug(pm.id)
        target = module_store.canonical_id(_slug(pm.extends)) if pm.extends.strip() else ""
        if target and target not in existing_ids:
            notes.append(f"extends '{pm.extends}', which isn't a module: proposed as a new one")
            target = ""
        if not target and (mid in existing_ids or pm.label.strip().lower() in existing_labels):
            left.append(f"module '{pm.label}': a module with this id or name exists already")
            continue
        params, core = [], []
        for p in pm.step.parameters:
            column, unit = column_for(p.column, p.unit, p.kind)
            kind, integer = p.kind, p.kind == "integer"
            if tidy:
                column, unit, kind, tidied_integer, note = tidy_parameter(column, unit, p.kind, p.description)
                integer = integer or tidied_integer
                if not column:
                    notes.append(f"`{p.column}` dropped: {note}")
                    continue
            if column in taken:
                notes.append(f"`{column}` dropped: the {taken[column]} module records it")
                continue
            entry = {"column": column, "description": clean_description(p.description)}
            unit, unit_note = _unit_note(column, unit)
            if unit_note:
                notes.append(unit_note)
            if unit:
                entry["unit"] = unit
            if kind == "text":
                entry["kind"] = "text"
            if integer:
                entry["integer"] = True
            if p.choices and kind == "text":
                entry["choices"] = [c for c in p.choices if c.strip()]
            if p.uncertainties and kind != "text":
                entry["uncertainties"] = True
            if is_core_column(column, unit, kind, p.description):
                core.append(entry)
                notes.append(f"`{column}` is a core condition: added to a pack's own first step only when it lacks it")
            else:
                params.append(entry)
        words = [w.strip() for w in pm.evidence_words if w.strip()]
        hits = evidence_hits(words, texts)
        n = max(1, len(texts))
        listed = _listed(pm.papers, texts)
        generic, loose = [], []
        for w in words:
            papers_w = {p for p, found in hits.items() if w in found}
            if len(papers_w) / n > GENERIC_SHARE and n >= 5:
                generic.append(w)
            elif listed and len(papers_w) >= 3 and len(papers_w & listed) / len(papers_w) < MIN_PRECISION:
                loose.append(f"{w} ({len(papers_w & listed)} of {len(papers_w)} papers using it report the values)")
        unseen = [w for w in words if not any(w in found for found in hits.values())]
        if generic:
            notes.append(f"evidence words in nearly every paper left out: {', '.join(generic)}")
        if loose:
            notes.append(f"evidence words that mostly hit other papers left out: {', '.join(loose)}")
        dropped = set(generic) | {x.split(" (")[0] for x in loose}
        evidence = [w for w in words if w not in dropped]
        hits = evidence_hits(evidence, texts)
        if unseen:
            notes.append(f"evidence words no sample paper uses (kept, they may still help): {', '.join(unseen)}")
        checked.append(CheckedModule(pm, params, core, evidence, hits, notes, extends=target))
    # two proposals with the same column: the larger one keeps it
    for a in sorted(checked, key=lambda c: -len(c.parameters)):
        for b in checked:
            if b is a or len(b.parameters) > len(a.parameters):
                continue
            shared = {p["column"] for p in a.parameters} & {p["column"] for p in b.parameters}
            if shared:
                b.parameters = [p for p in b.parameters if p["column"] not in shared]
                b.notes.append(f"{', '.join(sorted(shared))} left to '{a.proposal.label}', which has more values")
    out = []
    for c in checked:
        if len(c.parameters) < MIN_PARAMETERS:
            left.append(f"module '{c.proposal.label}': {len(c.parameters)} value(s) of its own after the checks -- "
                        f"fewer than {MIN_PARAMETERS} don't make a step worth a request" + (
                            f" ({'; '.join(c.notes)})" if c.notes else ""))
            continue
        if not c.evidence:
            left.append(f"module '{c.proposal.label}': no specific evidence words left")
            continue
        if not c.papers_with_evidence:
            c.notes.append("no sample paper uses its evidence words: drafts won't link it from these papers")
        out.append(c)
    return out, left


# ---- writing ------------------------------------------------------------------------------------------------------------

def module_files(c: CheckedModule) -> tuple:
    """(module.json dict, step spec dict) for a checked module."""
    pm, mid = c.proposal, c.id
    step_name = mid
    cat_id = _slug(pm.category.id) or mid
    columns = [p["column"] for p in c.parameters]
    manifest = {
        "id": mid, "label": pm.label.strip(), "description": pm.description.strip(), "covers": pm.covers.strip(),
        "version": 1,
        "evidence": {"words": c.evidence},
        "variable_categories": [{"id": cat_id, "table_order": 76, "label": pm.category.label.strip() or pm.label,
                                 "value_type": pm.category.value_type, "model_assigns": True,
                                 "description": pm.category.description.strip()}],
        "category_columns": {cat_id: {"columns": columns}},
    }
    if c.pack_parameters:
        manifest["pack_parameters"] = c.pack_parameters
    if pm.row_rules:
        manifest["row_rules"] = [r.strip() for r in pm.row_rules if r.strip()]
    spec = {
        "name": step_name, "label": pm.step.label.strip() or pm.label, "description": pm.step.description.strip(),
        "origin": pm.label.lower(), "schema_name": "".join(w.capitalize() for w in step_name.split("_")) + "Result",
        "system_prompt": "Extract values from a scientific paper. Report only what the paper states.",
        "trigger": {"keywords": c.evidence, "min_hits": MIN_TRIGGER_HITS}, "per": pm.step.per, "set_word": "experiment",
        "error_suffixes": ["_err_plus", "_err_minus"], "suffix_separator": "_", "table_images": True,
        "intro": f"{pm.step.description.strip()} For every set (and sample) in the structure plan below, extract "
                 "the values the paper reports. A value that holds for every set goes in ONE row with `set` ''; one "
                 "that differs between sets goes in each set's row; one that differs between the samples of a set "
                 "goes in each sample's row.",
        "parameters": c.parameters, "rules": [r.strip() for r in pm.step.rules if r.strip()],
    }
    return manifest, spec


def write_module(c: CheckedModule, base: Optional[Path] = None) -> Optional[Path]:
    """A new module folder; an addition to one of the user's modules goes into that module (its step file, its
    category's columns, its evidence words); an addition to one of the app's modules isn't written (None) -- the
    report lists it for the app's developers."""
    if c.extends:
        mod = module_store.available().get(c.extends)
        if mod is None or mod.builtin:
            return None
        manifest, spec = module_files(c)
        (mod.folder / "stages").mkdir(exist_ok=True)
        path = mod.folder / "stages" / f"{spec['name']}.json"
        if path.exists():
            raise ValueError(f"The module '{mod.label}' has a step file {path.name} already")
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        data = json.loads((mod.folder / "module.json").read_text())
        words = data.setdefault("evidence", {}).setdefault("words", [])
        words += [w for w in c.evidence if w not in words]
        data.setdefault("variable_categories", []).extend(manifest["variable_categories"])
        data.setdefault("category_columns", {}).update(manifest["category_columns"])
        (mod.folder / "module.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        module_store.clear_cache()
        return mod.folder
    base = Path(base) if base else module_store.user_modules_dir()
    folder = base / c.id
    if folder.exists():
        raise ValueError(f"A module folder '{c.id}' exists already: {folder}")
    manifest, spec = module_files(c)
    (folder / "stages").mkdir(parents=True)
    (folder / "module.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (folder / "stages" / f"{spec['name']}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    module_store.clear_cache()
    return folder


# ---- the whole run ------------------------------------------------------------------------------------------------------

def draft_modules(items: Sequence, config: RunConfig, area: str = "the papers' research fields",
                  on_progress: Optional[Callable[[int, int, str], None]] = None,
                  cancel_event: Optional[threading.Event] = None, workers: int = 4, passes: int = 2,
                  survey_cache: Optional[Path] = None, write: bool = False,
                  base: Optional[Path] = None) -> ModuleDraftResult:
    """Survey the papers, propose modules, check them; with `write`, write the ones that pass to the modules folder."""
    from parameter_extractor.errors import ApiKeyMissingError
    if config.needs_api_key and not config.api_key:
        raise ApiKeyMissingError()
    items = list(dict.fromkeys(items))
    if not items:
        raise PipelineError("Add at least one sample paper.")
    config = _config(config)
    report = on_progress or (lambda *a: None)
    work_dir = Path(config.output_dir) / f"module_draft_{datetime.now():%Y%m%d-%H%M%S}"
    work_dir.mkdir(parents=True, exist_ok=True)
    total = len(items) + 2
    report(0, total, f"Surveying {len(items)} paper(s)")
    papers = _survey_all(items, config, work_dir, area, "", cancel_event, passes, workers, report, total,
                         cache_dir=survey_cache)
    good = [p for p in papers if p.survey and p.survey.variables]
    if not good:
        raise PipelineError("None of the papers could be surveyed.")
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelledError()
    report(len(items), total, "Designing modules from the surveys")
    proposal, cost = propose_modules(good, config, work_dir, area, cancel_event)
    modules, left = check_proposals(proposal, good)
    result = ModuleDraftResult(modules, left, papers, proposal, work_dir,
                               cost_usd=round(sum(p.cost_usd for p in papers) + cost, 4))
    if write:
        result.written = [p for p in (write_module(m, base) for m in modules if m.include) if p is not None]
    (work_dir / "module_draft.md").write_text(report_text(result))
    report(total, total, f"{len(modules)} module(s) proposed; ${result.cost_usd:.3f}")
    return result


def report_text(result: ModuleDraftResult) -> str:
    lines = [f"# Modules drafted from {sum(1 for p in result.papers if p.survey)} paper(s)", "",
             f"{datetime.now():%Y-%m-%d %H:%M}; cost ${result.cost_usd:.3f}.", ""]
    for c in result.modules:
        pm = c.proposal
        head = f"## {pm.label} (`{c.id}`)"
        if c.extends:
            mod = module_store.available().get(c.extends)
            head += f" -- an addition to the {mod.label if mod else c.extends} module" + (
                " (one of the app's: for its developers to add)" if mod is not None and mod.builtin else "")
        lines += [head, "", pm.description, "", f"Covers: {pm.covers}", "",
                  "Evidence words: " + ", ".join(c.evidence),
                  "Papers using them: " + ("; ".join(f"{p} ({', '.join(w)})" for p, w in c.papers_with_evidence.items())
                                           or "none"), "", "Step values:"]
        lines += [f"- `{p['column']}`" + (f" [{p['unit']}]" if p.get("unit") else "") + f" -- {p['description']}"
                  for p in c.parameters]
        if c.pack_parameters:
            lines += ["", "Core conditions (added to a pack's own first step when missing):"] + [
                f"- `{p['column']}`" for p in c.pack_parameters]
        if c.notes:
            lines += ["", "Checks:"] + [f"- {n}" for n in c.notes]
        lines.append("")
    if result.left_out:
        lines += ["## Left out", ""] + [f"- {x}" for x in result.left_out] + [""]
    if result.proposal and result.proposal.notes:
        lines += ["## Designer's notes", "", result.proposal.notes, ""]
    return "\n".join(lines)
