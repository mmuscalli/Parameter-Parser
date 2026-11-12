- This is a database of prebiotic synthesis experiments (peptides,
  nucleotides, ...). Axis multipliers usually convert concentrations: an
  axis in mol dm-3 feeding an `_mM` column -> 1000; an axis labelled
  "10^3 (% Gly-Gly) per h" -> 0.001 to get % per h. Use a null column for
  derived quantities like rates, enthalpies or species-distribution
  percentages. `max_peptide_length` is for the longest peptide (amino-acid
  residues) only; the longest nucleic-acid oligomer is `max_oligomer_length_nt`
  and all oligomers together (an oligomerization yield, %) is
  `total_sampled_oligomers_yield`. A nucleic-acid oligomer of one length is
  named '<n>mer_<nucleotide>' (base letter: A C G U, DNA dA dC dG dT):
  'sampled_4mer_A_aq_%yield', 'sampled_10mer_G_aq_mM'. Every compound's
  column is '<role>_<name>_<phase>_<unit>' (phase aq, gas or s): a peptide is
  named by its sequence ('sampled_Gly-Gly_aq_%yield', 'sampled_(Gly)4_aq_mM',
  'sampled_cyclo_Gly-Gly_aq_mM' for the glycine diketopiperazine); any name
  repeating one unit 4 or more times is written '(X)n'. An axis of oligomer lengths
  like 8, 12, 16 nt, or any other quantity no column fits, gets a null column
  and a `new_column` (e.g. 'RNA_length_nt'); the user reviews it as a new
  variable. Bar charts of minerals: x `categorical`, column 'solid_material_name'.
- `positive_control` / `negative_control`: when the caption or text says
  which control experiments a series is compared with, give them as
  conditions (a short description, e.g. '15 mM ImpA, no mineral'), worded the
  same for every series that shares them; a control run for the whole paper
  is filled in by the app. A control shown as its own bar or line (e.g. the
  grey 'no mineral' bar) is still a series of its own.
- `pH_buffer`: a series run with a pH buffer (caption or text: "pH-buffered", "in
  50 mM HEPES") gets it as a condition -- its name and concentration as printed,
  or the paper's description when it names none ('organic pH buffers') -- even
  where the Methods say the other experiments used no buffer.
- Name each species as the paper does throughout: the vocabulary name, else the
  abbreviation the paper defines ("ImpA") -- the same name the chemistry uses.
- Every series with products or yields needs its starting composition (the
  starting compounds and their concentrations); a series label or legend
  entry such as "gly2 (A, 0.1 M)" or a caption "starting from 0.1 M glycine"
  gives it -- list it in `concentrations`. A curve the paper CALCULATED or
  modelled (not measured points) says so in the series' notes.
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
  `basis`, `source`; a power of ten as '10^-1 M' -- caption text like
  '10 - 1 M' lost its superscript, so read it from the figure): `panel` the
  panel it belongs to ('(A)') when panels differ, `series` [] when it holds
  for every series of that panel (or of every panel) (a fixed
  CuCl2 or glycine background, a 15 mM ImpA solution) -- the app adds it to
  each series -- or the exact labels of the series it applies to. A series'
  own `initial_species` (in mM) only for a component that is on no
  `concentrations` entry. Don't leave out one you mention in `notes`.
- Also give temperature and pH when stated, and every other condition:
  pressure (e.g. `initial_pressure_bar` for a reaction pressure), flow rate,
  volumes, gas or atmosphere, residence or reaction time when not on an
  axis. Category columns take only their listed values: `experiment_type` is
  only "Batch" or "Flowthrough".
