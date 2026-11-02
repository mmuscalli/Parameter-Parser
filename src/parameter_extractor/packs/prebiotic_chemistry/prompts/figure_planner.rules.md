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
- `positive_control` / `negative_control`: when the caption or text says
  which control experiments a series is compared with, give them as
  conditions (a short description, e.g. '15 mM ImpA, no mineral'), worded the
  same for every series that shares them; a control run for the whole paper
  is filled in by the app. A control shown as its own bar or line (e.g. the
  grey 'no mineral' bar) is still a series of its own.
- Name each species as the paper does throughout: the vocabulary name, else the
  abbreviation the paper defines ("ImpA") -- the same name the chemistry uses.
- Starting compositions: look in the caption, the passages about the figure,
  the structure plan AND the concentration passages from the rest of the
  paper below (starting concentrations are usually stated once, in the
  Methods; match them to the series by the conditions they're stated for,
  e.g. the injection system or pressure a panel uses). Name species with the
  controlled vocabulary where it has them, else the paper's name -- a species
  missing from the vocabulary (ImpA, an RNA oligomer) is still given: the
  user reviews it as a new variable. A concentration the paper reports only
  indirectly -- measured in a control run without reaction, or given for the
  feed or injected solution -- still counts (`basis` "indirect", `source`
  saying exactly what it is and where it's stated). A null concentration is
  only for a species whose amount the paper doesn't give at all.
- Say each concentration ONCE, in `concentrations` (as printed, with its unit,
  `basis`, `source`): `series` [] when it holds for every series (a fixed
  CuCl2 or glycine background, a 15 mM ImpA solution) -- the app adds it to
  each series -- or the exact labels of the series it applies to. A series'
  own `initial_species` (in mM) only for a component that is on no
  `concentrations` entry. Don't leave out one you mention in `notes`.
- Also give temperature and pH when stated, and every other condition:
  pressure (e.g. `initial_pressure_bar` for a reaction pressure), flow rate,
  volumes, gas or atmosphere, residence or reaction time when not on an
  axis. Category columns take only their listed values: `experiment_type` is
  only "Batch" or "Flowthrough".
