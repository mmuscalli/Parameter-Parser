"""
Answering for every parameter (Mickey, 2026-11-24): for controlled tests, the model says for each parameter it is
asked for whether the paper reports it -- found or not -- instead of leaving out what it didn't find.

- In an answer format: `checked`, an object with one REQUIRED entry per parameter (keyed by the column; other
  characters as '_'), each `s` reported / not reported / unclear and `n` a few words. A focused search has it with
  `check_every` (focused_search.py); a full run with RunConfig.check_every_parameter (every configurable step's
  parameters) and the data pack's check_columns (its Columns tab: step parameters and compound columns, the
  chemistry step answering per compound column) plus RunConfig.check_columns.
- After a run: what the model said, against the values it gave -- 'marked reported, but no value given' and
  'values given, but marked not reported' are problems (shown, nothing changed): parameter_checks.csv in the run's
  folder, a flag for each problem.

Off (the default), nothing here is used and every request is as before.
"""
from __future__ import annotations

import csv
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pydantic import ConfigDict, Field, create_model

STATUSES = ("reported", "not reported", "unclear")
CHECKS_FILE = "parameter_checks.csv"
MARKINGS_FILE = "must_answer.json"      # <app data>: {data pack id: [columns]} (2026-11-25, Mickey)
_lock = threading.Lock()


# ---- the 'Must answer' columns ---------------------------------------------------------------------------------------
# Kept in the user's app data, by data pack, not in the pack (Mickey, 2026-11-25: the app's own packs can be marked for
# tests without copying them). A pack's own check_columns (0.6.6 kept them in pack.json) still count; the editor moves
# them here.

def markings_path() -> Path:
    from parameter_extractor.registry import default_registry_path
    return default_registry_path().parent / MARKINGS_FILE


def _load_markings() -> Dict[str, List[str]]:
    import json
    path = markings_path()
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        return {}
    return {k: [c for c in v if isinstance(c, str)] for k, v in data.items() if isinstance(v, list)}


def marked(pack) -> List[str]:
    """The pack's 'Must answer' columns: the user's (app data), and any the pack's own file lists."""
    own = list(getattr(pack.manifest, "check_columns", []) or []) if pack is not None else []
    users = _load_markings().get(pack.id, []) if pack is not None else []
    return list(dict.fromkeys(users + own))


def set_marked(pack_id: str, columns) -> None:
    """The user's 'Must answer' columns for a pack (an empty list removes the pack's entry)."""
    import json
    with _lock:
        data = _load_markings()
        if columns:
            data[pack_id] = sorted(set(columns))
        else:
            data.pop(pack_id, None)
        path = markings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def check_keys(columns: Sequence[str]) -> Dict[str, str]:
    """{column: its key in `checked`} -- the column itself where it is a plain name, else with other characters as
    '_' (and a number when two would clash)."""
    out, used = {}, set()
    for c in columns:
        key = re.sub(r"[^A-Za-z0-9_-]", "_", c)[:60] or "p"
        base, n = key, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        used.add(key)
        out[c] = key
    return out


def checks_model(name: str, columns: Sequence[str]):
    """The `checked` object for these columns: one required entry each."""
    from typing import Literal
    Check = create_model(
        f"{name}Check", __config__=ConfigDict(json_schema_extra={"required": ["s", "n"]}),
        s=(Literal[STATUSES], Field(description="reported: the paper gives a value (in the answer's values); not "
                                                "reported; unclear: something might be it")),
        n=(str, Field(description="A few words: where it is, or what you checked")))
    keys = check_keys(columns)
    return create_model(
        f"{name}Checks", __config__=ConfigDict(populate_by_name=True,
                                               json_schema_extra={"required": list(keys.values())}),
        **{f"k{i}": (Check, Field(alias=keys[c], description=f"`{c}`")) for i, c in enumerate(columns)})


def with_checks(Base, columns: Sequence[str]):
    """`Base` (an answer format) with a required `checked` entry per column."""
    Checks = checks_model(Base.__name__, columns)
    original = Base.model_config.get("json_schema_extra")

    def extra(schema: dict) -> None:
        if callable(original):
            original(schema)
        elif isinstance(original, dict):
            schema.update(original)
        required = schema.setdefault("required", [])
        if "checked" not in required:
            required.append("checked")
    namespace = {"__annotations__": {"checked": Checks},
                 "checked": Field(description="One entry per parameter listed: does the paper report it?"),
                 "model_config": ConfigDict(**{**Base.model_config, "json_schema_extra": extra}),
                 "__module__": Base.__module__}
    return type(Base.__name__, (Base,), namespace)


def rule(columns: Sequence[str], what: str = "parameter", where: str = "the values") -> str:
    """The instruction that goes with `checked`."""
    keys = check_keys(columns)
    renamed = [f"`{c}` is `{k}`" for c, k in keys.items() if k != c]
    return (f"EVERY {what.upper()} CHECKED: `checked` has one entry for each of these {what}s, keyed by its name: "
            + ", ".join(f"`{c}`" for c in columns)
            + (f" ({', '.join(renamed)})" if renamed else "") + f". Look for EACH of them specifically, in the "
            f"text and the tables, and answer for every one: `s` 'reported' when the paper gives a value for it "
            f"(its values go in {where} as usual), 'not reported' when it doesn't, 'unclear' when something might "
            f"be it but you aren't sure; `n` a few words: where it is, or what you checked.")


def answers(result, columns: Sequence[str]) -> Dict[str, dict]:
    """{column: {"status", "note"}} from an answer's `checked` ({} when it has none)."""
    checked = getattr(result, "checked", None)
    if checked is None:
        return {}
    raw = checked.model_dump(by_alias=True)
    keys = check_keys(columns)
    return {c: {"status": (raw.get(keys[c]) or {}).get("s", "") or "no answer",
                "note": (raw.get(keys[c]) or {}).get("n", "")} for c in columns}


def record(ctx, step: str, result, columns: Sequence[str]) -> None:
    """Keep a step's answers on the run (the first pass's when there are several: voting keeps only the values)."""
    found = answers(result, columns)
    if not found:
        return
    with _lock:
        store = getattr(ctx, "parameter_checks", None)
        if store is None:
            store = {}
            ctx.parameter_checks = store
        store.setdefault(step, found)


# ---- the built-in steps' columns (2026-11-25, Mickey: every column that comes from a step can be marked) -------------

PAPER_DETAILS = {"paper_title": "paper_title", "author_list": "authors", "year_published": "year_published",
                 "journal_published": "journal_published", "paper_DOI": "paper_doi"}     # column -> PaperMetadata field


def asked_columns(config, step_columns, everything: bool = True) -> tuple:
    """The step's columns this run answers for: the data pack's 'Must answer' columns and the run's own
    (RunConfig.check_columns) among them; with check_every_parameter (`everything`), all of them."""
    from parameter_extractor import packs
    if everything and getattr(config, "check_every_parameter", False):
        return tuple(step_columns)
    wanted = set(marked(packs.current())) | set(getattr(config, "check_columns", []) or [])
    return tuple(c for c in step_columns if c in wanted)


def planner_columns(pack) -> List[str]:
    """The columns the row plan fills that a run can answer for: each sample's time (sample_time's column) and each
    set's type."""
    time = pack.row_value_column("duration_hr")
    return ([time] if time else []) + ["set_type"]


def planner_rule(columns: Sequence[str], pack) -> str:
    time = pack.row_value_column("duration_hr")
    what = {time: "each sample's time point `hr`", "set_type": "each set's `set_type`"}
    return ("Columns this run answers for in `checked`: " + "; ".join(f"`{c}` ({what.get(c, c)})" for c in columns)
            + ". " + rule(columns, "column", "the plan"))


def problem(status: str, n: int) -> str:
    if status == "reported" and n == 0:
        return "marked reported, but no value given"
    if status == "not reported" and n:
        return f"{n} value(s) given, but marked not reported"
    return ""


def finish(ctx, ex, run_dir: Path) -> list:
    """After a full run: parameter_checks.csv (step, parameter, what the model said, how many values it gave, the
    problem) and one flag per step listing its problems. [] when the run asked for no checks."""
    from parameter_extractor.validation.plausibility_checks import Flag
    store = getattr(ctx, "parameter_checks", None) or {}
    if not store:
        return []
    counts: Dict[str, Dict[str, int]] = {}
    for name, (spec, result) in (getattr(ex, "optional", None) or {}).items():
        c = counts.setdefault(name, {})
        for item in (getattr(result, "parameters", None) or []):
            c[item.parameter] = c.get(item.parameter, 0) + 1
    plan = getattr(ex, "structure", None)
    if plan is not None:                                   # the row plan: each sample's time, each set's type
        from parameter_extractor import packs
        time = packs.current().row_value_column("duration_hr")
        c = counts.setdefault("structure_planner", {})
        if time:
            c[time] = sum(1 for s in plan.experiment_sets for x in s.samples if x.duration_hr is not None)
        c["set_type"] = sum(1 for s in plan.experiment_sets if s.set_type)
    meta = getattr(ex, "metadata", None)
    if meta is not None:
        counts["metadata"] = {col: int(bool(getattr(meta, field, None))) for col, field in PAPER_DETAILS.items()}
    if getattr(ex, "chemistry", None) is not None:         # the chemistry step answers per compound column
        from parameter_extractor.ingestion.flatten_to_template import _species_column_of
        c = counts.setdefault("chemistry", {})
        for s in ex.chemistry.solutes:
            try:
                column = _species_column_of(s)
            except Exception:                             # an entry the column can't be worked out for
                continue
            c[column] = c.get(column, 0) + 1
    flags, lines = [], []
    for step, found in store.items():
        bad = []
        for column, a in found.items():
            n = counts.get(step, {}).get(column, 0)
            p = problem(a["status"], n)
            lines.append([step, column, a["status"], n, a["note"], p])
            if p:
                bad.append(f"{column}: {p}")
        if bad:
            flags.append(Flag("parameter_check", f"Answers for every parameter ({step}) that don't match the values "
                                                 f"given: " + "; ".join(bad[:12]) + (" ..." if len(bad) > 12 else "")
                                                 + ". Check those values against the paper."))
    with open(Path(run_dir) / CHECKS_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["step", "parameter", "status", "values", "note", "problem"])
        w.writerows(lines)
    return flags


__all__ = ["STATUSES", "CHECKS_FILE", "check_keys", "checks_model", "with_checks", "rule", "answers", "record",
           "problem", "finish"]
