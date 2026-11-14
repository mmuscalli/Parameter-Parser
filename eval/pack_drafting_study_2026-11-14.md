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

## Results (43 papers with hand data and a text layer)

| | Pack 5 | Pack 25 | Pack 56 | Curated |
|---|---|---|---|---|
| **Mean recall, all papers** | 0.48 | 0.48 | 0.50 | **0.57** |
| Mean recall, papers with rows (34) | 0.61 | 0.61 | 0.63 | **0.73** |
| Temperature recall / precision | 0.64 / 0.76 | 0.64 / 0.79 | 0.64 / 0.79 | **0.76 / 0.93** |
| Duration recall / precision | 0.37 / 0.80 | 0.38 / 0.77 | 0.36 / 0.76 | **0.51** / 0.79 |
| pH recall / precision | 0.49 / 0.85 | 0.44 / 0.81 | 0.47 / 0.87 | 0.46 / 0.83 |
| Starting amino acid recall / precision | 0.58 / 0.81 | 0.54 / 0.77 | 0.58 / 0.81 | 0.60 / 0.81 |
| Yield recall / precision | 0.36 / 0.83 | 0.38 / 0.72 | 0.44 / 0.75 | **0.51 / 0.84** |
| Rows (all 56 papers) | 860 | 1105 | 910 | 886 |
| Flags per row | 2.4 | 1.8 | 2.0 | 2.2 |

Row counts within 2× of the hand data: 56-58% of papers in every pack (71-74% of papers that got any rows).

**Papers inside vs outside the drafting sample** (mean recall):

| | Pack 5 | Pack 25 | Pack 56 | Curated |
|---|---|---|---|---|
| Pack 5's 5 papers | 0.52 | 0.47 | 0.52 | 0.55 |
| The other 38 | 0.48 | 0.48 | 0.50 | 0.58 |
| Pack 25's 23 papers (with hand data) | 0.46 | 0.45 | 0.51 | 0.56 |
| The other 20 | 0.50 | 0.50 | 0.49 | 0.59 |

Per-paper rows and recall for every pack: `per_paper_wide.csv`.

## What it shows

**Effect of the number of sample papers**
- **Small, and mostly on yields.** Yield recall rises 0.36 → 0.38 → 0.44 from 5 to 25 to 56 papers. Mean recall
  barely moves (0.48 → 0.48 → 0.50).
- **No paper is better extracted for having been in the sample.** Pack 25 scores 0.45 on its own 23 papers and 0.50
  on the rest; Pack 5's in-sample difference (0.52 against 0.48) rests on 5 papers.
- **Five papers already give the core of the pack.** Temperature, duration, pH and the starting composition come from
  the shared modules and the chemistry step, which even Pack 5 links. More papers add compounds (47 → 298), more
  outcome columns and the kinetics and flow-reactor modules. The yield gain comes from those.
- **More papers isn't monotonic in every way.** Pack 25 makes the most rows (1105; Kitadai2017 alone gives 175 against
  3 or 0 elsewhere) and has the lowest yield precision (0.72). Its extra steps (thermodynamics, surface adsorption)
  look like the cause.

**Drafted packs against the curated one**
- **The curated pack is ahead by about 0.08-0.10 in recall,** most of it in duration (0.51 against about 0.37),
  temperature (0.76 against 0.64) and yields. Precision is similar except for temperature (0.93 against about 0.78).
- **Part of that gap is settings drafting never writes.** The drafted packs get only the template's fill-in settings:
  - no `column_pairs` or `label_columns`;
  - no post-processing (`ambient_conditions`, `atmospheric_start`, `results_check`).
  `duration_hr` is filled on 602-661 rows in the drafted runs against 827 in the curated run, and temperature
  recall is identical in all three drafted packs (0.64). That points to the shared mechanism, not the sample size.

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

## Suggestions (not built; for Mickey to decide)

1. **Drafting writes the fill-in settings** for the conventional columns it creates: `label_columns` for
   temperature, time, pressure and pH; `column_pairs` such as sampled/initial temperature; and the general
   post-processing steps. This would close part of the gap to the curated pack at no cost per paper.
2. **Read line plots with markers automatically**, like scatter plots: 66 of the figures here. They're the main way
   these papers report time courses, and most of the nine papers with no rows are this kind.
3. **Reconsider automatic figure suggestions for unattended queues:** about 30% of the cost here for 3% of figures
   read. Suggestion 2 changes this balance.
4. **Text recognition for scanned PDFs** (macOS Vision, as already used for table images): 3 of 56 papers here.
5. **For drafting itself:** 5-10 sample papers give most of the benefit. If more are used, the draft would be
   improved by checking its own steps against the shared modules (Packs 5 and 25 duplicated the mineral-surfaces
   module with their own surface steps).
