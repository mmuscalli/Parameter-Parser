# Accuracy evaluation, November 2026: report

**Answer.** The Standard profile on the built-in packs is the most accurate set-up tested, and Economy ×3 comes
close for a sixth of the cost. Against a checked model standard, Standard finds 0.84–0.88 of the values in P1 and
E1 and writes 0.83–0.91 of its values correctly. Packs drafted from a few papers lose about a third of the values,
mostly by having no column for them. Papers outside the prebiotic pack's field (P3) are where every arm does worst.

Run 20–21 November 2026 on 0.6.0 (branch levels-and-facets). API cost $38.09 of the agreed $75 (drafting $0.53 included; the standard and the local arm cost nothing). Plan and
running notes: the "Accuracy Evaluation Plan" doc on claude.ai; dated record: `docs/history/2026-11.md`, Phases 0–6.

## What was run

| Batch | Papers | What they are | Scored against |
|---|---|---|---|
| P1 | 60 | prebiotic peptide synthesis, all with hand data | hand dataset (50 papers) and model standard (12) |
| P2 | 16 | prebiotic nucleotide and RNA chemistry, reviews | model standard (16) |
| P3 | 10 | impact, ablation and meteorite organics | model standard (10) |
| E1 | 32 | exoplanet discoveries, sampled by detection method | NASA Exoplanet Archive (32) and model standard (10) |

| Arm | Profile | Pack |
|---|---|---|
| A | Standard (Sonnet; paper details on Haiku) | built-in |
| B | Economy, 3 passes with a vote | built-in |
| C | Standard | drafted from 5 papers of the batch (P1: 10) |
| D | Economy ×3 | drafted pack |
| F | A, resumed with plots read automatically | built-in (P1 only) |
| L | qwen3.8:27b on the local server | built-in (12 P1 and 4 E1 papers) |

**Model standard (MS):** each paper's requests exported as a package and answered by Claude Opus 5.5 in Claude
Code, reading the text, the table images and, where the text layer was garbled, page renders. Then checked
against the hand data (P1: 0.858 of printed hand values found; every miss traced) and against the arms'
disagreements (Phase 5). No non-Claude assistant was available, so every arm and the standard are Claude's: a
shared blind spot would not show.

**Measures.** *Recall*: share of the reference's values the arm wrote (numbers within a tolerance, text by
matching words). *MS precision*: share of the arm's values the standard also has. *Cells right*: on rows paired
one-to-one with the standard, cells holding the standard's value. *Pack's own quantities*: recall counting only
quantities the arm's pack has a column for. Values the hand data lacks are not misses; figure-only values are
counted (figure rows waiting), not scored. 'Written' = what the app writes without review; the reviewed numbers
(new variables accepted) differ by at most a few points and change no ranking.

## Results ('written')

| Batch | Arm | Cost | Hand recall | Archive recall (pack's own) | MS recall (pack's own) | MS precision | Cells right |
|---|---|---|---|---|---|---|---|
| P1 | A | $6.09 | 0.717 | – | 0.884 (0.884) | 0.911 | 0.958 |
| P1 | B | $0.97 | 0.752 | – | 0.908 (0.908) | 0.849 | 0.897 |
| P1 | C | $6.41 | 0.716 | – | 0.713 (0.872) | 0.808 | 0.921 |
| P1 | D | $0.99 | 0.702 | – | 0.687 (0.828) | 0.738 | 0.911 |
| P1 | F | $10.68 | 0.736 | – | 0.884 (0.884) | 0.827 | 0.913 |
| P1 | L (12 papers) | $0 | 0.799 | – | 0.772 (0.783) | 0.829 | 0.781 |
| P2 | A | $2.29 | – | – | 0.727 (0.745) | 0.804 | 0.906 |
| P2 | B | $0.57 | – | – | 0.807 (0.809) | 0.754 | 0.843 |
| P2 | C | $2.64 | – | – | 0.350 (0.537) | 0.599 | 0.805 |
| P2 | D | $0.62 | – | – | 0.346 (0.594) | 0.516 | 0.744 |
| P3 | A | $0.85 | – | – | 0.476 (0.505) | 0.590 | 0.612 |
| P3 | B | $0.11 | – | – | 0.569 (0.627) | 0.362 | 0.605 |
| P3 | C | $1.12 | – | – | 0.220 (0.595) | 0.278 | 0.827 |
| P3 | D | $0.15 | – | – | 0.218 (0.618) | 0.255 | 0.828 |
| E1 | A | $4.55 | – | 0.756 (0.756) | 0.844 (0.869) | 0.834 | 0.958 |
| E1 | B | $0.73 | – | 0.679 (0.680) | 0.799 (0.825) | 0.766 | 0.962 |
| E1 | C | $3.87 | – | 0.527 (0.685) | 0.370 (0.785) | 0.917 | 0.909 |
| E1 | D | $0.67 | – | 0.514 (0.667) | 0.363 (0.746) | 0.879 | 0.935 |
| E1 | L (4 papers) | $0 | – | 0.543 (0.561) | 0.814 (0.872) | 0.749 | 0.953 |

Hand recall is over all P1 papers with hand data (a paper without rows counts 0). On the same 12 P1 papers, hand
recall is A 0.779, B 0.786, L 0.799. F's cost is its runs' summaries (the reused A answers included); the new spend for F was $4.93. Full tables, reviewed mode and per-paper rows: `results/`.

## Findings

1. **Standard vs Economy ×3.** On the prebiotic batches Economy ×3 finds as much or more (P1 0.908 vs 0.884, P2
   0.807 vs 0.727) but writes more that the standard doesn't support (P1 precision 0.849 vs 0.911; wrong cells
   9.2 % vs 3.7 %). On E1 Standard is ahead on every measure. Economy ×3 costs about a sixth. Standard stays the
   default; Economy ×3 is a sound choice for a first pass that a person reviews.
2. **Drafted packs** score close to the built-in pack on the quantities they have columns for (P1 0.872 vs 0.884,
   E1 0.785 vs 0.869) and far below it overall (P1 0.713, P2 0.350, E1 0.370): five sample papers don't anticipate
   what the rest of a batch reports. The papers a pack was drafted from score no better than held-out ones (P1 C
   0.667 vs 0.728). A drafted pack needs widening after its first runs before its numbers compare.
3. **Field fit matters most.** P3 (impact and space-sample papers in the prebiotic pack) is the lowest batch for
   every arm: A covers 6 of 10 papers and 0.48 of the values. Several P3 papers have no results table at all.
4. **Reading plots (F)** read 15 figures and added 275 rows to P1 (1,169 vs 894) for $4.93 more. Recall holds,
   MS precision drops (0.827 vs 0.911): digitized points are rows the standard doesn't have, and 131 figure
   rows carry no outcome value yet. Useful for coverage; the rows still need review.
5. **The local model (L)** finds the hand values (0.799) but splits tables into far more rows (347 vs 231 on the
   same 12 papers), so 0.781 of its cells land right against Standard's 0.958. Usable for a free first pass; not
   yet for unreviewed rows.
6. **Row structure** is the largest remaining disagreement between good arms and the standard: one row per
   nucleotide or per literature entry vs one per table row (Caimi2024 13 vs 32), whether field samples are rows
   (Parnell2007 0 vs 27), whether a no-table paper gets a summary row. The row-plan rules leave these open.

## App findings

| Finding | State |
|---|---|
| Drafted packs used lab units for astronomy (log g read as grams) | fixed in Phase 1 (`conventions.unit_system`) |
| arXiv lookup cache: parallel saves renamed each other's temp file, failing papers | fixed in Phase 3 (`LookupCache.save`) |
| One paper's finishing error stopped a whole queue; a text estimate broke `_estimate` | fixed in Phase 3 |
| An estimate by another method given as a range raised KeyError | fixed in Phase 4 |
| Resume could not turn plot reading on (arm F) | added in Phase 0 (`--resume --auto-figures`) |
| A unit printed '×10⁻⁶ g' stays unknown instead of µg (Mukhin1989) | fixed 2026-11-22 (`units.scaled_unit`) |
| Some table pages not cropped as images (iqubal2017; Islam2003's Table 1 crop shows Table 2) | fixed 2026-11-22 (`table_finder`) |
| A set label's salt and pH not carried to the rows when the chemistry answer omits them (Eder1994, arm A) | flagged since 2026-11-22 (`label_values.label_gaps`), not filled |
| Row structure left open (comparison tables, field samples, papers without tables) | decided and implemented 2026-11-22 (one row per entry; `result_type`; a summary row) |
| Local models over-split table rows | open (local_model_notes) |

## Follow-up: drafting closer to the built-in packs (2026-11-22)

The drafted packs were written again from their saved designs with two changes: every lab pack links the new
`lab_experiment` module (the general experiment conditions and their settings), and an astronomy design that mostly
records the archive's quantities is drafted on the exoplanet pack. Same papers (the model-standard ones), old drafted
pack (C) against new; `arms_redraft.json`, `results_redraft/`:

| Batch | Measure | C | New |
|---|---|---|---|
| E1 (10) | MS recall | 0.374 | 0.817 |
| E1 | MS precision (numbers only) | 0.919 (0.971) | 0.824 (0.959) |
| E1 | uncertainties, star values found | 0.57, 0.71 | 0.89, 0.88 |
| P1 (12), reviewed | MS recall (pack's own quantities) | 0.777 (0.933) | 0.891 (0.955) |
| P1, reviewed | MS precision; hand recall | 0.830; 0.817 | 0.817; 0.801 |
| P1, written | MS recall; hand recall | 0.782; 0.804 | 0.903; 0.790 |
| cost | E1; P1 | $0.92; $1.41 | $1.27; $1.81 |

E1's lower precision is composition, not error: its numbers are as well supported as before (0.959 vs 0.971, twice
as many), but it now writes the fit models' free-text descriptions (priors, assumptions, software), which the text
matcher rarely counts as the same, and 105 values in columns the standard has no counterpart for (microlensing,
imaged companions). P1's conditions gain experiment type, solution type and vessel, and volume 3 -> 6 of 8; solid
materials recorded as the drafted `catalyst` lose `solid_material_name` (14 -> 7 of 14) since the conditions are a
request of their own.

A second round (2026-11-24, arm C4): the lab module's conditions join the pack's first step (one request fewer a
paper), the remaining prebiotic conditions moved into their modules, peptides_oligomers and solution_chemistry carry
the prebiotic pack's compounds, and µmol/mL reads as mM (the standard's Alargov2002 rebuilt with that fix, $0). P1,
same 12 papers, reviewed (C = the first drafted pack, C3 = the round before):

| Measure | C | C3 | C4 |
|---|---|---|---|
| MS recall (pack's own quantities) | 0.776 (0.902) | 0.890 (0.927) | 0.846 (0.898) |
| MS precision | 0.830 | 0.817 | 0.826 |
| hand recall | 0.817 | 0.801 | 0.824 |
| solid material; pH | 14/14; 13/21 | 7/14; 14/21 | 14/14; 19/21 |
| cost | $1.41 | $1.81 | $1.54 |

C4 fixes what it targeted (solid materials back, the extra request gone) and has the best hand recall and precision;
its lower MS recall comes from values the changed steps don't touch, varying from run to run: run labels the row plan
gave once and not again (Rode1990, 12), particle sizes the mineral step gave once (iqubal2017, 5), and volumes
(Rode1990, Chen2007) with the starting concentrations that depend on them. One run per arm can't separate the two.

Why the drafted pack still misses values (C4, `column_gaps.py`, `miss_causes.py`): of 135 missed, 81 are in
quantities it has no column for -- a paper's own constants accepted as new variables in the standard (Sakata2014,
mitsuzawa2004: 29), run labels (12), Alargov2002's amino acids, whose unit the model wrote as 'µmol mL-1/sample' (26),
and single values. The 59 in columns it has: 27 other rows (about half are wordings the text match doesn't accept:
'ZnOCMo (Zn2[Mo(CN)8]·2H2O)' vs the formula alone), 13 not recorded (suppliers, controls), 11 recorded under another
column (volumes), 5 not printed in the paper (the standard's derived values), 3 near. In Rode1990 the conditions
step gave one temperature per table row without the row's sample, so every row of the set got the first (flagged,
twice: a conflict and a label mismatch) while the rows' own labels state each temperature.

A repeat (2026-11-24, arm C5: C4's pack and settings run again, $1.01) measures how much one run varies: reviewed
MS recall 0.846 and 0.870 (written 0.865 and 0.898), against C3's 0.890; per paper up to 11 values apart (Chen2007's
volumes and the concentrations that depend on them, Rode1990's run labels, iqubal2017's particle sizes, Bujdak1996's
cycles in one run and yields in the other). The step change of C4 is within that spread: no quantity was lost in
both runs except one solid-material type. kumar2012's solid materials came back in one run (14/14) and not the other
(7/14), so that miss is also variable. Comparisons of single runs of 12 papers should allow about +-0.03.

## Limits

- One model family throughout, the standard included. The standard covers 48 of 118 papers; P2, P3 and E1 have no
  hand data, so their recall rests on the standard alone.
- One run per arm: no repeat runs, so paper-to-paper variation (Eder1994's lost salts) is not separated from arm
  differences. Batch sizes for P2, P3 and the local arm are small.
- The scorer was corrected during the work (equivalent names, two-letter names, archive-filled columns, Jupiter
  vs Earth units); every arm was rescored with the final rules.

## Reproduce

From the repository root: `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 ../.venv/bin/python
eval/accuracy_2026-11/score.py eval/accuracy_2026-11/arms.json`. Runs live in `~/Documents/Parameter
Extractor/accuracy_20261120/` (local, not in the repository; papers in `Paper Files/Accuracy Test 2026-11/`).
