# Controlled test: the chosen columns only

## A: Standard (0.6.0, built-in pack)

Hand: 1291 printed values in 35 papers; recall 0.722 (close 0.749); agreement 0.858; 446 hand values not printed (figures, calculated) not scored.
Model standard: 527 values in 11 papers; recall 0.941 (close 0.941); agreement 1.0.

| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |
|---|---|---|---|---|---|---|
| `sampled_Gly-Gly_aq_%yield` | 285 | 0.765 | 0.875 | 109 | 1.0 | 1.0 |
| `duration_hr` | 161 | 0.702 | 0.817 | 48 | 1.0 | 1.0 |
| `initial_pH` | 88 | 0.432 | 0.683 | 12 | 1.0 | 1.0 |
| `sampled_cyclo_Gly-Gly_aq_%yield` | 86 | 0.814 | 0.886 | 69 | 1.0 | 1.0 |
| `sampled_Gly-Gly-Gly_aq_%yield` | 70 | 0.9 | 0.821 | 42 | 1.0 | 1.0 |
| `initial_temperature_C` | 66 | 0.955 | 0.9 | 25 | 1.0 | 1.0 |
| `sampled_cyclo_Ala-Ala_aq_%yield` | 60 | 0.9 | 1.0 | 42 | 1.0 | 1.0 |
| `sampled_Phe-Phe_aq_%yield` | 57 | 0.86 | 0.961 | 1 | 0.0 | – |
| `sampled_Ala-Ala_aq_%yield` | 54 | 0.833 | 0.754 | 35 | 0.971 | 1.0 |
| `initial_total_monomers_aq_mM` | 50 | 0.0 | – | 0 | – | – |
| `paper_title` | 35 | 0.943 | 0.971 | 11 | 1.0 | 1.0 |
| `initial_Gly_aq_mM` | 35 | 0.857 | 0.889 | 16 | 1.0 | 1.0 |
| `author_list` | 35 | 0.886 | 0.941 | 11 | 0.909 | 1.0 |
| `year_published` | 34 | 1.0 | 1.0 | 11 | 1.0 | 1.0 |
| `initial_pressure_bar` | 33 | 0.182 | 0.429 | 2 | 1.0 | 1.0 |
| `solid_material_name` | 28 | 0.25 | 0.714 | 14 | 0.143 | 1.0 |
| `initial_CuCl2_aq_mM` | 13 | 0.769 | 0.769 | 9 | 1.0 | 1.0 |
| `sampled_(Gly)4_aq_%yield` | 12 | 0.667 | 1.0 | 16 | 1.0 | 1.0 |
| `headspace_gas_name` | 10 | 0.9 | 0.769 | 5 | 0.6 | 1.0 |
| `solid_material_mass_g` | 9 | 0.778 | 1.0 | 3 | 1.0 | 1.0 |
| `cycle_number` | 9 | 0.556 | 1.0 | 9 | 0.556 | 1.0 |
| `initial_NaCl_aq_mM` | 9 | 0.667 | 0.545 | 8 | 1.0 | 1.0 |
| `sampled_Asp-Asp_aq_%yield` | 8 | 0.0 | – | 0 | – | – |
| `initial_Ala_aq_mM` | 7 | 0.857 | 0.875 | 6 | 0.667 | 1.0 |
| `initial_Phe_aq_mM` | 6 | 0.5 | 0.5 | 1 | 0.0 | – |
| `initial_Asp_aq_mM` | 5 | 1.0 | 1.0 | 0 | – | – |
| `initial_sodium_triMP_aq_mM` | 4 | 1.0 | 0.857 | 0 | – | – |
| `sampled_Trp-Trp_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Met-Met_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `flow_rate_mL_min` | 3 | 0.333 | 1.0 | 2 | 0.5 | 1.0 |
| `sampled_Val-Val_aq_%yield` | 3 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `sampled_Phe-Phe-Phe_aq_%yield` | 2 | 1.0 | 1.0 | 1 | 0.0 | – |
| `initial_Cys-_aq_mM` | 2 | 0.0 | – | 0 | – | – |
| `initial_Met_aq_mM` | 1 | 0.0 | – | 0 | – | – |
| `initial_Val_aq_mM` | 1 | 0.0 | 1.0 | 0 | – | – |
| `sampled_Ala-Ala-Ala_aq_%yield` | 1 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Trp_aq_mM` | 1 | 0.0 | – | 0 | – | – |
| `sampled_Asp-Asp-Asp_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Ser-Ser_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_His-His_aq_%yield` | 0 | – | – | 0 | – | – |
| `max_oligomer_length_nt` | 0 | – | – | 4 | 0.25 | 1.0 |
| `initial_Cys_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_His_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_Ser_aq_mM` | 0 | – | 1.0 | 1 | 0.0 | – |
| `analysis_method` | 0 | – | – | 12 | 0.917 | 1.0 |

## B: Economy x3 (0.6.0, built-in pack)

Hand: 1291 printed values in 35 papers; recall 0.738 (close 0.763); agreement 0.855; 446 hand values not printed (figures, calculated) not scored.
Model standard: 527 values in 11 papers; recall 0.934 (close 0.939); agreement 0.996.

| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |
|---|---|---|---|---|---|---|
| `sampled_Gly-Gly_aq_%yield` | 285 | 0.74 | 0.878 | 109 | 0.991 | 1.0 |
| `duration_hr` | 161 | 0.689 | 0.809 | 48 | 0.979 | 1.0 |
| `initial_pH` | 88 | 0.386 | 0.597 | 12 | 0.417 | 1.0 |
| `sampled_cyclo_Gly-Gly_aq_%yield` | 86 | 0.814 | 0.886 | 69 | 1.0 | 1.0 |
| `sampled_Gly-Gly-Gly_aq_%yield` | 70 | 0.9 | 0.842 | 42 | 0.952 | 1.0 |
| `initial_temperature_C` | 66 | 0.955 | 0.878 | 25 | 1.0 | 1.0 |
| `sampled_cyclo_Ala-Ala_aq_%yield` | 60 | 0.9 | 1.0 | 42 | 1.0 | 1.0 |
| `sampled_Phe-Phe_aq_%yield` | 57 | 0.86 | 0.98 | 1 | 0.0 | – |
| `sampled_Ala-Ala_aq_%yield` | 54 | 0.741 | 0.75 | 35 | 0.943 | 1.0 |
| `initial_total_monomers_aq_mM` | 50 | 0.0 | – | 0 | – | – |
| `paper_title` | 35 | 0.971 | 0.971 | 11 | 1.0 | 1.0 |
| `initial_Gly_aq_mM` | 35 | 0.886 | 0.868 | 16 | 1.0 | 1.0 |
| `author_list` | 35 | 0.886 | 0.97 | 11 | 0.909 | 1.0 |
| `year_published` | 34 | 0.971 | 1.0 | 11 | 1.0 | 1.0 |
| `initial_pressure_bar` | 33 | 0.242 | 0.5 | 2 | 1.0 | 1.0 |
| `solid_material_name` | 28 | 0.786 | 0.85 | 14 | 0.429 | 0.889 |
| `initial_CuCl2_aq_mM` | 13 | 0.692 | 0.9 | 9 | 1.0 | 1.0 |
| `sampled_(Gly)4_aq_%yield` | 12 | 0.667 | 1.0 | 16 | 1.0 | 1.0 |
| `headspace_gas_name` | 10 | 1.0 | 0.688 | 5 | 0.6 | 0.833 |
| `solid_material_mass_g` | 9 | 1.0 | 0.818 | 3 | 1.0 | 1.0 |
| `cycle_number` | 9 | 1.0 | 1.0 | 9 | 1.0 | 1.0 |
| `initial_NaCl_aq_mM` | 9 | 0.889 | 0.615 | 8 | 1.0 | 1.0 |
| `sampled_Asp-Asp_aq_%yield` | 8 | 1.0 | 1.0 | 0 | – | – |
| `initial_Ala_aq_mM` | 7 | 1.0 | 0.889 | 6 | 1.0 | 1.0 |
| `initial_Phe_aq_mM` | 6 | 0.667 | 0.5 | 1 | 1.0 | 1.0 |
| `initial_Asp_aq_mM` | 5 | 1.0 | 1.0 | 0 | – | – |
| `initial_sodium_triMP_aq_mM` | 4 | 1.0 | 0.857 | 0 | – | – |
| `sampled_Trp-Trp_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Met-Met_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `flow_rate_mL_min` | 3 | 0.333 | 1.0 | 2 | 0.5 | 1.0 |
| `sampled_Val-Val_aq_%yield` | 3 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `sampled_Phe-Phe-Phe_aq_%yield` | 2 | 1.0 | 1.0 | 1 | 0.0 | – |
| `initial_Cys-_aq_mM` | 2 | 0.0 | – | 0 | – | – |
| `initial_Met_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `initial_Val_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Ala-Ala-Ala_aq_%yield` | 1 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Trp_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Asp-Asp-Asp_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Ser-Ser_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_His-His_aq_%yield` | 0 | – | – | 0 | – | – |
| `max_oligomer_length_nt` | 0 | – | – | 4 | 0.0 | – |
| `initial_Cys_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_His_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_Ser_aq_mM` | 0 | – | 1.0 | 1 | 1.0 | 1.0 |
| `analysis_method` | 0 | – | – | 12 | 0.667 | 1.0 |
