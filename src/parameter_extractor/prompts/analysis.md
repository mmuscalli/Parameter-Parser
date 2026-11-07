You are recording HOW the experiments' products (or solutions) were ANALYSED in this {{RESEARCH_AREA}} paper:
every analytical technique and every instrument setting the paper states for it. Don't extract results (yields,
concentrations, lengths): other steps record those. Report only what the paper states.

One entry in `methods` per technique used on the experiments: chromatography, electrophoresis, mass
spectrometry, spectroscopy, NMR, X-ray, electrodes, sequencing, microscopy... A coupled technique is ONE entry
(LC-MS, GC-MS) holding the settings of both parts. Techniques used only to characterise starting materials
(e.g. XRD of a mineral before use) count too -- say so in `measured`. Not techniques of OTHER papers mentioned
in the introduction or discussion, and not preparative purification (preparative HPLC or columns used to make a
standard or isolate a product) unless the same run also measured the experiments' products.

- `tech`: the technique's name from the vocabulary below (choose the most specific that fits: 'RP-HPLC' over
  'HPLC' when the paper says reversed phase or a C18 column; 'MALDI-TOF-MS' over 'MS'; 'NMR-31P' for 31P NMR).
  One the vocabulary lacks: the paper's usual abbreviation, hyphenated. `nm`: as the paper names it.
- `set`: '' when the technique and these settings were used for every experiment; else the set label from the
  structure plan -- repeat the technique for each set analysed differently (a different column, gradient or
  matrix), each with its own settings.
- `settings`: EVERY setting the paper states for the technique, one entry each, named from the vocabulary of the
  technique's families plus the `general` family. Always include `measured` (what the technique was used for,
  e.g. 'maximum oligomer length', 'Gly-Gly and DKP yields') and `instrument` (make and model) when given.
  A setting the vocabulary lacks: a short hyphenated name of your own (e.g. 'ion-source-1-voltage').
  - Numbers: `v` with the unit as printed in `u` ('0.5' 'mL/min', '19' 'kV', '140' 'ns', '260' 'nm', '5' 'µm',
    '150' 'mm'); a range: `v` low and `hi` high ('75-85%': v 75, hi 85, u '%'). Give the unit printed; the app
    converts. A setting whose vocabulary unit is text: `txt` as printed (column, mobile phase, matrix, polarity).
  - Column dimensions written together ('4.6 x 150 mm, 5 µm'): `column-diameter` 4.6 mm, `column-length` 150 mm,
    `particle-size` 5 µm -- one entry each, and the column name in `column`.
  - A gradient: the mobile phases in `mobile-phase`, the programme in `elution`.
  - Two quantities in one phrase ('5 sets of 1000 shots', '4.6 x 150 mm'): one setting each.
  - Instrument settings tables (e.g. 'Table 2. MALDI-TOF MS instrument settings'): every row is a setting.
  - `replicate-measurements` counts measurements of ONE sample (injections, spectra per sample) -- not
    replicate experiments ('triplicate experiments' is not a setting here: another step records it).
- `q`: the paper's own words, the shortest span that shows the setting (at most 20 words; for a table: row +
  value). `src`: the table or section and paragraph. `c`: high when stated plainly; medium when you inferred
  which technique or set it belongs to.
- Compound numbers ('nicotinamide 6') and citation numbers ('ammonia.14') are never values.
{{PACK_RULES}}
{{ANALYSIS_VOCABULARY}}

Return an AnalysisResult; `methods` [] when the paper describes no analysis.

---
STRUCTURE PLAN:

{{STRUCTURE_PLAN_JSON}}

---
PAPER TEXT:

{{PAPER_TEXT}}
