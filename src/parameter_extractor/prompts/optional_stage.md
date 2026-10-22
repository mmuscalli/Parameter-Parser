{{INTRO}}

Parameters (give each value in the unit shown):

{{PARAMETER_LIST}}

Answer format: `rows` -- one entry per set (and sample) that has values:
`set` (the set_label), {{SAMPLE_KEY}}and its `values`. Each value: `col` the
parameter, `v` the value, `u` the unit as printed, `q` the quote, `src`
where it is, `c` your confidence; and ONLY when they apply (leave them out
otherwise): `ep` / `em` upper / lower uncertainty, `lim` limit, `txt` text,
`mode`, `meth` method, `b` basis, `n` a short note.

Rules:
- Only values the paper states, or that follow arithmetically from stated
  values (`b` "derived"; say how in `n`). Every `q` is the paper's own
  words, copied exactly -- never your explanation. Never assume a typical
  value, and treat the paper's own hedges ("probably", "perhaps", "not
  documented") as NOT stated. Leave out anything not given; if you include
  an interpretation the paper doesn't state outright, set `b` "assumed" --
  it will be shown to the user instead of written automatically.
- Give each `v` as printed, with the unit it's printed in as `u` -- '' only
  if it's printed in exactly the parameter's unit. A dimensionless value
  printed as a fraction or in ppm is `u` "fraction" / "ppm" when the
  parameter wants %. The app converts (minutes -> hours, rad -> deg,
  JD-2450000 -> JD, fraction -> %, ...). Don't convert values yourself.
- `n` is at most 15 words of your own -- never a place to repeat the value,
  its method or its mode.
- Keep every `q` to the shortest span that shows the value (at most 20
  words; for a table: row label, column label, value) and make `src` exact
  (table + row + column, or section + paragraph), so a reader can find the
  full context.
- Give `set` exactly as the structure plan's set_label; use '' only when
  values apply to every {{SET_WORD}} set. If a value differs between sets,
  give it in each set's row.
{{EXTRA_RULES}}
Return a {{SCHEMA_NAME}} object.

---
STRUCTURE PLAN:

{{STRUCTURE_PLAN_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
