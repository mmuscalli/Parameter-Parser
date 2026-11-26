# Controlled test: the chosen columns only

## A0: Standard, 0.6.0 (Nov 20), built-in pack

Hand: 1037 printed values in 35 papers; recall 0.841 (close 0.863); agreement 0.861; 569 hand values not printed (figures, calculated) not scored.
Model standard: 525 values in 11 papers; recall 0.943 (close 0.943); agreement 0.996.

| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |
|---|---|---|---|---|---|---|
| `sampled_Gly-Gly_aq_%yield` | 240 | 0.883 | 0.882 | 109 | 1.0 | 1.0 |
| `duration_hr` | 118 | 0.814 | 0.829 | 48 | 1.0 | 1.0 |
| `initial_pH` | 81 | 0.481 | 0.636 | 12 | 1.0 | 1.0 |
| `sampled_cyclo_Gly-Gly_aq_%yield` | 75 | 0.92 | 0.886 | 69 | 1.0 | 1.0 |
| `initial_temperature_C` | 66 | 0.955 | 0.857 | 25 | 1.0 | 0.926 |
| `sampled_cyclo_Ala-Ala_aq_%yield` | 51 | 1.0 | 1.0 | 42 | 1.0 | 1.0 |
| `sampled_Phe-Phe_aq_%yield` | 49 | 1.0 | 0.961 | 1 | 0.0 | – |
| `sampled_Ala-Ala_aq_%yield` | 46 | 0.957 | 0.754 | 35 | 0.971 | 1.0 |
| `sampled_Gly-Gly-Gly_aq_%yield` | 41 | 0.927 | 0.821 | 42 | 1.0 | 1.0 |
| `paper_title` | 35 | 0.943 | 0.971 | 11 | 1.0 | 1.0 |
| `author_list` | 35 | 0.914 | 0.941 | 11 | 0.909 | 1.0 |
| `initial_Gly_aq_mM` | 34 | 0.912 | 0.868 | 16 | 1.0 | 1.0 |
| `year_published` | 30 | 1.0 | 1.0 | 11 | 1.0 | 1.0 |
| `solid_material_name` | 28 | 0.286 | 0.857 | 14 | 0.143 | 1.0 |
| `initial_CuCl2_aq_mM` | 12 | 0.833 | 0.769 | 9 | 1.0 | 1.0 |
| `headspace_gas_name` | 10 | 0.9 | 0.769 | 5 | 0.6 | 1.0 |
| `initial_NaCl_aq_mM` | 9 | 0.667 | 0.545 | 8 | 1.0 | 1.0 |
| `solid_material_mass_g` | 9 | 0.778 | 1.0 | 3 | 1.0 | 1.0 |
| `cycle_number` | 9 | 0.556 | 1.0 | 9 | 0.556 | 1.0 |
| `sampled_Asp-Asp_aq_%yield` | 8 | 0.0 | – | 0 | – | – |
| `sampled_(Gly)4_aq_%yield` | 8 | 1.0 | 1.0 | 16 | 1.0 | 1.0 |
| `initial_Ala_aq_mM` | 7 | 0.857 | 0.875 | 6 | 0.667 | 1.0 |
| `initial_Phe_aq_mM` | 6 | 0.5 | 0.5 | 1 | 0.0 | – |
| `initial_Asp_aq_mM` | 5 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Met-Met_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `initial_sodium_triMP_aq_mM` | 4 | 1.0 | 0.857 | 0 | – | – |
| `sampled_Val-Val_aq_%yield` | 3 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `flow_rate_mL_min` | 3 | 0.333 | 1.0 | 2 | 0.5 | 1.0 |
| `sampled_Trp-Trp_aq_%yield` | 3 | 1.0 | 1.0 | 0 | – | – |
| `initial_Cys-_aq_mM` | 2 | 0.0 | – | 0 | – | – |
| `sampled_Phe-Phe-Phe_aq_%yield` | 2 | 1.0 | 1.0 | 1 | 0.0 | – |
| `initial_Met_aq_mM` | 1 | 0.0 | – | 0 | – | – |
| `sampled_Ala-Ala-Ala_aq_%yield` | 1 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Val_aq_mM` | 1 | 0.0 | 1.0 | 0 | – | – |
| `initial_Trp_aq_mM` | 1 | 0.0 | – | 0 | – | – |
| `sampled_His-His_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Asp-Asp-Asp_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Ser-Ser_aq_%yield` | 0 | – | – | 0 | – | – |
| `max_oligomer_length_nt` | 0 | – | – | 4 | 0.25 | 1.0 |
| `initial_Cys_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_His_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_Ser_aq_mM` | 0 | – | 1.0 | 1 | 0.0 | – |
| `analysis_method` | 0 | – | – | 12 | 1.0 | 1.0 |

## A1: Standard, 0.6.11, Must answer pack

Hand: 1037 printed values in 35 papers; recall 0.875 (close 0.894); agreement 0.866; 569 hand values not printed (figures, calculated) not scored.
Model standard: 525 values in 11 papers; recall 0.97 (close 0.97); agreement 0.996.

| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |
|---|---|---|---|---|---|---|
| `sampled_Gly-Gly_aq_%yield` | 240 | 0.908 | 0.895 | 109 | 0.991 | 1.0 |
| `duration_hr` | 118 | 0.814 | 0.833 | 48 | 1.0 | 1.0 |
| `initial_pH` | 81 | 0.58 | 0.705 | 12 | 1.0 | 1.0 |
| `sampled_cyclo_Gly-Gly_aq_%yield` | 75 | 0.92 | 0.886 | 69 | 1.0 | 1.0 |
| `initial_temperature_C` | 66 | 0.97 | 0.859 | 25 | 1.0 | 0.926 |
| `sampled_cyclo_Ala-Ala_aq_%yield` | 51 | 1.0 | 0.984 | 42 | 1.0 | 1.0 |
| `sampled_Phe-Phe_aq_%yield` | 49 | 1.0 | 0.942 | 1 | 1.0 | 1.0 |
| `sampled_Ala-Ala_aq_%yield` | 46 | 0.957 | 0.75 | 35 | 1.0 | 1.0 |
| `sampled_Gly-Gly-Gly_aq_%yield` | 41 | 0.951 | 0.823 | 42 | 1.0 | 1.0 |
| `paper_title` | 35 | 0.971 | 1.0 | 11 | 1.0 | 1.0 |
| `author_list` | 35 | 0.914 | 0.97 | 11 | 0.909 | 1.0 |
| `initial_Gly_aq_mM` | 34 | 0.912 | 0.892 | 16 | 1.0 | 1.0 |
| `year_published` | 30 | 1.0 | 1.0 | 11 | 1.0 | 1.0 |
| `solid_material_name` | 28 | 0.714 | 0.895 | 14 | 0.643 | 1.0 |
| `initial_CuCl2_aq_mM` | 12 | 0.833 | 0.769 | 9 | 1.0 | 1.0 |
| `headspace_gas_name` | 10 | 0.9 | 0.818 | 5 | 1.0 | 1.0 |
| `initial_NaCl_aq_mM` | 9 | 0.889 | 0.615 | 8 | 1.0 | 1.0 |
| `solid_material_mass_g` | 9 | 0.778 | 1.0 | 3 | 1.0 | 1.0 |
| `cycle_number` | 9 | 0.556 | 1.0 | 9 | 0.556 | 1.0 |
| `sampled_Asp-Asp_aq_%yield` | 8 | 0.0 | – | 0 | – | – |
| `sampled_(Gly)4_aq_%yield` | 8 | 1.0 | 1.0 | 16 | 1.0 | 1.0 |
| `initial_Ala_aq_mM` | 7 | 0.857 | 0.875 | 6 | 1.0 | 1.0 |
| `initial_Phe_aq_mM` | 6 | 0.667 | 0.5 | 1 | 1.0 | 1.0 |
| `initial_Asp_aq_mM` | 5 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Met-Met_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `initial_sodium_triMP_aq_mM` | 4 | 1.0 | 0.857 | 0 | – | – |
| `sampled_Val-Val_aq_%yield` | 3 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `flow_rate_mL_min` | 3 | 0.333 | 1.0 | 2 | 0.5 | 1.0 |
| `sampled_Trp-Trp_aq_%yield` | 3 | 1.0 | 1.0 | 0 | – | – |
| `initial_Cys-_aq_mM` | 2 | 0.0 | – | 0 | – | – |
| `sampled_Phe-Phe-Phe_aq_%yield` | 2 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Met_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Ala-Ala-Ala_aq_%yield` | 1 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Val_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `initial_Trp_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_His-His_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Asp-Asp-Asp_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Ser-Ser_aq_%yield` | 0 | – | – | 0 | – | – |
| `max_oligomer_length_nt` | 0 | – | – | 4 | 0.0 | – |
| `initial_Cys_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_His_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_Ser_aq_mM` | 0 | – | 1.0 | 1 | 1.0 | 1.0 |
| `analysis_method` | 0 | – | – | 12 | 1.0 | 1.0 |

## B0: Economy x3, 0.6.0 (Nov 20), built-in pack

Hand: 1037 printed values in 35 papers; recall 0.86 (close 0.881); agreement 0.856; 569 hand values not printed (figures, calculated) not scored.
Model standard: 525 values in 11 papers; recall 0.958 (close 0.964); agreement 0.994.

| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |
|---|---|---|---|---|---|---|
| `sampled_Gly-Gly_aq_%yield` | 240 | 0.854 | 0.886 | 109 | 0.991 | 1.0 |
| `duration_hr` | 118 | 0.797 | 0.821 | 48 | 0.979 | 1.0 |
| `initial_pH` | 81 | 0.432 | 0.535 | 12 | 0.417 | 1.0 |
| `sampled_cyclo_Gly-Gly_aq_%yield` | 75 | 0.92 | 0.886 | 69 | 1.0 | 1.0 |
| `initial_temperature_C` | 66 | 0.955 | 0.837 | 25 | 1.0 | 0.926 |
| `sampled_cyclo_Ala-Ala_aq_%yield` | 51 | 1.0 | 1.0 | 42 | 1.0 | 1.0 |
| `sampled_Phe-Phe_aq_%yield` | 49 | 1.0 | 0.98 | 1 | 0.0 | – |
| `sampled_Ala-Ala_aq_%yield` | 46 | 0.826 | 0.75 | 35 | 0.943 | 1.0 |
| `sampled_Gly-Gly-Gly_aq_%yield` | 41 | 0.927 | 0.842 | 42 | 0.952 | 1.0 |
| `paper_title` | 35 | 0.971 | 0.971 | 11 | 1.0 | 1.0 |
| `author_list` | 35 | 0.914 | 0.97 | 11 | 0.909 | 1.0 |
| `initial_Gly_aq_mM` | 34 | 0.941 | 0.857 | 16 | 1.0 | 1.0 |
| `year_published` | 30 | 1.0 | 1.0 | 11 | 1.0 | 1.0 |
| `solid_material_name` | 28 | 0.857 | 0.9 | 14 | 0.929 | 1.0 |
| `initial_CuCl2_aq_mM` | 12 | 0.75 | 0.9 | 9 | 1.0 | 1.0 |
| `headspace_gas_name` | 10 | 1.0 | 0.688 | 5 | 1.0 | 0.833 |
| `initial_NaCl_aq_mM` | 9 | 0.889 | 0.615 | 8 | 1.0 | 1.0 |
| `solid_material_mass_g` | 9 | 1.0 | 0.818 | 3 | 1.0 | 1.0 |
| `cycle_number` | 9 | 1.0 | 1.0 | 9 | 1.0 | 1.0 |
| `sampled_Asp-Asp_aq_%yield` | 8 | 1.0 | 1.0 | 0 | – | – |
| `sampled_(Gly)4_aq_%yield` | 8 | 1.0 | 1.0 | 16 | 1.0 | 1.0 |
| `initial_Ala_aq_mM` | 7 | 1.0 | 0.889 | 6 | 1.0 | 1.0 |
| `initial_Phe_aq_mM` | 6 | 0.667 | 0.5 | 1 | 1.0 | 1.0 |
| `initial_Asp_aq_mM` | 5 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Met-Met_aq_%yield` | 4 | 1.0 | 1.0 | 0 | – | – |
| `initial_sodium_triMP_aq_mM` | 4 | 1.0 | 0.857 | 0 | – | – |
| `sampled_Val-Val_aq_%yield` | 3 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `flow_rate_mL_min` | 3 | 0.333 | 1.0 | 2 | 0.5 | 1.0 |
| `sampled_Trp-Trp_aq_%yield` | 3 | 1.0 | 1.0 | 0 | – | – |
| `initial_Cys-_aq_mM` | 2 | 0.0 | – | 0 | – | – |
| `sampled_Phe-Phe-Phe_aq_%yield` | 2 | 1.0 | 1.0 | 1 | 0.0 | – |
| `initial_Met_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Ala-Ala-Ala_aq_%yield` | 1 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Val_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `initial_Trp_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_His-His_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Asp-Asp-Asp_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Ser-Ser_aq_%yield` | 0 | – | – | 0 | – | – |
| `max_oligomer_length_nt` | 0 | – | – | 4 | 0.0 | – |
| `initial_Cys_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_His_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_Ser_aq_mM` | 0 | – | 1.0 | 1 | 1.0 | 1.0 |
| `analysis_method` | 0 | – | – | 12 | 1.0 | 1.0 |

## B1: Economy x3, 0.6.11, Must answer pack

Hand: 1037 printed values in 35 papers; recall 0.86 (close 0.881); agreement 0.872; 569 hand values not printed (figures, calculated) not scored.
Model standard: 525 values in 11 papers; recall 0.96 (close 0.962); agreement 0.99.

| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |
|---|---|---|---|---|---|---|
| `sampled_Gly-Gly_aq_%yield` | 240 | 0.888 | 0.892 | 109 | 0.991 | 1.0 |
| `duration_hr` | 118 | 0.814 | 0.837 | 48 | 1.0 | 1.0 |
| `initial_pH` | 81 | 0.506 | 0.746 | 12 | 1.0 | 1.0 |
| `sampled_cyclo_Gly-Gly_aq_%yield` | 75 | 0.92 | 0.886 | 69 | 1.0 | 1.0 |
| `initial_temperature_C` | 66 | 0.939 | 0.855 | 25 | 0.96 | 0.923 |
| `sampled_cyclo_Ala-Ala_aq_%yield` | 51 | 1.0 | 0.984 | 42 | 1.0 | 1.0 |
| `sampled_Phe-Phe_aq_%yield` | 49 | 0.918 | 1.0 | 1 | 0.0 | – |
| `sampled_Ala-Ala_aq_%yield` | 46 | 0.87 | 0.742 | 35 | 0.943 | 1.0 |
| `sampled_Gly-Gly-Gly_aq_%yield` | 41 | 0.951 | 0.823 | 42 | 0.976 | 1.0 |
| `paper_title` | 35 | 0.943 | 0.971 | 11 | 1.0 | 1.0 |
| `author_list` | 35 | 0.914 | 0.941 | 11 | 0.909 | 1.0 |
| `initial_Gly_aq_mM` | 34 | 0.941 | 0.895 | 16 | 1.0 | 1.0 |
| `year_published` | 30 | 1.0 | 1.0 | 11 | 1.0 | 1.0 |
| `solid_material_name` | 28 | 0.643 | 0.85 | 14 | 0.5 | 0.875 |
| `initial_CuCl2_aq_mM` | 12 | 0.833 | 0.769 | 9 | 1.0 | 1.0 |
| `headspace_gas_name` | 10 | 1.0 | 0.786 | 5 | 1.0 | 1.0 |
| `initial_NaCl_aq_mM` | 9 | 0.889 | 0.615 | 8 | 1.0 | 1.0 |
| `solid_material_mass_g` | 9 | 1.0 | 1.0 | 3 | 1.0 | 1.0 |
| `cycle_number` | 9 | 1.0 | 1.0 | 9 | 1.0 | 1.0 |
| `sampled_Asp-Asp_aq_%yield` | 8 | 1.0 | 1.0 | 0 | – | – |
| `sampled_(Gly)4_aq_%yield` | 8 | 1.0 | 1.0 | 16 | 1.0 | 1.0 |
| `initial_Ala_aq_mM` | 7 | 1.0 | 0.889 | 6 | 1.0 | 1.0 |
| `initial_Phe_aq_mM` | 6 | 0.667 | 0.5 | 1 | 1.0 | 1.0 |
| `initial_Asp_aq_mM` | 5 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Met-Met_aq_%yield` | 4 | 0.0 | – | 0 | – | – |
| `initial_sodium_triMP_aq_mM` | 4 | 1.0 | 0.857 | 0 | – | – |
| `sampled_Val-Val_aq_%yield` | 3 | 0.333 | 1.0 | 1 | 1.0 | 1.0 |
| `flow_rate_mL_min` | 3 | 0.667 | 1.0 | 2 | 0.5 | 0.5 |
| `sampled_Trp-Trp_aq_%yield` | 3 | 0.0 | – | 0 | – | – |
| `initial_Cys-_aq_mM` | 2 | 0.0 | – | 0 | – | – |
| `sampled_Phe-Phe-Phe_aq_%yield` | 2 | 1.0 | 1.0 | 1 | 0.0 | – |
| `initial_Met_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_Ala-Ala-Ala_aq_%yield` | 1 | 1.0 | 1.0 | 1 | 1.0 | 1.0 |
| `initial_Val_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `initial_Trp_aq_mM` | 1 | 1.0 | 1.0 | 0 | – | – |
| `sampled_His-His_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Asp-Asp-Asp_aq_%yield` | 0 | – | – | 0 | – | – |
| `sampled_Ser-Ser_aq_%yield` | 0 | – | – | 0 | – | – |
| `max_oligomer_length_nt` | 0 | – | – | 4 | 0.0 | – |
| `initial_Cys_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_His_aq_mM` | 0 | – | – | 0 | – | – |
| `initial_Ser_aq_mM` | 0 | – | 1.0 | 1 | 1.0 | 1.0 |
| `analysis_method` | 0 | – | – | 12 | 0.917 | 0.923 |
