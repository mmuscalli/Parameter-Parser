Extract every chemical species and its concentration mentioned as part of the
INITIAL reaction composition or as a SAMPLED/measured product, for every
experiment set in the structure plan below.

Answer format -- two parts:

`tables`: every TABLE of values (measured products, and starting
concentrations that a table lists per row), in the table's own layout:
`src` the table ("Table 1"), `c` your confidence, `cols` one entry per
species column (`nm` name, `r` role, `ph` phase, `u` the column's unit as
printed, `lbl` the header as printed, `how` only when the header doesn't
name the species), and `rows` one entry per table row that is a sample in
the structure plan: `set` and `sample` (exact structure-plan labels), `row`
the row's label as printed, and `v` its values, one per column in column
order, exactly as printed -- "nd" for a product the paper reports as not
detected, "detected" for one present without an amount, "" for an empty or
not-measured cell. A table whose rows belong to several sets lists each
row with its own `set`. Don't repeat table values in `groups`.
TABLES IN "TABLE GRIDS" (marked "=== TABLE GRID ..." in or after the paper
text -- the app has already read their cells; r = row number, [n] = column
number): for each of them you
MUST answer with a mapping instead of copying numbers -- `grid` its id ("G1"),
each column `gc` its column number [n], each row `gr` its row number r, and
NO `v`: the app reads every mapped cell. Only rows that are samples in the
plan; never map a header row. Copy values with `v` only for a table that is
NOT in TABLE GRIDS, for cells marked "not readable", or when the grid
clearly differs from the table image (a column split wrongly).

`groups`: everything NOT in a table -- values stated in the text, and the
starting composition when it's given in the text (as it usually is): one
entry per set (and sample) that has species:
`set` (the set_label; '' for values constant across the whole paper),
`sample` when needed (below), and its `species`. Each species: `nm` name,
`r` role, `ph` phase, `v` value and `u` unit as printed, `q` quote, `src`
where it is, `c` confidence; and ONLY when they apply (leave them out
otherwise): `hi` the upper end of a range, `mM` the value in mM, `cn` why there's no mM value, `b` "stock"
and `stk` for a stock-solution concentration, `how` when the quoted words
don't name the species, `ep` / `em` an uncertainty, `det` for a product reported without an amount
(see below).

For each species:
- `ph` is part of the species' column name, so choose it carefully: "aq"
  for anything dissolved or measured in solution -- including products of a
  dry-down or wet-dry experiment analysed after the residue was taken up in
  water (HPLC, MS, NMR of a solution); "gas" only for an amount of a gas
  (a headspace partial pressure or gas volume); "solid" only for an amount of
  an undissolved solid phase (a mineral, a precipitate weighed as a solid).
  When unsure, "aq".
- Use the controlled vocabulary list provided below when the compound is
  already tracked (same name, e.g. "NaCl" not "sodium chloride"). If a
  species isn't in the list, still extract it -- name it the way the paper
  does, with ordinary spaces and punctuation (e.g. "cytidine 2'-phosphate",
  "ribose 1,2-cyclic phosphate"), and add the name to `unmapped_species`.
  Never silently drop a species.
- Peptides: name a peptide by its sequence in three-letter codes, N- to
  C-terminus, joined by "-": "Gly-Gly" (diglycine), "Gly-Gly-Gly"
  (triglycine), "Gly-Ala-Ala" -- order matters, so keep it exactly as the
  paper gives it. A run of 4 or more of one residue is written "(Gly)4":
  "(Gly)4" for tetraglycine, "(Gly)10", "Gly-(Ala)4". The same holds for any
  compound whose name repeats one unit 4 or more times with hyphens (other
  polymers too): "X-X-X-X" is written "(X)4".
  A cyclic peptide (including diketopiperazines) is "cyclo_" plus its
  residues the same way: "cyclo_Gly-Gly" for the glycine DKP,
  "cyclo_Val-Gly".
- Nucleic-acid oligomers: "<n>mer_<nucleotide>" -- n the chain length, the
  nucleotide by its base letter, RNA "A" "C" "G" "U", DNA "dA" "dC" "dG"
  "dT": "4mer_A" for an adenylate tetramer / (pA)4, "43mer_U", "12mer_dT".
  A mixed oligomer by its letters as the paper gives them (a sequence, or a
  composition when the order wasn't determined): "3mer_AAU", "3mer_dATG".
  A table of oligomer lengths (columns 1, 2, 3, ... under "% oligomer")
  gives one species per length: "1mer_A", "2mer_A", ... All oligomers
  together (an oligomerization yield, "RNA oligomers") is named "oligomers";
  the longest oligomer detected is not a species (another step records it).
  Polymers of unstated length keep their names (poly(A)).
- Give the concentration as printed (`v` + `u`). Add `mM` only when the
  conversion is unambiguous (mol dm-3 -> mM is x1000; mass/volume needs a
  molecular weight -- only for well-known compounds; otherwise leave `mM`
  out and say why in `cn`). An AMOUNT (mol, mmol, µmol: "acid (3 mmol)") is
  given as printed with no `mM`: the pipeline divides it by the reaction
  volume itself.
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
  on an added solution only when that set's VOLUMES differ from the others:
  a solution added at the same volume in every set is listed once with
  `set_label` '' -- even when its concentration differs between sets (that
  goes on the species entries).
  If the volumes differ between the SAMPLES of one set (one row per amount
  added), give one entry per sample with `sample_label` -- never put a volume
  in a species' concentration.
  If the paper states the concentration in the mixture itself, record that
  without `b` -- and if it gives both, record both.
- Molar ratios: when the paper gives a ratio between species (e.g. "3 :
  cytosine = 1:2", "a 1:3 molar ratio of A to B") list it in `molar_ratios`
  for each set it applies to, with both species named as in `nm`. Don't
  calculate a concentration from a ratio yourself, and don't enter one the
  paper doesn't state -- the pipeline calculates it from the ratio and marks
  it as calculated. Record the ratio even when the concentrations are also
  given (it's used as a check).
- Totals: when the paper gives ONE amount or concentration for several
  species together with their ratio ("amino acids and/or peptides (1:1 ratio
  of each component, total 1 mmol)"), add a `mixture_totals` entry for each
  set (and `sample`, when the components differ by sample): `total` as
  printed, `parts` = every species sharing it with its share (`nm`, `n`; a
  single species gets the whole total), `q`, `src`. Don't split the total
  yourself and don't put a share in the species' `v` -- list the species
  with `v` null, or leave them out; the pipeline divides the total.
- `set`: exactly a `set_label` from the structure plan, or '' if the value
  is constant across the whole paper (e.g. a fixed background reagent in
  every condition).
- `sample`: for every "sampled" value, exactly the `sample_label` (within
  that set) from the structure plan, so each measured value lands on the
  right row. For "initial" values leave it out when the value applies to the
  whole set -- but if a starting concentration DIFFERS between the samples
  of one set (a sweep of initial concentrations, one per row), put each in
  its sample's group; otherwise the values can't be told apart.
- Compound numbers and citations: papers often label compounds with bold numbers defined once
  (in the text or a figure caption: "ribose-1,2-cyclic phosphate 4", "nicotinamide 6") and then
  write only the number ("the yield of 7", "Yield of 7 (%)"); and the text layer prints
  superscript citations inline ("ammonia.14", "phosphate20"). Name every species by its NAME
  (look up where the number is defined), never "7" or "compound 7", and give the number in `how`
  ("compound 7 = nicotinamide ribose 2'-phosphate, Fig. 2 caption"). A number right after a
  name is a label or a citation, never a concentration, amount or volume.
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
- A product the paper lists as observed but gives no amount for (a list of
  identified products, "+" in a table): `v` null, `det` "detected". A product
  the paper says was looked for and not found ("no product was detected",
  "n.d.", "-" explained as not detected): `v` null, `det` "not detected" --
  one entry per product and sample. In both cases `u` = the unit the paper's
  other results of that kind use (e.g. "%" in a yield table).
- When the structure plan has no sets (the results are only in figures), still
  give the starting solutions -- stock and reaction concentrations -- with
  `set` '': the figures' rows use them.
- One name per species, the same in every entry: the vocabulary name when it
  has the species, else the abbreviation the paper defines for it ("ImpA", not
  "adenosine 5'-phosphorimidazolide (ImpA)" in one entry and "ImpA" in
  another). A stock solution used as the reaction solution itself (no other
  solution added) is that species' starting concentration too: give the
  mixture value (`b` left out) as well as the stock value.
- Averages: a value the paper reports as an AVERAGE over several runs or
  replicates (mean, avg., "averaged across triplicate experiments") gets
  `avg` true -- on the table column, or on the species. Individual runs'
  values don't. An average stated only in the TEXT for experiments that are
  rows of the structure plan (e.g. "the average yield of Gly-Gly over these
  runs was 4%") goes in `groups` with that set's `set`, NO `sample`, `avg`
  true: it's written on each row of the set. An average in the text for
  experiments that aren't in the plan is left out.
- A value printed as a range ("5-10 mM", "0.1 to 0.5 M"): `v` the lower end,
  `hi` the upper end, `u` their unit (in a table, copy the cell as printed,
  e.g. "5-10") -- never one end alone or the midpoint.
- Reported percent yields (e.g. "% (Gly)2") go in `v` with the unit as
  stated in `u` (no `mM`).
- Uncertainties: a value given with an error ("29.18 ± 2.40", "65 (±3)%", s.d.
  or error bars stated in numbers) keeps it -- in a table, copy the cell as
  printed (the app reads the ±); in `groups`, `ep` the upper and `em` the lower
  uncertainty (negative) in the value's unit: "29.18 ± 2.40 mM" -> v 29.18,
  ep 2.40, em -2.40. Leave both out when none is given.
- A percentage of a STARTING material left over ("Recovered nicotinamide (%)",
  "unreacted 4"): role sampled, `meas` "recovered" (on the table column or the species) -- it
  isn't a yield.
- A RATE of change of a species' concentration (a table of "DAP (mM/h)" per
  time interval, "consumption rate of ImpA 0.2 mM h-1"): role sampled, `meas`
  "rate", `u` as printed, negative for consumption as printed. Rate
  CONSTANTS (k, k_obs, half-lives) are not species values: another step
  records them.
- A RATIO between products ("Ratio ribo : arabino" = II : III): role sampled, `meas` "ratio", `u`
  "ratio", named by what it compares ("cytidine 2':3'-cyclic phosphate : aracytidine 3'-phosphate").
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
