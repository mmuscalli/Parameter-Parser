"""
Recorded answers of the old built-in methodology step (Methodology) as answers of
the prebiotic pack's `experimental_conditions` stage (2026-10-22), so reference
runs recorded before the change still replay through the current pipeline
(tests/test_pipeline_offline.make_replay). Paper-wide fields -> values for every
set ('' set_label), per-set overrides -> per-set values, other_parameters ->
`other`. Field names follow flatten_to_template._METHOD_COLUMNS.
"""
from __future__ import annotations

TEXT_FIELDS = {"experiment_type", "solution_type", "vessel_material", "solvent_name", "analysis_method",
               "headspace_gas"}
FIELD_TO_COLUMN = {"experiment_type": "experiment_type", "solution_type": "solution_type",
                   "vessel_material": "vessel_material", "solvent_name": "solvent_name",
                   "analysis_method": "analysis_method", "headspace_gas": "headspace_gas_name",
                   "initial_pressure_bar": "initial_pressure_bar", "initial_temperature_C": "initial_temperature_C",
                   "sampled_temperature_C": "sampled_temperature_C", "initial_pH": "initial_pH"}


def conditions_from_methodology(methodology: dict) -> dict:
    """A Methodology answer (dict, long field names) as an experimental-conditions answer in the
    flat recorded format ({"parameters": [...], "other": [...], "notes": ""})."""
    items = []
    for field, column in FIELD_TO_COLUMN.items():
        f = methodology.get(field) or {}
        value = f.get("value")
        if value in (None, ""):
            continue
        text = field in TEXT_FIELDS
        items.append({"set_label": "", "sample_label": "", "parameter": column,
                      "value": 0.0 if text else float(value), "text": str(value) if text else "",
                      "basis": "stated", "quote": f.get("quote") or "", "source": f.get("source") or "",
                      "confidence": f.get("confidence") or "low", "note": f.get("note") or ""})
    for o in methodology.get("per_set_overrides") or []:
        items.append({"set_label": o["set_label"], "sample_label": "",
                      "parameter": FIELD_TO_COLUMN.get(o["field_name"], o["field_name"]),
                      "value": float(o["value"]), "basis": o.get("basis", "stated"), "quote": o.get("quote", ""),
                      "source": o.get("source", ""), "confidence": o.get("confidence", "high"), "note": o.get("note", "")})
    other = [{"name": p["name"], "value": p["value"], "set_label": p.get("set_label") or "", "sample_label": "",
              "quote": p.get("quote", ""), "source": p.get("source", ""), "confidence": p.get("confidence", "low")}
             for p in methodology.get("other_parameters") or []]
    return {"parameters": items, "other": other, "notes": ""}
