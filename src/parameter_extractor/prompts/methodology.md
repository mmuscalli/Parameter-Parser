Extract the experimental methodology parameters below. For EVERY field, you
must set `status` appropriately:

- "found" -- the paper states it; include a short supporting `quote` and
  `source` (section/table name).
- "not_reported" -- the paper never states this; do not guess a typical/
  default value (e.g. don't assume 1 atm pressure just because none is given).
- "below_threshold" -- paper gives a qualitative bound instead of a number
  (e.g. "yields below 0.15% were not listed"); put the bound in `note`.
- "ambiguous" -- found, but required a judgment call (e.g. inferring vessel
  material from a device model name); explain the judgment in `note`.
- "conflicting" -- the paper states this more than once with different
  values; give both in `note`.

Fields to extract:
- experiment_type: "Batch" or "Flowthrough" (POLO's controlled vocabulary --
  do not invent other values). Infer from the description of the experimental
  setup (e.g. sealed/closed vessels heated in place = Batch; continuous fluid
  flow through a stationary phase = Flowthrough).
- solution_type: "Wet" or "Dry".
- vessel_material, solvent_name, analysis_method, headspace_gas.
- initial_pressure_bar, initial_temperature_C, sampled_temperature_C,
  initial_pH.

If a field's value differs by experiment set (e.g. several sets at slightly
different temperatures) rather than being constant across the whole paper,
set it "ambiguous" at the top level with a note pointing to
`per_set_overrides`, and add one `per_set_overrides` entry per (set, field),
using the exact `set_label` strings from the structure plan below.

Return a Methodology object.

---
STRUCTURE PLAN (for set_label reference):

{{STRUCTURE_PLAN_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
