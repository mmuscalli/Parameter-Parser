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
- Convert to the parameter's unit (minutes -> hours, kPa -> bar, etc.).
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
