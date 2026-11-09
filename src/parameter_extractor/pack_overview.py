"""
What happens to each paper with a data pack (Mickey, 2026-11-09: show users where the model requests come from).

`paper_flow(pack)` lists, in run order, every REQUEST to the AI model a paper can get -- the row planning, the paper's
details, each step (built-in or configurable) with what triggers it and where it comes from (the app, the data pack,
a module) -- then the CALCULATIONS done on the user's computer afterwards (no model requests). The editor's Overview
tab and the Data Packs window show it; the words match the user-facing terms:

  step         one request to the AI model for each paper (built-in steps are written in code; configurable steps
               are described in a file of the pack or a module -- stages/*.json)
  calculation  done on your computer from the model's answers; costs nothing
  module       a shared part several data packs link (steps, calculations, columns, rules, a vocabulary)
  data pack    columns, categories, row rules, its own configurable steps, the modules it links and its settings
               for them, formulas
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

APP = "the app"
# built-in steps by what they do
BUILTIN_LABELS = {"chemistry": "Compounds and their amounts", "analysis": "Analysis methods and instrument settings",
                  "fit_models": "How the fits were made"}
PACK = "this data pack"


@dataclass
class FlowStep:
    kind: str                 # "request" (one model request per paper) | "local" (on your computer) | "optional"
    name: str                 # internal name (stage / calculation id)
    label: str
    source: str               # APP, PACK or "the <label> module"
    when: str                 # which papers it runs for
    what: str = ""
    repeats: bool = False     # asked again for each extra reading (Options: "Read values twice / three times")
    always: bool = False      # runs for every paper with rows (no trigger)


def _module_label(mod) -> str:
    return f"the {mod.label} module"


def trigger_text(spec) -> str:
    t = spec.trigger
    if t.always:
        return "every paper with rows"
    parts = []
    if t.keywords:
        words = ", ".join(f"'{w}'" for w in t.keywords[:6]) + (" …" if len(t.keywords) > 6 else "")
        parts.append(f"papers that mention {words}")
    if t.set_types:
        parts.append("papers with " + " / ".join(t.set_types) + " experiments")
    if t.set_patterns:
        parts.append("papers whose experiment groups look like " + spec.set_word + " experiments")
    if t.sample_fields:
        parts.append("rows with " + ", ".join(t.sample_fields))
    return "; or ".join(parts) or "never (no trigger set)"


def paper_flow(pack) -> List[FlowStep]:
    """Every model request and calculation for a paper with this pack (a packs.Pack, as saved)."""
    from parameter_extractor.pack_editing import BUILTIN_STAGES, CALCULATIONS
    from parameter_extractor.stages.optional import _specs_in, load_specs
    mods = list(getattr(pack, "modules", []))
    own_prompt = (pack.folder / "prompts" / "structure_planner.md").is_file()
    out = [FlowStep("request", "structure_planner", "Plan the rows",
                    PACK if own_prompt else APP + " (with this data pack's row rules)", "every paper",
                    "reads the whole paper and decides which results become rows and how they group", always=True),
           FlowStep("request", "metadata", "Read the paper's details", APP,
                    "every paper (first page only; not needed when the text comes from arXiv)",
                    "title, authors, year, journal, DOI", always=True)]

    def source_of_step(name: str) -> str:
        if name in pack.own_manifest.builtin_stages:
            return PACK
        mod = next((m for m in mods if name in m.manifest.builtin_stages), None)
        return _module_label(mod) if mod else PACK
    for name in pack.manifest.builtin_stages:
        if name == "methodology":
            continue
        out.append(FlowStep("request", name, f"{BUILTIN_LABELS.get(name, name.replace('_', ' ').capitalize())} (built-in step)",
                            source_of_step(name), "every paper with rows", BUILTIN_STAGES.get(name, ""),
                            repeats=name == "chemistry", always=True))
    module_step = {s.name: m for m in mods for s in (_specs_in(m.stages_dir).values() if m.stages_dir.is_dir() else [])}
    for name, spec in load_specs(pack).items():
        mod = module_step.get(name)
        out.append(FlowStep("request", name, spec.label, _module_label(mod) if mod else PACK, trigger_text(spec),
                            spec.description or spec.intro.split(".")[0], repeats=True, always=spec.trigger.always))
    out.append(FlowStep("optional", "figure_planner", "Suggestions for a figure", APP,
                        "figures you choose to digitize (one request per figure)",
                        "which columns the axes and series go into; skipped for figures you skip"))
    out.append(FlowStep("optional", "equations", "Numbered equations as text", APP,
                        "papers read with that option on (one request per paper)"))
    calc_source = {c: _module_label(m) for m in mods for c in m.manifest.postprocess}
    for calc in pack.manifest.postprocess:
        about = CALCULATIONS.get(calc, ("", ""))[0]
        out.append(FlowStep("local", calc, calc.replace("_", " "),
                            PACK if calc in pack.own_manifest.postprocess else calc_source.get(calc, PACK),
                            "every paper", about))
    for f in pack.manifest.formulas:
        out.append(FlowStep("local", f.get("column", ""), f"formula: {f.get('column', '')}", PACK, "every paper",
                            f.get("expression", "")))
    return out


def summary(steps: List[FlowStep]) -> str:
    """One line: how many model requests a paper gets."""
    always = sum(1 for s in steps if s.kind == "request" and s.always)
    maybe = sum(1 for s in steps if s.kind == "request" and not s.always)
    local = sum(1 for s in steps if s.kind == "local")
    text = f"{always} model requests for every paper"
    if maybe:
        text += f", up to {maybe} more for papers that need them"
    return text + f"; {local} calculations on your computer (free)."


# the terms, for the editor's Overview tab and Help > How data packs work (Mickey, 2026-11-09: steps / stages /
# modules were ambiguous)
PARTS = [
    ("Step", "One request to the AI model for each paper it runs for. <i>Built-in steps</i> are written in the app's "
             "code (compounds, analysis methods, fitting models). <i>Configurable steps</i> are described in a file you "
             "can edit (the Steps tab). A step runs for every paper, or only for papers that call for it (trigger "
             "words, kinds of experiments)."),
    ("Calculation", "Done on your computer from the model's answers: unit conversions, totals, formulas. Costs "
                    "nothing."),
    ("Data pack", "Everything for one field: its columns and categories, rules for planning the rows, its own steps, "
                  "calculations and formulas, its compound vocabulary, and the modules it links with its own settings "
                  "for them."),
    ("Module", "A shared part several data packs link: it can bring steps, calculations, columns, rules and a "
               "vocabulary. It isn't copied into the pack, so an improvement to a module reaches every pack that "
               "links it. What one pack changes about a module (parts switched off, units, trigger words, extra rules) "
               "is set on that pack's Modules tab and applies to that pack only."),
    ("Remembered from your reviews", "Columns, synonyms and compound names you accept while reviewing papers. Kept "
                                     "for you, on top of the data pack."),
]

STYLE = ("<style>h2 { margin-top: 18px; margin-bottom: 8px; } h3 { margin-top: 18px; margin-bottom: 6px; } "
         "p { margin-top: 6px; margin-bottom: 8px; line-height: 140%; } td { line-height: 135%; } "
         ".muted { color: #8a8a8a; } .term { font-weight: 600; }</style>")


def parts_html(heading: str = "How a data pack is put together") -> str:
    from html import escape
    rows = "".join(f"<tr><td class='term' width='190' valign='top'>{escape(t)}</td><td valign='top'>{d}</td></tr>"
                   for t, d in PARTS)
    return (STYLE + f"<h2>{escape(heading)}</h2>"
            f"<table cellpadding='7' cellspacing='0' width='100%'>{rows}</table>"
            "<p>Besides its steps, every paper gets two of the app's own requests: planning the rows and reading the "
            "paper's details. Reading the values twice or three times (Options) repeats the steps that extract "
            "values.</p>")


def as_html(steps: List[FlowStep], passes_note: bool = True) -> str:
    """The flow as tables for a QTextBrowser: one per kind (model requests, on request, calculations)."""
    from html import escape
    out = [STYLE, f"<p><b>{escape(summary(steps))}</b></p>"]
    sections = (("request", "Requests to the AI model", "each one is paid for, per paper it runs for"),
                ("optional", "Only when you ask for them", ""),
                ("local", "Calculations on your computer", "no model requests, free"))
    for kind, title, note in sections:
        items = [s for s in steps if s.kind == kind]
        if not items:
            continue
        out.append(f"<h3>{escape(title)}" + (f" <span class='muted'>— {escape(note)}</span>" if note else "")
                   + "</h3>")
        rows = ["<tr><td class='muted' width='4%'>#</td><td class='muted' width='46%'>Step</td>"
                "<td class='muted' width='22%'>From</td><td class='muted'>Runs for</td></tr>"]
        for n, s in enumerate(items, 1):
            extra = "<br><span class='muted'>repeated for each extra reading</span>" if passes_note and s.repeats else ""
            what = f"<br><span class='muted'>{escape(s.what)}</span>" if s.what else ""
            rows.append(f"<tr><td valign='top'>{n}</td><td valign='top'><b>{escape(s.label)}</b>{what}</td>"
                        f"<td valign='top'>{escape(s.source)}</td><td valign='top'>{escape(s.when)}{extra}</td></tr>")
        out.append("<table cellpadding='6' cellspacing='0' width='100%'>" + "".join(rows) + "</table>")
    return "".join(out)
