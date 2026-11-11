"""
What a built-in step does, for people (Mickey, 2026-11-11: the chemistry step underlies most chemistry modules but
nothing in the app showed what it contains). Read-only: built-in steps are code; a data pack can only switch them
on (directly or through a module), add rules to them, and give them a compound list or vocabulary.

`describe(step, pack)` -> StepInfo for a step of a SAVED pack: what it does and when it runs, where it comes from
(the pack or a module), what it reads, what it records (taken from the answer format the model is given, so it
can't drift from the code), the columns it fills, the rules modules and the pack add to its instructions, the
calculations that use its answer, its vocabulary, and the full instructions as the model receives them for this
pack (the paper and the row plan shown as placeholders). `as_html(info)` renders it (pack editor: Steps tab and the
module pages; Data Packs window).
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

STEPS = ("chemistry", "analysis", "fit_models")
PAPER_PLACEHOLDER = "[the paper's text and its tables are inserted here]"
PLAN_PLACEHOLDER = "[the row plan of the paper (its sets and samples) is inserted here]"

# the hand-written part: what the step is for and the columns it fills (the rest is read from the code)
DOCS = {
    "chemistry": {
        "label": "Compounds and their amounts (chemistry)",
        "does": "Reads every compound the paper's experiments use or produce, with its amount, for each row of the "
                "row plan: starting concentrations, stock solutions and the volumes combined, molar ratios, totals "
                "split between components, and measured products (yields, concentrations, amounts recovered, rates). "
                "Tables are read from their images as well as their text.",
        "columns": [
            ("initial_<compound>_<phase>_mM", "a starting concentration, e.g. initial_NaCl_aq_mM, initial_Gly_aq_mM"),
            ("stock_<compound>_<phase>_mM", "a stock solution's concentration (the mixture's is calculated from it)"),
            ("sampled_<compound>_<phase>_<measure>", "a measured product: %yield, mM, %recovered, ratio, rate_mM_hr "
                                                     "or the unit as printed, e.g. sampled_Gly-Gly_aq_%yield"),
            ("added_<solution>_volume_uL", "the volume of each solution combined"),
            ("…_avg / …_range / …_err_plus, …_err_minus", "averages, ranges ('low:high') and uncertainties of the "
                                                         "same values"),
        ],
        "phase": "Phase: aq (dissolved; also products of a dried residue analysed in solution), gas, s (an "
                 "undissolved solid). Names follow the app's naming rules: one name per compound, the paper's "
                 "abbreviation, peptides as sequences.",
        "known": "Compounds in the data pack's compound list (Compounds tab) are written straight into the dataset; "
                 "any other compound is extracted too and offered in the review at the end of the run (accepted "
                 "once, it is written automatically afterwards).",
    },
    "analysis": {
        "label": "Analysis methods and instrument settings",
        "does": "Reads the analytical techniques used to measure the results (HPLC, MS, NMR, …) and their instrument "
                "settings (column, flow rate, wavelength, voltages, …), as printed, for the rows they apply to.",
        "columns": [("analysis_<technique>_<setting>[_range][_<unit>]",
                     "e.g. analysis_RP-HPLC_flow-rate_mL_min, analysis_MALDI-TOF-MS_laser-intensity_range_%, "
                     "analysis_RP-HPLC_column")],
        "phase": "",
        "known": "A technique and setting in the analysis vocabulary (Modules tab, Analysis methods) is written "
                 "straight into the dataset, converted to the setting's unit; others are offered in the review.",
    },
    "fit_models": {
        "label": "How the values were obtained (fitting models)",
        "does": "Reads how an astronomy paper derived its parameters: each fitting model, the data it used, joint "
                "fits, the software, priors and assumptions, and which rows and stars it produced.",
        "columns": [("pl_fit… / st_fit…", "the fit's label, data, joint flags, software, EXOFAST version, "
                                          "assumptions and priors"),
                    ("<column>priortype / priorcen / priorwid / priorlo / priorhi", "a parameter's prior, in the "
                                                                                     "column's unit")],
        "phase": "",
        "known": "",
    },
}


@dataclass
class StepInfo:
    name: str
    label: str
    does: str
    source: str                                  # 'this data pack' or 'the X module'
    when: str
    reads: str
    records: List[Tuple[int, str, str]]          # (depth, field, description) from the answer format
    columns: List[Tuple[str, str]]
    notes: List[str]
    rules: List[Tuple[str, List[str]]]           # (where from, rules) added to the instructions
    calculations: List[Tuple[str, str]]          # (name, what it does) that use the step's answer
    vocabulary: str
    instructions: str                            # the full prompt as sent (paper and plan as placeholders)
    system: str = ""
    problems: List[str] = field(default_factory=list)


def _alias_names(model) -> dict:
    """Short field names the model writes ('nm') -> the readable field names in the code ('name')."""
    import typing
    from pydantic import BaseModel
    out, todo, seen = {}, [model], set()
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        for name, f in m.model_fields.items():
            if f.alias and f.alias != name:
                out.setdefault(f.alias, name)
            stack = [f.annotation]
            while stack:
                t = stack.pop()
                if isinstance(t, type) and issubclass(t, BaseModel):
                    todo.append(t)
                stack.extend(typing.get_args(t))
    return out


def _schema_rows(model) -> List[Tuple[int, str, str]]:
    """Fields and their descriptions as the model sees them (the model-facing answer format); a short name is shown
    with the readable one ('nm (name)')."""
    import re
    from anthropic.lib._parse._transform import transform_schema
    from parameter_extractor.api_client import model_facing_schema
    schema = model_facing_schema(transform_schema(model))
    defs = schema.get("$defs", {})
    names = _alias_names(model)
    rows: List[Tuple[int, str, str]] = []

    def resolve(node):
        while isinstance(node, dict) and "$ref" in node:
            node = defs.get(node["$ref"].split("/")[-1], {})
        if isinstance(node, dict) and "anyOf" in node:
            node = next((n for n in node["anyOf"] if n.get("type") != "null"), node)
            return resolve(node)
        return node

    def walk(node, depth, seen):
        node = resolve(node)
        if node.get("type") == "array":
            return walk(node.get("items", {}), depth, seen)
        for name, prop in (node.get("properties") or {}).items():
            target = resolve(prop)
            kind = "list of" if target.get("type") == "array" else ""
            desc = prop.get("description") or target.get("description") or ""
            enum = target.get("enum") or resolve(target.get("items", {})).get("enum")
            if enum:
                desc = (desc + " " if desc else "") + "One of: " + ", ".join(map(str, enum)) + "."
            shown = f"{name} ({names[name].replace('_', ' ')})" if name in names else name
            desc = re.sub(r"\s*\{default:[^}]*\}", "", desc)
            rows.append((depth, shown + (", a list" if kind else ""), " ".join(desc.split())))
            inner = resolve(target.get("items", {})) if kind else target
            key = json.dumps(inner, sort_keys=True)[:200]
            if inner.get("properties") and key not in seen and depth < 4:
                walk(inner, depth + 1, seen | {key})
    walk(schema, 0, frozenset())
    return rows


def _answer_model(step: str):
    if step == "chemistry":
        from parameter_extractor.schemas.chemistry import ChemistryExtraction
        return ChemistryExtraction
    if step == "analysis":
        from parameter_extractor.schemas.analysis import AnalysisResult
        return AnalysisResult
    from parameter_extractor.schemas.fit_models import FitModels
    return FitModels


def _instructions(step: str, pack) -> Tuple[str, str]:
    """(system line, the step's prompt) for `pack`, as a run builds them."""
    from parameter_extractor.stages import analysis as analysis_stage, chemistry_extractor, fit_models as fit_stage
    if step == "chemistry":
        return ("Extract every species and concentration from text and tables only (not figures). Never drop a "
                "species that doesn't match the controlled vocabulary -- flag it instead.",
                chemistry_extractor.prompt_text(PAPER_PLACEHOLDER, PLAN_PLACEHOLDER, pack.species_names, grids=False))
    if step == "analysis":
        return ("You record how a chemistry paper analysed its products: the analytical techniques and their "
                "instrument settings. Report only what the paper states.",
                analysis_stage.prompt_text(PAPER_PLACEHOLDER, PLAN_PLACEHOLDER))
    return ("You record how an astronomy paper derived its reported parameters: models, data, priors and "
            "assumptions. Report only what the paper states.", fit_stage.prompt_text(PAPER_PLACEHOLDER,
                                                                                     PLAN_PLACEHOLDER))


def describe(step: str, pack) -> StepInfo:
    """The built-in `step` as the saved `pack` (packs.Pack) runs it. Loads the pack for the moment (like a run) to
    assemble its instructions, then puts the previous one back."""
    from parameter_extractor import packs
    from parameter_extractor.pack_editing import CALCULATIONS
    if step not in DOCS:
        raise ValueError(f"no description of a built-in step '{step}'")
    doc = DOCS[step]
    previous = packs._current
    packs._current = pack
    try:
        system, instructions = _instructions(step, pack)
        mods = list(pack.modules)
        source = "this data pack"
        if step not in pack.own_manifest.builtin_stages:
            mod = next((m for m in mods if step in m.manifest.builtin_stages), None)
            source = f"the {mod.manifest.label} module" if mod else source
        rules = []
        from parameter_extractor import module_settings as ms
        for mod in mods:
            off = set(ms.settings_for(pack.own_manifest.module_settings, mod.id).prompt_rules_off)
            own = [r for r in (getattr(mod.manifest, "prompt_rules", {}) or {}).get(step, []) if r not in off]
            if own:
                rules.append((f"the {mod.manifest.label} module", own))
        pack_rules = pack.prompt_rules(step).strip() if step != "structure_planner" else ""
        if pack_rules:
            rules.append(("this data pack", [line.lstrip("- ").strip() for line in pack_rules.splitlines()
                                             if line.strip()]))
        calcs = [(name, CALCULATIONS[name][0]) for name in pack.manifest.postprocess
                 if name in CALCULATIONS and CALCULATIONS[name][1] == step]
        vocabulary = ""
        if step == "chemistry":
            vocabulary = (f"{len(pack.species_names)} compounds in this data pack's compound list (Compounds tab), "
                          f"given to the model so it uses their names.")
        elif step == "analysis":
            from parameter_extractor.analysis_vocab import vocabulary as analysis_vocabulary
            vocab = analysis_vocabulary()
            vocabulary = (f"{len(vocab.techniques)} techniques in {len(vocab.families)} "
                          f"instrument families (the Analysis methods vocabulary), given to the model by name and "
                          f"unit.") if vocab else "No analysis vocabulary: every technique goes to the review."
        problems = []
        if step == "chemistry" and not pack.species_names:
            problems.append("The compound list is empty: every compound will go to the review.")
        return StepInfo(name=step, label=doc["label"], does=doc["does"], source=source,
                        when=("Every paper whose row plan has rows, at the same time as the other steps; "
                              "once per pass when values are read two or three times." if step == "chemistry"
                              else "Every paper whose row plan has rows, at the same time as the other steps."),
                        reads="The whole paper (its text) with images of its tables, and the row plan.",
                        records=_schema_rows(_answer_model(step)), columns=doc["columns"],
                        notes=[n for n in (doc["phase"], doc["known"]) if n], rules=rules, calculations=calcs,
                        vocabulary=vocabulary, instructions=instructions, system=system, problems=problems)
    finally:
        packs._current = previous


def built_in_steps(pack) -> List[str]:
    """The described built-in steps the pack runs (its own or its modules')."""
    return [s for s in pack.manifest.builtin_stages if s in DOCS]


STYLE = """<style>
h2 { margin: 0 0 4px 0; } h3 { margin: 18px 0 6px 0; }
td { padding: 3px 10px 3px 0; vertical-align: top; } .muted { color: palette(placeholder-text); }
code { font-family: Menlo, monospace; } pre { white-space: pre-wrap; font-family: Menlo, monospace; font-size: 11px; }
</style>"""


def as_html(info: StepInfo, with_instructions: bool = True) -> str:
    e = html.escape
    parts = [STYLE, f"<h2>{e(info.label)}</h2>",
             f"<p class='muted'>Built-in step <code>{e(info.name)}</code> · from {e(info.source)} · one request to "
             f"the AI model per paper · view only: data packs and modules switch it on and add rules to it, but its "
             f"answer format and instructions are part of the app.</p>",
             f"<p>{e(info.does)}</p>"]
    parts += [f"<p style='color:#c0392b'>{e(p)}</p>" for p in info.problems]
    parts.append(f"<h3>When it runs and what it reads</h3><p>{e(info.when)}<br>{e(info.reads)}</p>")
    parts.append("<h3>Columns it fills</h3><table>" + "".join(
        f"<tr><td><code>{e(c)}</code></td><td>{e(d)}</td></tr>" for c, d in info.columns) + "</table>")
    parts += [f"<p>{e(n)}</p>" for n in info.notes]
    if info.vocabulary:
        parts.append(f"<h3>Vocabulary</h3><p>{e(info.vocabulary)}</p>")
    if info.rules:
        parts.append("<h3>Rules added to its instructions</h3>")
        for where, rules in info.rules:
            parts.append(f"<p><b>From {e(where)}</b></p><ul>" + "".join(f"<li>{e(r)}</li>" for r in rules) + "</ul>")
    else:
        parts.append("<h3>Rules added to its instructions</h3><p class='muted'>None: it runs with the app's own "
                     "instructions.</p>")
    if info.calculations:
        parts.append("<h3>Calculations that use its answer</h3><table>" + "".join(
            f"<tr><td><code>{e(n)}</code></td><td>{e(d)}</td></tr>" for n, d in info.calculations) + "</table>")
    parts.append("<h3>What it records (the answer format the model fills in)</h3><table>" + "".join(
        f"<tr><td style='padding-left:{depth * 18}px'><code>{e(name)}</code></td><td>{e(desc)}</td></tr>"
        for depth, name, desc in info.records) + "</table>")
    if with_instructions:
        parts.append("<h3>Its instructions, as the model receives them for this data pack</h3>"
                     f"<p class='muted'>{e(info.system)}</p><pre>{e(info.instructions)}</pre>")
    return "".join(parts)
