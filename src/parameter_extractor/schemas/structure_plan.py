"""Stage 2: figure out the row skeleton BEFORE extracting any values.

This is the step the earlier design discussion flagged as the most
consequential one to get right: papers routinely report a sweep (different
salts, concentrations, time points) in a single table, and getting the
grouping/row-count wrong here corrupts everything extracted after it.
Mirrors the template's full_id / set_id / sample_id / set_type hierarchy.
"""
from __future__ import annotations
import json
import re
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

# "Average" (Mickey, 2026-10-31): a result averaged over several runs whose individual values the paper doesn't give
SetType = Literal["Independent", "Time Series", "Evaporation Cycle", "Average"]
# what kind of paper it is (Mickey, 2026-11-03): anything but 'experimental' with no rows skips the extraction steps
PaperKind = Literal["experimental", "review", "perspective", "theory", "abstract", "other"]


# The model answers with short field names (aliases; 2026-11-03: the plan's field names were ~20% of its output
# tokens -- eder1994's 42 samples repeat "sample_label", "duration_hr", "source" 42 times). The code, the saved
# answers (structure_planner.output.json) and the other steps' prompts keep the full names; answers recorded with
# the full names still load (populate_by_name).
_SHORT = ConfigDict(populate_by_name=True)


class PlannedSample(BaseModel):
    model_config = _SHORT
    sample_label: str = Field(alias="label", description="Short human-readable label, e.g. 't = 97.3 h'")
    duration_hr: Optional[float] = Field(default=None, alias="hr", description="The sample's duration in hours.")
    # a duration stated as a range ('3-7 days'): hr the lower end, hi the upper (both in hours) -> duration_range_hr
    duration_hr_high: Optional[float] = Field(default=None, alias="hi",
                                              description="Upper end of a duration given as a range, in hours.")
    source: str = Field("", alias="src", description="Only when the sample is somewhere other than its set's src "
                                                     "(another table, a figure, a section); '' for a row of the "
                                                     "set's table.")


class PlannedSet(BaseModel):
    model_config = _SHORT
    set_label: str = Field(alias="set", description="e.g. 'Na+ 3.33 mol dm-3, 81 C'")
    set_type: SetType = Field(alias="type")
    varying_condition_summary: str = Field(
        alias="varies",
        description="What distinguishes this set from the others, e.g. 'cation = Na+, "
                    "salt conc = 3.33 mol/dm3, T = 81 C'"
    )
    source_table_or_section: str = Field(alias="src", description="The table or section, e.g. 'Table 1'.")
    data_source: str = Field(
        default="", alias="ds",
        description="'' if this set's data was measured in THIS paper. If the paper reproduces it from "
                    "another publication (cited table, redrawn figure, quoted results), the original "
                    "reference as the paper gives it, e.g. 'Rodriguez-Garcia et al. 2015, Nat. Commun. 6:8385 "
                    "(ref. 12)'.")
    samples: List[PlannedSample]


class StructurePlan(BaseModel):
    model_config = _SHORT
    paper_id: SkipJsonSchema[str] = ""            # not used; not asked of the model
    paper_kind: PaperKind = Field(
        default="experimental", alias="kind",
        description="'experimental' if the paper reports experiments of its own (results in tables, figures or "
                    "text); 'review', 'perspective', 'theory' (models / calculations only), 'abstract' (a short "
                    "conference abstract without data) or 'other' otherwise.")
    experiment_sets: List[PlannedSet] = Field(alias="sets")
    total_planned_rows: int = Field(alias="n_rows", description="Sum of len(samples) across all sets -- sanity check.")
    excluded_data: List[str] = Field(
        default_factory=list, alias="excluded",
        description="Data explicitly NOT being planned into rows and why -- e.g. figure-only "
                    "data points, evaporation-cycle experiments, etc.",
    )
    notes: Optional[str] = None


# ---- the plan as the extraction steps read it (2026-11-09 cost pass) -----------------------------------------------
# Every step got the whole plan as indented JSON with every field (its sources, notes and excluded data too), uncached,
# and wrote each value's set and sample label in full -- 'Na+ 3.33 mol dm-3, 81 C' on every table row. Now the steps
# get a compact plan with an id for every set ('S1') and sample ('S1.2') and may answer with the ids; the app puts
# the labels back (api_client.call_structured -> expand_ids) before anything reads the answer.

ID_NOTE = ("Each set and sample has an `id`. Wherever your answer names a set or a sample (`set`, `sample`, "
           "`set_label`, `sample_label`), write its id ('S2', 'S2.3') instead of the label -- the app puts the label "
           "back. '' still means every set.")


def plan_ids(structure: "StructurePlan") -> dict:
    """{'S1': ('set', set_label), 'S1.2': ('sample', set_label, sample_label)} for a plan."""
    out = {}
    for i, s in enumerate(structure.experiment_sets, 1):
        out[f"S{i}"] = ("set", s.set_label)
        for j, smp in enumerate(s.samples, 1):
            out[f"S{i}.{j}"] = ("sample", s.set_label, smp.sample_label)
    return out


def step_plan_json(structure: "StructurePlan") -> str:
    """The plan for the extraction steps: one line, the fields they use, an id per set and sample."""
    sets = []
    for i, s in enumerate(structure.experiment_sets, 1):
        entry = {"id": f"S{i}", "set": s.set_label, "type": s.set_type, "varies": s.varying_condition_summary,
                 "src": s.source_table_or_section}
        if s.data_source:
            entry["ds"] = s.data_source
        samples = []
        for j, smp in enumerate(s.samples, 1):
            e = {"id": f"S{i}.{j}", "label": smp.sample_label}
            if smp.duration_hr is not None:
                e["hr"] = smp.duration_hr
            if smp.duration_hr_high is not None:
                e["hi"] = smp.duration_hr_high
            if smp.source and smp.source != s.source_table_or_section:
                e["src"] = smp.source
            samples.append(e)
        entry["samples"] = samples
        sets.append(entry)
    return ID_NOTE + "\n" + json.dumps({"sets": sets}, ensure_ascii=False, separators=(",", ":"))


_ID = re.compile(r"^\s*S(\d+)(?:\.(\d+))?\s*$")


def expand_ids(obj, ids: dict, field: str = "") -> object:
    """Put the plan's labels back where an answer used ids (in place for models, lists and dicts; returns the value
    for a string): a set field gets the set's label (also for a sample id), a sample field the sample's label, any
    other field holding an id the label of what it names. Labels pass unchanged."""
    from pydantic import BaseModel
    if isinstance(obj, str):
        m = _ID.match(obj)
        if not m or obj.strip() not in ids:
            return obj
        hit = ids[obj.strip()]
        if hit[0] == "set":
            return hit[1]
        return hit[1] if ("set" in field and "sample" not in field) else hit[2]
    if isinstance(obj, BaseModel):
        _fill_set_from_sample(obj, ids)              # while the sample is still an id: it says which set
        for name in list(type(obj).model_fields):
            value = getattr(obj, name, None)
            new = expand_ids(value, ids, name)
            if new is not value:
                try:
                    object.__setattr__(obj, name, new)
                except (AttributeError, TypeError, ValueError):
                    pass
        return obj
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            new = expand_ids(v, ids, field)
            if new is not v:
                obj[i] = new
        return obj
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            new = expand_ids(v, ids, k if isinstance(k, str) else field)
            if new is not v:
                obj[k] = new
        return obj
    return obj


def _fill_set_from_sample(obj, ids: dict) -> None:
    """A value naming only a sample by its id ('set' '' / 'sample' 'S2.3') gets that sample's set too."""
    names = type(obj).model_fields
    for set_f, sample_f in (("set_label", "sample_label"), ("set", "sample")):
        if set_f in names and sample_f in names and not getattr(obj, set_f, ""):
            value = getattr(obj, sample_f, "")
            hit = ids.get(value.strip()) if isinstance(value, str) else None
            if hit and hit[0] == "sample":
                try:
                    object.__setattr__(obj, set_f, hit[1])
                except (AttributeError, TypeError, ValueError):
                    pass
