You are checking one research paper for a few specific parameters ONLY. Report
every value the paper gives for these parameters, and nothing else.

Parameters to look for:
{{PARAMETERS}}

{{SCOPE}}

Rows: the results are one row per {{SAMPLE_WORD}}, grouped by {{SET_WORD}} -- the
same rows a full extraction of this paper makes. Each value says which row it
belongs to: `set` the {{SET_WORD}} it belongs to, named as the paper names it
('' when the value is about the paper as a whole, e.g. the software used), and
`obj` the {{SAMPLE_WORD}} within that {{SET_WORD}} ('' when the value is the same
for the whole {{SET_WORD}}). Use the same `set` name every time for one
{{SET_WORD}}.

Answer format: `rows` -- every row of the paper's results ({{SAMPLE_WORD}}s with their
`set` and `obj`), also rows with none of the requested values, in the paper's
order; `values` -- one entry per value found: `set` and `obj` (above),
`col` the parameter, `v` the value exactly as printed (text or number,
e.g. "EXOFASTv2", "323.21"), `u` its unit as printed ('' if none), `ep` / `em`
its upper / lower uncertainty as printed (leave out if none), `q` the shortest
quote that shows it (at most 12 words, copied exactly), `src` where it is
(section, table + row), `c` your confidence. `not_found`: every parameter the
paper doesn't report.

Rules:
- Only what the paper states. Never a typical or assumed value.
- One entry per object and per distinct value: if the paper gives a
  parameter for several rows, or several fits / methods, list each one
  (name the fit or method in `obj`, e.g. "HD 1397 b [joint fit]").
- A parameter that is only mentioned as something done by OTHER work (e.g.
  "Smith et al. used EXOFAST", an introduction summarising earlier
  experiments) isn't this paper's value: leave it out.
- Values written in LaTeX: in `x_{-a}^{+b}` the superscript +b is `ep` and
  the subscript -a is `em`.
- Keep quotes short. No notes or explanations.
{{PACK_RULES}}
