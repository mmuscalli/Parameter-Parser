# Controlled test (2026-11-25, Mickey)

39 papers (`Paper Files/Paper Lists/Initial Easy Papers/Controlled Test Papers/`, all in batch P1 of the accuracy
evaluation) and the 45 'Must answer' columns of Mickey's data pack *Controlled Test Prebio Dupe* (a copy of the
prebiotic pack). Runs are scored on those columns only: a row needn't represent its whole experiment.

`score_columns.py config.json`: per arm, paper and column, the distinct values each side has, against the hand dataset
(printed values only; zeros left out) and the checked model standard where there is one (11 of the 39). Writes
per_paper_column.csv, per_column.csv and summary.md to the config's `out`.

## Baseline: the November runs (0.6.0, built-in pack, no Must answer), `baseline_0.6.0.json` -> `baseline_0.6.0/`

| Arm | Cost (39 papers) | Hand recall (1,291 printed values, 35 papers) | Agreement | MS recall (527 values, 11 papers) |
|---|---|---|---|---|
| A Standard | $4.22 | 0.722 (close 0.749) | 0.858 | 0.941 |
| B Economy x3 | $0.70 | 0.738 (close 0.763) | 0.855 | 0.934 |

Weak columns (Standard hand recall): `initial_pressure_bar` 0.18 (the hand values are mostly converted or assumed:
1 atm = 0.9993 bar, saturation pressures), `solid_material_name` 0.25 (Economy 0.79; the solid-material fix came after
0.6.0), `initial_pH` 0.43, `duration_hr` 0.70. `initial_total_monomers_aq_mM` (50 hand values) is calculated in the
hand dataset and nothing in the app fills it. The 'printed' check is loose (a number anywhere in the text, x/÷ 1000 or
100), so a few calculated hand values (1 bar from 1 atm) still count as printed.

## Run 1 (2026-11-25, 0.6.11; Mickey's 43 columns after unticking initial_total_monomers_aq_mM and initial_pressure_bar), `run_20261125.json` -> `run_20261125/`

Same 39 PDFs (the P1 copies), batch mode, the data pack *Controlled Test Prebio Dupe* with its Must answer columns.
The baseline arms (A0, B0) are rescored on the same 43 columns. Queues: `~/Documents/Parameter Extractor/controlled_test_20261125/`.

| Arm | Cost | Hand recall (1,208 printed values, 35 papers) | Agreement | MS recall (525 values, 11 papers) |
|---|---|---|---|---|
| A0 Standard, 0.6.0 | $4.22 | 0.768 | 0.864 | 0.943 |
| **A1 Standard, 0.6.11, Must answer** | $4.67 | **0.803** | 0.870 | **0.970** |
| B0 Economy x3, 0.6.0 | $0.70 | 0.785 | 0.861 | 0.958 |
| B1 Economy x3, 0.6.11, Must answer | $0.93 | 0.783 | 0.876 | 0.960 |

- A0 -> A1 is 0.6.0 -> 0.6.11 as well as Must answer (the solid-material fix among them), so the gain isn't Must
  answer's alone. Gains: initial_pH 0.43 -> 0.60, solid_material_name 0.29 -> 0.71, initial_NaCl 0.67 -> 0.89.
  Economy is unchanged overall.
- Still low on both: duration_hr 0.70 (161 values), initial_pH (B1 0.43), sampled_(Gly)4 0.67, flow_rate 0.33;
  Standard alone: cycle_number 0.56 and sampled_Asp-Asp 0 (Economy has both).
- The B1 queue first failed on every paper: a step voted over 3 passes lost its `checked` answers (fixed in 0.6.12,
  voting.vote_stage); resumed from the saved answers for $0.03.
- parameter_checks.csv: Standard 490 'reported', 1,168 'not reported', 18 'unclear'; 32 answers disagree with the
  values written (parameter_check flags), Economy 36.
- Text columns: names match either way round ('goethite' / 'goethite (alpha-FeOOH)'); the baseline numbers above the
  run moved slightly with that change.

## Why duration_hr and initial_pH were missed (2026-11-25)

Every hand value the runs missed was traced to the paper (scratch scripts: misses per paper, pH mentions).

**Scoring changes** (the numbers above were rescored): a hand value counts as printed only when the paper prints it
at that precision (7.2177 read off a figure no longer counts because the text has a '7' somewhere); a run's value
matches within the hand value's own rounding (0.08 h vs 0.0833 h, 5 min); a column's range column counts as its
values (initial_pH_range 4:5). Hand recall now: A0 0.841, **A1 0.875**, B0 0.860, B1 0.860 (1,037 printed values;
569 not printed: figures, calculated). duration_hr 0.81 (A1), initial_pH 0.58 (A1) / 0.51 (B1).

**duration_hr: the app is right in nearly every remaining case.**
- Hand values in DAYS in the hours column: Halmann1968 (2-28 for 48-672 h), Rabinowitz1978 (14, 26 for 336, 624 h).
- Figure-only times: Eder1994 (Fig. 1's short runs), Fuchida2016 (Fig. 4; Table 1 is 8 days = 192 h, which the app
  has), Takaoka1991 (Table I gives rates per day; times only in figures), Chen2007 (2 h, Figure 1), Nooner1977
  (hand 24 h; Table 2's footnote says 16 h, which the app has), Zamaraev1996, fuchida2014, Rode1990, Schwendinger1991.

**initial_pH: four causes.**
1. Figures: Eder1994 (Fig. 1's caption lists pH 1.93-3.04 per curve), Rode1990 (Fig. 2, pH 2 and 3).
2. Final pH: Leman2004's table column is "Final pH" -- the app puts it in sampled_pH (right); the hand dataset has it
   in sampled_pH AND initial_pH (also faisal2005). A convention question, not an extraction error.
3. A pH column that doesn't say when it was measured went to initial_pH in one run and sampled_pH in another
   (Huber1998, faisal2005: Standard initial, Economy sampled): the step's two descriptions overlapped ("a 'pH'
   column of the conditions" / "a pH column among the results").
4. Found but held back as 'unclear', with nothing written: Schwendinger1991 (pH 2.8 for every experiment, only in
   figure captions), Zamaraev1996 (pH of the silicate suspensions, Table II, "not reaction start").
   Debatable: Matrajt2003 (pH 5-6 said for the adsorption experiments), Rabinowitz1985 (the table's measured ranges
   while the pH was readjusted daily to 8.9 or 10.5; the app gives the targets).

**Changes (0.6.13):** initial_pH / sampled_pH descriptions (prebiotic experimental_conditions, lab_experiment
lab_conditions, and Mickey's dupe pack, backed up in pack_backups/): an untimed pH column, a measured pH of the
reaction mixture or suspension, and a pH stated once for all experiments (methods or only figure captions, as a
paper-wide value) go to initial_pH; sampled_pH only when the paper says after the reaction / at sampling. A Must
answer marked 'unclear' with no value is now a parameter_check flag carrying the model's note.
