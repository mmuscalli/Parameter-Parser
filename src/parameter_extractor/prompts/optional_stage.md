{{INTRO}}

Parameters (give each value in the unit shown):

{{PARAMETER_LIST}}

Rules:
- Only values the paper states (`basis` "stated"), or that follow
  arithmetically from stated values (`basis` "derived"; say how in `note`).
  Every `quote` is the paper's own words, copied exactly -- never your
  explanation. Never assume a typical value, and treat the paper's own
  hedges ("probably", "perhaps", "not documented") as NOT stated. Leave out
  anything not given; if you include an interpretation the paper doesn't
  state outright, mark it `basis` "assumed" -- it will be shown to the user
  instead of written automatically.
- Give each `value` as printed, with the unit it's printed in as `unit`
  ('' if that's already the parameter's unit): the app converts it
  (minutes -> hours, rad -> deg, JD-2450000 -> JD, ...). Don't convert
  values yourself.
- Fill every field. `note` is at most 15 words of your own ('' if nothing
  to add) -- never a place to repeat the value, its method or its mode.
- Keep every `quote` to the shortest span that shows the value (at most 20 words; for a table: row label, column label, value) and make `source` exact (table + row + column, or section + paragraph), so a reader can find the full context.
- Give `set_label` exactly as in the structure plan; use '' only when a value
  applies to every {{SET_WORD}} set. If a value differs between sets, give one
  entry per set.
{{EXTRA_RULES}}
Return a {{SCHEMA_NAME}} object.

---
STRUCTURE PLAN:

{{STRUCTURE_PLAN_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
