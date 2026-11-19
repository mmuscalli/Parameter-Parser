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
    cfg = ctx.config
    folder = Path(cfg.exchange_dir)
    if cfg.exchange_mode == "export":
        return _record(ctx, folder, stage, system_prompt, content, response_model)
    return _answer_from_package(folder, stage, response_model)


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


def _record(ctx, folder: Path, stage: str, system_prompt: str, content, response_model):
    folder.mkdir(parents=True, exist_ok=True)
    texts, images = _texts_and_images(folder, content)
    paper = getattr(getattr(ctx, "paper", None), "text", "") or ""
    if paper and any(paper in t for t in texts):        # the paper once, in paper.txt -- not in every request
        with _lock:
            (folder / "paper.txt").write_text(paper)
        texts = [t.replace(paper, PAPER_MARK) for t in texts]
    request = {"stage": stage, "instructions": system_prompt, "texts": texts, "images": images,
               "schema": response_model.model_json_schema(by_alias=True)}
    with _lock:
        _recorded.setdefault(str(folder), {})[stage] = request
    if stage == "structure_planner":                 # a stand-in plan: the steps that need one are made too
        from parameter_extractor.schemas.structure_plan import StructurePlan
        plan = StructurePlan.model_validate({"kind": "experimental", "n_rows": 1, "excluded": [], "notes": "",
                                             "sets": [{"set": "(a set)", "type": "Independent", "varies": "",
                                                       "src": "", "samples": [{"label": "(a sample)"}]}]})
        return SimpleNamespace(id="export-plan", stop_reason="end_turn", parsed_output=plan,
                               content=[SimpleNamespace(type="text", text=plan.model_dump_json(by_alias=True))],
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    raise RequestsRecorded(folder, [stage])


def _answer_from_package(folder: Path, stage: str, response_model):
    manifest = json.loads((folder / PACKAGE_FILE).read_text())
    entry = next((r for r in manifest["requests"] if r["stage"] == stage), None)
    if entry is None and stage == "figure_planner":
        raise PipelineError("Figure suggestions aren't part of a package for another assistant: digitize the figure "
                            "by hand (its axes and series), or skip it.")
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
    try:
        pipeline.run_pipeline(item, cfg, on_progress=on_progress)
    except RequestsRecorded:
        pass
    finally:
        for p in patches:
            p.stop()
    requests = _recorded.pop(str(folder), {})
    if "structure_planner" not in requests:
        shutil.rmtree(folder, ignore_errors=True)
        raise PipelineError("The paper couldn't be prepared for another assistant: no requests were made.")
    _write_package(folder, item, config, requests, conditional, work)
    shutil.rmtree(work, ignore_errors=True)
    return folder


def _condition(spec) -> str:
    from parameter_extractor.pack_overview import trigger_text
    return (f"Answer this step only if it applies to this paper: {trigger_text(spec)}. Otherwise write "
            f'{{"skipped": true}} as its answer.')


def _write_package(folder: Path, item, config, requests: Dict[str, dict], conditional: Dict[str, str], work: Path):
    from parameter_extractor import __version__, packs
    from parameter_extractor.pipeline import stage_label, stage_order
    from parameter_extractor.schemas.structure_plan import ID_NOTE
    order = stage_order()
    stages = sorted(requests, key=lambda s: order.index(s) if s in order else len(order))
    (folder / "requests").mkdir(exist_ok=True)
    (folder / "answers").mkdir(exist_ok=True)
    entries = []
    for n, stage in enumerate(stages, 1):
        r = requests[stage]
        name = f"{n:02d}-{NAMES.get(stage, stage.replace('_', '-'))}"
        label = "Plan the rows" if stage == "structure_planner" else stage_label(stage)
        uses_plan = any(ROW_PLAN_MARK in t for t in r["texts"])
        parts = [f"# Request {n:02d}: {label}", "",
                 f"**Write your answer to:** `answers/{name}.json` -- ONE JSON object in the answer format at the end.",
                 ""]
        if stage in conditional:
            parts += [f"**Conditional.** {conditional[stage]}", ""]
        if uses_plan:
            parts += [f"**Uses your row plan.** Where the task says `{ROW_PLAN_MARK}`, use your answer to request 01 "
                      "(see INSTRUCTIONS.md: the sets numbered S1, S2 ..., their samples S1.1, S1.2 ...).", ""]
        parts += ["## Instructions", "", r["instructions"].strip(), "", "## Inputs", "",
                  "- The paper's text: `paper.txt`" if (folder / "paper.txt").is_file() else "- (no separate text)"]
        parts += [f"- Image: `{img}`" + (f" -- {lab}" if lab else "") for img, lab in r["images"]]
        task = [re.sub(r"Answer by calling the `[\w-]+` tool\.", "Answer with ONE JSON object in the format below.",
                       t.strip()) for t in r["texts"]]
        parts += ["", "## Task", ""] + task + ["", "## Answer format (JSON Schema)", "", "```json",
                                                json.dumps(r["schema"], indent=1, ensure_ascii=False), "```", ""]
        (folder / "requests" / f"{name}.md").write_text("\n".join(parts))
        entries.append({"n": n, "stage": stage, "label": label, "request": f"requests/{name}.md",
                        "answer": f"answers/{name}.json", "conditional": stage in conditional,
                        "uses_row_plan": uses_plan})
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
                "requests": entries}
    (folder / PACKAGE_FILE).write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    (folder / INSTRUCTIONS_FILE).write_text(_instructions(entries, pack, ID_NOTE))


def _instructions(entries: List[dict], pack, id_note: str) -> str:
    units = pack.manifest.units or {}
    lines = [
        f"# Requests to answer: {pack.label}", "",
        "This folder holds the requests a research tool (Parameter Extractor) needs answered to turn one scientific "
        "paper into rows of a dataset. Work through them yourself -- you are the assistant answering them. Nothing "
        "here needs a network connection or another program.", "",
        "## What to do", "",
        "1. Read the paper: `paper.txt` (its text as the tool read it; the PDF beside it is the original) "
        "and any image a request lists (paths are relative to this folder).",
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
        '(your row plan), else write `{"skipped": true}` as its answer.',
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
        notes = [x for x, on in (("conditional", e["conditional"]), ("uses your row plan", e["uses_row_plan"])) if on]
        lines.append(f"- `{e['request']}` -> `{e['answer']}`: {e['label']}" + (f" ({', '.join(notes)})" if notes else ""))
    lines += ["", f"In this research area one row of the dataset is one {units.get('sample', 'sample')}, and a set "
                  f"is one {units.get('set', 'set')}.", ""]
    return "\n".join(lines)


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
                   auto_digitize_figures=False,
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
            if not r.get("conditional") and not (folder / r["answer"]).is_file()]


def import_package(folder, config, on_progress=None, cancel_event=None):
    """Run the package's paper with its answers (pipeline.run_pipeline); AnswersMissingError lists what's missing."""
    from parameter_extractor import pipeline
    missing = missing_answers(folder)
    if missing:                                     # all of them at once, before the paper is read
        raise AnswersMissingError(Path(folder), missing)
    return pipeline.run_pipeline(paper_item(folder), import_config(folder, config), on_progress=on_progress,
                                 cancel_event=cancel_event)
