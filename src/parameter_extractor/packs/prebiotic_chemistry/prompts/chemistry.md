Extract every chemical species and its concentration mentioned as part of the
INITIAL reaction composition or as a SAMPLED/measured product, for every
experiment set in the structure plan below.

Answer format: `groups` -- one entry per set (and sample) that has species:
`set` (the set_label; '' for values constant across the whole paper),
`sample` when needed (below), and its `species`. Each species: `nm` name,
`r` role, `ph` phase, `v` value and `u` unit as printed, `q` quote, `src`
where it is, `c` confidence; and ONLY when they apply (leave them out
otherwise): `mM` the value in mM, `cn` why there's no mM value, `b` "stock"
and `stk` for a stock-solution concentration, `how` when the quoted words
don't name the species (see below).

For each species:
- Use the controlled vocabulary list provided below when the compound is
  already tracked (same name, e.g. "NaCl" not "sodium chloride"). If a
  species isn't in the list, still extract it -- name it the way the paper
  does, with ordinary spaces and punctuation (e.g. "cytidine 2'-phosphate",
  "ribose 1,2-cyclic phosphate"), and add the name to `unmapped_species`.
  Never silently drop a species.
- Peptides: name a homopolymer "<n>peptide_<AA>" ("3peptide_Gly" for
  triglycine) and a peptide of different amino acids by its sequence in
  three-letter codes, N- to C-terminus, joined by "-" ("Gly-Ala-Ala") --
  order matters there, so keep it exactly as the paper gives it.
  A cyclic peptide (including diketopiperazines) is "cyclo_" plus its
  residues the same way: "cyclo_Gly-Gly" for the glycine DKP,
  "cyclo_Val-Gly".
- Give the concentration as printed (`v` + `u`). Add `mM` only when the
  conversion is unambiguous (mol dm-3 -> mM is x1000; mass/volume needs a
  molecular weight -- only for well-known compounds; otherwise leave `mM`
  out and say why in `cn`).
- `r`: "initial" for the starting composition, "sampled" for a measured
  product concentration.
- Stock solutions vs the reaction mixture: if the paper gives the
  concentration of a solution BEFORE it was combined with others (e.g.
  "5 µL of a 15 mM solution of X, 20 µL of Y ... were mixed"), record that
  value as printed with `b` "stock" and `stk` the label of the solution it
  was in. Do NOT work out the concentration in the mixture yourself --
  instead list, in `added_solutions`, EVERY solution and solvent that was
  combined (including plain water or buffer), each with its volume exactly
  as printed and a quote; the pipeline does the arithmetic. Use `set_label`
  on an added solution only when that set's volumes differ from the others.
  If the paper states the concentration in the mixture itself, record that
  without `b` -- and if it gives both, record both.
- Molar ratios: when the paper gives a ratio between species (e.g. "3 :
  cytosine = 1:2", "a 1:3 molar ratio of A to B") list it in `molar_ratios`
  for each set it applies to, with both species named as in `nm`. Don't
  calculate a concentration from a ratio yourself, and don't enter one the
  paper doesn't state -- the pipeline calculates it from the ratio and marks
  it as calculated. Record the ratio even when the concentrations are also
  given (it's used as a check).
- `set`: exactly a `set_label` from the structure plan, or '' if the value
  is constant across the whole paper (e.g. a fixed background reagent in
  every condition).
- `sample`: for every "sampled" value, exactly the `sample_label` (within
  that set) from the structure plan, so each measured value lands on the
  right row. For "initial" values leave it out when the value applies to the
  whole set -- but if a starting concentration DIFFERS between the samples
  of one set (a sweep of initial concentrations, one per row), put each in
  its sample's group; otherwise the values can't be told apart.
- When the quote can't name the species -- a table that shows compounds as
  structure drawings, a compound number ("7"), a general procedure ("the
  carboxylic acid (3 mmol)") that applies to several entries -- say in `how`
  how you identified it ("structure drawing, Table 2 entry 3", "compound 7 =
  N-cyclohexylisobutyramide", "Table 2 entry 4: phenylacetic acid"), and use
  `c` "medium" unless the paper also names it in words.
- A product whose composition is known but whose SEQUENCE the paper says it
  didn't determine (e.g. shown in parentheses, "(FFA)") must not be given a
  sequence: name it by its residues and counts, e.g. "Phe2Ala (sequence not
  determined)".
- Reported percent yields (e.g. "% (Gly)2") go in `v` with the unit as
  stated in `u` (no `mM`).
- Do not extract values that only appear as a point on a scatter plot/figure
  -- table and in-text values only, for this pass.
- Keep every `q` to the shortest span that shows the value (at most 20
  words; for a table: row label, column label, value) and make `src` exact
  (table + row + column, or section + paragraph), so a reader can find the
  full context.
- If page images are attached, they are renders of the pages with tables
  (cut into pieces when large). For numeric table values, read them off the
  IMAGE, not the text -- table layouts routinely garble row order and column
  alignment in plain text extraction. Use the text for everything else.

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
