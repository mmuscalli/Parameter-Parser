"""
Optional extraction stages defined as data (each domain pack's stages/*.json), not code.

A spec names the stage, says when it runs (its trigger), and lists the
parameters it extracts -- each a column with a unit and a description. From
that the app builds:

  - the structured-output schema (a flat list of per-set values: parameter,
    value, set_label, basis stated/derived/assumed, quote, source,
    confidence, note -- no Optional fields, so the grammar stays small);
  - the prompt: the spec's intro, parameter list and extra rules inside one
    shared template (prompts/optional_stage.md) that carries the rules every
    stage needs (only stated values, verbatim quotes, assumed values go to
    the user);
  - how results reach the rows (optional_values), the flags and the review --
    the same for every stage.

Triggers are decided locally from the structure plan (set types, sample
fields) or the paper text (keywords), so a stage costs nothing on papers it
doesn't concern; triggered stages run in parallel with chemistry
(pipeline.extract). Wet-dry cycling was the first stage converted to a spec
(2026-10-20; its replay test reproduces the earlier output exactly).

Spec fields:
  name, label             machine name / what the user sees
  origin                  provenance label of its values (default: label, lower case)
  schema_name             name of the generated response model (default: CamelCase name + "Result")
  system_prompt           optional; a sensible default is built from the label
  trigger                 {"set_types": [...], "sample_fields": [...], "keywords": [...],
                           "always": false} -- any match runs the stage
  set_word                how the prompt and flags refer to the sets it concerns ("cycling")
  intro                   what the stage is about, first lines of the prompt
  parameters              [{"column", "unit", "description"}] in output order
  rules                   extra, topic-specific rules for the prompt
Columns that aren't template columns become standard columns of the app
(registry.py), written after the template's block, in spec order.
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, create_model

from parameter_extractor.schemas.common import Basis
from parameter_extractor.schemas.structure_plan import StructurePlan



class StageParameter(BaseModel):
    column: str
    unit: str = ""
    description: str = ""


class StageTrigger(BaseModel):
    set_types: List[str] = Field(default_factory=list)
    sample_fields: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    always: bool = False


class StageSpec(BaseModel):
    name: str
    label: str
    origin: str = ""
    schema_name: str = ""
    system_prompt: str = ""
    trigger: StageTrigger = Field(default_factory=StageTrigger)
    set_word: str = "relevant"
    # "set": one value per set (or '' = every set); "sample": values can also name a sample
    # (a row) -- e.g. one planet of a planetary system
    per: Literal["set", "sample"] = "set"
    intro: str
    parameters: List[StageParameter]
    rules: List[str] = Field(default_factory=list)

    def units(self, which: str) -> str:
        from parameter_extractor.packs import current
        return current().manifest.units.get(which, which)

    @property
    def origin_label(self) -> str:
        return self.origin or self.label.lower()

    @property
    def model_name(self) -> str:
        return self.schema_name or "".join(p.title() for p in self.name.split("_")) + "Result"

    @property
    def columns(self) -> List[str]:
        return [p.column for p in self.parameters]

    # ---- when it runs, and which sets it concerns ---------------------------------

    def _set_matches(self, s) -> bool:
        t = self.trigger
        return s.set_type in t.set_types or any(getattr(x, f, None) is not None
                                               for x in s.samples for f in t.sample_fields)

    def triggered(self, structure: StructurePlan, paper_text: str = "") -> bool:
        t = self.trigger
        if t.always or any(self._set_matches(s) for s in structure.experiment_sets):
            return True
        return any(re.search(rf"\b{re.escape(k)}\b", paper_text, re.IGNORECASE) for k in t.keywords)

    def target_sets(self, structure: StructurePlan) -> List[str]:
        """The sets a value with set_label '' applies to: those that match the trigger's set
        conditions, or every set when the stage was triggered by keywords or always runs."""
        matching = [s.set_label for s in structure.experiment_sets if self._set_matches(s)]
        return matching or [s.set_label for s in structure.experiment_sets]

    # ---- schema and prompt ---------------------------------------------------------

    def models(self) -> Tuple[type, type]:
        return _models(self.model_dump_json())

    def prompt(self, structure: StructurePlan, paper_text: str) -> str:
        from parameter_extractor.stages.prompt_loader import load_prompt
        listing = "\n".join(f"- `{p.column}`" + (f" ({p.unit})" if p.unit else "") + f": {p.description}"
                            for p in self.parameters)
        return load_prompt("optional_stage", INTRO=self.intro, PARAMETER_LIST=listing,
                           SET_WORD=self.set_word, SCHEMA_NAME=self.model_name,
                           EXTRA_RULES="".join(f"- {r}\n" for r in self.rules + (
                               [f"Give `sample_label` exactly as in the structure plan when a value belongs "
                                f"to one {self.units('sample')} only; '' when it applies to the whole set."]
                               if self.per == "sample" else [])),
                           STRUCTURE_PLAN_JSON=structure.model_dump_json(indent=2), PAPER_TEXT=paper_text)


@lru_cache(maxsize=None)
def _models(spec_json: str) -> Tuple[type, type]:
    """(item model, result model) for a spec -- the same classes for the same spec."""
    spec = StageSpec.model_validate_json(spec_json)
    name = spec.model_name
    sample_field = {} if spec.per == "set" else {"sample_label": (str, Field(
        default="", description="Exact structure-plan sample_label within the set if the value is for one "
                                "sample only; '' if it applies to the whole set."))}
    Item = create_model(
        f"{name}Value",
        set_label=(str, Field(description="Exact structure-plan set_label; '' if it applies to every "
                                          f"{spec.set_word} set.")),
        **sample_field,
        parameter=(Literal[tuple(spec.columns)], ...),
        value=(float, Field(description="In the parameter's unit.")),
        basis=(Basis, Field(default="stated", description="'stated' in the paper; 'derived' by arithmetic from "
                                                          "stated values; 'assumed' if not stated.")),
        quote=(str, Field(description="Copied word for word from the paper (for a table value: its row/column "
                                      "labels and the value exactly as printed). Never your own words -- "
                                      "explanations go in `note`.")),
        source=(str, ...),
        confidence=(Literal["high", "medium", "low"], ...),
        note=(str, Field(default="", description="Your explanation, e.g. how a 'derived' value was calculated; "
                                                 "'' if none.")),
    )
    Result = create_model(
        name,
        parameters=(List[Item], Field(default_factory=list,
                                      description="Only values the paper states. Leave a parameter out if not given.")),
        notes=(str, Field(default="", description="Anything that didn't fit the parameters.")),
    )
    return Item, Result


def load_specs() -> Dict[str, StageSpec]:
    """The active domain pack's stage specs (its stages/*.json), by name, in file order."""
    from parameter_extractor.packs import current
    return _specs_in(current().stages_dir)


@lru_cache(maxsize=None)
def _specs_in(folder: Path) -> Dict[str, StageSpec]:
    specs = {}
    for path in sorted(Path(folder).glob("*.json")):
        spec = StageSpec.model_validate_json(path.read_text())
        specs[spec.name] = spec
    return specs


def spec_standard_columns() -> List[Tuple[str, str]]:
    """(column, description) of every spec parameter, in spec order -- the registry adds
    the ones that aren't template columns to its standard columns."""
    out = []
    for spec in load_specs().values():
        for p in spec.parameters:
            out.append((p.column, f"{spec.label}: {p.description}"))
    return out


def run_optional_stage(ctx, spec: StageSpec, paper_text: str, structure: StructurePlan):
    from parameter_extractor.api_client import call_structured
    _, Result = spec.models()
    return call_structured(
        ctx,
        stage=spec.name,
        system_prompt=spec.system_prompt or f"Extract {spec.label.lower()} from a scientific paper. Report "
                                            f"only what the paper states.",
        user_content=spec.prompt(structure, paper_text),
        response_model=Result,
    )


def optional_values(spec: StageSpec, result, structure: StructurePlan) -> Dict[Tuple[str, str, str], object]:
    """{(set_label, sample_label, column): value record} for the values written automatically
    (sample_label '' = the whole set): assumed ones are left to the review; a set-specific
    value wins over a paper-wide one."""
    targets = spec.target_sets(structure)
    out: Dict[Tuple[str, str, str], object] = {}
    for v in (result.parameters if result is not None else []):
        if v.basis == "assumed":
            continue
        sample = getattr(v, "sample_label", "") or ""
        for label in ([v.set_label] if v.set_label else targets):
            if v.set_label or (label, sample, v.parameter) not in out:
                out[(label, sample, v.parameter)] = v
    return out


def optional_results(optional=None, wet_dry=None) -> List[Tuple[StageSpec, object]]:
    """[(spec, result)] from either the list form or a bare wet-dry result (older callers)."""
    out = [(spec, result) for spec, result in (optional or []) if result is not None]
    if wet_dry is not None and not any(spec.name == "wet_dry" for spec, _ in out):
        out.append((load_specs()["wet_dry"], wet_dry))
    return out


def triggered_specs(structure: StructurePlan, paper_text: str,
                    choices: Optional[Dict[str, str]] = None) -> List[StageSpec]:
    """The stages to run: triggered ones, unless the user turned them off ('off'), plus
    any forced on ('on')."""
    choices = choices or {}
    out = []
    for name, spec in load_specs().items():
        choice = choices.get(name, "auto")
        if choice == "on" or (choice == "auto" and spec.triggered(structure, paper_text)):
            out.append(spec)
    return out
