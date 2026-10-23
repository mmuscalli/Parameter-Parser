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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from pydantic.json_schema import SkipJsonSchema

from parameter_extractor.schemas.common import NOTE_DESC, QUOTE_DESC, SOURCE_DESC, Basis
from parameter_extractor.schemas.structure_plan import StructurePlan



class StageParameter(BaseModel):
    column: str
    unit: str = ""
    description: str = ""
    kind: Literal["number", "text"] = "number"
    uncertainties: bool = False     # also +/- uncertainty and limit columns (StageSpec.error_suffixes)
    error_suffixes: Optional[List[str]] = None   # this parameter's own (e.g. no limit column)


class StageTrigger(BaseModel):
    set_types: List[str] = Field(default_factory=list)
    sample_fields: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    always: bool = False


class StageSpec(BaseModel):
    name: str
    label: str
    description: str = ""           # what the user sees next to the stage's on/off switch
    origin: str = ""
    schema_name: str = ""
    system_prompt: str = ""
    trigger: StageTrigger = Field(default_factory=StageTrigger)
    set_word: str = "relevant"
    # "set": one value per set (or '' = every set); "sample": values can also name a sample
    # (a row) -- e.g. one planet of a planetary system
    per: Literal["set", "sample"] = "set"
    # column suffixes for a parameter's upper uncertainty, lower uncertainty and limit flag
    # (the Exoplanet Archive's convention: pl_orbpererr1, pl_orbpererr2, pl_orbperlim)
    error_suffixes: List[str] = Field(default_factory=lambda: ["err1", "err2", "lim"])
    intro: str
    parameters: List[StageParameter]
    rules: List[str] = Field(default_factory=list)
    # more than one value per parameter for the posterior's modes (a bimodal inclination:
    # prograde / retrograde) -> <col>modal_flag, <col>mode<N>, <col>mode<N>err1/err2, <col>mode<N>desc
    modes: bool = False
    # other estimates of a parameter by other methods (a rotation period from v sin i, from an
    # activity relation, from a GP fit): the adopted value stays in <col>; the others go to
    # <col>alt<N>, <col>alt<N>err1/err2/lim, <col>alt<N>method
    alternatives: bool = False
    # send the rendered table pages along (tables whose text layer is garbled or sideways)
    table_images: bool = False

    def _field_rules(self) -> List[str]:
        rules = []
        if self.has_text:
            rules.append("Text parameters: put the text in `txt` (exactly as printed) and 0 in `v`.")
        if self.modes:
            rules.append("Record EVERY value the paper reports for a parameter. If the posterior is bi- or "
                         "multimodal and the paper gives a value per mode (e.g. an inclination for prograde "
                         "i < 90 deg and retrograde i > 90 deg orbits), give the overall value (if printed) "
                         "without `mode` and each mode's value as its own entry with `mode` describing the mode "
                         "as printed, e.g. 'i < 90 deg (prograde)'.")
        if self.alternatives:
            rules.append("If the paper gives SEVERAL estimates of one parameter for the same object from different "
                         "methods (e.g. a rotation period from v sin i, from an activity-rotation relation and from "
                         "a GP fit; a stellar mass from isochrones and from asteroseismology), give each: the one "
                         "the paper adopts (its tables) without `meth`, every other one as its own entry with "
                         "`meth` naming the method as the paper does, e.g. 'activity-rotation relation "
                         "(Mamajek & Hillenbrand 2008)'. Limits ('> 13 d') count as estimates. Different fits of "
                         "a planet are separate rows, not methods.")
        if self.table_images:
            rules.append("Page images, if attached, are renders of the pages with tables (sideways ones shown "
                         "upright). Read table values and their uncertainties from the images; the text layer "
                         "of a table can be scrambled.")
        if self.has_uncertainties:
            rules.append("Uncertainties: `ep` is the upper uncertainty (positive), `em` the lower one "
                         "(negative, e.g. -0.05); for a symmetric '±x' give x and -x. Leave both out when none "
                         "is given. For an upper or lower limit ('<', '>') set `lim` to 'upper' or 'lower'.")
        return rules

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

    def suffixes_for(self, p: StageParameter) -> List[str]:
        return p.error_suffixes if p.error_suffixes is not None else self.error_suffixes

    @property
    def has_text(self) -> bool:
        return any(p.kind == "text" for p in self.parameters)

    @property
    def has_uncertainties(self) -> bool:
        return any(p.uncertainties for p in self.parameters)

    def output_columns(self) -> List[str]:
        """Every column the stage can fill, in order: each parameter, then its uncertainty and
        limit columns when it has them."""
        out = []
        for p in self.parameters:
            out.append(p.column)
            if p.uncertainties:
                out += [p.column + s for s in self.suffixes_for(p)]
        if self.modes:                               # after the archive-style block, per parameter
            for p in self.parameters:
                if p.kind == "number":
                    out += mode_columns(p.column, p.uncertainties and self.suffixes_for(p)[:2] or [])
        if self.alternatives:
            for p in self.parameters:
                if p.kind == "number":
                    out += alternative_columns(p.column, p.uncertainties and self.suffixes_for(p) or [])
        return out

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

    # ---- output budget ---------------------------------------------------------------

    def output_budget(self, structure: StructurePlan) -> int:
        """Output tokens this stage can plausibly need: a few hundred per value (with its quote
        and note) for every parameter of every set (and sample), modes counted twice, plus
        room for notes. A runaway answer then stops early instead of after the full maximum
        (api_client retries once with the full maximum)."""
        targets = len(structure.experiment_sets)
        if self.per == "sample":
            targets += sum(len(s.samples) for s in structure.experiment_sets)
        values = targets * len(self.parameters) * (1 + self.modes + self.alternatives)
        return 4000 + 250 * values

    # ---- schema and prompt ---------------------------------------------------------

    def models(self) -> Tuple[type, type]:
        return _models(self.model_dump_json())

    def prompt(self, structure: StructurePlan, paper_text: str) -> str:
        from parameter_extractor.stages.prompt_loader import load_prompt
        listing = "\n".join(f"- `{p.column}`" + (f" ({p.unit})" if p.unit else "") + f": {p.description}"
                            for p in self.parameters)
        return load_prompt("optional_stage", INTRO=self.intro, PARAMETER_LIST=listing,
                           SET_WORD=self.set_word, SCHEMA_NAME=self.model_name,
                           SAMPLE_KEY="`sample` (the sample_label, if the values are for one "
                                      f"{self.units('sample')} only) " if self.per == "sample" else "",
                           EXTRA_RULES="".join(f"- {r}\n" for r in self.rules + self._field_rules() + (
                               [f"Give a row's `sample` exactly as the structure plan's sample_label when its "
                                f"values belong to one {self.units('sample')} only; leave `sample` out for values "
                                f"of the whole set."]
                               if self.per == "sample" else [])),
                           STRUCTURE_PLAN_JSON=structure.model_dump_json(indent=2), PAPER_TEXT=paper_text)


def _require_all(schema: dict) -> None:
    schema["required"] = list(schema.get("properties", {}))


# Every field REQUIRED in the schema sent to the model (aa57186-25: with defaults, fields were
# optional, the model skipped `method`, wrote the method into `note` and ran on -- "Done. Done.
# ..." -- until cut off). The Python defaults stay, so older recorded answers still validate.
ALL_REQUIRED = ConfigDict(json_schema_extra=_require_all)


# The answer format (2026-10-22, measured with the token-counting endpoint on teng2023's 306
# stellar values): values grouped under their row -- the system / planet named once, not per value --
# with short field names, and empty fields left out: 30% fewer output tokens than one object with 16
# named fields per value (field names were 45% of the output). Short names are ALIASES: the code
# reads `item.parameter`, `item.quote`, ...; answers recorded in the old flat format
# ({"parameters": [...]}) still load. Only the core fields are required (col, v, q, src, c);
# the note stays capped -- with fields optional, the model once wrote a skipped field into the note
# and ran on (aa57186-25), which the short-note rule, the stage's output budget and the retry guard.
# `u` is required too: optional, the model left out "fraction" for a transit depth (nielsen2019) and
# the value went in unconverted -- a wrong number costs more than the ~4 tokens a value
CORE_FIELDS = ["col", "v", "u", "q", "src", "c"]


def _required(names: List[str]):
    def extra(schema: dict) -> None:
        schema["required"] = [n for n in names if n in schema.get("properties", {})]
    return extra


class _CompactResult(BaseModel):
    """Base of every stage's answer: `rows` of grouped values (the model's format) and the flat
    `parameters` list the code works with (rows flattened, plus answers recorded in the old format)."""
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["rows", "notes"]))
    _columns: frozenset = frozenset()          # the stage's parameters (set by _models)

    @model_validator(mode="before")
    @classmethod
    def _known_columns_only(cls, data):
        """A value for a parameter the stage no longer has (a pack dropped it -- e.g.
        cycle_duration_hr, 2026-10-22 -- in a recorded answer, or a model slip) is skipped
        rather than failing the whole step."""
        if not isinstance(data, dict) or not cls._columns:
            return data
        known = lambda v: not isinstance(v, dict) or (v.get("col") or v.get("parameter")) in cls._columns
        data = dict(data)
        if isinstance(data.get("parameters"), list):
            data["parameters"] = [v for v in data["parameters"] if known(v)]
        if isinstance(data.get("rows"), list):
            data["rows"] = [dict(r, values=[v for v in r.get("values", []) if known(v)])
                            if isinstance(r, dict) and isinstance(r.get("values"), list) else r
                            for r in data["rows"]]
        return data

    @property
    def parameters(self) -> list:
        out = list(self.legacy_parameters)
        for row in self.rows:
            labels = {"set_label": row.set_label}
            if "sample_label" in type(row).model_fields:
                labels["sample_label"] = row.sample_label
            out += [v.model_copy(update=labels) for v in row.values]
        return out


@lru_cache(maxsize=None)
def _models(spec_json: str) -> Tuple[type, type]:
    """(item model, result model) for a spec -- the same classes for the same spec."""
    spec = StageSpec.model_validate_json(spec_json)
    name = spec.model_name
    hidden_sample = {} if spec.per == "set" else {"sample_label": (SkipJsonSchema[str], "")}
    Item = create_model(
        f"{name}Value",
        __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(CORE_FIELDS)),
        set_label=(SkipJsonSchema[str], ""),            # from the row (or the old flat format)
        **hidden_sample,
        parameter=(Literal[tuple(spec.columns)], Field(alias="col", description="The parameter (column).")),
        value=(float, Field(alias="v", description="As printed (see u); 0 for a text parameter.")),
        unit=(str, Field(default="", alias="u", description="Unit as printed, e.g. 'rad', 'min', 'JD-2450000', "
                                                            "'L_sun', 'fraction', 'ppm', '10^9 erg s-1 cm-2'; '' only "
                                                            "if printed in exactly the parameter's unit. The app "
                                                            "converts.")),
        **({"text": (str, Field(default="", alias="txt", description="A text parameter's text as printed."))}
           if spec.has_text else {}),
        **({"mode": (str, Field(default="", alias="mode", description="Only for one mode of a bi-/multimodal "
                                                                      "posterior: the mode as printed, e.g. "
                                                                      "'i < 90 deg (prograde)'."))}
           if spec.modes else {}),
        **({"method": (str, Field(default="", alias="meth", description="Only for an estimate the paper does NOT "
                                                                        "adopt: its method as the paper names it."))}
           if spec.alternatives else {}),
        **({"err_plus": (float, Field(default=0.0, alias="ep", description="Upper uncertainty, positive.")),
            "err_minus": (float, Field(default=0.0, alias="em", description="Lower uncertainty, negative.")),
            "limit": (Literal["", "upper", "lower"], Field(default="", alias="lim",
                                                           description="'upper' for '<x', 'lower' for '>x'."))}
           if spec.has_uncertainties else {}),
        basis=(Basis, Field(default="stated", alias="b", description="Leave out when stated; 'derived' if "
                                                                     "calculated from stated values; 'assumed' "
                                                                     "if not stated.")),
        quote=(str, Field(alias="q", description=QUOTE_DESC)),
        source=(str, Field(alias="src", description=SOURCE_DESC)),
        confidence=(Literal["high", "medium", "low"], Field(alias="c")),
        note=(str, Field(default="", alias="n", description=NOTE_DESC + " Never the method or mode -- those "
                                                                        "have their own fields.")),
    )
    sample_field = {} if spec.per == "set" else {"sample_label": (str, Field(
        default="", alias="sample", description=f"Exact structure-plan sample_label if these values are for one "
                                                f"{spec.units('sample')} only; leave out for the whole set."))}
    Row = create_model(
        f"{name}Row",
        __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(["set", "values"])),
        set_label=(str, Field(alias="set", description="Exact structure-plan set_label; '' if these values apply "
                                                       f"to every {spec.set_word} set.")),
        **sample_field,
        values=(List[Item], Field(description="This row's values.")),
    )
    Result = create_model(
        name,
        __base__=_CompactResult,
        rows=(List[Row], Field(default_factory=list, description="Values grouped by set (and sample): one entry per "
                                                                 "set/sample with values. Only values the paper "
                                                                 "states.")),
        notes=(str, Field(default="", description="Anything that didn't fit, briefly.")),
        legacy_parameters=(SkipJsonSchema[List[Item]], Field(default_factory=list, validation_alias="parameters")),
    )
    Result._columns = frozenset(spec.columns)
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
        for column in spec.output_columns():
            out.append((column, spec.label))
    return out


# an answer that reports its own failure ("Extraction failed" in its notes, aa57186-25: 4 values
# instead of 21) is valid JSON, so api_client's retry doesn't see it
GAVE_UP = re.compile(r"\b(extraction failed|failed to extract|unable to (?:extract|complete)|could not "
                     r"(?:extract|complete))\b", re.IGNORECASE)


def run_optional_stage(ctx, spec: StageSpec, paper_text: str, structure: StructurePlan,
                       table_images: Optional[List[Path]] = None):
    from parameter_extractor.api_client import call_structured
    _, Result = spec.models()
    ask = lambda: call_structured(
        ctx,
        stage=spec.name,
        system_prompt=spec.system_prompt or f"Extract {spec.label.lower()} from a scientific paper. Report "
                                            f"only what the paper states.",
        user_content=spec.prompt(structure, paper_text),
        response_model=Result,
        paper_text=paper_text,
        image_paths=(table_images or None) if spec.table_images else None,
        max_tokens=spec.output_budget(structure),
    )
    result = ask()
    if GAVE_UP.search(result.notes or ""):
        ctx.note(spec.name, f"{spec.label}: the answer reported a failure -- asking again")
        result = ask()
        if GAVE_UP.search(result.notes or ""):
            result.notes = (f"[The model reported a failure twice -- its values may be incomplete.] "
                            f"{result.notes}")
    return result


@dataclass
class StageValue:
    """One value a stage writes into one column, after conversion to the parameter's unit."""
    value: object
    basis: str
    quote: str
    source: str
    confidence: str
    note: str = ""


def stage_values(spec: StageSpec, item) -> Tuple[Dict[str, StageValue], List[str]]:
    """{column: StageValue} for one extracted item (its value, and its uncertainty and limit
    columns), converted to the parameter's unit; and the problems (unconvertible units)."""
    param = next(p for p in spec.parameters if p.column == item.parameter)
    printed = getattr(item, "unit", "") or ""
    base = dict(basis=item.basis, quote=item.quote, source=item.source, confidence=item.confidence)
    if param.kind == "text":
        text = (getattr(item, "text", "") or "").strip()
        return ({param.column: StageValue(text, note=item.note, **base)} if text else {}), []
    from parameter_extractor.units import convert_printed
    value, note = convert_printed(item.value, printed, param.unit)
    if value is None:
        return {}, [f"{spec.label}: {param.column} = {item.value:g} {printed} for '{item.set_label}' left out -- {note}."]
    notes = "; ".join(n for n in (item.note, note) if n)
    out = {param.column: StageValue(value, note=notes, **base)}
    if param.uncertainties:
        suffixes = spec.suffixes_for(param)
        cols = [param.column + s for s in suffixes]
        for col, err in zip(cols[:2], (getattr(item, "err_plus", 0.0), getattr(item, "err_minus", 0.0))):
            if err:
                converted, _ = convert_printed(err, printed, param.unit, is_error=True)
                if converted is not None:
                    out[col] = StageValue(converted, **base)
        if len(cols) > 2:                       # limit flag: 1 upper limit, -1 lower limit, 0 a measurement
            out[cols[2]] = StageValue({"upper": 1, "lower": -1}.get(getattr(item, "limit", ""), 0), **base)
    return out, []


MAX_MODES = 3


def alternative_columns(column: str, error_suffixes: List[str]) -> List[str]:
    """Per other estimate N: <col>altN, its uncertainties and limit flag, <col>altNmethod."""
    out = []
    for n in range(1, MAX_MODES + 1):
        out += [f"{column}alt{n}"] + [f"{column}alt{n}{s}" for s in error_suffixes] + [f"{column}alt{n}method"]
    return out


def mode_columns(column: str, error_suffixes: List[str]) -> List[str]:
    """<col>modal_flag, then per mode N: <col>modeN, its uncertainties, <col>modeNdesc."""
    out = [column + "modal_flag"]
    for n in range(1, MAX_MODES + 1):
        out += [f"{column}mode{n}"] + [f"{column}mode{n}{s}" for s in error_suffixes] + [f"{column}mode{n}desc"]
    return out


@dataclass
class StageConflict:
    """The same parameter given twice for one set/sample with different values (e.g. a
    planet's orbit from an RV-only fit and from a joint fit): the first is kept, with its
    own uncertainties, and the user is told."""
    message: str
    quote: str
    source: str


def _same_value(a, b, unit: str = "") -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if unit == "deg":                                   # -12.7 deg is 347.3 deg
            a = b + ((a - b + 180) % 360 - 180)
        return abs(a - b) <= 0.005 * max(abs(a), abs(b), 1e-12)
    return str(a).strip().lower() == str(b).strip().lower()


def optional_values(spec: StageSpec, result, structure: StructurePlan,
                    problems: Optional[List[str]] = None,
                    conflicts: Optional[List[StageConflict]] = None) -> Dict[Tuple[str, str, str], StageValue]:
    """{(set_label, sample_label, column): StageValue} for the values written automatically
    (sample_label '' = the whole set): assumed ones are left to the review; a set-specific
    value wins over a paper-wide one. A value and its uncertainty/limit columns always come
    from the same item: when two items give one parameter different values, the first one
    is kept and the other reported in `conflicts`. Unconvertible values go in `problems`."""
    targets = spec.target_sets(structure)
    out: Dict[Tuple[str, str, str], StageValue] = {}
    owner: Dict[Tuple[str, str, str], Tuple[object, List[str]]] = {}   # (label, sample, parameter) -> (item, its columns)
    modes: Dict[Tuple[str, str, str], list] = {}                       # same key -> [(mode text, columns)]
    alternatives: Dict[Tuple[str, str, str], list] = {}                # same key -> [(method, columns)]
    for v in (result.parameters if result is not None else []):
        if v.basis == "assumed":
            continue
        columns, issues = stage_values(spec, v)
        if problems is not None:
            problems += issues
        if not columns:
            continue
        sample = getattr(v, "sample_label", "") or ""
        mode = (getattr(v, "mode", "") or "").strip()
        method = (getattr(v, "method", "") or "").strip()
        if method:                                      # another method's estimate: its own columns
            label_text = f"{method} -- {mode}" if mode else method
            for label in ([v.set_label] if v.set_label else targets):
                alternatives.setdefault((label, sample, v.parameter), []).append((label_text, columns))
            continue
        if mode:                                        # one mode of a multimodal posterior: its own columns
            for label in ([v.set_label] if v.set_label else targets):
                modes.setdefault((label, sample, v.parameter), []).append((mode, columns))
            continue
        for label in ([v.set_label] if v.set_label else targets):
            key = (label, sample, v.parameter)
            if key in owner:
                first, first_cols = owner[key]
                if not v.set_label and first.set_label:
                    continue                                    # paper-wide never replaces set-specific
                if v.set_label and not first.set_label:
                    for c in first_cols:                        # set-specific replaces paper-wide, whole group
                        out.pop((label, sample, c), None)
                else:
                    old, new = out.get((label, sample, v.parameter)), columns.get(v.parameter)
                    unit = next((p.unit for p in spec.parameters if p.column == v.parameter), "")
                    if old is not None and new is not None and _same_value(old.value, new.value, unit):
                        for column, value in columns.items():   # same value: only fill what's missing
                            out.setdefault((label, sample, column), value)
                        continue
                    if conflicts is not None and old is not None and new is not None:
                        where = sample or label
                        conflicts.append(StageConflict(
                            f"{spec.label}: {where} has two values for {v.parameter} -- {old.value:g} "
                            f"({old.source or 'no source'}) and {new.value:g} ({new.source or 'no source'}); "
                            f"the first is in the CSV with its own uncertainties"
                            if isinstance(old.value, (int, float)) and isinstance(new.value, (int, float)) else
                            f"{spec.label}: {where} has two values for {v.parameter} -- '{old.value}' "
                            f"({old.source or 'no source'}) and '{new.value}' ({new.source or 'no source'}); "
                            f"the first is in the CSV", quote=new.quote, source=new.source))
                    continue
            owner[key] = (v, list(columns))
            for column, value in columns.items():
                out[(label, sample, column)] = value
    for (label, sample, param), found in modes.items():
        param_spec = next(p for p in spec.parameters if p.column == param)
        suffixes = spec.suffixes_for(param_spec)[:2] if param_spec.uncertainties else []
        seen = []
        for mode, columns in found:
            if any(m == mode for m, _ in seen):
                continue
            seen.append((mode, columns))
        if len(seen) > MAX_MODES and problems is not None:
            problems.append(f"{spec.label}: {sample or label} has {len(seen)} modes for {param}; the first "
                            f"{MAX_MODES} are in the CSV ({', '.join(m for m, _ in seen[MAX_MODES:])} left out).")
        first = seen[0][1][param]
        out[(label, sample, param + "modal_flag")] = StageValue(1, first.basis, first.quote, first.source,
                                                                first.confidence, "bi-/multimodal posterior")
        for n, (mode, columns) in enumerate(seen[:MAX_MODES], start=1):
            main = columns[param]
            out[(label, sample, f"{param}mode{n}")] = main
            for s in suffixes:
                if param + s in columns:
                    out[(label, sample, f"{param}mode{n}{s}")] = columns[param + s]
            out[(label, sample, f"{param}mode{n}desc")] = StageValue(mode, main.basis, main.quote, main.source,
                                                                     main.confidence)
    for (label, sample, param), found in alternatives.items():
        param_spec = next(p for p in spec.parameters if p.column == param)
        suffixes = spec.suffixes_for(param_spec) if param_spec.uncertainties else []
        main_value = out.get((label, sample, param))
        seen = []
        for method, columns in found:
            same = lambda a, b: (a is None) == (b is None) and (a is None or a.value == b.value)
            repeat = main_value is not None and _same_value(main_value.value, columns[param].value,
                                                            param_spec.unit) and \
                all(same(out.get((label, sample, param + s)), columns.get(param + s)) for s in suffixes)
            if repeat or any(m == method for m, _ in seen):
                continue                                # a repeat of the adopted value isn't another estimate
            seen.append((method, columns))
        if len(seen) > MAX_MODES and problems is not None:
            problems.append(f"{spec.label}: {sample or label} has {len(seen)} other estimates of {param}; the "
                            f"first {MAX_MODES} are in the CSV ({', '.join(m for m, _ in seen[MAX_MODES:])} left out).")
        for n, (method, columns) in enumerate(seen[:MAX_MODES], start=1):
            value = columns[param]
            out[(label, sample, f"{param}alt{n}")] = value
            for s in suffixes:
                if param + s in columns:
                    out[(label, sample, f"{param}alt{n}{s}")] = columns[param + s]
            out[(label, sample, f"{param}alt{n}method")] = StageValue(method, value.basis, value.quote,
                                                                      value.source, value.confidence)
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


@dataclass
class StageToggle:
    """A stage the user can switch off (GUI checkboxes, CLI --skip-stage): the pack's
    spec stages and its optional code stages. `conditional`: runs only when the paper
    calls for it (its trigger), even when switched on."""
    name: str
    label: str
    description: str
    conditional: bool


def _code_stage_toggles() -> Dict[str, Tuple[str, str]]:
    from parameter_extractor.stages import fit_models
    return {"fit_models": (fit_models.LABEL, fit_models.DESCRIPTION)}


def toggleable_stages(pack=None) -> List[StageToggle]:
    """The switchable stages of a domain pack (default: the active one), in run order."""
    from parameter_extractor.packs import current
    pack = pack or current()
    out = []
    for spec in _specs_in(pack.stages_dir).values():
        t = spec.trigger
        when = "" if t.always else " Runs only when the paper " + (
            f"mentions {', '.join(t.keywords[:3])}" if t.keywords else f"has {spec.set_word} experiments") + "."
        listed = ", ".join(p.column for p in spec.parameters[:6]) + (", ..." if len(spec.parameters) > 6 else "")
        what = spec.description or spec.label
        out.append(StageToggle(spec.name, spec.label, f"{what} Columns: {listed}. One API call.{when}",
                               not t.always))
    for name, (label, description) in _code_stage_toggles().items():
        if pack.uses(name):
            out.append(StageToggle(name, label, description, False))
    return out
