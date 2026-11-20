"""
Requests for another assistant (Mickey, 2026-11-19): a paper's model requests written out as a package for an
assistant outside the app -- any model or agent the user chooses -- and its answers imported back into a normal run.
No account, login or program of anyone's is used or driven: the app writes files, the user takes them to their
assistant (or points their own agent at the folder), and brings the answers back. Brand-neutral throughout.

Export (`export_package`): the paper is read as for a run (`read_paper`), then every request the run would send is
recorded instead of sent -- the row plan, the paper's details, then each extraction step the data pack has for this
paper (a step that depends on the row plan's sets is marked conditional). The steps are built before the row plan
exists: where a step's task holds the plan, the request says ROW_PLAN_MARK, and the package's instructions tell the
assistant to put its own row-plan answer there in the steps' form (`step_plan_json`: sets S1, S2 ..., samples S1.1
...), so it can answer every request in one go, in order.

    <folder>/<paper>/
        INSTRUCTIONS.md          for the assistant (and the person): what to do, in order
        package.json             the app's record: the paper, data pack, settings, each request and its answer file
        <paper>.pdf              the paper (when it is a file); paper.txt its text as the app read it
        images/                  table-page images and figure crops the requests refer to
        requests/NN-<step>.md    one per request: instructions, inputs, task, answer format (JSON Schema)
        answers/NN-<step>.json   the assistant's answer: ONE JSON object matching the request's format
        answers/about.json       which model / assistant answered (shown with the results, kept in the run)

Import (`import_package`): the paper is run again with the package's settings; each request is answered from its
file instead of being sent (the row plan first, then every step with the real plan). An answer that's missing or
doesn't fit its format is listed (answers/NN-<step>.error.txt says why); fix it and import again. The results are
flagged as answered outside the app, by the model about.json names -- like a local model's, unvalidated.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

from parameter_extractor.errors import AnswersNeededError, PipelineError

PACKAGE_FILE = "package.json"
INSTRUCTIONS_FILE = "INSTRUCTIONS.md"
ABOUT_FILE = "about.json"
ROW_PLAN_MARK = "[[ROW PLAN]]"
ROW_PLAN_ANSWER_MARK = "[[ROW PLAN AS ANSWERED]]"
FORMAT = 1
NAMES = {"structure_planner": "row-plan", "metadata": "paper-details"}
_lock = threading.Lock()
_recorded: Dict[str, dict] = {}            # export: folder -> {stage: request}


class RequestsRecorded(AnswersNeededError):
    """Export: the round's requests were recorded (the run stops here, as handoff does)."""

    def _message(self) -> str:
        return f"{len(self.keys)} request(s) recorded for the package in {self.folder}."


class AnswersMissingError(AnswersNeededError):
    """Import: answers missing, skipped although the step applies, or not fitting their format."""

    def _message(self) -> str:
        missing = [k for k in self.keys if k not in self.invalid]
        parts = []
        if missing:
            parts.append(f"{len(missing)} answer(s) missing: {', '.join(missing)}")
        if self.invalid:
            parts.append(f"{len(self.invalid)} answer(s) don't fit their format: {', '.join(self.invalid)} "
                         f"(answers/*.error.txt says why)")
        return (f"The package in {self.folder} can't be imported yet -- " + "; ".join(parts) +
                ". Answer or fix them (INSTRUCTIONS.md there), then import again.")


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("_") or "paper"


# ---- the requests, as a run makes them ---------------------------------------------------------------------------

def answer(ctx, stage: str, system_prompt: str, content, response_model):
    """api_client's stand-in for a request in an exchange run: export records it (the row plan gets a stand-in
    answer so the steps are made too); import answers it from the package."""
    from parameter_extractor import api_client
    cfg = ctx.config
    folder = Path(cfg.exchange_dir)
    name = (getattr(api_client._streamed, "request_name", "") or stage).removesuffix(".retry")
    if cfg.exchange_mode == "export":
        return _record(ctx, folder, stage, name, system_prompt, content, response_model)
    return _answer_from_package(folder, stage, name, response_model)


def _texts_and_images(folder: Path, content):
    """(text parts, [(image path, label)]) of a request's content; the paper text to paper.txt, images to images/."""
    import base64
    import hashlib
    if isinstance(content, str):
        return [content], []
    texts, images = [], []
    for block in content:
        if block.get("type") == "image":
            data = base64.standard_b64decode(block["source"]["data"])
            ext = ".png" if block["source"]["media_type"] == "image/png" else ".jpg"
            name = f"images/{hashlib.sha1(data).hexdigest()[:12]}{ext}"
            if not (folder / name).is_file():
                (folder / name).parent.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(data)
            label = texts.pop() if texts and texts[-1].startswith(("Page ", "Supplementary")) and \
                "\n" not in texts[-1] else ""
            images.append((name, label))
        elif block.get("type") == "text":
            text = block["text"]
            if text.startswith("PAPER TEXT:"):
                with _lock:
                    (folder / "paper.txt").write_text(text[len("PAPER TEXT:"):].lstrip("\n"))
                continue
            texts.append(text)
    return texts, images


PAPER_MARK = "[[THE PAPER'S TEXT: read it in paper.txt]]"


def _stand_in_plan():
    """The row plan the export answers itself with (the steps and figures are made with it, then its place marked)."""
    from parameter_extractor.schemas.structure_plan import StructurePlan
    return StructurePlan.model_validate({"kind": "experimental", "n_rows": 1, "excluded": [], "notes": "",
                                         "sets": [{"set": "(a set)", "type": "Independent", "varies": "",
                                                   "src": "", "samples": [{"label": "(a sample)"}]}]})


def _record(ctx, folder: Path, stage: str, name: str, system_prompt: str, content, response_model):
    folder.mkdir(parents=True, exist_ok=True)
    texts, images = _texts_and_images(folder, content)
    paper = getattr(getattr(ctx, "paper", None), "text", "") or ""
    if paper and any(paper in t for t in texts):        # the paper once, in paper.txt -- not in every request
        with _lock:
            (folder / "paper.txt").write_text(paper)
        texts = [t.replace(paper, PAPER_MARK) for t in texts]
    whole = _stand_in_plan().model_dump_json(indent=2)  # a figure's suggestions get the plan as answered
    texts = [t.replace(whole, ROW_PLAN_ANSWER_MARK) for t in texts]
    request = {"stage": stage, "name": name, "instructions": system_prompt, "texts": texts, "images": images,
               "schema": response_model.model_json_schema(by_alias=True)}
    with _lock:
        _recorded.setdefault(str(folder), {})[name] = request
    if stage == "structure_planner":                 # a stand-in plan: the steps that need one are made too
        plan = _stand_in_plan()
        return SimpleNamespace(id="export-plan", stop_reason="end_turn", parsed_output=plan,
                               content=[SimpleNamespace(type="text", text=plan.model_dump_json(by_alias=True))],
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    raise RequestsRecorded(folder, [stage])


def _answer_from_package(folder: Path, stage: str, name: str, response_model):
    manifest = json.loads((folder / PACKAGE_FILE).read_text())
    entry = next((r for r in manifest["requests"] if r.get("name", r["stage"]) == name), None) or \
        next((r for r in manifest["requests"] if r["stage"] == stage and stage != "figure_planner"), None)
    if stage == "figure_planner" and (entry is None or not (folder / entry["answer"]).is_file()):
        raise PipelineError("The package has no suggestions for this figure (its assistant didn't answer that "
                            "request, or the figure wasn't in it): digitize it by hand -- its axes and series -- or "
                            "skip it.")
    if entry is None:
        raise PipelineError(f"The package in {folder} has no request for the step '{stage}' this paper needs: export "
                            f"the paper again (the data pack or its settings may have changed).")
    path = folder / entry["answer"]
    error_path = path.with_suffix(".error.txt")
    name = Path(entry["answer"]).stem
    if not path.is_file():
        raise AnswersMissingError(folder, [name])
    raw = path.read_text()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("skipped") is True and len(data) <= 2:
            error_path.write_text("This step was skipped, but it applies to this paper (from the row plan's sets): "
                                  "answer it as its request asks.")
            raise AnswersMissingError(folder, [name], invalid=[name])
        from parameter_extractor.api_client import _decoded
        parsed = response_model.model_validate(_decoded(data) if isinstance(data, dict) else data)
    except AnswersMissingError:
        raise
    except Exception as e:  # noqa: BLE001 -- any problem with the answer goes back to whoever answered it
        error_path.write_text(f"The answer in {path.name} doesn't fit its request's answer format:\n\n{e}\n\n"
                              f"Fix it (or answer it again), then import the package again.")
        raise AnswersMissingError(folder, [name], invalid=[name]) from None
    error_path.unlink(missing_ok=True)
    return SimpleNamespace(id=f"import-{name}", stop_reason="end_turn", parsed_output=parsed,
                           content=[SimpleNamespace(type="text", text=raw)],
                           usage=SimpleNamespace(input_tokens=0, output_tokens=0))


def answered_by(folder) -> str:
    """'<model> (<assistant or tool>)' from answers/about.json, or '' when it isn't there."""
    path = Path(folder) / "answers" / ABOUT_FILE
    try:
        about = json.loads(path.read_text())
    except (OSError, ValueError):
        return ""
    model = str(about.get("model") or "").strip()
    tool = str(about.get("assistant") or about.get("tool") or "").strip()
    return f"{model} ({tool})" if model and tool else model or tool


# ---- export --------------------------------------------------------------------------------------------------------

def export_package(item, config, out_dir, on_progress=None) -> Path:
    """Write `item`'s (a PDF, arXiv id, DOI) package under `out_dir`; returns its folder. No request is sent."""
    from dataclasses import replace
    from unittest.mock import patch
    from parameter_extractor import pipeline
    from parameter_extractor.paper_source import run_name
    from parameter_extractor.stages import optional
    out_dir = Path(out_dir)
    folder = out_dir / _safe(run_name(item))
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    work = folder / ".run"                            # the app's own run folder while recording (removed after)
    cfg = replace(config, exchange_dir=folder, exchange_mode="export", output_dir=work, passes=1, batch_mode=False,
                  prompt_caching=False, shared_instructions=False, equations_to_latex=False, handoff_dir=None,
                  online_checks=False)
    from parameter_extractor import schemas
    plan_modules = [m for name, m in list(__import__("sys").modules.items())
                    if name.startswith("parameter_extractor.") and getattr(m, "step_plan_json", None) is not None
                    and m is not schemas.structure_plan]
    conditional: Dict[str, str] = {}

    def triggered(spec, structure, paper_text=""):
        """Every step that could apply: a step that depends on the row plan's sets is answered only if they fit."""
        t = spec.trigger
        sure = t.always or (t.keywords and spec.keyword_hits(paper_text) >= max(1, t.min_hits))
        if not sure and spec.could_trigger(paper_text):
            conditional[spec.name] = _condition(spec)
        return sure or spec.could_trigger(paper_text)
    _recorded.pop(str(folder), None)
    patches = [patch.object(m, "step_plan_json", lambda structure: ROW_PLAN_MARK) for m in plan_modules]
    patches.append(patch.object(optional.StageSpec, "triggered", triggered))
    for p in patches:
        p.start()
    figures = []
    try:
        ex = pipeline.read_paper(item, cfg, on_progress=on_progress)
        try:
            pipeline.extract_steps(ex)
        except RequestsRecorded:
            pass
        for fig in ex.figures:                       # suggestions for digitizing each figure: optional answers
            try:
                pipeline.plan_figure(ex, fig)
            except RequestsRecorded:
                figures.append(fig)
    finally:
        for p in patches:
            p.stop()
    requests = _recorded.pop(str(folder), {})
    about = {f"figure_planner.fig{f.tag}": f for f in figures}
    if "structure_planner" not in requests:
        shutil.rmtree(folder, ignore_errors=True)
        raise PipelineError("The paper couldn't be prepared for another assistant: no requests were made.")
    _write_package(folder, item, config, requests, conditional, work, about)
    shutil.rmtree(work, ignore_errors=True)
    return folder


def _condition(spec) -> str:
    from parameter_extractor.pack_overview import trigger_text
    return (f"Answer this step only if it applies to this paper: {trigger_text(spec)}. Otherwise write "
            f'{{"skipped": true}} as its answer.')


def _write_package(folder: Path, item, config, requests: Dict[str, dict], conditional: Dict[str, str], work: Path,
                   figures: Optional[dict] = None):
    from parameter_extractor import __version__, packs
    from parameter_extractor.pipeline import stage_label, stage_order
    from parameter_extractor.schemas.structure_plan import ID_NOTE
    order = stage_order()
    figures = figures or {}
    stages = sorted(requests, key=lambda s: (s in figures, order.index(requests[s]["stage"])
                                             if requests[s]["stage"] in order else len(order), s))
    (folder / "requests").mkdir(exist_ok=True)
    (folder / "answers").mkdir(exist_ok=True)
    entries, docs = [], {}
    for n, key in enumerate(stages, 1):
        r = requests[key]
        stage = r["stage"]
        fig = figures.get(key)
        name = f"{n:02d}-figure-{fig.tag}" if fig else \
            f"{n:02d}-{NAMES.get(stage, stage.replace('_', '-'))}"
        label = (f"Suggestions for digitizing {fig.figure_id} (page {fig.page_label or fig.page})" if fig else
                 "Plan the rows" if stage == "structure_planner" else stage_label(stage))
        uses_plan = any(ROW_PLAN_MARK in t or ROW_PLAN_ANSWER_MARK in t for t in r["texts"])
        parts = [f"# Request {n:02d}: {label}", "",
                 f"**Write your answer to:** `answers/{name}.json` -- ONE JSON object in the answer format at the end.",
                 ""]
        if stage in conditional:
            parts += [f"**Conditional.** {conditional[stage]}", ""]
        if fig:
            parts += ["**Optional.** Suggestions for digitizing this figure in the app (which columns its axes and "
                      "series go into). Answer it only if the person asked for figure suggestions; otherwise leave it "
                      "unanswered -- the figure is then digitized by hand, or not at all.", ""]
        if any(ROW_PLAN_MARK in t for t in r["texts"]):
            parts += [f"**Uses your row plan.** Where the task says `{ROW_PLAN_MARK}`, use your answer to request 01 "
                      "(see INSTRUCTIONS.md: the sets numbered S1, S2 ..., their samples S1.1, S1.2 ...).", ""]
        if any(ROW_PLAN_ANSWER_MARK in t for t in r["texts"]):
            parts += [f"**Uses your row plan as you wrote it.** Where the task says `{ROW_PLAN_ANSWER_MARK}`, put "
                      "your answer to request 01 exactly as you wrote it.", ""]
        parts += ["## Instructions", "", r["instructions"].strip(), "", "## Inputs", "",
                  "- The paper's text: `paper.txt`" if (folder / "paper.txt").is_file() else "- (no separate text)"]
        parts += [f"- Image: `{img}`" + (f" -- {lab}" if lab else "") for img, lab in r["images"]]
        task = [re.sub(r"Answer by calling the `[\w-]+` tool\.", "Answer with ONE JSON object in the format below.",
                       t.strip()) for t in r["texts"]]
        parts += ["", "## Task", ""] + task + ["", "## Answer format (JSON Schema)", "", "```json",
                                                json.dumps(r["schema"], ensure_ascii=False, separators=(",", ":")),
                                                "```", ""]
        docs[f"requests/{name}.md"] = "\n".join(parts)
        entries.append({"n": n, "stage": stage, "name": key, "label": label, "request": f"requests/{name}.md",
                        "answer": f"answers/{name}.json", "conditional": stage in conditional and not fig,
                        "figure": fig.figure_id if fig else "", "uses_row_plan": uses_plan})
    shared_docs, shared = share_blocks(docs, optional={f"requests/{Path(e['request']).name}" for e in entries
                                                       if e.get("figure")})
    try:                                        # each request reads back exactly, or the package isn't shared
        same = all(expand_shared(shared_docs[p], shared) == text for p, text in docs.items())
    except KeyError:
        same = False
    if same:
        docs = shared_docs
    else:
        shared = {}
    for path, text in {**docs, **shared}.items():
        (folder / path).write_text(text)
    pdf = None
    source = Path(str(item))
    if source.suffix.lower() == ".pdf" and source.is_file():
        shutil.copy2(source, folder / source.name)    # its own name: the import's run folder is named after it
        pdf = source.name
    pack = packs.current()
    manifest = {"format": FORMAT, "app_version": __version__, "created": datetime.now().isoformat(timespec="seconds"),
                "item": str(item), "pdf": pdf, "data_pack": pack.id, "data_pack_label": pack.label,
                "settings": {"rows_from_text": bool(getattr(config, "rows_from_text", False)),
                             "paper_prefix": getattr(config, "paper_prefix", "") or ""},
                "requests": entries, "shared": sorted(shared)}
    (folder / PACKAGE_FILE).write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    (folder / INSTRUCTIONS_FILE).write_text(_instructions(entries, pack, ID_NOTE))


SHARED_FILE, SHARED_OPTIONAL_FILE = "SHARED.md", "SHARED-OPTIONAL.md"
SHARED_HEAD = {SHARED_FILE: "# Shared parts of the requests\n\nRead this file once, before request 01. Where a request "
                            "says [[SHARED §NN]], the section §NN below belongs there.",
               SHARED_OPTIONAL_FILE: "# Shared parts of the optional requests\n\nRead this file once, only if you "
                                     "answer the Optional requests. Where one says [[SHARED §NN]], the section §NN "
                                     "below belongs there."}
SHARED_MIN_CHARS = 300          # shorter repeats aren't worth a pointer
SHARED_MIN_ITEM = 150           # a repeated list item (a rule) worth sharing
SHARED_MARK_OPEN, SHARED_MARK_CLOSE = "[[SHARED ", "]]"


def share_blocks(docs: Dict[str, str], optional=()):
    """(docs, {shared file: text}): text repeated across requests written once -- as numbered sections of SHARED.md,
    read once at the start (one file: an agent pays for every file it opens), or of SHARED-OPTIONAL.md when only
    `optional` requests use it -- and replaced in each request by a one-line pointer. Two passes: a whole paragraph (text between blank lines -- a code block is one) of
    at least SHARED_MIN_CHARS in two or more requests; then, inside the other paragraphs, a run of consecutive list
    items ('- ' lines with their continuations, at least SHARED_MIN_ITEM chars each) that two or more requests share --
    the rules every step repeats. Content-agnostic: whatever a data pack, its steps and modules repeat (answer formats,
    column and compound lists, rules) is found the same way; nothing about a step is assumed."""
    parted = {path: re.split(r"(\n\s*\n)", text) for path, text in docs.items()}   # paragraphs and the gaps between
    split = {path: ps[0::2] for path, ps in parted.items()}
    gaps = {path: ps[1::2] for path, ps in parted.items()}
    order = list(docs)
    blocks: Dict[str, str] = {}                   # repeated text -> shared file (numbered in reading order)

    def users_of(units_by_doc):
        users: Dict[object, List[str]] = {}
        for path, units in units_by_doc.items():
            for u in dict.fromkeys(units):
                users.setdefault(u, []).append(path)
        return users
    # 1. whole paragraphs
    paras = users_of({p: [x for x in ps if len(x.strip()) >= SHARED_MIN_CHARS] for p, ps in split.items()})
    whole = {x for x, us in paras.items() if len(us) > 1}
    # 2. runs of list items inside the rest: a run = consecutive items present in the same requests
    items = {path: [re.split(r"\n(?=- )", x) for x in ps if x not in whole] for path, ps in split.items()}
    item_users = users_of({p: [i for para in ps for i in para if len(i) >= SHARED_MIN_ITEM] for p, ps in items.items()})

    def runs(para_items):
        out, run, key = [], [], None
        for it in para_items:
            k = tuple(item_users.get(it, ())) if len(item_users.get(it, ())) > 1 else None
            if k != key and run:
                out.append((key, run))
                run = []
            key = k
            run.append(it)
        if run:
            out.append((key, run))
        return out
    run_users = users_of({p: ["\n".join(r) for ps in pp for k, r in runs(ps) if k] for p, pp in items.items()})
    shared_runs = {x for x, us in run_users.items() if len(us) > 1}
    found = sorted(whole | shared_runs, key=lambda x: min(order.index(u) for u in (paras.get(x) or run_users[x])))
    sections: Dict[str, List[str]] = {SHARED_FILE: [], SHARED_OPTIONAL_FILE: []}
    for i, x in enumerate(found, 1):
        blocks[x] = f"§{i:02d}"
        users = paras.get(x) if x in whole else run_users[x]
        file = SHARED_OPTIONAL_FILE if all(u in optional for u in users) else SHARED_FILE
        sections[file].append(f"## §{i:02d} (in requests {', '.join(Path(u).stem[:2] for u in users)})\n\n{x}\n")
    shared = {file: (SHARED_HEAD[file] + "\n\n" + "\n".join(parts)) for file, parts in sections.items() if parts}
    pointer = lambda x: f"{SHARED_MARK_OPEN}{blocks[x]}{SHARED_MARK_CLOSE}"
    out = {}
    for path, ps in split.items():
        new = []
        for para in ps:
            if para in whole:
                new.append(pointer(para))
                continue
            chunks = []
            for key, run in runs(re.split(r"\n(?=- )", para)):
                text = "\n".join(run)
                chunks.append(f"- {pointer(text)}" if key and text in blocks else text)
            new.append("\n".join(chunks))
        out[path] = "".join(part for pair in zip(new, gaps[path] + [""]) for part in pair)
    return out, shared


def expand_shared(text: str, shared: Dict[str, str]) -> str:
    """A request with its [[SHARED §NN]] pointers replaced by the sections' text (`shared`: {file: its text}) -- the
    request as it was before sharing (tests; anyone reading a request on its own)."""
    sections = {}
    for body in shared.values():
        for m in re.finditer(r"^## (§\d+) \(in requests [^)]*\)\n\n(.*?)\n(?=\n## §|\Z)", body, re.S | re.M):
            sections[m.group(1)] = m.group(2)
    pattern = re.escape(SHARED_MARK_OPEN) + r"(§\d+)" + re.escape(SHARED_MARK_CLOSE)
    text = re.sub(r"^- " + pattern + "$", lambda m: sections[m.group(1)], text, flags=re.M)
    return re.sub(pattern, lambda m: sections[m.group(1)], text)


def _instructions(entries: List[dict], pack, id_note: str) -> str:
    units = pack.manifest.units or {}
    lines = [
        f"# Requests to answer: {pack.label}", "",
        "This folder holds the requests a research tool (Parameter Extractor) needs answered to turn one scientific "
        "paper into rows of a dataset. Work through them yourself -- you are the assistant answering them. Nothing "
        "here needs a network connection or another program.", "",
        "## Work economically", "",
        "These requests are long; the person's usage allowance pays for every time a file is read again.", "",
        "- Read `paper.txt` once, and each image once, the first time a request lists it. Note what you need from it "
        "(a table's values, a figure's axes) instead of opening it again.",
        f"- Read each request once, in full, then write its answer in one go. `{SHARED_FILE}` is read once at the "
        "start; a pointer to a section means its text -- don't open the file again for it.",
        "- Don't re-read a request or its answer format to check an answer you've written: the app checks every answer "
        "when it imports the folder and says exactly what to fix.",
        "- Don't print or list whole files when a part is enough, and skip the Optional requests unless the person "
        "asked for them.",
        "- Answer every request of this paper in one session, in order: the later ones build on your earlier answers.",
        "",
        "## What to do", "",
        "1. Read the paper: `paper.txt` (its text as the tool read it; the PDF beside it is the original) "
        "and any image a request lists (paths are relative to this folder).",
        f"   Then read `{SHARED_FILE}` once: the long parts several requests share (answer formats, rules, lists of "
        f"columns or compounds), kept there once. Where a request says `{SHARED_MARK_OPEN}§NN{SHARED_MARK_CLOSE}`, that "
        f"section belongs there. (`{SHARED_OPTIONAL_FILE}` does the same for the Optional requests.)",
        "2. Answer the requests in `requests/` **in their numbered order**, one at a time. Each says where its answer "
        "goes and gives its answer format (a JSON Schema). Write each answer as ONE JSON object to that file in "
        "`answers/`, using the schema's own short field names (`v`, `q`, `src`, ...). Report only what the paper "
        "states, as each request's instructions say.",
        "3. Request 01 plans the dataset's rows. The later requests build on it: where a task says "
        f"`{ROW_PLAN_MARK}`, use your answer to request 01 in this form -- the sets in the order of your answer, "
        "numbered S1, S2, ..., and each set's samples numbered S1.1, S1.2, ...:", "",
        "   ```json",
        '   {"sets": [{"id": "S1", "set": "<set label>", "type": "<type>", "varies": "<varies>", "src": "<src>",',
        '              "samples": [{"id": "S1.1", "label": "<sample label>", "hr": <hours, if given>}]}]}',
        "   ```", "",
        f"   {id_note}", "",
        "4. A request marked **Conditional** applies only to some papers: answer it if its condition fits this paper "
        '(your row plan), else write `{"skipped": true}` as its answer. Requests marked **Optional** (suggestions '
        "for digitizing a figure) come last: answer them only if the person asked for figure suggestions; the "
        "app's import doesn't need them.",
        f"5. Last, write `answers/{ABOUT_FILE}` saying who answered:", "",
        "   ```json",
        '   {"model": "<the model\'s name and version>", "provider": "<who provides it>", '
        '"assistant": "<the app or agent you ran in>", "date": "<today>", "notes": "<anything worth knowing>"}',
        "   ```", "",
        "Then import the folder in Parameter Extractor (File > Import answers from another assistant…). It checks "
        "every answer against its format; an answer that doesn't fit gets an `answers/<name>.error.txt` saying why -- "
        "fix it and import again.", "",
        "## The requests", ""]
    for e in entries:
        notes = [x for x, on in (("conditional", e["conditional"]), ("optional", bool(e.get("figure"))),
                                 ("uses your row plan", e["uses_row_plan"])) if on]
        lines.append(f"- `{e['request']}` -> `{e['answer']}`: {e['label']}" + (f" ({', '.join(notes)})" if notes else ""))
    lines += ["", f"In this research area one row of the dataset is one {units.get('sample', 'sample')}, and a set "
                  f"is one {units.get('set', 'set')}.", "",
              "## For the person using this package", "",
              *[f"- {c}" for c in CAVEATS], ""]
    return "\n".join(lines)


# what the person is told with every package (the app's export message, INSTRUCTIONS.md)
CAVEATS = [
    "Best with an assistant that can read and write the files in this folder and look at images (an agent "
    "with file access). A chat-only assistant may struggle with requests this long and exact.",
    "The app hasn't been tried with your model or assistant and can't vouch for its answers: on import it checks only "
    "that each answer fits its format. Review the results against the paper -- you can ask your assistant to check "
    "them too.",
    "Each step is answered once (the app's own runs can read a step several times and vote).",
    "Good for trying a few papers or tuning a data pack without a full-cost run.",
    "Using your assistant is under its provider's terms; the paper's text and images go to that provider when you "
    "share this folder with it.",
]


# ---- import --------------------------------------------------------------------------------------------------------

def read_package(folder) -> dict:
    folder = Path(folder)
    path = folder / PACKAGE_FILE
    if not path.is_file():
        raise PipelineError(f"{folder} isn't a package of requests for another assistant (no {PACKAGE_FILE}).")
    manifest = json.loads(path.read_text())
    if manifest.get("format", 0) > FORMAT:
        raise PipelineError("This package was made by a newer version of the app: update the app to import it.")
    return manifest


def import_config(folder, config):
    """`config` set to answer from the package: its data pack and settings, no requests sent."""
    from dataclasses import replace
    manifest = read_package(folder)
    settings = manifest.get("settings", {})
    return replace(config, exchange_dir=Path(folder), exchange_mode="import", pack=manifest["data_pack"], passes=1,
                   batch_mode=False, prompt_caching=False, shared_instructions=False, equations_to_latex=False,
                          handoff_dir=None, rows_from_text=settings.get("rows_from_text", False),
                   paper_prefix=settings.get("paper_prefix", "") or getattr(config, "paper_prefix", ""))


def paper_item(folder) -> str:
    """What to read for the import: the package's copy of the PDF, else what the export read (an arXiv id ...)."""
    manifest = read_package(folder)
    return str(Path(folder) / manifest["pdf"]) if manifest.get("pdf") else manifest["item"]


def missing_answers(folder) -> List[str]:
    """The answers a package still lacks that every paper needs (conditional steps are checked during the import,
    against the row plan's sets)."""
    folder = Path(folder)
    return [Path(r["answer"]).stem for r in read_package(folder)["requests"]
            if not r.get("conditional") and not r.get("figure") and not (folder / r["answer"]).is_file()]


def import_package(folder, config, on_progress=None, cancel_event=None):
    """Run the package's paper with its answers (pipeline.run_pipeline); AnswersMissingError lists what's missing."""
    from parameter_extractor import pipeline
    missing = missing_answers(folder)
    if missing:                                     # all of them at once, before the paper is read
        raise AnswersMissingError(Path(folder), missing)
    return pipeline.run_pipeline(paper_item(folder), import_config(folder, config), on_progress=on_progress,
                                 cancel_event=cancel_event)
