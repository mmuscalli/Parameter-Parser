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
                           "set_patterns": [...], "always": false} -- any match runs the stage;
                           set_patterns are regular expressions matched (case-insensitive) against a
                           set's label and what varies, e.g. wet-dry cycling sets of type Independent
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

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model, model_validator
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
    # a text parameter with a fixed vocabulary (e.g. experiment_type: Batch / Flowthrough): matched
    # case-insensitively to these spellings; anything else is left out and reported
    choices: Optional[List[str]] = None
    integer: bool = False           # a count (cycle_number): written as a whole number


class StageTrigger(BaseModel):
    set_types: List[str] = Field(default_factory=list)
    sample_fields: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    set_patterns: List[str] = Field(default_factory=list)   # regexes on a set's label / what varies
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
    # the prompt rule for `alternatives`, when the default's examples (astronomy) don't fit the field
    alternatives_rule: str = ""
    # also collect conditions/parameters that have no column (`other`: name, value as stated, ...),
    # offered in the review like the old methodology step's other_parameters
    open_ended: bool = False
    # between a parameter and the extra columns of its modes / other estimates: "" gives the archive's
    # style (pl_orbinclmode1, st_rotpalt1method), "_" gives initial_temperature_C_alt1_method
    suffix_separator: str = ""
    open_ended_hint: str = ""
    # a text column for the time system of the epochs, filled from the printed unit of any
    # Julian-date parameter ('BJD_TDB - 2450000' -> 'BJD_TDB'): exoplanets' pl_tsystemref
    time_system_column: str = ""        # what kinds of other parameters to look for (prompt)
    # the hint's wording depends on another step running (2026-11-07): {stage: {"runs": text, "off": text}},
    # appended to open_ended_hint -- e.g. analysis details go to `other` only when the analysis step is off
    hint_by_stage: Dict[str, Dict[str, str]] = Field(default_factory=dict)

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
            rules.append(self.alternatives_rule or ALTERNATIVES_RULE)
        if self.open_ended:
            rules.append("Also list in `other` any OTHER condition or parameter that could affect the outcome but "
                         "has no parameter above" + (f" -- {self.open_ended_hint}" if self.open_ended_hint else "")
                         + ". Each: `nm` a short noun phrase naming it (the same name each time it recurs), "
                         + (f"`cat` its category -- {_category_listing()} -- " if _category_listing() else "")
                         + "`v` the value as stated with its unit, in its category's format, `set` (and "
                         "`sample`) only if it applies to one set (sample), `q`, `src`, `c`. A value with "
                         "several quantities (a tube's volume, diameter and length) is one entry per quantity. "
                         "Leave `other` empty if there's nothing else.")
        if self.table_images:
            rules.append("TABLES IN 'TABLE GRIDS' (marked '=== TABLE GRID' in or after the paper text; the app has already "
                         "read their cells "
                         "-- r = row number, [n] = column number): you MUST answer for them with a mapping in "
                         "`grids` and NOT copy their values into `rows`. Map: `grid` the "
                         "id; parameters in COLUMNS: `cols` each grid column [n] holding a parameter (`c` its number, "
                         "`col` the parameter, `u` the unit printed in its header"
                         + (", `part` 'err' / 'err_plus' / 'err_minus' for a column of uncertainties" if
                            self.has_uncertainties else "")
                         + ") and `rows` each grid row r holding a set's or sample's values (`r`, `set`"
                         + (", `sample`" if self.per == "sample" else "") + "); OR parameters in ROWS (a parameter "
                         "table: one row per parameter, one column per object or solution): `prows` each grid row "
                         "holding a parameter (`r`, `col`, `u` the unit printed in the row's label"
                         + (", `part`" if self.has_uncertainties else "") + ") and `scols` each grid column holding "
                         "a set's or sample's values (`c`, `set`" + (", `sample`" if self.per == "sample" else "")
                         + "). The app reads every mapped cell "
                         "(value, uncertainties, limits, ranges). A column can be listed twice for two parameters "
                         "(the reaction temperature as initial AND sampled temperature). Never map header rows. "
                         "Values a grid doesn't hold, cells marked 'not readable', or a cell that clearly differs "
                         "from the table image go in `rows` as usual.")
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

    # column names of a parameter's modes and other estimates
    def mode_col(self, param: str, n: int, part: str = "") -> str:
        return f"{param}{self.suffix_separator}mode{n}" + (f"{self.suffix_separator}desc" if part == "desc" else part)

    def alt_col(self, param: str, n: int, part: str = "") -> str:
        return f"{param}{self.suffix_separator}alt{n}" + (f"{self.suffix_separator}method" if part == "method" else part)

    def modal_flag_col(self, param: str) -> str:
        return f"{param}{self.suffix_separator}modal_flag"

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
                    out += [self.modal_flag_col(p.column)] + [
                        c for n in range(1, MAX_MODES + 1) for c in
                        [self.mode_col(p.column, n)] + [self.mode_col(p.column, n, s) for s in
                                                        (p.uncertainties and self.suffixes_for(p)[:2] or [])]
                        + [self.mode_col(p.column, n, "desc")]]
        if self.alternatives:
            for p in self.parameters:
                if p.kind == "number":
                    out += [c for n in range(1, MAX_MODES + 1) for c in
                            [self.alt_col(p.column, n)] + [self.alt_col(p.column, n, s) for s in
                                                           (p.uncertainties and self.suffixes_for(p) or [])]
                            + [self.alt_col(p.column, n, "method")]]
        return out

    # ---- when it runs, and which sets it concerns ---------------------------------

    def _set_matches(self, s) -> bool:
        t = self.trigger
        described = f"{s.set_label} {s.varying_condition_summary or ''}"
        return (s.set_type in t.set_types
                or any(getattr(x, f, None) is not None for x in s.samples for f in t.sample_fields)
                or any(re.search(p, described, re.IGNORECASE) for p in t.set_patterns))

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
        categories = ()
        if self.open_ended:
            from parameter_extractor.variable_categories import assignable
            categories = tuple(c.id for c in assignable())
        return _models(self.model_dump_json(), categories)

    def prompt(self, structure: StructurePlan, paper_text: str) -> str:
        from parameter_extractor.stages.prompt_loader import load_prompt
        listing = "\n".join(f"- `{p.column}`" + (f" ({p.unit})" if p.unit else "") + f": {p.description}"
                            + (f" One of: {', '.join(p.choices)}." if p.choices else "")
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


ALTERNATIVES_RULE = (
    "If the paper gives SEVERAL estimates of one parameter for the same object from different "
    "methods (e.g. a rotation period from v sin i, from an activity-rotation relation and from "
    "a GP fit; a stellar mass from isochrones and from asteroseismology), give each: the one "
    "the paper adopts (its tables) without `meth`, every other one as its own entry with "
    "`meth` naming the method as the paper does, e.g. 'activity-rotation relation "
    "(Mamajek & Hillenbrand 2008)'. Limits ('> 13 d') count as estimates. Different fits of "
    "a planet are separate rows, not methods.")


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
    _grid_items: list = PrivateAttr(default_factory=list)      # values read from TABLE GRIDS (fill_grids)
    _grid_problems: list = PrivateAttr(default_factory=list)

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
        if isinstance(data.get("grids"), list):           # a grid map naming an unknown parameter: that entry only
            data["grids"] = [dict(g, **{k: [e for e in g[k] if known(e)] for k in ("cols", "prows", "columns",
                                                                                 "param_rows")
                                        if isinstance(g.get(k), list)})
                             if isinstance(g, dict) else g for g in data["grids"]]
        return data

    @property
    def parameters(self) -> list:
        out = list(self.legacy_parameters)
        for row in self.rows:
            labels = {"set_label": row.set_label}
            if "sample_label" in type(row).model_fields:
                labels["sample_label"] = row.sample_label
            out += [v.model_copy(update=labels) for v in row.values]
        return out + list(self._grid_items)


@lru_cache(maxsize=None)
def _models(spec_json: str, categories: Tuple[str, ...] = ()) -> Tuple[type, type]:
    """(item model, result model) for a spec -- the same classes for the same spec (and the active
    pack's new-variable categories, for an open-ended stage's `other` items)."""
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
        high=(float, Field(default=0.0, alias="hi", description="Only for a value printed as a range ('5-6 mg'): "
                                                              "its upper end (v = the lower end, same unit).")),
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
    class _OtherBase(BaseModel):
        model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(
            ["nm", "cat", "v", "q", "src", "c"] if categories else ["nm", "v", "q", "src", "c"]))

        @model_validator(mode="before")
        @classmethod
        def _value_as_text(cls, data):
            """An item written like a parameter value -- `v` a number with `u` its unit, or `txt` the text
            (Haiku, kim2017, 2026-11-03: the whole step failed validation twice) -- read as the one string
            an `other` value is: '0.3 mL', or the text."""
            if not isinstance(data, dict):
                return data
            data = dict(data)
            key = "v" if "v" in data else "value"
            text, unit = data.pop("txt", None), data.pop("u", None)
            if text:
                data[key] = text
            elif isinstance(data.get(key), (int, float)) and not isinstance(data.get(key), bool):
                if data[key] == 0 and not unit:          # a placeholder 0: the quote says what it is
                    data[key] = data.get("q") or data.get("quote") or ""
                else:
                    data[key] = f"{data[key]:g} {unit}".strip() if unit else f"{data[key]:g}"
            return data

    Other = create_model(
        f"{name}Other",
        __base__=_OtherBase,
        name=(str, Field(alias="nm", description="Short noun phrase naming the quantity or property, e.g. "
                                                 "'stirring rate', 'reaction volume' -- not a sentence.")),
        **({"category": (Literal[categories], Field(default="", alias="cat",   # "" = recorded before categories
                                                    description="Its category (see the rules); the value follows "
                                                                "that category's format.",
                                                    json_schema_extra=lambda schema: schema.pop("default", None)))}
           if categories else {"category": (SkipJsonSchema[str], "")}),
        value=(str, Field(alias="v", description="As stated, with its unit, e.g. '300 rpm', '254 nm'.")),
        set_label=(str, Field(default="", alias="set", description="Exact set_label if for one set only.")),
        sample_label=(str, Field(default="", alias="sample", description="Exact sample_label if for one sample.")),
        quote=(str, Field(alias="q", description=QUOTE_DESC)),
        source=(str, Field(alias="src", description=SOURCE_DESC)),
        confidence=(Literal["high", "medium", "low"], Field(alias="c")),
    )
    other_field = {"other": (List[Other], Field(default_factory=list, description=(
        "Other conditions that have no parameter of their own."))) } if spec.open_ended else {}
    grid_field = {}
    if spec.table_images:
        # a table the app read itself (TABLE GRIDS, ingestion/table_grid.py): which grid column holds which
        # parameter and which grid row is which set / sample -- the app reads the cells (fill_grids)
        parts = ["value", "err", "err_plus", "err_minus"] if spec.has_uncertainties else ["value"]
        GridCol = create_model(
            f"{name}GridCol",
            __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(["c", "col", "u"])),
            column=(int, Field(alias="c", description="The grid column number [n].")),
            parameter=(Literal[tuple(spec.columns)], Field(alias="col", description="The parameter it holds.")),
            unit=(str, Field(default="", alias="u", description="The unit printed in the column's header (or '' "
                                                               "if the cells carry their unit).")),
            part=(Literal[tuple(parts)], Field(default="value", alias="part", description=(
                "'value' (the default: the cells hold the values, with any uncertainties in the same cell)"
                + ("; 'err' for a column of symmetric uncertainties (±) of the parameter, 'err_plus' / 'err_minus' "
                   "for separate upper / lower uncertainty columns" if spec.has_uncertainties else "") + "."))),
        )
        grid_sample = {} if spec.per == "set" else {"sample_label": (str, Field(default="", alias="sample",
                                                                                  description="Exact sample_label."))}
        GridRow = create_model(
            f"{name}GridRow",
            __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(["r", "set"])),
            row=(int, Field(alias="r", description="The grid row number r.")),
            set_label=(str, Field(alias="set", description="Exact structure-plan set_label of this row.")),
            **grid_sample,
        )
        # the same, transposed (parameter tables: one row per parameter, one column per object / solution)
        ParamRow = create_model(
            f"{name}GridParamRow",
            __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(["r", "col", "u"])),
            row=(int, Field(alias="r", description="The grid row number r.")),
            parameter=(Literal[tuple(spec.columns)], Field(alias="col", description="The parameter it holds.")),
            unit=(str, Field(default="", alias="u", description="The unit printed in the row's label (or '').")),
            part=(Literal[tuple(parts)], Field(default="value", alias="part", description="As for a column.")),
        )
        SampleCol = create_model(
            f"{name}GridSampleCol",
            __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(["c", "set"])),
            column=(int, Field(alias="c", description="The grid column number [n].")),
            set_label=(str, Field(alias="set", description="Exact structure-plan set_label of this column.")),
            **grid_sample,
        )
        GridMap = create_model(
            f"{name}GridMap",
            __config__=ConfigDict(populate_by_name=True, json_schema_extra=_required(["grid"])),
            grid=(str, Field(alias="grid", description="The grid id, e.g. 'G1'.")),
            columns=(List[GridCol], Field(default_factory=list, alias="cols",
                                          description="Parameters in columns: each grid column holding a parameter.")),
            rows=(List[GridRow], Field(default_factory=list, alias="rows",
                                       description="...with each grid row holding a set's / sample's values.")),
            param_rows=(List[ParamRow], Field(default_factory=list, alias="prows",
                                              description="OR parameters in rows (a parameter table): each grid row "
                                                          "holding a parameter...")),
            sample_cols=(List[SampleCol], Field(default_factory=list, alias="scols",
                                                description="...with each grid column holding a set's / sample's "
                                                            "values.")),
            confidence=(Literal["high", "medium", "low"], Field(default="high", alias="c")),
        )
        grid_field = {"grids": (List[GridMap], Field(default_factory=list, description=(
            "Tables in TABLE GRIDS: map their columns and rows here instead of copying the values into `rows`.")))}
    Result = create_model(
        name,
        __base__=_CompactResult,
        **other_field,
        **grid_field,
        rows=(List[Row], Field(default_factory=list, description="Values grouped by set (and sample): one entry per "
                                                                 "set/sample with values. Only values the paper "
                                                                 "states.")),
        notes=(str, Field(default="", description="Anything that didn't fit, briefly.")),
        legacy_parameters=(SkipJsonSchema[List[Item]], Field(default_factory=list, validation_alias="parameters")),
    )
    Result._columns = frozenset(spec.columns)
    return Item, Result


def _category_listing() -> str:
    from parameter_extractor.variable_categories import prompt_listing
    return prompt_listing()


def load_specs(pack=None) -> Dict[str, StageSpec]:
    """A domain pack's stage specs (its stages/*.json; default the active pack), by name, in file order."""
    from parameter_extractor.packs import current
    return _specs_in((pack or current()).stages_dir)


@lru_cache(maxsize=None)
def _specs_in(folder: Path) -> Dict[str, StageSpec]:
    specs = {}
    for path in sorted(Path(folder).glob("*.json")):
        spec = StageSpec.model_validate_json(path.read_text())
        specs[spec.name] = spec
    return specs


def spec_standard_columns(pack=None) -> List[Tuple[str, str]]:
    """(column, description) of every spec parameter, in spec order -- the registry adds
    the ones that aren't template columns to its standard columns."""
    out = []
    for spec in load_specs(pack).values():
        for column in spec.output_columns():
            out.append((column, spec.label))
    return out


# an answer that reports its own failure ("Extraction failed" in its notes, aa57186-25: 4 values
# instead of 21) is valid JSON, so api_client's retry doesn't see it
GAVE_UP = re.compile(r"\b(extraction failed|failed to extract|unable to (?:extract|complete)|could not "
                     r"(?:extract|complete))\b", re.IGNORECASE)


def fill_grids(spec: StageSpec, result, grids) -> List[str]:
    """Values of the tables the model mapped onto TABLE GRIDS (`result.grids`), read from the cells by the app
    (ingestion/table_grid.py): one item per mapped value cell, like the items the model writes -- uncertainties,
    limits and ranges read from the cell (or from mapped uncertainty columns / rows), the quote the row's label and
    the cell, the source the table, row and column. A map has parameters in columns (`cols` x `rows`) or, for a
    parameter table, in rows (`prows` x `scols`). Returns problems (unknown grid, unreadable cells), also kept on the
    result."""
    from parameter_extractor.ingestion.table_grid import cell_value
    maps = getattr(result, "grids", None) or []
    if not maps:
        return []
    Item, _ = spec.models()
    by_id = {g.grid_id: g for g in grids or []}
    params = {p.column: p for p in spec.parameters}
    items, problems = [], []
    for m in maps:
        grid = by_id.get(m.grid)
        if grid is None:
            problems.append(f"{spec.label}: the answer mapped {m.grid}, which isn't one of the table grids -- "
                            f"its values were not read")
            continue
        # (row, column, parameter entry, set/sample entry, uncertainty cells of that parameter) per value cell
        cells = []
        for row in m.rows:
            for col in [c for c in m.columns if c.part == "value"]:
                errs = [(row.row, e.column, e.part) for e in m.columns
                        if e.parameter == col.parameter and e.part != "value"]
                cells.append((row.row, col.column, col, row, errs))
        for scol in m.sample_cols:
            for prow in [p for p in m.param_rows if p.part == "value"]:
                errs = [(e.row, scol.column, e.part) for e in m.param_rows
                        if e.parameter == prow.parameter and e.part != "value"]
                cells.append((prow.row, scol.column, prow, scol, errs))
        first = min([r for r, *_ in cells] or [0])
        for r, c, param, target, errs in cells:
            raw = grid.cell(r, c)
            if not raw.strip() or raw.strip() in ("-", "–", "—", "...", "…", "$\\cdots$"):
                continue
            label = grid.cell(r, 0)
            header = grid.header(c, first) or f"column {c}"
            fields = dict(parameter=param.parameter, unit=param.unit, quote=f"{label} {raw}".strip()[:200],
                          source=f"{grid.table_id}, row {label or r}, column {header}",
                          confidence=m.confidence, set_label=target.set_label,
                          sample_label=getattr(target, "sample_label", "") or "")
            p = params.get(param.parameter)
            cv = cell_value(raw)
            if p is not None and p.kind == "text":
                fields.update(value=0.0, text=raw.strip())
            elif cv.value is None:
                problems.append(f"{spec.label}: {grid.table_id} row {label or r}, {param.parameter} = '{raw}' isn't "
                                f"a number -- not read")
                continue
            else:
                fields.update(value=cv.value, high=cv.high)
                if cv.unit and not param.unit:
                    fields["unit"] = cv.unit
                ep, em = cv.err_plus, cv.err_minus
                for er, ec, part in errs:
                    ev = cell_value(grid.cell(er, ec))
                    if ev.value is None:
                        continue
                    if part in ("err", "err_plus"):
                        ep = abs(ev.value)
                    if part in ("err", "err_minus"):
                        em = -abs(ev.value)
                fields.update(err_plus=ep, err_minus=em, limit={1: "upper", -1: "lower"}.get(cv.limit, ""))
            items.append(Item(**{k: v for k, v in fields.items() if k in Item.model_fields}))
    result._grid_items = items
    result._grid_problems = problems
    return problems


def run_optional_stage(ctx, spec: StageSpec, paper_text: str, structure: StructurePlan,
                       table_images: Optional[List[Path]] = None, grids: Optional[list] = None):
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
    fill_grids(spec, result, grids)       # tables mapped onto the app's grids: cells read here
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
    param = next((p for p in spec.parameters if p.column == item.parameter), None)
    if param is None:                           # not (or no longer) one of the stage's parameters
        return {}, [f"{spec.label}: '{item.parameter}' isn't one of this stage's parameters -- left out."]
    printed = getattr(item, "unit", "") or ""
    base = dict(basis=item.basis, quote=item.quote, source=item.source, confidence=item.confidence)
    if param.kind == "text":
        text = (getattr(item, "text", "") or "").strip()
        if text and param.choices:
            match = next((c for c in param.choices if c.lower() == text.lower()), None)
            if match is None:
                return {}, [f"{spec.label}: {param.column} '{text}' for '{item.set_label or 'every set'}' left out "
                            f"-- it must be one of {', '.join(param.choices)}."]
            text = match
        return ({param.column: StageValue(text, note=item.note, **base)} if text else {}), []
    from parameter_extractor.units import convert_printed
    high = getattr(item, "high", 0.0) or 0.0
    if high and high > item.value:     # a range: '<column>_range<unit>' = 'low:high' (Mickey, 2026-10-31)
        from parameter_extractor.ingestion.flatten_to_template import with_range
        from parameter_extractor.units import format_range
        lo, lo_note = convert_printed(item.value, printed, param.unit)
        hi, _ = convert_printed(high, printed, param.unit)
        if lo is None or hi is None:
            return {}, [f"{spec.label}: {param.column} = {item.value:g}-{high:g} {printed} for "
                        f"'{item.set_label}' left out -- {lo_note}."]
        note = "; ".join(n for n in (item.note, f"range printed as {item.value:g}-{high:g} {printed}".strip()) if n)
        return {with_range(param.column): StageValue(format_range(lo, hi), note=note, **base)}, []
    if param.integer and not item.value and (getattr(item, "text", "") or "").strip():
        # a count written out ('triplicate experiments; lengths averaged'): read as the number
        from parameter_extractor.value_types import whole_number
        n = whole_number(item.text)
        if n is None:
            return {}, [f"{spec.label}: {param.column} '{item.text}' for '{item.set_label or 'every set'}' left out "
                        f"-- it must be a whole number."]
        return {param.column: StageValue(n, note="; ".join(x for x in (item.note, f"read from '{item.text}'") if x),
                                         **base)}, []
    value, note = convert_printed(item.value, printed, param.unit)
    if value is None:
        return {}, [f"{spec.label}: {param.column} = {item.value:g} {printed} for '{item.set_label}' left out -- {note}."]
    notes = "; ".join(n for n in (item.note, note) if n)
    if param.integer:
        if not float(value).is_integer():
            return {}, [f"{spec.label}: {param.column} = {value:g} for '{item.set_label or 'every set'}' left out "
                        f"-- it must be a whole number."]
        value = int(value)
    out = {param.column: StageValue(value, note=notes, **base)}
    system = time_system(printed) if spec.time_system_column else ""
    if system:                         # 'JD-2450000' printed: the epochs are on the JD time system
        out[spec.time_system_column] = StageValue(system, note=f"from the unit printed for {param.column}",
                                                  **dict(base, basis="derived"))
    if param.uncertainties:
        suffixes = spec.suffixes_for(param)
        cols = [param.column + s for s in suffixes]
        for col, err in zip(cols[:2], (getattr(item, "err_plus", 0.0), getattr(item, "err_minus", 0.0))):
            if err:
                converted, _ = convert_printed(err, printed, param.unit, is_error=True, about=item.value)
                if converted is not None:
                    out[col] = StageValue(converted, **base)
        if len(cols) > 2:                       # limit flag: 1 upper limit, -1 lower limit, 0 a measurement
            out[cols[2]] = StageValue({"upper": 1, "lower": -1}.get(getattr(item, "limit", ""), 0), **base)
    return out, []


def time_system(printed: str) -> str:
    """'JD-2450000' -> 'JD', 'BJD_TDB - 2,450,000' -> 'BJD_TDB'; '' when it isn't a Julian date."""
    from parameter_extractor.units import _JD_OFFSET, _JD_PLAIN
    p = (printed or "").strip()
    if not (_JD_OFFSET.match(p) or _JD_PLAIN.match(p)):
        return ""
    return re.split(r"\s*[-−–]\s*[\d,]+$", p)[0].strip()


MAX_MODES = 3


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
        out[(label, sample, spec.modal_flag_col(param))] = StageValue(1, first.basis, first.quote, first.source,
                                                                      first.confidence, "bi-/multimodal posterior")
        for n, (mode, columns) in enumerate(seen[:MAX_MODES], start=1):
            main = columns[param]
            out[(label, sample, spec.mode_col(param, n))] = main
            for s in suffixes:
                if param + s in columns:
                    out[(label, sample, spec.mode_col(param, n, s))] = columns[param + s]
            out[(label, sample, spec.mode_col(param, n, "desc"))] = StageValue(mode, main.basis, main.quote, main.source,
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
            out[(label, sample, spec.alt_col(param, n))] = value
            for s in suffixes:
                if param + s in columns:
                    out[(label, sample, spec.alt_col(param, n, s))] = columns[param + s]
            out[(label, sample, spec.alt_col(param, n, "method"))] = StageValue(method, value.basis, value.quote,
                                                                      value.source, value.confidence)
    return out


def optional_results(optional=None, wet_dry=None) -> List[Tuple[StageSpec, object]]:
    """[(spec, result)] from either the list form or a bare wet-dry result (older callers)."""
    out = [(spec, result) for spec, result in (optional or []) if result is not None]
    if wet_dry is not None and not any(spec.name == "wet_dry" for spec, _ in out):
        out.append((load_specs()["wet_dry"], wet_dry))
    return out


def triggered_specs(structure: StructurePlan, paper_text: str,
                    choices: Optional[Dict[str, str]] = None, suggest: bool = True,
                    running: Optional[set] = None) -> List[StageSpec]:
    """The stages to run: triggered ones, unless the user turned them off ('off'), plus
    any forced on ('on'). `suggest` False: without their open-ended part (see for_run). `running`: the
    other steps this run makes (for hint_by_stage)."""
    choices = choices or {}
    out = []
    for name, spec in load_specs().items():
        choice = choices.get(name, "auto")
        if choice == "on" or (choice == "auto" and spec.triggered(structure, paper_text)):
            out.append(for_run(spec, suggest, running))
    return out


def for_run(spec: StageSpec, suggest: bool = True, running: Optional[set] = None) -> StageSpec:
    """The spec as a run uses it: with new-variable suggestions off (RunConfig.suggest_new_variables),
    an open-ended stage doesn't ask for `other` conditions; hint_by_stage's wording for the steps that run."""
    update = {}
    if not suggest and spec.open_ended:
        update["open_ended"] = False
    if spec.hint_by_stage:
        extra = [texts.get("runs" if stage in (running or set()) else "off", "")
                 for stage, texts in spec.hint_by_stage.items()]
        update["open_ended_hint"] = "; ".join(x for x in [spec.open_ended_hint.rstrip(" .;")] + extra if x)
        update["hint_by_stage"] = {}
    return spec.model_copy(update=update) if update else spec


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
    from parameter_extractor.stages import analysis, fit_models
    return {"fit_models": (fit_models.LABEL, fit_models.DESCRIPTION),
            "analysis": (analysis.LABEL, analysis.DESCRIPTION)}


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
