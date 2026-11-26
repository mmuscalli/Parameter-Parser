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
