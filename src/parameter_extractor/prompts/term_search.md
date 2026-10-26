The user has asked specifically for the experimental parameters listed below.
Search the paper carefully for each one -- methods, results, table captions
and footnotes, figure captions -- including where the paper uses different
wording for the same thing (e.g. "recirculation time" vs "residence time").

For EVERY search term return at least one finding:
- If the paper states it: `found` = true, the parameter as the paper names
  it, its `value` with the unit exactly as stated, a short verbatim `quote`
  and its `source`. If the value differs between experiment sets, give one
  finding per set with that set's exact `set_label` from the structure plan
  below ('' if it applies to the whole paper).
- If the paper doesn't state it: a single finding with `found` = false and
  the other text fields empty (''). Never guess or assume a typical value.

`column`: the column from the list below that this value belongs in, if one
clearly matches (e.g. a reaction volume -> 'solvent_volume_mL'); '' if none.

Return a TermSearch object.

---
SEARCH TERMS:
{{TERMS}}

---
STRUCTURE PLAN (for set_label reference):

{{STRUCTURE_PLAN_JSON}}

---
COLUMNS:

{{COLUMNS_JSON}}

{{PACK_RULES}}
---
PAPER TEXT:

{{PAPER_TEXT}}
