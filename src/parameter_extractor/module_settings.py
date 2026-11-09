"""
Module settings: a data pack's own changes to the modules it links (Mickey, 2026-11-09).

A module stays ONE shared thing, linked by reference (modules/__init__.py); what a pack may change is a small set of
settings, kept in its pack.json and applied when the pack loads -- never a copy of the module:

  "module_settings": {
    "<module id>": {
      "steps":       {"<step name>": {"off": true, "keywords": [...], "table_images": false,
                                      "rules_off": ["<rule text>"], "extra_rules": ["..."]}},
      "parameters":  {"<module's column>": {"off": true, "unit": "min", "description": "..."}},
      "calculations_off": ["oligomer_totals"],
      "row_rules_off":    ["<rule text>"],         # rules the module adds to the row planning
      "stage_rules_off":  ["<rule text>"],         # rules the module adds to the pack's own steps
      "families_off":     ["nmr"]                  # the analysis vocabulary's instrument families
    }
  }

A parameter's unit is the unit its values are STORED in: changing it renames the column ('half_life_hr' in hours ->
'half_life_min' in minutes), since the app reads a column's unit from its name; values are converted to it as usual.
Columns the app's own calculations read by name (module.json "fixed") keep their name and unit.
Anything not mentioned is the module's default, so an improvement to the module still reaches the pack.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class StepSetting(BaseModel):
    off: bool = False
    keywords: Optional[List[str]] = None          # None = the module's trigger words
    table_images: Optional[bool] = None
    rules_off: List[str] = Field(default_factory=list)
    extra_rules: List[str] = Field(default_factory=list)


class ParameterSetting(BaseModel):
    off: bool = False
    unit: str = ""                                # '' = the module's
    description: str = ""                         # '' = the module's


class ModuleSettings(BaseModel):
    steps: Dict[str, StepSetting] = Field(default_factory=dict)
    parameters: Dict[str, ParameterSetting] = Field(default_factory=dict)
    calculations_off: List[str] = Field(default_factory=list)
    row_rules_off: List[str] = Field(default_factory=list)
    stage_rules_off: List[str] = Field(default_factory=list)
    families_off: List[str] = Field(default_factory=list)


def settings_for(module_settings: Optional[dict], module_id: str) -> ModuleSettings:
    raw = (module_settings or {}).get(module_id) or {}
    try:
        return ModuleSettings.model_validate(raw)
    except ValueError:
        return ModuleSettings()                   # a broken entry: the module's defaults (the check reports it)


def cleaned(settings: ModuleSettings) -> dict:
    """The settings as stored: only what differs from the module's defaults (empty -> {})."""
    out: dict = {}
    steps = {}
    for name, s in settings.steps.items():
        d = {k: v for k, v in s.model_dump().items()
             if (k in ("keywords", "table_images") and v is not None) or (k not in ("keywords", "table_images") and v)}
        if d:
            steps[name] = d
    if steps:
        out["steps"] = steps
    params = {c: {k: v for k, v in p.model_dump().items() if v} for c, p in settings.parameters.items()}
    params = {c: p for c, p in params.items() if p}
    if params:
        out["parameters"] = params
    for key in ("calculations_off", "row_rules_off", "stage_rules_off", "families_off"):
        if getattr(settings, key):
            out[key] = list(getattr(settings, key))
    return out


# ---- units ------------------------------------------------------------------------------------------------------------

def base_name(column: str) -> str:
    """The column without its unit ('half_life_hr' -> 'half_life', 'activation_energy_kJ_mol' -> 'activation_energy')."""
    from parameter_extractor.ingestion.observations import unit_for_column
    parts = column.split("_")
    while len(parts) > 1 and unit_for_column("_".join(parts)):
        parts = parts[:-1]
    if len(parts) > 1 and parts[-1] == "per":
        parts = parts[:-1]
    return "_".join(parts)


def unit_choices(column: str, unit: str) -> List[Tuple[str, str]]:
    """[(unit, column)] the parameter can be stored in: units of the same kind whose column name the app reads back
    in that unit -- the module's own first. [] for text / unitless parameters."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import _UNITS, canonical_unit, unit_slug
    from parameter_extractor.variable_categories import unit_suffix
    canon = canonical_unit(unit or "") or (unit or "")
    if not canon or canon not in _UNITS:
        return []
    dimension = _UNITS[canon][0]
    base = base_name(column)
    out = [(canon, column)]
    for u, (dim, _) in _UNITS.items():
        if dim != dimension or u == canon:
            continue
        for suffix in (unit_suffix(u), "_" + unit_slug(u)):
            name = base + suffix if suffix and suffix != "_" else ""
            if not name or re.search(r"_\d|_per_\w+_per_|[^\w]", name):
                continue
            read = unit_for_column(name)
            if read == u or canonical_unit(read or "") == u:
                out.append((u, name))
                break
    return out


def column_in_unit(column: str, unit: str, new_unit: str) -> Optional[str]:
    """The column's name for values stored in `new_unit`, or None when the app can't name one."""
    from parameter_extractor.units import canonical_unit
    want = canonical_unit(new_unit or "") or new_unit
    return next((c for u, c in unit_choices(column, unit) if u == want), None)


# ---- applying the settings --------------------------------------------------------------------------------------------

def renames(module, settings: ModuleSettings) -> Dict[str, str]:
    """{module column: the pack's column} for parameters stored in another unit."""
    from parameter_extractor.stages.optional import _specs_in
    fixed = set(module.manifest.fixed)
    params = {p.column: p.unit for s in _specs_in(module.stages_dir).values() for p in s.parameters} \
        if module.stages_dir.is_dir() else {}
    params.update({p["column"]: p.get("unit", "") for p in module.manifest.pack_parameters})
    out = {}
    for col, ps in settings.parameters.items():
        if ps.unit and col in params and col not in fixed:
            new = column_in_unit(col, params[col], ps.unit)
            if new and new != col:
                out[col] = new
    return out


def _renamed_text(text: str, names: Dict[str, str]) -> str:
    for old, new in names.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def apply_to_spec(spec, settings: ModuleSettings, names: Dict[str, str]):
    """A module step as this pack runs it, or None when the pack switched it off."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import canonical_unit
    step = settings.steps.get(spec.name, StepSetting())
    if step.off:
        return None
    params = []
    for p in spec.parameters:
        ps = settings.parameters.get(p.column, ParameterSetting())
        if ps.off:
            continue
        update = {}
        if p.column in names:
            new = names[p.column]
            update.update(column=new, unit=unit_for_column(new) or canonical_unit(ps.unit) or ps.unit)
        if ps.description:
            update["description"] = ps.description
        params.append(p.model_copy(update=update) if update else p)
    if not params:
        return None
    update = {"parameters": params}
    if step.keywords is not None:
        update["trigger"] = spec.trigger.model_copy(update={"keywords": list(step.keywords)})
    if step.table_images is not None:
        update["table_images"] = step.table_images
    rules = [r for r in spec.rules if r not in step.rules_off] + list(step.extra_rules)
    if names:
        rules = [_renamed_text(r, names) for r in rules]
        update["intro"] = _renamed_text(spec.intro, names)
    update["rules"] = rules
    return spec.model_copy(update=update)


def pack_parameter(entry: dict, settings: ModuleSettings, names: Dict[str, str]) -> Optional[dict]:
    """A parameter the module adds to the pack's first always-on step, as this pack has it (None: switched off)."""
    from parameter_extractor.ingestion.observations import unit_for_column
    ps = settings.parameters.get(entry["column"], ParameterSetting())
    if ps.off:
        return None
    out = dict(entry)
    if entry["column"] in names:
        out["column"] = names[entry["column"]]
        out["unit"] = unit_for_column(out["column"]) or ps.unit
    if ps.description:
        out["description"] = ps.description
    return out


def apply_to_category_columns(category_columns: Dict[str, dict], names: Dict[str, str]) -> Dict[str, dict]:
    if not names:
        return category_columns
    return {cid: dict(entry, columns=[names.get(c, c) for c in entry.get("columns", [])])
            if entry.get("columns") else entry for cid, entry in category_columns.items()}


def is_default(settings: ModuleSettings) -> bool:
    return not cleaned(settings)


def problems(module_settings: dict, mods) -> List[Tuple[str, str]]:
    """(level, message) for settings that don't fit the modules: unknown modules / steps / parameters /
    calculations / families, units the column can't be named in, a step left without trigger words."""
    from parameter_extractor.stages.optional import _specs_in
    out = []
    by_id = {m.id: m for m in mods}
    for mid, raw in (module_settings or {}).items():
        mod = by_id.get(mid)
        if mod is None:
            out.append(("warning", f"settings for module '{mid}', which this data pack doesn't link (ignored)."))
            continue
        try:
            s = ModuleSettings.model_validate(raw or {})
        except ValueError as e:
            out.append(("error", f"{mod.label}: the settings can't be read ({e})."))
            continue
        specs = _specs_in(mod.stages_dir) if mod.stages_dir.is_dir() else {}
        params = {p.column: p.unit for sp in specs.values() for p in sp.parameters}
        params.update({p["column"]: p.get("unit", "") for p in mod.manifest.pack_parameters})
        for name, st in s.steps.items():
            if name not in specs:
                out.append(("warning", f"{mod.label}: no step '{name}' (setting ignored)."))
            elif st.keywords is not None and not st.keywords and not st.off:
                trig = specs[name].trigger
                if not (trig.always or trig.set_types or trig.set_patterns or trig.sample_fields):
                    out.append(("warning", f"{mod.label}: step '{name}' has no trigger words left, so it never runs."))
        for col, ps in s.parameters.items():
            if col not in params:
                out.append(("warning", f"{mod.label}: no parameter '{col}' (setting ignored)."))
            elif ps.unit and col in mod.manifest.fixed:
                out.append(("warning", f"{mod.label}: '{col}' keeps its unit ({mod.manifest.fixed[col]})."))
            elif ps.unit and column_in_unit(col, params[col], ps.unit) is None:
                out.append(("error", f"{mod.label}: '{col}' can't be stored in {ps.unit} (no column name the app "
                                     f"reads in that unit)."))
        for calc in s.calculations_off:
            if calc not in mod.manifest.postprocess:
                out.append(("warning", f"{mod.label}: no calculation '{calc}' (setting ignored)."))
        if s.families_off and not mod.file("analysis_vocab.json"):
            out.append(("warning", f"{mod.label}: has no instrument families (setting ignored)."))
    return out
