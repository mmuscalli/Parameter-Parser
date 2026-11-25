"""
Focused search (Mickey, 2026-10-24): a few chosen parameters, across many papers, cheaply -- e.g.
"which of these 50 exoplanet papers used EXOFAST, and which version?".

For each paper (a local PDF, or an arXiv ID / DOI / ADS bibcode read from arXiv -- paper_source):
1. its text is searched locally for the search words (the user's, else words from the chosen
   parameters' descriptions). A paper that never mentions them is reported "not mentioned" with
   NO API call;
2. otherwise ONE small call: only the passages around the hits (default), or the whole paper
   ("whole paper" toggle, for when recall matters more than cost), asking for those parameters
   only -- per object (planet, sample), value as printed, a quote of at most 12 words, where;
3. numbers are converted to the parameter's unit as in a full run (units.convert_printed).

No structure planner, no other stages, no review: the results go to one CSV for the whole search
(focused_results.csv: a line per value) and a CSV of the papers (papers.csv: what was read, status,
cost). Papers run in parallel (Batch mode and the model profile apply as usual).
"""
from __future__ import annotations
import csv
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, create_model

from parameter_extractor import packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError, RunCancelledError
from parameter_extractor.paper_source import PaperItem, resolve_paper, run_name
from parameter_extractor.parameter_checks import STATUSES as CHECK_STATUSES, check_keys  # noqa: F401 (shared)
from parameter_extractor.run_context import RunContext, total_cost

STAGE = "focused_search"
CHECKS_FILE = "parameter_checks.csv"      # check_every: one line per paper and parameter
CONTEXT_LINES = 3                 # lines kept around a hit (a table around a hit is kept whole)
# a hit this many lines above a table also keeps it: captions without a 'Table N' label (PASJ's \tbl
# 'Orbital parameters.' sits 7 lines above teng2023's Table 3 rows, past footnote marks)
TABLE_LOOKBACK = 10
# answer budget: a table of ~40 planets x 2 parameters is ~8K output tokens (teng2023 broke off at
# 3000 + 500 per parameter). Only generated tokens are billed; the budget just stops a runaway answer.
OUTPUT_BASE, OUTPUT_PER_PARAMETER = 6000, 4000
# papers handled at once: direct calls (each a model call in flight), or batch mode (each waiting in a
# shared batch -- cheap threads; arXiv downloads stay one at a time either way)
DIRECT_WORKERS, BATCH_WORKERS = 8, 64
HEAD_CHARS = 1500                 # the start of the paper (title, authors, abstract) always goes along
MAX_PASSAGE_CHARS = 60_000
QUOTE_WORDS = 12
_STOP = {"with", "from", "that", "this", "used", "when", "were", "have", "been", "than", "only", "each", "given",
         "value", "values", "paper", "data", "model", "models", "planet", "planets", "star", "stellar", "e.g.",
         "time", "such", "also", "into", "their", "they", "them", "which", "where", "what", "fitting", "else"}


@dataclass
class FocusParameter:
    column: str
    group: str                    # the stage it belongs to (GUI grouping)
    description: str
    unit: str = ""
    kind: str = "number"          # "number" | "text"
    # columns for its upper / lower uncertainty, in the pack's naming (pl_orbpererr1 / pl_orbpererr2,
    # initial_temperature_C_err_plus ...); empty when the parameter has none
    error_columns: tuple = ()
    compound: str = ""            # a compound column's compound (its default name); '' for a step's parameter
    names: tuple = ()             # its other names (PubChem title and synonyms, the app's words): the search words


COMPOUND_GROUP = "Chemical compounds"
_COMPOUND_COLUMN = re.compile(r"^(?P<role>initial|sampled|stock|calculated)_(?P<name>.+)_(?P<phase>aq|gas|s)_"
                              r"(?P<measure>mM|%yield|%recovered|ratio|rate_mM_hr)$")
_ROLE_TEXT = {"initial": "starting {m} of {n} in the reaction mixture", "sampled": "measured {m} of {n} (a product, "
              "or a reactant left over)", "stock": "{m} of {n} in a stock solution, before mixing",
              "calculated": "{m} of {n} that the paper calculated or modelled"}
_MEASURE_TEXT = {"mM": "concentration", "%yield": "yield (%)", "%recovered": "amount recovered (%)",
                 "ratio": "ratio", "rate_mM_hr": "rate of change"}
_PHASE_TEXT = {"aq": "dissolved", "gas": "gas", "s": "solid"}
MAX_COMPOUND_NAMES = 8


def compound_names_for(name: str, info: Optional[dict] = None) -> List[str]:
    """Other names of a compound for a search: PubChem's title and best synonyms (pubchem.useful_synonyms, from the
    pack's and its modules' species_cids.json or the registry), and the app's own words for it (an amino acid's name,
    a peptide's residues); the column name itself left out."""
    from parameter_extractor.names import AMINO_ACIDS, peptide_codes
    from parameter_extractor.pubchem import useful_synonyms
    info = info or {}
    names = [info.get("title", "")] + list(info.get("synonyms", []))
    if name in AMINO_ACIDS:
        names.insert(0, AMINO_ACIDS[name])
    elif (codes := peptide_codes(name)) and len(codes) > 1:
        names.insert(0, "-".join(AMINO_ACIDS.get(c, c) for c in codes))
    return [n for n in useful_synonyms([n for n in names if n], MAX_COMPOUND_NAMES + 4)
            if n.lower() != name.lower()][:MAX_COMPOUND_NAMES]


def compound_parameters(pack) -> List[FocusParameter]:
    """The pack's compound columns (its own and its modules': initial_Gly_aq_mM, sampled_Gly-Gly_aq_%yield ...) as
    searchable parameters (2026-11-24, Mickey): each described by what it holds and the compound's other names, so a
    paper writing 'glycine' or 'aminoacetic acid' is found and screened in too."""
    from parameter_extractor.compound_names import bundled
    from parameter_extractor.ingestion.flatten_to_template import column_safe_name
    from parameter_extractor.ingestion.observations import unit_for_column
    if not pack.uses("chemistry"):
        return []
    species = list(pack.vocab.get("species_names", []))
    by_slug = {column_safe_name(n): n for n in species}
    identities = bundled(pack)
    out = []
    for column in pack.template_columns:
        m = _COMPOUND_COLUMN.match(column)
        if not m or m.group("name") not in by_slug:
            continue
        name = by_slug[m.group("name")]
        others = compound_names_for(name, identities.get(name))
        what = _ROLE_TEXT[m.group("role")].format(m=_MEASURE_TEXT[m.group("measure")],
                                                  n=f"{name} ({_PHASE_TEXT[m.group('phase')]})")
        description = what + (f"; the paper may call it: {'; '.join(others)}" if others else "")
        out.append(FocusParameter(column, COMPOUND_GROUP, description, unit_for_column(column) or "", "number",
                                  (column + "_err_plus", column + "_err_minus"), compound=name, names=tuple(others)))
    return out


def available_parameters(pack=None, optional_stages: Optional[Dict[str, str]] = None) -> List[FocusParameter]:
    """What can be searched for: the parameters of the research area's stages that aren't switched
    off (RunConfig.optional_stages), and the fitting-model columns when that stage is on."""
    from parameter_extractor.stages.optional import load_specs
    pack = pack or packs.current()
    off = {name for name, mode in (optional_stages or {}).items() if mode == "off"}
    out = []
    for spec in load_specs(pack).values():
        if spec.name in off:
            continue
        out += [FocusParameter(p.column, spec.label, p.description, p.unit, p.kind,
                               tuple(p.column + x for x in spec.suffixes_for(p)[:2]) if p.uncertainties else ())
                for p in spec.parameters]
    if pack.uses("fit_models") and "fit_models" not in off:
        from parameter_extractor.calculators.exoplanet_fits import PLANET_COLUMNS, STELLAR_COLUMNS
        out += [FocusParameter(c, "Fitting models", d, "", "text") for c, d in PLANET_COLUMNS + STELLAR_COLUMNS
                if c != "pl_fitlabel"]
    if "chemistry" not in off:
        known = {p.column for p in out}
        out += [p for p in compound_parameters(pack) if p.column not in known]
    return out


def keywords_for(params: Sequence[FocusParameter], search_words: Sequence[str] = ()) -> List[str]:
    """The words a paper's text is screened for: the user's search words when given (precise), else
    the significant words of the parameters' descriptions (broad)."""
    words = [w.strip().lower() for w in search_words if w.strip()]
    if words:
        return list(dict.fromkeys(words))
    found = []
    for p in params:
        if p.compound:              # a compound: its names, whole (a name under 3 characters would match any line)
            found += [n.lower() for n in [p.compound, *p.names] if len(n) >= 3]
            continue
        found += [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", p.description) if w.lower() not in _STOP]
    return list(dict.fromkeys(found))


_CAPTION = re.compile(r"\s*Table\s*(?:[A-Z]?\d|[IVX]{1,6}[.:])")


def table_spans(lines: List[str]) -> List[range]:
    """The tables in a text: runs of ' | ' rows (arXiv text), blank lines between rows allowed (arXiv's
    rows are blank-line separated), with the 'Table N' caption just above or below when there is one."""
    spans, i, n = [], 0, len(lines)
    is_row = lambda k: k < n and " | " in lines[k]
    while i < n:
        if not is_row(i):
            i += 1
            continue
        lo = hi = i
        j = i + 1
        while j < n:
            if is_row(j):
                hi = j
            elif lines[j].strip() or not (is_row(j + 1) or (not lines[j + 1].strip() if j + 1 < n else False)
                                          and is_row(j + 2)):
                break
            j += 1
        caption = next((k for k in range(lo - 1, max(lo - 8, -1), -1) if _CAPTION.match(lines[k])), None)
        if caption is not None:
            lo = caption
        else:
            below = next((k for k in range(hi + 1, min(hi + 6, n)) if _CAPTION.match(lines[k])), None)
            hi = below if below is not None else hi
        spans.append(range(lo, hi + 1))
        i = hi + 1
    return spans


def passages(text: str, keywords: Sequence[str], whole_tables: bool = True) -> tuple:
    """(the paper's start + every passage around a keyword, number of lines with a hit). With
    `whole_tables`, a hit in a table -- a row, its header or its caption -- or just above it keeps
    the whole table: the rows themselves rarely contain the search words (teng2023's planet table).
    '[...]' marks skipped text."""
    lines = text.splitlines()
    kws = [k.lower() for k in keywords if k]
    hits = [i for i, line in enumerate(lines) if any(k in line.lower() for k in kws)]
    keep = set()
    spans = table_spans(lines) if whole_tables else []
    for i in hits:
        keep.update(range(max(i - CONTEXT_LINES, 0), min(i + CONTEXT_LINES + 1, len(lines))))
        for span in spans:
            if span.start - TABLE_LOOKBACK <= i < span.stop:
                keep.update(span)
    out, last, size = [text[:HEAD_CHARS].rstrip(), "[...]"], None, HEAD_CHARS
    for i in sorted(keep):
        if size > MAX_PASSAGE_CHARS:
            out.append("[... further passages left out ...]")
            break
        if last is not None and i != last + 1:
            out.append("[...]")
        out.append(lines[i])
        size += len(lines[i]) + 1
        last = i
    return "\n".join(out), len(hits)


def answer_model(columns: Sequence[str], check_every: bool = False):
    """The answer schema for these columns: flat, every field required (optional fields invited
    runaway answers, see docs/history/), short field names. `check_every` (2026-11-24, Mickey: controlled
    tests): `checked` has one required entry per parameter -- the model has to answer for each, found or not --
    in place of the free `not_found` list."""
    Col = Literal[tuple(columns)]
    required = lambda names: {"json_schema_extra": {"required": names}}
    Value = create_model(
        "FocusedValue", __config__=ConfigDict(populate_by_name=True, **required(
            ["set", "obj", "col", "v", "u", "ep", "em", "q", "src", "c"])),
        # the pack's two row levels, as in a full run's structure plan (2026-10-30: eder1994's focused rows
        # were whole experiment sets, every time point in one row)
        grp=(str, Field(default="", alias="set", description="The set (experiment condition / system) the value "
                                                             "belongs to; '' for the paper as a whole")),
        obj=(str, Field(description="The sample (row) within the set; '' for a value of the whole set")),
        col=(Col, Field(description="The parameter")),
        v=(str, Field(description="The value exactly as printed")),
        u=(str, Field(description="Its unit as printed, '' if none")),
        ep=(str, Field(default="", description="Upper uncertainty as printed, '' if none")),
        em=(str, Field(default="", description="Lower uncertainty as printed, '' if none")),
        q=(str, Field(description=f"Shortest exact quote showing it, at most {QUOTE_WORDS} words")),
        src=(str, Field(description="Where: section, or table + row")),
        c=(Literal["high", "medium", "low"], Field(description="Confidence")))
    Row = create_model(
        "FocusedRow", __config__=ConfigDict(populate_by_name=True, **required(["set", "obj"])),
        grp=(str, Field(alias="set", description="The set")), obj=(str, Field(description="The row within it")))
    if check_every:
        Check = create_model(
            "ParameterCheck", __config__=ConfigDict(json_schema_extra={"required": ["s", "n"]}),
            s=(Literal[CHECK_STATUSES], Field(description="reported: the paper gives a value (in `values`); not "
                                                         "reported; unclear: something might be it")),
            n=(str, Field(description="A few words: where it is, or what you checked")))
        keys = check_keys(columns)
        Checks = create_model(
            "ParameterChecks", __config__=ConfigDict(populate_by_name=True,
                                                     json_schema_extra={"required": list(keys.values())}),
            **{f"k{i}": (Check, Field(alias=keys[c], description=f"`{c}`")) for i, c in enumerate(columns)})
        return create_model(
            "FocusedAnswer", __config__=ConfigDict(json_schema_extra={"required": ["rows", "values", "checked"]}),
            rows=(List[Row], Field(default_factory=list, description="Every row (set + sample) of the paper's results")),
            values=(List[Value], Field(default_factory=list)),
            checked=(Checks, Field(description="One entry per parameter: was it reported?")))
    return create_model(
        "FocusedAnswer", __config__=ConfigDict(json_schema_extra={"required": ["rows", "values", "not_found"]}),
        # every row the paper's results make, also those with no requested value: a set's values then fill
        # each of its rows (a search for set-level conditions alone gave one row per set)
        rows=(List[Row], Field(default_factory=list, description="Every row (set + sample) of the paper's results")),
        values=(List[Value], Field(default_factory=list)),
        not_found=(List[Col], Field(default_factory=list, description="Parameters the paper doesn't report")))


@dataclass
class FocusedValue:
    paper: str
    obj: str                      # the sample (row); '' for a value of the whole set / paper
    parameter: str
    value: object                 # in the parameter's unit when it's a number that converted
    unit: str
    err_plus: object = ""
    err_minus: object = ""
    printed: str = ""             # value + unit as printed
    quote: str = ""
    where: str = ""
    confidence: str = ""
    note: str = ""
    set: str = ""                 # the set the sample belongs to; '' for the whole paper


@dataclass
class PaperOutcome:
    item: str                     # as given (PDF path or identifier)
    reference: str = ""           # the list's label for it, e.g. 'Tala Pinto et al. 2020' 
    paper: str = ""               # run name
    read_from: str = ""
    title: str = ""
    status: str = ""              # found | not found | not mentioned | error
    found: List[str] = field(default_factory=list)
    hits: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    message: str = ""
    values: List[FocusedValue] = field(default_factory=list)
    rows: List[tuple] = field(default_factory=list)   # (set, sample) of every row the paper's results make
    # check_every: {column: {"status", "note", "values", "problem"}} -- what the model said about each parameter
    checks: Dict[str, dict] = field(default_factory=dict)


def _number(text: str) -> Optional[float]:
    t = (text or "").strip().replace("−", "-").replace("–", "-").replace(",", "").lstrip("+")
    t = re.sub(r"^\$|\$$", "", t)
    try:
        return float(t)
    except ValueError:
        return None


def _converted(param: FocusParameter, item, paper: str) -> FocusedValue:
    from parameter_extractor.units import convert_printed
    printed = f"{item.v} {item.u}".strip()
    out = FocusedValue(paper=paper, obj=item.obj, set=getattr(item, "grp", "") or "", parameter=item.col, value=item.v, unit=item.u, printed=printed,
                       quote=item.q, where=item.src, confidence=item.c, err_plus=item.ep, err_minus=item.em)
    if param.column.endswith("exofastver"):          # the column is the version: 'EXOFASTv2' -> 2
        m = re.search(r"exofast\s*v?(?:ersion)?\s*([12])\b|^\s*v?([12])\s*$", item.v, re.IGNORECASE)
        out.value = int(m.group(1) or m.group(2)) if m else item.v
        if not m:
            out.note = "no EXOFAST version stated"
        return out
    number = _number(item.v)
    if param.kind != "number" or number is None:
        return out
    value, note = convert_printed(number, item.u, param.unit)
    if value is None:
        out.note = f"not converted to {param.unit or 'the column unit'}: {note}"
        return out
    out.value, out.unit, out.note = value, param.unit, note
    for name in ("err_plus", "err_minus"):
        e = _number(getattr(item, "ep" if name == "err_plus" else "em"))
        if e is not None:
            if name == "err_minus" and e > 0:
                e = -e
            converted, _ = convert_printed(e, item.u, param.unit, is_error=True, about=number)
            setattr(out, name, converted if converted is not None else e)
    return out


def _paper_text(source, run_dir: Path, whole_paper: bool, rasterize: bool, dpi: int, supplements: bool = True):
    """(text, table images): arXiv text as is; a PDF's text (+ its table images, whole-paper mode)."""
    from parameter_extractor.pipeline import compact_text
    if source.from_arxiv_text:
        return source.text, []
    from parameter_extractor.ingestion.pdf_parser import parse_pdf, rasterize_table_pages
    parsed = parse_pdf(str(source.pdf))
    if not parsed.has_text_layer:
        raise PipelineError(f"'{source.pdf.name}' has no text layer (a scan): not searched.")
    if supplements:                       # '<paper>_SI.pdf' next to it is searched with it
        from parameter_extractor.ingestion.supplements import find_supplements
        for si_path in find_supplements(source.pdf):
            si = parse_pdf(str(si_path))
            if si.has_text_layer:
                parsed.add_supplement(si, si_path)
    images = []
    if whole_paper and rasterize and parsed.table_pages:
        by_page = rasterize_table_pages(parsed, run_dir / "page_images", dpi=dpi)
        images = [p for page in sorted(by_page) for p in by_page[page]]
    return compact_text(parsed.text), images


def search_paper(item: PaperItem, params: Sequence[FocusParameter], config: RunConfig, run_dir: Path,
                 search_words: Sequence[str] = (), whole_paper: bool = False,
                 cancel_event: Optional[threading.Event] = None, whole_tables: bool = True,
                 record=None, cache=None, client=None, collector=None, plan_rows: bool = False,
                 check_every: bool = False) -> PaperOutcome:
    """`record`: the identifier's arXiv record (or the PaperSourceError) from the batched lookup;
    `cache`: arXiv texts kept between runs; `client` / `collector`: shared by all papers (one
    Anthropic client; in batch mode, requests pooled into shared batches)."""
    from parameter_extractor.api_client import call_structured
    from parameter_extractor.stages.prompt_loader import load_prompt
    outcome = PaperOutcome(item=str(item), paper=run_name(item), reference=getattr(item, "label", ""))
    run_dir.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(config=config, run_dir=run_dir, total_steps=1, cancel_event=cancel_event)
    ctx._client, ctx.batch_collector = client, collector
    ctx.check_cancelled()
    if isinstance(record, PipelineError):
        raise record
    source = resolve_paper(item, run_dir, prefer_arxiv=config.prefer_arxiv, ads_token=config.ads_token,
                           record=record, cache=cache)
    (run_dir / "source.json").write_text(json.dumps(source.summary(), indent=2, ensure_ascii=False))
    outcome.read_from = source.label
    # rows as in a full extraction: the table images are needed to plan them (eder1994's text-layer tables
    # are garbled), and go with the focused question too
    text, images = _paper_text(source, run_dir, whole_paper or plan_rows, config.rasterize_table_pages,
                               config.table_raster_dpi, config.include_supplements)
    outcome.title = (source.record.title if source.record else next(
        (line.strip() for line in text.splitlines()[:60] if len(line.strip()) > 25
         and not re.search(r"https?://|doi\.org|^\W*(?:a&a|astronomy|publ\.|journal)\b", line.strip(), re.IGNORECASE)),
        ""))[:200]
    keywords = keywords_for(params, search_words)
    if whole_paper:
        body = text
        _, outcome.hits = passages(text, keywords)
    else:
        body, outcome.hits = passages(text, keywords, whole_tables)
        if outcome.hits == 0:
            outcome.status = "not mentioned"
            outcome.message = f"none of the search words appear in the text ({', '.join(keywords[:8])})"
            if check_every:
                outcome.checks = {p.column: {"status": "not searched", "note": "no search word in the text (screened "
                                             "on this computer, no request)", "values": 0, "problem": ""}
                                  for p in params}
            return outcome
    pack = packs.current()
    listing = "\n".join(f"- `{p.column}`: {p.description}" + (f" (unit: {p.unit})" if p.unit else "")
                        for p in params)
    scope = ("The whole paper follows." if whole_paper else
             "Only PASSAGES of the paper follow: its start, and the parts around these words: "
             + ", ".join(keywords[:20]) + ". '[...]' marks text left out"
             + ("; tables near a match are complete." if whole_tables else "."))
    units = pack.manifest.units
    prompt = load_prompt(STAGE, PARAMETERS=listing, SCOPE=scope, SET_WORD=units.get("set", "set"),
                         SAMPLE_WORD=units.get("sample", "sample"))
    plan = None
    if plan_rows:
        from parameter_extractor.stages.structure_planner import run_structure_planner
        plan = run_structure_planner(ctx, text, table_images=images or None)
        if plan.experiment_sets:
            prompt += ("\n\nROW PLAN of this paper (from its full row planning): use EXACTLY these `set` and `obj` "
                       "labels -- every value goes on one of these rows (`obj` '' for a value of a whole set, `set` "
                       "'' for the whole paper); leave `rows` empty.\n" + "\n".join(
                           f"- set {s.set_label!r}: " + ", ".join(repr(x.sample_label) for x in s.samples)
                           for s in plan.experiment_sets))
    if check_every:
        keys = check_keys([p.column for p in params])
        prompt += ("\n\nEVERY PARAMETER CHECKED: instead of `not_found`, `checked` has one entry per parameter above, "
                   "keyed by its name" + ("" if all(k == c for c, k in keys.items()) else " (" + ", ".join(
                       f"`{c}` is `{k}`" for c, k in keys.items() if k != c) + ")") + ". Look for EACH parameter "
                   "specifically, in the text and the tables, and answer for every one: `s` 'reported' when the paper "
                   "gives a value for it (its values go in `values`), 'not reported' when it doesn't, 'unclear' when "
                   "something might be it but you aren't sure; `n` a few words: where it is, or what you checked.")
    content = f"{prompt}\n\nPAPER {'TEXT' if whole_paper else 'PASSAGES'}:\n{body}"
    model = answer_model([p.column for p in params], check_every)
    answer = call_structured(ctx, stage=STAGE, system_prompt="Find only the requested parameters in a research "
                             "paper. Report only what the paper states.", user_content=content,
                             response_model=model, image_paths=images or None,
                             max_tokens=OUTPUT_BASE + OUTPUT_PER_PARAMETER * len(params))
    by_column = {p.column: p for p in params}
    outcome.values = [_converted(by_column[v.col], v, outcome.paper) for v in answer.values if v.col in by_column]
    outcome.rows = list(dict.fromkeys((r.grp, r.obj) for r in getattr(answer, "rows", []) if r.obj or r.grp))
    if plan is not None and plan.experiment_sets:          # the planned rows, in the plan's order
        outcome.rows = [(s.set_label, x.sample_label) for s in plan.experiment_sets for x in s.samples]
    outcome.found = list(dict.fromkeys(v.parameter for v in outcome.values))
    if check_every:
        outcome.checks = _checks(answer, params, outcome.values)
    outcome.status = "found" if outcome.values else "not found"
    outcome.cost_usd = total_cost(ctx.usage) or 0.0
    outcome.input_tokens = sum(u.prompt_tokens for u in ctx.usage)
    outcome.output_tokens = sum(u.output_tokens for u in ctx.usage)
    return outcome


def _checks(answer, params: Sequence[FocusParameter], values: Sequence["FocusedValue"]) -> Dict[str, dict]:
    """What the model said about each parameter, against the values it gave: 'reported' with no value, or values
    for one it marked 'not reported', is a problem (shown, nothing changed)."""
    keys = check_keys([p.column for p in params])
    checked = getattr(answer, "checked", None)
    raw = checked.model_dump(by_alias=True) if checked is not None else {}
    counts = {p.column: sum(v.parameter == p.column for v in values) for p in params}
    out = {}
    for p in params:
        entry = raw.get(keys[p.column]) or {}
        status, n = entry.get("s", ""), counts[p.column]
        problem = ("marked reported, but no value given" if status == "reported" and n == 0 else
                   f"{n} value(s) given, but marked not reported" if status == "not reported" and n else "")
        out[p.column] = {"status": status or "no answer", "note": entry.get("n", ""), "values": n, "problem": problem}
    return out


@dataclass
class FocusedRun:
    out_dir: Path
    results_csv: Path             # one row per paper (and object), a column per parameter
    papers_csv: Path
    outcomes: List[PaperOutcome]
    cost_usd: float
    params: List[FocusParameter] = field(default_factory=list)
    quotes_csv: Optional[Path] = None   # one line per value, with its quote and where it is


@dataclass
class WideRow:
    """One row of the results: a paper, or one sample (row) of a set in it -- the pack's rows, as in a
    full run -- with its values by parameter. A set's values (obj '') go on each of that set's sample
    rows, the paper's (set and obj '') on every row; a set with no sample values is a row of its own."""
    outcome: PaperOutcome
    obj: str
    cells: Dict[str, List[FocusedValue]] = field(default_factory=dict)
    set: str = ""


def wide_rows(outcomes: Sequence[PaperOutcome]) -> List[WideRow]:
    rows = []
    for o in outcomes:
        paper_wide = [v for v in o.values if not v.obj and not v.set]
        # the rows the answer listed (the pack's rows), then any row a value names that wasn't listed
        keys = list(dict.fromkeys([k for k in o.rows if k[1]] + [(v.set, v.obj) for v in o.values if v.obj]))
        with_samples = {s for s, _ in keys}
        keys += list(dict.fromkeys((v.set, "") for v in o.values if v.set and not v.obj and v.set not in with_samples))
        for set_label, obj in keys or [("", "")]:
            row = WideRow(o, obj, set=set_label)
            own = [v for v in o.values if v.set == set_label and v.obj == obj and (obj or set_label)]
            whole_set = [v for v in o.values if set_label and v.set == set_label and not v.obj] if obj else []
            # the most specific level wins for a parameter, as in a full run (sample > set > paper):
            # eder1994's paper-wide "oven at 80 C" (a different, untabulated experiment) sat next to each
            # set's own temperature as "80; 81"
            for level in (own, whole_set, paper_wide):
                for v in level:
                    if v.parameter not in row.cells or level is own or row.cells[v.parameter][0] in level:
                        row.cells.setdefault(v.parameter, []).append(v)
            rows.append(row)
    return rows


def _shown(v: FocusedValue, param: Optional[FocusParameter]) -> str:
    """A value as the results show it: in the column's unit, else with the unit it was printed in."""
    value = f"{v.value:g}" if isinstance(v.value, float) else str(v.value)
    return value if not v.unit or (param and v.unit == param.unit) else f"{value} {v.unit}"


def cell_text(values: Sequence[FocusedValue], param: Optional[FocusParameter] = None, part: str = "value") -> str:
    """The text of one results cell: the value(s) -- several distinct ones joined by '; ' -- or their
    upper / lower uncertainty (part 'err_plus' / 'err_minus')."""
    if part == "value":
        texts = [_shown(v, param) for v in values]
    else:
        texts = [f"{getattr(v, part):g}" if isinstance(getattr(v, part), float) else str(getattr(v, part))
                 for v in values if getattr(v, part) not in ("", None)]
    return "; ".join(dict.fromkeys(t for t in texts if t))


def value_tip(values: Sequence[FocusedValue]) -> str:
    """Hover text for a results cell: each value as printed, its quote and where it is."""
    lines = []
    for v in values:
        errs = (f" (+{v.err_plus} / {v.err_minus})" if v.err_plus not in ("", None) else "")
        lines.append(f"{v.printed}{errs}" + (f" -> {_shown(v, None)}" if v.note and "->" not in v.note else "")
                     + f"\n    \u201c{v.quote}\u201d ({v.where}, {v.confidence} confidence)"
                     + (f"\n    {v.note}" if v.note else ""))
    return "\n".join(lines)


RESULT_COLUMNS = ["paper", "set", "obj", "parameter", "value", "unit", "err_plus", "err_minus", "printed", "quote", "where",
                  "confidence", "note"]
PAPER_COLUMNS = ["item", "reference", "paper", "read_from", "title", "status", "found", "hits", "cost_usd", "input_tokens",
                 "output_tokens", "message"]


def read_paper_list(path: Path, only_failed: bool = False) -> List[PaperItem]:
    """A CSV (or plain list) of papers: in each line, the first cell that's an arXiv ID, a DOI, an ADS
    bibcode or a .pdf path (relative paths are next to the list). Header lines are skipped. An earlier
    search's papers.csv works too (its labels are kept); `only_failed`: just its 'error' rows."""
    from parameter_extractor.ingestion.arxiv_source import PaperRef, identifier_in_cell
    path = Path(path)
    items: List[PaperItem] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        text = f.read()
    rows = list(csv.reader(text.splitlines()))
    # a line that is a whole .pdf path is taken as it is: file names can hold commas ('2',3'-Cyclic ...',
    # 'Heated gas bubbles enrich, crystallize, dry, ...'), which the CSV reading cuts apart (2026-11-09)
    whole = {}
    for n, line in enumerate(text.splitlines()):
        stripped = line.strip().strip('"')
        if stripped.lower().endswith(".pdf") and "," in stripped:
            pdf = Path(stripped).expanduser()
            pdf = pdf if pdf.is_absolute() else path.parent / pdf
            if pdf.is_file():
                whole[n] = pdf
    header = [c.strip().lower() for c in rows[0]] if rows else []
    if "item" in header and "status" in header:          # an earlier focused search's papers.csv
        at = {name: header.index(name) for name in ("item", "status", "reference") if name in header}
        for row in rows[1:]:
            if len(row) <= at["item"] or (only_failed and row[at["status"]] != "error"):
                continue
            label = row[at["reference"]] if "reference" in at and len(row) > at["reference"] else ""
            cell = row[at["item"]].strip()
            if cell.lower().endswith(".pdf"):
                items.append(Path(cell))
            elif identifier_in_cell(cell):
                items.append(PaperRef(str(identifier_in_cell(cell)), label))
        return list(dict.fromkeys(items))
    for n, row in enumerate(rows):
        if n in whole:
            items.append(whole[n])
            continue
        for cell in (c.strip() for c in row):
            if cell.lower().endswith(".pdf"):
                pdf = Path(cell).expanduser()
                items.append(pdf if pdf.is_absolute() else path.parent / pdf)
                break
            ref = identifier_in_cell(cell)      # also reference links (Exoplanet Archive export)
            if ref:
                items.append(ref)
                break
    return list(dict.fromkeys(items))


def _new_dir(output_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out, n = output_dir / f"focused_search_{stamp}", 2
    while out.exists():
        out, n = output_dir / f"focused_search_{stamp}_{n}", n + 1
    out.mkdir(parents=True)
    return out


def run_focused_search(items: Sequence[PaperItem], columns: Sequence[str], config: RunConfig,
                       search_words: Sequence[str] = (), whole_paper: bool = False,
                       on_progress: Optional[Callable[[int, int, str], None]] = None,
                       cancel_event: Optional[threading.Event] = None, max_workers: int = 0,
                       whole_tables: bool = True, plan_rows: Optional[bool] = None,
                       check_every: bool = False) -> FocusedRun:
    """Search every paper for `columns` only. `plan_rows`: plan each paper's rows with the pack's structure
    planner first, as a full extraction does (more tokens: the whole paper + its table images); None = the
    pack's default (pack.json focused_row_plan). on_progress(done, total, message). `whole_tables`
    (passages mode): a match in or just above a table sends the whole table (measured 2026-10-24:
    +10-45% passage tokens, ~$0.003 a paper on Economy; without it teng2023's planet table -- rows
    without the search words -- was missed). `check_every`: the model answers for every parameter, found or not
    (parameter_checks.csv) -- for controlled tests."""
    from parameter_extractor.errors import ApiKeyMissingError
    if config.needs_api_key and not config.api_key:
        raise ApiKeyMissingError()
    packs.activate(config.pack)
    known = {p.column: p for p in available_parameters(optional_stages=config.optional_stages)}
    unknown = [c for c in columns if c not in known]
    if unknown or not columns:
        raise PipelineError(f"Not parameters of the active stages of '{packs.current().label}': "
                            f"{', '.join(unknown) or '(none chosen)'}.")
    params = [known[c] for c in dict.fromkeys(columns)]
    if plan_rows is None:
        plan_rows = packs.current().manifest.focused_row_plan
    items = list(dict.fromkeys(items))
    if config.include_supplements:        # an SI file is searched with its paper, not on its own
        from parameter_extractor.ingestion.supplements import drop_supplements
        items, _ = drop_supplements(items)
    out_dir = _new_dir(Path(config.output_dir))
    report = on_progress or (lambda *a: None)
    # 1. every identifier looked up at once (batched arXiv queries; cached lookups reused)
    from parameter_extractor.ingestion import arxiv_source as ax
    from parameter_extractor.paper_source import is_identifier
    cache = ax.LookupCache(config.arxiv_cache_dir)
    identifiers = [item for item in items if is_identifier(item)]
    report(0, len(items), f"Looking up {len(identifiers)} paper(s) on arXiv")
    records = ax.resolve_many(identifiers, config.ads_token, cache,
                              note=lambda m: report(0, len(items), m)) if identifiers else {}
    # 2. one client for all papers; in batch mode their requests share batches, and many papers can
    #    wait in the queue at once (the arXiv downloads stay one at a time: arxiv_source's rate limit)
    from parameter_extractor.api_client import BatchCollector
    client = collector = None
    if not config.is_local:                       # a local server needs no client (local_models.py)
        import anthropic
        client = anthropic.Anthropic(api_key=config.api_key, max_retries=5)
        collector = BatchCollector(client) if config.batch_mode else None
    workers = max_workers if max_workers else (BATCH_WORKERS if config.batch_mode else DIRECT_WORKERS)
    names: Dict[str, int] = {}
    jobs = []
    for item in items:
        name = run_name(item)
        names[name] = names.get(name, 0) + 1
        jobs.append((item, out_dir / "papers" / (name if names[name] == 1 else f"{name}_{names[name]}")))
    outcomes: List[PaperOutcome] = []
    done = 0
    report(0, len(jobs), f"Searching {len(jobs)} paper(s) for {', '.join(c for c in columns)}")
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="focused") as pool:
        futures = {pool.submit(search_paper, item, params, config, run_dir, search_words, whole_paper,
                               cancel_event, whole_tables, records.get(str(item)), cache, client, collector,
                               plan_rows, check_every):
                   (item, run_dir) for item, run_dir in jobs}
        try:
            for future in as_completed(futures):
                item, run_dir = futures[future]
                try:
                    outcome = future.result()
                except RunCancelledError:
                    raise
                except PipelineError as e:
                    outcome = PaperOutcome(item=str(item), paper=run_dir.name, status="error", message=str(e),
                                           reference=getattr(item, "label", ""))
                except Exception as e:                      # one bad paper doesn't stop the others
                    outcome = PaperOutcome(item=str(item), paper=run_dir.name, status="error",
                                           message=f"{type(e).__name__}: {e}", reference=getattr(item, "label", ""))
                outcomes.append(outcome)
                done += 1
                if done % 50 == 0:
                    cache.save()
                report(done, len(jobs), f"{outcome.paper}: {outcome.status}"
                                        + (f" ({', '.join(outcome.found)})" if outcome.found else ""))
        except RunCancelledError:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    cache.save()
    order = {str(item): i for i, (item, _) in enumerate(jobs)}
    outcomes.sort(key=lambda o: order.get(o.item, len(order)))
    return _write(out_dir, outcomes, params, config, search_words, whole_paper, whole_tables, check_every)


def result_columns(params: Sequence[FocusParameter], outcomes: Sequence[PaperOutcome]) -> List[tuple]:
    """(column name, parameter, part) for the results: each parameter's value column, then its
    uncertainty columns when any value has an uncertainty."""
    with_errors = {v.parameter for o in outcomes for v in o.values if v.err_plus not in ("", None)
                   or v.err_minus not in ("", None)}
    out = []
    for p in params:
        out.append((p.column, p, "value"))
        if p.column in with_errors:
            plus, minus = p.error_columns or (p.column + "_err_plus", p.column + "_err_minus")
            out += [(plus, p, "err_plus"), (minus, p, "err_minus")]
    return out


def _write(out_dir: Path, outcomes: List[PaperOutcome], params, config: RunConfig, search_words, whole_paper,
           whole_tables: bool = True, check_every: bool = False) -> FocusedRun:
    results_csv, papers_csv = out_dir / "focused_results.csv", out_dir / "papers.csv"
    quotes_csv = out_dir / "focused_values_with_quotes.csv"
    columns = result_columns(params, outcomes)
    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["reference", "paper", "set", "obj", "status"] + [c for c, _, _ in columns] + ["read_from", "title"])
        for row in wide_rows(outcomes):
            o = row.outcome
            w.writerow([o.reference, o.paper, row.set, row.obj, o.status]
                       + [cell_text(row.cells.get(p.column, []), p, part) for _, p, part in columns]
                       + [o.read_from, o.title])
    with open(quotes_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_COLUMNS)
        w.writeheader()
        for o in outcomes:
            for v in o.values:
                w.writerow({k: getattr(v, k) for k in RESULT_COLUMNS})
    with open(papers_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PAPER_COLUMNS)
        w.writeheader()
        for o in outcomes:
            row = {k: getattr(o, k) for k in PAPER_COLUMNS}
            row["found"] = "; ".join(o.found)
            row["cost_usd"] = round(o.cost_usd, 5)
            w.writerow(row)
    if check_every:                              # one line per paper and parameter: what the model said about it
        with open(out_dir / CHECKS_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["reference", "paper", "parameter", "status", "values", "note", "problem"])
            for o in outcomes:
                for p in params:
                    c = o.checks.get(p.column) or {"status": "error" if o.status == "error" else "no answer",
                                                   "note": o.message if o.status == "error" else "", "values": 0,
                                                   "problem": ""}
                    w.writerow([o.reference, o.paper, p.column, c["status"], c["values"], c["note"], c["problem"]])
    cost = sum(o.cost_usd for o in outcomes)
    summary = {"finished": datetime.now().isoformat(timespec="seconds"), "config": config.to_public_dict(),
               "parameters": [asdict(p) for p in params], "search_words": list(search_words),
               "whole_paper": whole_paper, "whole_tables": whole_tables and not whole_paper, "papers": len(outcomes),
               "check_every_parameter": check_every,
               "status_counts": {s: sum(o.status == s for o in outcomes) for s in
                                 ("found", "not found", "not mentioned", "error")},
               "estimated_cost_usd": round(cost, 5)}
    (out_dir / "focused_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return FocusedRun(out_dir, results_csv, papers_csv, outcomes, cost, list(params), quotes_csv)
