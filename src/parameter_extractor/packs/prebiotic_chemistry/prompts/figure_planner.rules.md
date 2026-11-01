- This is a database of prebiotic synthesis experiments (peptides,
  nucleotides, ...). Axis multipliers usually convert concentrations: an
  axis in mol dm-3 feeding an `_mM` column -> 1000; an axis labelled
  "10^3 (% Gly-Gly) per h" -> 0.001 to get % per h. Use a null column for
  derived quantities like rates, enthalpies or species-distribution
  percentages. `max_peptide_length` is for the longest peptide (amino-acid
  residues) only: an RNA / nucleotide length -- also an axis of oligomer
  lengths like 8, 12, 16 nt -- or any other quantity no column fits, gets a
  null column and a `new_column` (e.g. 'max_linear_oligomer_length_nt',
  'RNA_length_nt'); the user reviews it as a new variable. Bar charts of
  minerals: x `categorical`, column 'solid_material_name'.
- Give each series its COMPLETE initial composition in `initial_species`
  (controlled-vocabulary names where the vocabulary has the species, else the
  paper's name -- a species missing from the vocabulary, e.g. ImpA or an RNA
  oligomer, is still listed with its concentration: the user reviews it as a
  new variable -- never leave `initial_species` empty because a species has
  no column yet;
  concentrations converted to mM, including components shared by all series
  such as a fixed CuCl2 or glycine background) -- look for it in the caption, the passages about the figure,
  the structure plan AND the concentration passages from the rest of the
  paper below (starting concentrations are usually stated once, in the
  Methods, not next to the figure; match them to the series by the
  conditions they're stated for, e.g. the injection system or pressure a
  panel uses).
- A concentration the paper reports only indirectly -- measured in a control
  run without reaction, or given for the feed or injected solution -- still
  counts: put it in `concentration_mM` (converted to mM) on EVERY series it
  applies to, with `basis` "indirect" and `source` saying exactly what it is
  and where it's stated (every suggestion is shown to the user to check). A
  null concentration is only for a species whose amount the paper doesn't
  give at all -- never for one you've identified in the text.
- Also give temperature and pH when stated, and every other condition:
  pressure (e.g. `initial_pressure_bar` for a reaction pressure), flow rate,
  volumes, gas or atmosphere, residence or reaction time when not on an
  axis. Category columns take only their listed values: `experiment_type` is
  only "Batch" or "Flowthrough".
- `concentrations`: list EVERY concentration the paper gives for the species
  in these series -- stated as a starting concentration, or given indirectly
  (a control run without reaction, a feed or injected solution: `basis`
  "indirect") -- as printed with its unit, the exact labels of the series it
  applies to ([] for all) and where it's stated. Include values you also put
  in `initial_species`, and species missing from the vocabulary. This list is
  how the app fills in concentrations, so don't leave out one you mention in
  `notes`.
