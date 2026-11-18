"""
Reading a table again when it was read incompletely (Mickey, 2026-11-17: Huber1998's Table 1 -- a pH per run, the page
image legible -- came back without pH in 2 of 3 runs; "a fallback to detect if a table likely parsed incorrectly",
then re-read it automatically).

At the end of the step phase (pipeline.extract_steps), before any row is built, the row plan is compared with what
each configurable step answered -- the same evidence calculators/plan_checks.py uses on the finished rows: a set whose
plan says a condition differs per row ('pH per run', 'pH (2.0, 9.0, 10.5)', 'different pH', a range with nothing
given), but whose step answer gives that condition no per-row values (none, or one), and whose rows' own labels don't
state it either. For each step with such sets, ONE small follow-up request: the same step with only those
parameters, told which sets (by their plan ids) need a value on every row. Its rows join the step's answer; values
the first answer already gave keep their place (sample-level values only add).

Only when something is missing, so a paper read completely costs nothing more. The request is a step of its own
(`<step>_repair`, its audit and answer saved like any other), so a rebuild reuses it and a resume asks it only if it
is missing. A set still incomplete afterwards is flagged by plan_checks as before.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from parameter_extractor.calculators.plan_checks import varies_evidence

SUFFIX = "_repair"


def _given(values: dict, set_label: str, column: str) -> set:
    """The distinct per-row values a step answer gives a set for a column (its range column too)."""
    out = set()
    for (label, _sample, col), v in values.items():
        if label == set_label and (col == column or col.replace("_range", "") == column):
            out.add(str(v.value))
    return out


def _labels_state(pset, kind: str) -> bool:
    """The rows' own labels give this kind of condition (label_values fills it from them)."""
    from parameter_extractor.calculators.label_values import label_quantities
    return any(q.kind == kind for smp in pset.samples for q in label_quantities(smp.sample_label))


def incomplete(structure, optional_list, label_columns: Dict[str, str]) -> List[Tuple[object, List[str], List[str]]]:
    """[(spec, set ids, columns)] -- per step, the sets whose per-row condition its answer left out."""
    from parameter_extractor.schemas.structure_plan import plan_ids
    from parameter_extractor.stages.optional import optional_values
    if not label_columns or structure is None or not structure.experiment_sets:
        return []
    ids = {v[1]: k for k, v in plan_ids(structure).items() if v[0] == "set"}
    out = []
    for spec, result in optional_list:
        if result is None or spec.name.endswith(SUFFIX):
            continue
        values = optional_values(spec, result, structure)
        sets, columns = [], []
        for pset in structure.experiment_sets:
            if len(pset.samples) < 2:
                continue
            for kind, column in label_columns.items():
                if column not in spec.columns:
                    continue
                evidence = varies_evidence(kind, pset.varying_condition_summary or "") if kind in (
                    "pH", "temperature", "pressure", "time") else ""
                if not evidence or _labels_state(pset, kind):
                    continue
                given = _given(values, pset.set_label, column)
                if len(given) > 1 or (evidence == "range" and given):
                    continue
                if ids[pset.set_label] not in sets:
                    sets.append(ids[pset.set_label])
                if column not in columns:
                    columns.append(column)
        if sets:
            out.append((spec, sets, columns))
    return out


def repair_spec(spec, sets: List[str], columns: List[str]):
    """The step asked again: only `columns`, a rule naming the sets; no `other`, no grids."""
    keep = [p for p in spec.parameters if p.column in columns]
    rule = (f"READ AGAIN: the structure plan says the rows of {', '.join(sets)} differ in {', '.join(columns)}, but no "
            f"per-row values were given. Read their table (or text) again and give, for EVERY sample of these sets, "
            f"its own value of {', '.join(columns)} as printed for that row -- one row per sample with its `sample` "
            f"id. Leave out any other set and any value the paper doesn't give for that row.")
    return spec.model_copy(update={"name": spec.name + SUFFIX, "parameters": keep, "rules": list(spec.rules) + [rule],
                                   "open_ended": False, "grids": False, "hint_by_stage": {}})


def repair_steps(ctx, ex, paper_text: str, table_images, label_columns: Dict[str, str]) -> List[str]:
    """Ask again for what the steps left out (module text); their rows join the answers in place. Returns notes."""
    from parameter_extractor.stages.optional import run_optional_stage
    notes = []
    for spec, sets, columns in incomplete(ex.structure, ex.optional_list, label_columns):
        narrowed = repair_spec(spec, sets, columns)
        if not narrowed.parameters:
            continue
        ctx.total_steps += 1
        ctx.note(spec.name, f"{spec.label}: {', '.join(columns)} missing on the rows of {', '.join(sets)} -- reading "
                            f"them again")
        try:
            again = run_optional_stage(ctx, narrowed, paper_text, ex.structure, table_images)
        except Exception as e:                       # noqa: BLE001 -- a second try is a convenience
            if "Rebuilding needs" in str(e):        # a rebuild of a run from before this step: never asks
                notes.append(f"{spec.label}: {', '.join(columns)} not read again -- the earlier run has no such "
                             f"follow-up answer (Resume asks for it)")
            else:
                notes.append(f"{spec.label}: reading {', '.join(columns)} again failed ({type(e).__name__}: {e})")
            continue
        result = ex.optional[spec.name][1]
        added = [row for row in again.rows if getattr(row, "sample_label", "")]   # per-row values only
        result.rows = list(result.rows) + added
        n = sum(len(r.values) for r in added)
        notes.append(f"{spec.label}: {', '.join(columns)} read again for {', '.join(sets)} -- {n} value(s) added")
    return notes
