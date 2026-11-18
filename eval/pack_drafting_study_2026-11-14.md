# Drafted data packs from 5, 25 and 56 papers vs the curated pack (2026-11-14)

Mickey's question: how does the number of sample papers used to draft a data pack affect the quality of the data the
pack extracts? Data: `eval/pack_drafting_study_2026-11-14/` (per-paper metrics, summary, paper samples, the evaluator).
Runs: `~/Documents/Parameter Extractor/pack_study_20261114/` (local, not in the repository).

## Setup

- **Papers:** the 56 PDFs of `Paper Files/Paper Lists/Initial Easy Papers`, one per paper. Watanabe1963 and
  Okamoto1964 used their English (DeepL) versions; Rodriguez-Garcia2015 (supplement only) and two empty folders were
  left out. Three papers are scans with no text layer (Flores1973, Inoue1993, Rabinowitz1969) and get no rows anywhere.
- **Packs:** drafted with the app's "Draft made from sample papers" (CLI `--draft-pack`, 2 survey passes, app column
  names), all with the same name pattern and description:
  - Peptide Pack 5: 5 papers; Peptide Pack 25: 25; Peptide Pack 56: all 56.
  - The samples are nested: one shuffle with seed 20261114, Pack 5 = the first 5, Pack 25 = the first 25.
  - Baseline: the curated Prebiotic chemistry pack.
- **Runs:** every pack over all 56 papers as a paper queue: Standard profile, batch mode, "Read simple plots
  automatically" on, "Make rows from results in the body text" off. No person reviewed figures or new variables.
- **Ground truth:** the hand-built dataset (`PaperDataTemplate.xlsx`): 46 of the 56 papers are in it, 43 with a text
  layer.
- **Score:** per paper and quantity, the DISTINCT values the hand dataset has vs the run's.
  - Recall: the share of hand values the run has. Precision: the share of the run's values the hand data has.
  - Tolerances: temperature 1 °C; duration 2%; pH 0.15; starting amino-acid concentration 3%; yields 3% or 0.05.
  - Quantities: initial temperature, duration, initial pH, starting amino-acid concentration (mM), and every product
    yield (% columns; zero yields left out).
  - Column names differ between packs. The drafted packs use the app's conventions (`initial_temperature_C`,
    `duration_hr`, `initial_pH`), checked in their CSVs, so the comparison is like for like.

## The packs

| | Pack 5 | Pack 25 | Pack 56 | Prebiotic (curated) |
|---|---|---|---|---|
| Shared modules | 5 (no kinetics, flow reactor) | 7 | 7 | 7 |
| Own steps | conditions, results, surface characterization | conditions, outcomes, surface adsorption, thermodynamics | conditions, outcomes | experimental conditions |
| Step columns | 41 | 58 | 50 | 55 |
| Known compounds | 47 | 185 | 298 | 129 |
| Drafting cost | $0.10 | $0.40 | $0.63 | — |
| Run cost (56 papers) | $14.06 | $16.71 | $15.31 | $14.25 |

- Every drafted pack has the chemistry and analysis steps and its own row-planning rules.
- Packs 5 and 25 each add their own surface step next to the mineral-surfaces module (overlap). Pack 56 converges on
  the curated pack's shape: one conditions step, one outcomes step and the modules.
- About 30% of each run's cost was figure suggestions ($3.9-4.9 per pack), which gave 6-7 figures in all (below).

## Results

### Scoring (revised 2026-11-14, Mickey's review)

The first scoring compared five quantities against every hand value. That included calculated and internal columns
(`total_sampled_peptides_yield`, even the `is_max_peptide_yield` flag), and values Mickey digitized from figures by
hand, which an unattended run can't read. The revised scoring (`evaluate_v2.py`):

- **Scope:** only what the app is meant to extract.
  - Metadata: title, year, journal, DOI.
  - Methodology: experiment and solution type, solvent, vessel, analysis, headspace gas, solid material and mass,
    initial temperature, pressure (flowthrough rows only: batch pressures in the hand data are calculated), duration,
    reported pH, volumes, flow rate, cycles.
  - Solution and solid chemistry: inputs (every `initial_` constituent, mM) and outputs (product concentrations and
    % yields).
  - Left out: internal columns (flags, filters, ids) and calculated ones (ion speciation, pKa, computed pH, totals,
    ratios, total monomers).
- **Printed values only:** the hand data doesn't record where a value came from. A hand value counts for recall only
  when the paper's text prints it with a unit of its quantity right after it, in any common unit (25 °C or 298 K;
  2 h or 120 min; 100 mM or 0.1 M; 12 %). Values not printed came from figures or calculations: they're counted
  separately and left out of recall. Precision is still against all hand values.
- **Text fields** (titles, names) are matched on their words, recall only. A column the pack doesn't have is "not in
  pack", not a miss: `experiment_type`, `solution_type` and `vessel_material` are this dataset's own conventions,
  which a drafted pack has no reason to invent.
- **Two views:** all 45 papers with hand data and a text layer, and the 34 that got rows in every pack (the other 11
  report their results in figures; see below).

Most of the hand outputs are not printed: of about 4,260 distinct product values, 121 are printed with a unit (62
yields, 59 concentrations). The rest came from figures and calculations. The unit check also drops some printed
values whose unit the PDF's text layer garbles (a degree sign read as '8'), which shrinks the sample without favouring
any pack.

### Recall / precision, papers with rows (34)

| | Pack 5 | Pack 25 | Pack 56 | Curated |
|---|---|---|---|---|
| **Overall, mean recall per paper** | 0.65 | 0.62 | **0.71** | **0.72** |
| Overall, pooled recall / precision | 0.60 / 0.84 | 0.58 / 0.80 | 0.65 / 0.81 | 0.68 / 0.86 |
| Metadata (136 values) | 0.92 / 0.96 | 0.92 / 0.96 | 0.95 / 0.97 | 0.92 / 0.96 |
| Methodology (494) | 0.53 / 0.76 | 0.46 / 0.74 | 0.57 / 0.78 | 0.63 / 0.80 |
| - temperature (24) | 1.00 | 1.00 | 1.00 | 1.00 |
| - duration (104) | 0.39 | 0.39 | 0.39 | **0.57** |
| - pH (107) | 0.47 | 0.42 | 0.49 | 0.47 |
| - volumes (19) | 0.63 | 0.63 | 0.68 | 0.68 |
| - solvent (34) | 0.91 | 0.94 | 0.82 | 0.97 |
| - solid material (27) | 0.30 | 0.30 | **0.81** | 0.22 |
| - experiment type / solution type / vessel | not in pack | not in pack | not in pack | 0.97 / 0.83 / 0.59 |
| Chemistry inputs, mM (61) | 0.67 / 0.81 | 0.79 / 0.75 | 0.80 / 0.73 | 0.82 / 0.74 |
| Chemistry outputs (102) | 0.44 / 0.88 | 0.45 / 0.82 | 0.47 / 0.82 | 0.54 / 0.90 |
| - product % yields (59) | 0.73 | 0.73 | 0.76 | **0.88** |
| - product concentrations (43) | 0.05 | 0.07 | 0.07 | 0.07 |

All 45 papers (11 of them with no rows in any pack): mean recall per paper 0.49 / 0.47 / 0.53 / 0.54.

Product concentrations score low in every pack, including the curated one: most of the few printed ones are probably
coincidences of the check (the hand concentrations were mostly calculated from yields), so this row says little.

**Papers inside vs outside the drafting sample** (mean recall per paper, papers with rows):

| | Pack 5 | Pack 25 | Pack 56 | Curated |
|---|---|---|---|---|
| Pack 5's papers | 0.64 | 0.51 | 0.64 | 0.68 |
| The others | 0.65 | 0.64 | 0.71 | 0.72 |
| Pack 25's papers | 0.59 | 0.56 | 0.66 | 0.68 |
| The others | 0.73 | 0.71 | 0.77 | 0.76 |

Every pack, the curated one included, scores lower on Pack 25's sample than on the rest: those papers are harder.
Relative to the other packs, being in the sample gave Pack 25 no advantage.

Per-paper data: `per_paper_v2.csv` (revised), `per_paper_wide.csv` (rows per pack and the first scoring).

### First scoring (superseded)

Against every hand value of five quantities: mean recall 0.48 / 0.48 / 0.50 / 0.57 for Packs 5 / 25 / 56 and the
curated pack. It understated every pack, and the drafted ones most: calculated and internal columns counted, and
figure-derived hand values counted as misses.

## What it shows

**Effect of the number of sample papers**
- **Pack 56 nearly matches the curated pack** on what it extracts (0.71 against 0.72 mean recall per paper, papers
  with rows). Packs 5 and 25 trail it by 6-9 points, mostly in methodology (pH, solid material) and yields.
- **The gain isn't steady with sample size:** Pack 25 scores below Pack 5 overall (0.62 against 0.65). Its extra
  steps (thermodynamics, surface adsorption) and over-split rows cost it. The contents of the sample matter as much
  as its size.
- **No paper is better extracted for having been in the sample** (table above).
- **Five papers already give the core of the pack.** Temperature, starting composition and metadata come from the
  shared modules and the chemistry step, which even Pack 5 links. More papers add compounds (47 → 298), outcome
  columns, the kinetics and flow-reactor modules, and a solid-material column (Pack 56: 0.81 recall on solid
  materials against 0.22-0.30 for the others).

**Drafted packs against the curated one**
- **The curated pack's lead is mostly duration (0.57 against 0.39) and product yields (0.88 against 0.73-0.76).**
- **Part of that gap is settings drafting never wrote:** the drafted packs got only the template's fill-in settings,
  with no `column_pairs`, `label_columns` or post-processing. `duration_hr` was filled on 602-661 rows in the drafted
  runs against 827 in the curated run. (Fixed after this study: drafting now writes them.)
- **Drafted packs don't have this dataset's own classification columns** (experiment type, solution type, vessel).
  That's expected: they're conventions of this dataset, not something the papers name.

**The pack matters less than the paper's format**
- **Row structure is set by the paper, not the pack:** a paper usually gets exactly the same number of rows in all
  four packs (kumar2012 48/48/48/48, Halmann1968 23 in all four). Differences between packs are in the values.
- **Nine of the 43 papers get no rows in any pack:** Bujdak2000, Imai1998, Kawamura2009, Nagayama1989, Shen1990,
  Yamagata1997, Yamanaka1987, Yoshiaki2000 and lemke2009, together 418 of the 1,350 hand rows (31%). Sakata2010
  gets 1-10 rows of 114.
  - These papers report their results in figures (and text). With body-text rows off, only figures can give them
    rows.
- **Reading plots automatically gave 6-7 figures of about 225 per pack**, in 3-4 papers. The reasons the others
  weren't read (curated run):
  - 88: not a numeric data plot (schemes, spectra, photos);
  - 66: line plots (only bar charts and scatter plots are parsed; most time courses here are markers joined by lines);
  - about 30: axes not calibrated automatically;
  - 5: may repeat a table's data;
  - 2: "math domain error" (a bug).
- **Three scanned PDFs** (no text layer) get nothing.

**The hand data isn't always right.** Chen2007 scores near 0 in every pack. The paper gives 10 mmol of potassium
ferricyanide and 10 mmol of Na2CO3 in 10 mL of water, which is 1000 mM; the runs say 1000 mM and the hand data
10 mM (mmol entered as mM). Recall against the hand data is a lower bound wherever the hand data has such slips.

**Too many rows for some papers** (all packs): Huber1998 34-46 rows against 10, Islam2003 22-35 against 5,
Rabinowitz1978 25 against 10.

## Problems found during the study

- **Fixed:** an unattended queue requested figure suggestions one figure and one paper at a time, each a batch wait of
  about 2 minutes (a projected 9 hours for one 56-paper queue). Now every figure of a paper, and every paper's
  figures, are requested together (commit 29f26bd, tests/test_batch_speed.py). The queues were stopped and resumed
  from their saved answers: nothing was paid twice. All four packs over 56 papers took about an hour in all.
- **Not fixed:**
  - "math domain error" in automatic figure digitizing (2 figures).
  - A resumed queue's `papers.csv` and summary show only the cost spent after resuming ($3.6-4.5 per pack against
    $14-17 actually spent).

## Follow-up (2026-11-14, Mickey's answers)

1. **Drafting writes the fill-in settings** for the standard columns a drafted pack has (`pack_drafting.fill_in_settings`):
   - `label_columns` for temperature, time, pressure and pH;
   - the related-column pairs whose two columns exist;
   - post-processing: 'ambient' conditions when there's a temperature or pressure column, the sealed-vessel start
     pressure when its columns exist, and the no-results check with the chemistry step.

   The three study packs were drafted before this change and don't have them.
2. **Line plots with markers are read automatically** when every series names a marker shape the finder knows. Their
   points are found as markers (the plot kind decides; guessing had taken connecting lines for bars).
   - Replayed offline on the curated run's 66 line plots (saved suggestions, no cost):
     - 28 have no markers on every series, and stay with the user;
     - of the 38 with markers, 3 are now read automatically.
   - The rest fail on calibration (no plot frame found; too few tick numbers read from low-quality images) or have
     series that can't be told apart (four series all 'open circles joined by line'). These correctly go to the
     editor.
3. **Automatic figure suggestions in unattended queues:** left as they are. Mickey: the user digitizes most plots by
   hand, helped by the automatic detection where it works.
4. **Text recognition for scanned pages** (`ingestion/page_ocr.py`, macOS Vision):
   - A page with almost no text over an image is read. Inoue1993's only text was a watermark, so this is decided page
     by page.
   - Lines are put back in reading order: two columns; pieces of one printed line joined; a raised decimal point
     ('0•28') read as a point.
   - Pages read this way are flagged in the results.
   - All three study scans now give text: Flores1973 3 pages, Inoue1993 5, Rabinowitz1969 2, about 2 s each.
   - Image figures with fewer than 4 tick numbers in the text layer get theirs read from the image too, which helps
     both automatic calibration and the digitizer's Auto-calibrate. Imai1998 Fig. 3 now calibrates (0.001-10 mM, log).
   - Not done: finding figures on fully scanned pages (figures are found by their 'Fig. N' captions in the text
     layer).
5. **The "math domain error"** was a real bug. On Imai1998's log-scale axis (0.001-10 mM), automatic rounding to 2
   decimals turned 0.003 mM into 0.00, and log10(0) stopped the figure; the digitizer's rounding by hand had the same
   flaw. On a log axis the decimals now mean significant figures (decimals + 1), and a value that would still round
   to 0 keeps its exact value (`calibration.rounded`, used for snapping points and for stored values).

## Re-measured (2026-11-17, Mickey: items 1 and 2 of the next steps)

**Method.** The four queues (and the scanned papers' reruns) were rebuilt from their saved answers: free, no requests,
current code and the study packs with their fill-in settings. Scored with `evaluate_v3.py` against the corrected hand
dataset (`PaperDataTemplate_Nov15_2026.csv`). Mickey's rules:
- the hand dataset is a reference gathered by another method, not ground truth (slips, figures not digitized);
- new columns (parameters the hand dataset has no column for) don't count against accuracy: counted, not scored;
- rounding and digitizing differ: every comparison has a 'match' tier (within rounding) and a 'close' tier (10 %).

Measures: recall of the printed hand values (as v2); agreement of the run's values in columns both datasets fill for
the paper (hand names brought to the app's names); new values. Each run is scored as written and 'reviewed' (plus the
values an unattended run holds back for review: compounds and variables outside the pack's vocabulary,
new_variables.json, as if accepted).

**Mean recall per paper, papers with rows (37):**

| | Pack 5 | Pack 25 | Pack 56 | Curated |
|---|---|---|---|---|
| Old runs, old hand data (v3 rules) | 0.666 | 0.613 | 0.711 | 0.721 |
| Old runs, corrected hand data | 0.690 | 0.646 | 0.735 | 0.737 |
| Rebuilt, corrected hand data | 0.699 | 0.648 | 0.736 | 0.737 |
| Rebuilt + held-back values accepted | 0.731 | 0.662 | 0.751 | 0.741 |

- The corrected hand data accounts for 2-3 points; the rebuild (fill-in settings, pH fix below) under 1; the review
  step 1-3 (most for chemistry: Pack 5 inputs 0.70 -> 0.92, outputs % 0.73 -> 0.86).
- Agreement on shared columns (match / close): methodology 0.78-0.86 / 0.85-0.88, chemistry in 0.85-0.88 /
  0.87-0.89, chemistry out 0.88-0.91 / 0.90-0.93.
- Fill-in settings barely moved duration (drafted 0.42 -> 0.43-0.44; curated 0.59). Same `duration_hr` column, but
  drafted packs fill it on 622-709 rows against 827: a real gap, next to look into. pH recall is low in every pack
  (0.42-0.54 of 107 printed values), outputs in mM 0.05-0.07 (most hand mM are back-calculated from yields).

**Item 2, 'too many rows', is not over-splitting.** The extra rows are real rows without values in an unattended run:
- Islam2003 (22 vs 5): Table 3's 5 rows match the hand data value for value; 17 rows from Figs 2 and 7, not digitized.
- Huber1998 (46 vs 10): Table 1 has 46 runs (Phe 12, L-Tyr 12, DL-Tyr 12, Gly 10); the hand data took the 10 Gly runs.
  The Phe / Tyr products, initial Tyr, FeS and NiS (90 values) were extracted and held back for review.
- Rabinowitz1978 (25 vs 10): 8 rows reproduce Table 2, cited from Wieker (1960) (polyphosphates, no peptides), marked
  with `original_data_reference`.
per_paper_v3.csv has, per paper: rows with a product value, figure rows still empty, cited rows, other empty rows.

**Fixed on the way:** a number parameter answered in its text field with value 0 was written as 0 (Huber1998: pH
'7.5-9.9 (varies by run, see sample)' -> pH 0.0 on 12 rows); and 'not on arXiv' was never cached by the table check,
so every run and rebuild asked arXiv again for every paper, 3 s apart (a 56-paper rebuild crawled).

## Duration and pH gaps (2026-11-17, Mickey: fix them; values calculated for the hand dataset aren't misses)

**Scoring v3, revised** (`evaluate_v3.py`):
- A hand value counts as printed only when the paper prints it AS that value: in the printed unit it has no more
  decimals than the printed number and equals it at that precision; in a converted unit the printed number converted
  equals it at its own precision. Digitized or calculated hand values no longer count as misses (Sakata2010's
  23.8 / 71.37 h had matched a printed '24 h' / '3 d'). Printed durations 107 -> 56.
- pH is found in any pH column (`initial_pH`, `sampled_pH`): the hand dataset keeps final pH in `initial_pH` in places
  (faisal2005's results-table pH, Leman2004's 'Final pH').
- Both ends of a range column count for recall (Rabinowitz1985's '8.3:8.9').

Mean recall per paper, rebuilt runs (37 papers with rows): Pack 5 0.75, Pack 25 0.70, Pack 56 0.79, curated 0.76.
Duration 0.59 / 0.59 / 0.55 / 0.88; pH 0.75 / 0.67 / 0.71 / 0.42.

**Causes and fixes** (requests change: measured only by a new run, not a rebuild):
- Duration, drafted packs: the shared row-planning prompt (packs without their own: drafted and users' packs) asked
  for `hr` only "when the rows are time points (else leave it empty)", so a set of separate experiments, each with its
  own time (Eder1992 Table 1: 106, 107, 114 ... h), got none. Now: whenever the paper states one -- a time point, a time
  per table row, or one time for the whole table or experiment. The curated pack's own prompt already said so.
- pH, curated pack: `pH_buffer` took the pH ("500 mM Me3N buffer, initial pH 9.1", Leman2004) or 'none' (mitsuzawa2004)
  and the per-row pH columns of the tables were never read ('Final pH', '(Starting pH)'). The descriptions now say:
  `initial_pH` as set or measured before the reaction, per set or row when a table gives it, a buffer's pH when there
  is no other; `sampled_pH` after the reaction or at sampling, per row from a results table ('final pH'); a buffer's
  pH also goes in `initial_pH`.
- Left as they are: Sakata2010 and Zamaraev1996 (results in figures: their rows don't exist unattended), Takaoka1991,
  Rabinowitz1978 and Nooner1977 (1-2 values each).

### Validation run (2026-11-17, Mickey approved ~$3; spent $1.50)

New runs (batch Standard, no automatic figures) with the two fixes: Pack 56 on 6 papers whose durations the drafted
packs had missed, the curated pack on 6 papers with pH misses (faisal2005 as a regression check). Scored with
evaluate_v3 against the rebuilt runs (`per_paper_v3_validation_20261117.csv`). Printed hand values found, before -> after:

| Pack | Paper | Duration | pH | Recall (all numeric) |
|---|---|---|---|---|
| Pack 56 | Eder1992 | 0 -> 12 of 12 | 1 -> 1 of 1 | 0.18 -> 0.94 |
| Pack 56 | Rode1990 | 2 -> 3 of 3 | 0 of 2 | 0.71 -> 0.81 |
| Pack 56 | Ying2019 | 0 of 1 | 0 -> 1 of 1 | 0.00 -> 0.75 |
| Pack 56 | Leman2015, Rabinowitz1985, Steinman1966 | unchanged | unchanged | unchanged |
| Curated | Leman2015 | 1 of 1 | 4 -> 14 of 14 | 0.45 -> 0.91 |
| Curated | Leman2004 | 5 of 5 | 0 -> 3 of 11 | 0.45 -> 0.59 |
| Curated | Rabinowitz1985 | 1 of 1 | 1 -> 3 of 13 | 0.28 -> 0.39 |
| Curated | Huber1998 | -- | 0 of 7 | 0.08 |
| Curated | mitsuzawa2004 | -- | 0 of 5 | 0.17 |
| Curated | faisal2005 | -- | 6 -> 0 of 6 | 0.93 -> 0.50 |

- The duration fix works (Eder1992's per-row times now on every row).
- The pH descriptions help where the pH is in the text or a labelled column, but the curated conditions step still
  answers set-level where a TABLE gives pH per row: Huber1998 'see sample' (now left out, not written as 0), mitsuzawa
  2004's starting pH not given, and faisal2005's results-table pH no longer given at all (2 to 5 rows per answer
  against Pack 56's 47 per-run rows for Huber1998; both answers complete, end_turn).
- Added after this run: a curated-pack rule -- a condition a table gives row by row goes on each sample's own row,
  never a set-wide range or 'see sample', including a pH column among a results table's columns. Not measured yet
  (6 papers, ~$0.80).

### Second validation run: the per-row rule (2026-11-17, Mickey approved; $0.88, total $2.38)

The curated pack on the same 6 papers with the per-row table rule (`per_paper_v3_validation2_20261117.csv`). Printed
pH values found, rebuilt -> first validation -> second validation:

| Paper | pH | Recall (all numeric) |
|---|---|---|
| Huber1998 | 0 -> 0 -> 7 of 7 | 0.08 -> 0.67 |
| Leman2004 | 0 -> 3 -> 11 of 11 | 0.45 -> 0.95 |
| Leman2015 | 4 -> 14 -> 14 of 14 | 0.45 -> 0.91 |
| Rabinowitz1985 | 1 -> 3 -> 13 of 13 | 0.28 -> 0.94 |
| faisal2005 | 6 -> 0 -> 6 of 6 | 0.93 (regression gone) |
| mitsuzawa2004 | 0 -> 0 -> 0 of 5 | 0.17 |

51 of 56 printed pH values against 11 before. Agreement on shared methodology columns 0.94. Left: mitsuzawa2004 --
its starting pH is printed per starting material in a rate-constant table ('Starting material (Starting pH)'), and its rows
(2-5) come from the reactor runs, not that table; the hand data's 37 rows are figure points.
