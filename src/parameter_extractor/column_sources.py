"""
What fills each of a data pack's columns (Mickey, 2026-11-19: the Columns tab's "Filled by" named only the pack's own
configurable steps, so most columns read "not filled by a step" although a built-in step, the row plan, a calculation
or the archive fills them -- "make 'Filled by' name the real source; only the truly empty ones 'nothing fills this
automatically'").

A column's sources, in this order: the pack's own configurable steps (as edited, saved or not) and its modules'
(each with its uncertainty, limit, mode and other-estimate columns: `StageSpec.output_columns`); the built-in steps
the pack uses (compounds, analysis, fitting models -- by the columns' naming rules); the app's paper-details step and
row plan; the pack's calculations and formulas; the app's row identifiers. Nothing found: nothing fills it
automatically (a reviewer's correction, a digitized figure or a step's 'other values' answer still can).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

COMPOUND = re.compile(r"^(initial|sampled|stock|calculated)_.+_(aq|s|gas|g|l)_|^added_.+_volume_")
METADATA = {"paper_title", "author_list", "year_published", "journal_published", "paper_DOI"}
ROW_PLAN = {"set_type", "duration_hr", "duration_hr_high", "run", "data_location", "original_data_reference",
            "result_type"}
IDENTIFIERS = {"full_id", "set_id", "sample_id", "entry_number"}
FIT_MODELS = re.compile(r"^(pl|st|sy)_fit")
# calculation -> the columns it writes (by name or pattern); calculators/ and pipeline.finish
CALCULATED = {
    "peptide_totals": re.compile(r"^total_sampled_peptides_yield$"),
    "oligomer_totals": re.compile(r"^(total_sampled_oligomers_yield|max_oligomer_length_nt)$"),
    "result_basis": re.compile(r"^result_basis$"),
    "row_labels": re.compile(r"^(pl_name|hostname|pl_letter|pl_fitlabel)$"),
    "exoplanet_masses": re.compile(r"^pl_(masse|msinie|rade|bmasse|bmassj|bmassprov)(err1|err2|lim)?$"),
    "reference_names": re.compile(r"^(pl|st|disc)_refname$"),
}
ALWAYS_CALCULATED = {"set_independent_variable": "calculated: what its set varies",
                     "set_independent_value": "calculated: what its set varies"}


def _builtin_label(step: str) -> str:
    from parameter_extractor import step_info
    return step_info.DOCS.get(step, {}).get("label", step)


def sources(draft) -> Dict[str, List[str]]:
    """{column: [what fills it, in words]} for every column of `draft` (PackDraft, as edited) and its steps."""
    from parameter_extractor.stages.optional import StageSpec
    out: Dict[str, List[str]] = {}

    def add(column: str, what: str) -> None:
        if what not in out.setdefault(column, []):
            out[column].append(what)
    own = set()
    for raw in draft.stages.values():                    # the pack's own steps, as edited
        try:
            spec = StageSpec.model_validate(raw)
        except Exception:                                # noqa: BLE001 -- a step being written: its plain columns
            for p in raw.get("parameters", []):
                if p.get("column"):
                    add(p["column"], raw.get("label") or raw.get("name", "?"))
            continue
        own.add(spec.name)
        for column in spec.output_columns():
            add(column, spec.label)
    try:                                                 # the linked modules' steps, as this pack sets them
        for mod, spec in draft.module_specs():
            for column in spec.output_columns():
                add(column, f"{spec.label} ({mod.label} module)")
    except Exception:                                    # noqa: BLE001 -- a module that can't load: the rest
        pass
    steps = set(draft.effective_steps())
    calcs = set(draft.effective_calculations())
    formulas = {f.get("column"): f.get("expression", "") for f in draft.manifest.get("formulas", []) if f.get("column")}
    row_values = {}                                      # the modules' row values (sample_time's duration_hr)
    try:
        for mod in draft.linked_modules():
            for f in getattr(mod.manifest, "formulas", []):
                formulas.setdefault(f.get("column"), f.get("expression", ""))       # the pack's own formula wins
            for v in getattr(mod.manifest, "row_values", []):
                row_values[v["column"]] = mod.label
    except Exception:                                    # noqa: BLE001 -- a module that can't load: the pack's own
        pass
    archive = None
    if "archive_values" in calcs:
        from parameter_extractor.validation import exoplanet_archive as archive
    for column in set(draft.columns) | set(out) | set(row_values) | set(formulas):
        if "chemistry" in steps and COMPOUND.match(column):
            add(column, _builtin_label("chemistry") + " (built-in)")
        if "analysis" in steps and column.startswith("analysis_"):
            add(column, _builtin_label("analysis") + " (built-in)")
        if "fit_models" in steps and FIT_MODELS.match(column):
            add(column, _builtin_label("fit_models") + " (built-in)")
        if column in METADATA:
            add(column, "the paper's details (Paper details module, core)")
        if column in row_values:
            add(column, f"the row plan ({row_values[column]} module)")
        elif column in ROW_PLAN:
            add(column, "the row plan (Rows module, core)")
        if column in IDENTIFIERS:
            add(column, "row identifier (Rows module, core)")
        if column in ALWAYS_CALCULATED:
            add(column, ALWAYS_CALCULATED[column])
        for calc, pattern in CALCULATED.items():
            if calc in calcs and pattern.match(column):
                add(column, f"calculated: {calc.replace('_', ' ')}")
        if archive is not None and archive.fillable(column) and not out.get(column):
            add(column, "the NASA Exoplanet Archive (online)")
        if column in formulas:
            add(column, f"formula: {formulas[column]}")
    return out


NOTHING = "nothing fills this automatically"


def filled_by(column: str, found: Dict[str, List[str]]) -> Optional[str]:
    """The 'Filled by' text: its sources, or None when nothing fills it."""
    return ", ".join(found.get(column, [])) or None
