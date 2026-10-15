Extract every chemical species and its concentration mentioned as part of the
INITIAL reaction composition or as a SAMPLED/measured product, for every
experiment set in the structure plan below.

For each species:
- Use the controlled vocabulary list provided below when the compound is
  already tracked (match on the same name, e.g. "NaCl" not "sodium chloride").
  Set `in_controlled_vocab` accordingly. If a species genuinely isn't in the
  list, still extract it, set `in_controlled_vocab: false`, and add its name
  to `unmapped_species` -- never silently drop it and never silently invent a
  new column name as if it were already standard.
- Record the concentration in BOTH its original reported unit
  (`concentration_value` + `concentration_unit_raw`) and converted to mM
  (`concentration_mM`). Only fill `concentration_mM` when the conversion is
  unambiguous (e.g. mol/dm3 -> mM is a straight x1000; converting from mass/
  volume to mM requires a molecular weight -- do that only for well-known
  compounds, and otherwise leave `concentration_mM` null and explain in
  `conversion_note`).
- `role`: "initial" for starting composition, "sampled" for a measured
  product concentration.
- `set_label`: match exactly to a `set_label` from the structure plan, or null
  if the value is constant across the whole paper (e.g. a fixed background
  reagent concentration present in every condition).
- `sample_label`: for every "sampled" value, match exactly to the
  `sample_label` (within that set) from the structure plan, so each measured
  value can be placed on the right row. For "initial" values, leave it null
  when the value applies to the whole set -- but if a starting
  concentration DIFFERS between the samples of one set (e.g. a sweep of
  initial concentrations, one per row), give each its sample's
  `sample_label`; otherwise the values can't be told apart.
- Reported percent yields (e.g. "% (Gly)2") go in `concentration_value` with
  the unit as stated in `concentration_unit_raw`; leave `concentration_mM`
  null for them.
- Do not extract values that only appear as a point on a scatter plot/figure
  -- table and in-text values only, for this pass.
- Every entry needs a `quote` and `source`.
- If page images are attached, they are rasterized renders of the pages
  containing a "Table N" caption, given alongside the OCR'd/pdftotext text
  below. For numeric table values specifically, read them off the IMAGE, not
  the text -- two-column table layouts routinely garble row order and
  column alignment in plain text extraction. Use the text for everything
  else (narrative concentrations, methodology, species names).

Return a ChemistryExtraction object.

---
STRUCTURE PLAN:

{{STRUCTURE_PLAN_JSON}}

---
CONTROLLED VOCABULARY (existing tracked species names):

{{CONTROLLED_VOCAB_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
