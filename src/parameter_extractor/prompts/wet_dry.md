This paper includes wet-dry (hydration-dehydration / evaporation) cycling
experiments. For each cycling set in the structure plan below, extract the
cycle conditions the paper states:

- `cycle_duration_hr`: length of one full wet + dry cycle, in hours.
- `wet_phase_temperature_C`, `wet_phase_duration_hr`,
  `wet_phase_relative_humidity_pct`: conditions while the sample is wet,
  rehydrated or held humid (e.g. "40 C and 70% RH for 20 h").
- `dry_phase_temperature_C`, `dry_phase_duration_hr`: conditions while it
  dries / is dehydrated (e.g. "120 C for 4 h on a hot plate").

Rules:
- Only values the paper states (or that follow arithmetically from stated
  values, e.g. a 24 h cycle from 20 h + 4 h -- say so in the quote's
  context). Never assume a typical value. Leave out anything not given.
- Convert to the parameter's unit (minutes -> hours, etc.).
- Give `set_label` exactly as in the structure plan; use '' only when a value
  applies to every cycling set. If a value differs between sets, give one
  entry per set.
- If a set's cycling scheme doesn't fit these fields (e.g. phases that
  change from cycle to cycle), describe it in `notes`.

Return a WetDryConditions object.

---
STRUCTURE PLAN:

{{STRUCTURE_PLAN_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
