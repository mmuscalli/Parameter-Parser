"""
Resume and rebuild (W1, 2026-11-11): a run that reuses the answers saved in an earlier run's folder.

- **Resume**: a run that stopped part-way (network, out of credits, Cancel, a crash) is run again; each step whose
  request is the same as before is answered from the old folder (no tokens, no cost) and only the others are asked.
- **Rebuild**: the dataset is built again from the old folder's answers with NO request at all -- after something
  local changed (accepted variables, a data pack's formulas or calculations, compound names). A step whose request
  differs from the saved one (the data pack's prompts changed) still uses the saved answer and is flagged; a step
  with no saved answer stops the rebuild (Resume asks the model for it).

Both write a NEW run folder (Mickey: never write into the old one); its run_summary.json names the old folder
(`resumed_from`, `rebuilt`), and the reused answers are copied into it with `reused_from` in their audits. The old
run's settings (data pack, models, passes, options; run_config.json, else its run_summary.json) are used, so the
requests match; the key, output folder and registry are the current ones. Digitized figures and review decisions
saved in the old folder are used again: the figures aren't offered for digitizing, and a variable decided in the old
review isn't asked about again.

How a saved answer is matched to a request: `api_client.request_fingerprint` is stored in every audit since
2026-11-11. Older audits have none; they match when the model, the step's input (paper text, plan) and any cached
prefix are the same and, where the audit kept them, the step's instructions.
"""
from __future__ import annotations

import json
import threading
from dataclasses import fields, replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from parameter_extractor import errors
from parameter_extractor.config.run_config import RunConfig

CONFIG_FILE = "run_config.json"              # written when a run starts (pipeline.read_paper): settings + the paper
# settings that stay the current session's own, not the old run's
_NOT_COPIED = {"api_key", "output_dir", "registry_path", "pubchem_cache_path", "arxiv_cache_dir", "handoff_dir",
               "ads_token", "resume_from", "rebuild"}
_lock = threading.Lock()


# ---- matching saved answers (called by api_client.call_structured) --------------------------------------------

def _legacy_match(audit: dict, model: str, system_prompt, user_content: str, cached_prefix) -> bool:
    """An audit written before request fingerprints: the same model, step input and cached prefix, and the same
    instructions where the audit kept them (with caching on, it names the cached system prompt instead)."""
    if audit.get("model") != model or audit.get("user_content") != user_content:
        return False
    if (audit.get("cached_prefix") or "") != (cached_prefix or ""):
        return False
    saved = audit.get("system_prompt")
    from parameter_extractor.api_client import SHARED_SYSTEM
    if isinstance(saved, str) and isinstance(system_prompt, str) and not saved.startswith(SHARED_SYSTEM):
        return saved == system_prompt
    return True


def saved_answer(ctx, stage: str, name: str, model: str, fingerprint: str, system_prompt, user_content: str,
                 cached_prefix, response_model):
    """The validated answer saved for this request in the old folder (config.resume_from), copied into the new run
    folder and recorded as reused; None when the model has to be asked. A rebuild never returns None: it raises
    when there is no saved answer."""
    from parameter_extractor.run_context import StageUsage
    config = ctx.config
    old = Path(config.resume_from)
    audit_path, output_path = old / f"{name}.audit.json", old / f"{name}.output.json"
    audit = None
    if audit_path.is_file() and output_path.is_file():
        try:
            audit = json.loads(audit_path.read_text())
        except (OSError, ValueError):
            audit = None
    if audit is not None and "voted_from" in audit:          # a vote's result, not one request's answer
        audit = None
    if audit is None:
        if config.rebuild:
            raise errors.PipelineError(
                f"Rebuilding needs the '{stage}' step's saved answer ({name}.output.json), which the folder "
                f"{old.name} doesn't have: that run stopped before it, or this data pack now runs a step the old run "
                f"didn't. Use Resume instead: it asks the model only for the missing steps.")
        _note(ctx, stage, f"{stage}: no saved answer in the earlier run -- asking the model")
        return None
    same = (audit.get("request_fingerprint") == fingerprint if audit.get("request_fingerprint")
            else _legacy_match(audit, model, system_prompt, user_content, cached_prefix))
    if not same and not config.rebuild:
        _note(ctx, stage, f"{stage}: the request changed since the earlier run (data pack, prompts or model) -- "
                          f"asking the model again")
        return None
    try:
        parsed = response_model.model_validate_json(output_path.read_text())
    except ValueError as e:
        if config.rebuild:
            raise errors.PipelineError(f"The '{stage}' step's saved answer in {old.name} can't be read by this "
                                       f"version of the app ({e.errors()[0].get('msg', e) if hasattr(e, 'errors') else e}"
                                       f"). Use Resume to ask the model for it again.") from None
        _note(ctx, stage, f"{stage}: the saved answer can't be read by this version -- asking the model again")
        return None
    if not same:
        with _lock:
            ctx.reused_changed = getattr(ctx, "reused_changed", []) + [stage]
    run_dir = Path(ctx.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    audit = dict(audit, reused_from=str(old), request_fingerprint_now=fingerprint, request_changed=not same)
    (run_dir / f"{name}.audit.json").write_text(json.dumps(audit, indent=2))
    (run_dir / f"{name}.output.json").write_text(output_path.read_text())
    ctx.record_usage(StageUsage(stage=stage, model=audit.get("model", model), input_tokens=0, output_tokens=0,
                                elapsed_sec=0.0, cost_usd=0.0, reused=True))
    _note(ctx, stage, f"{stage}: answer reused from the earlier run" + ("" if same else " (its request has changed)"))
    return parsed


def _note(ctx, stage: str, message: str) -> None:
    if hasattr(ctx, "note"):
        ctx.note(stage, message)


# ---- what the old run read, and how ----------------------------------------------------------------------------

def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def original_item(old: Path) -> str:
    """The paper the old run read: as given to it (run_config.json), else the PDF path / arXiv ID it recorded."""
    old = Path(old)
    item = _read(old / CONFIG_FILE).get("item")
    if item:
        return item
    summary, source = _read(old / "run_summary.json"), _read(old / "source.json")
    pdf = source.get("pdf") or ""
    if pdf and Path(pdf).is_file() and old not in Path(pdf).parents:      # a local PDF (not one downloaded there)
        return pdf
    arxiv = (source.get("arxiv") or {}).get("id") or (source.get("arxiv") or {}).get("arxiv_id")
    if arxiv:
        return arxiv
    if summary.get("source_pdf"):
        return summary["source_pdf"]
    raise errors.PipelineError(f"{old.name} doesn't say which paper it read (no {CONFIG_FILE}, run_summary.json or "
                               f"source.json): it can't be resumed or rebuilt.")


def saved_settings(old: Path) -> dict:
    """The old run's settings (without the key): run_config.json, else run_summary.json's copy; {} if neither."""
    return _read(Path(old) / CONFIG_FILE).get("config") or _read(Path(old) / "run_summary.json").get("config") or {}


def config_for(old: Path, base: RunConfig, rebuild: bool = False) -> RunConfig:
    """`base` (the current session's key, folders, registry) with the old run's settings, set to reuse its answers."""
    saved = saved_settings(old)
    known = {f.name for f in fields(RunConfig)} - _NOT_COPIED
    changes = {k: v for k, v in saved.items() if k in known and v is not None}
    if isinstance(changes.get("local"), dict):         # the local server's key is never saved: the current one
        changes["local"] = dict(changes["local"], api_key=(base.local or {}).get("api_key", ""))
    try:
        config = replace(base, **changes)
    except TypeError:                                  # a setting of another version: only what still fits
        config = base
    config.resume_from = Path(old)
    config.rebuild = rebuild
    if rebuild:
        config.batch_mode = False                      # nothing is sent: no batches to wait for
    return config


# ---- figures and review decisions -------------------------------------------------------------------------------

def saved_figures(old: Path, run_dir: Path, figure_ids: Sequence[str]) -> Tuple[list, List[str]]:
    """(digitized figures saved in the old folder, ids of the paper's other figures -- skipped)."""
    from parameter_extractor.schemas.figures import DigitizedFigure
    digitized = []
    for path in sorted((Path(old) / "figures").glob("fig-*.digitized.json")):
        try:
            fig = DigitizedFigure.model_validate_json(path.read_text())
        except ValueError:
            continue
        here = Path(run_dir) / "figures" / Path(fig.page_image).name       # rendered again by the new run
        if here.is_file():
            fig.page_image = str(here)
        elif not Path(fig.page_image).is_file():
            continue
        digitized.append(fig)
    done = {f.figure_id for f in digitized}
    return digitized, [f for f in figure_ids if f not in done]


def saved_decisions(old: Path) -> list:
    """The review decisions of the old run (new_variables.json)."""
    from parameter_extractor.ingestion.new_variables import VariableDecision
    out = []
    for d in _read(Path(old) / "new_variables.json").get("decisions", []):
        try:
            out.append(VariableDecision(**{k: v for k, v in d.items()
                                           if k in VariableDecision.__dataclass_fields__}))
        except TypeError:
            continue
    return out


def review_with_saved(old: Path, ask: Optional[Callable] = None) -> Callable:
    """A review callback: groups the old review decided are decided the same way again; the rest go to `ask` (the
    window's review), or aren't added when there is none (the command line)."""
    saved = {(d.kind, d.alias_name): d for d in saved_decisions(old)}

    def review(groups, unfound, registry):
        decided = [saved[(g.kind, g.alias_name)] for g in groups if (g.kind, g.alias_name) in saved]
        rest = [g for g in groups if (g.kind, g.alias_name) not in saved]
        if ask and (rest or (unfound and not decided)):
            return decided + list(ask(rest, unfound, registry) or [])
        return decided
    return review


# ---- the runs ------------------------------------------------------------------------------------------------------

def extract_again(old: Path, config: RunConfig, on_progress=None, cancel_event=None):
    """The extraction steps of a resumed / rebuilt run (`config` from config_for): the paper read again, each step
    answered from the old folder where it can be. Returns (Extraction, digitized, skipped figure ids)."""
    from parameter_extractor.pipeline import extract_steps, read_paper
    old = Path(old)
    if not old.is_dir():
        raise errors.PipelineError(f"{old} doesn't exist.")
    item = original_item(old)
    ex = read_paper(item, config, on_progress, cancel_event)
    digitized, skipped = saved_figures(old, ex.ctx.run_dir, [f.figure_id for f in ex.figures])
    ex.no_figure_rows = not digitized
    return extract_steps(ex), digitized, skipped


def resume_run(old: Path, base: RunConfig, rebuild: bool = False, on_progress=None, cancel_event=None,
               review=None):
    """Resume (or rebuild) the run in `old` into a new folder; `review` = the window's review for variables the old
    run didn't decide (None: not added). Returns the RunResult."""
    from parameter_extractor.pipeline import finish
    config = config_for(old, base, rebuild)
    ex, digitized, skipped = extract_again(old, config, on_progress, cancel_event)
    return finish(ex, digitized, skipped, review=review_with_saved(old, review))


# ---- queues --------------------------------------------------------------------------------------------------------

def _paper_folders(queue: Path) -> dict:
    """prefix -> the latest run folder in an old queue's folder for that paper (its run_config.json, else its
    run_summary.json, names the paper_prefix)."""
    found = {}
    for d in sorted(p for p in Path(queue).iterdir() if p.is_dir()):
        settings = saved_settings(d)
        prefix = settings.get("paper_prefix")
        if prefix:
            found[prefix] = d                       # sorted by name (= start time): the last one wins
    return found


def queue_papers(queue: Path) -> List[dict]:
    """An earlier queue's papers in order: [{prefix, item, label, run_dir}] (run_dir None for a paper that never
    started). From queue.json (written when a queue starts, since 2026-11-11), else papers.csv (written when it
    ends), else the paper folders inside it."""
    import csv
    queue = Path(queue)
    folders = _paper_folders(queue) if queue.is_dir() else {}
    listed = _read(queue / "queue.json").get("papers")
    if not listed and (queue / "papers.csv").is_file():
        with open(queue / "papers.csv", newline="", encoding="utf-8") as f:
            listed = [{"prefix": r["prefix"], "item": r["item"], "label": r.get("label", "")} for r in csv.DictReader(f)]
    if not listed:
        listed = []
        for prefix, d in sorted(folders.items()):
            try:
                listed.append({"prefix": prefix, "item": original_item(d), "label": ""})
            except errors.PipelineError:
                continue
    if not listed:
        raise errors.PipelineError(f"{queue} isn't a paper queue's folder (no queue.json, papers.csv or paper "
                                   f"folders in it).")
    return [dict(p, run_dir=folders.get(p["prefix"])) for p in listed]


def is_queue_folder(folder: Path) -> bool:
    folder = Path(folder)
    return (folder / "queue.json").is_file() or (folder / "papers.csv").is_file() or \
        (folder.name.startswith("queue_") and folder.is_dir())
