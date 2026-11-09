# Drafting a data pack with modules (2026-11-09)

Mickey asked whether "new data pack from sample papers" uses the module format correctly, and how well it works
overall. The test drafted a pack from four papers that call for every module: kim2017 (HPLC, nucleotides, dry-down),
truman2024 (wet-dry cycling, peptides), mitsuzawa2004 (kinetics, peptides), Riggi2023 (MALDI, oligonucleotides).
The drafts used Standard models with two survey passes, run live. One paper drafting hadn't seen, eder1994, was then
extracted with the drafted pack.

## Before: modules were added after the design

The design request didn't know which modules would be linked. They were attached afterwards, so the draft asked for the
same values twice:

| Drafted pack (before) | Duplicated |
|---|---|
| step "analytical_methods" (HPLC/MALDI keywords) | the Analysis methods module's step |
| step "kinetics_fits" (rate constants) | the Kinetics module's step: two kinetics requests per paper |
| `cycle_number` in the conditions step | the Wet-dry module's step |
| step "results": product_name, product_yield_pct, product_concentration, max_oligomer_length_nt, total_peptide_yield_pct | the chemistry step (per compound) and the totals calculations |
| starting_material / salt_or_additive + their concentrations | the chemistry step |

Other problems:

- The chemistry step (brought along by the totals module) had no compound vocabulary, and the check warned about it.
- A drafted step named like a module's step (`kinetics`) would have replaced the module's step without any notice.

## After

1. **Modules first.** The surveys choose the modules before the design. Solution chemistry now has its own evidence:
   compounds with concentrations or amounts in solution.
2. **The design request knows them.** It gets a "SHARED MODULES" section built from each module's new `covers` text.
3. **Safety net.** A parameter or step a linked module covers is left out and listed under "Left to the modules" in
   the report. A step whose name clashes with a module's step is renamed.
4. **Compounds.** The compound vocabulary is filled from the surveys whenever the chemistry step is linked (PubChem
   when online lookups are on).
   - Compounds used only for analysis (mobile phases, MALDI matrices) get a new survey role, `analysis`, and stay out.
   - The paper's compound numbers are stripped ('nicotinamide 6', '4').
   - A product's measure comes from how the paper reports it: '13.96 %' gives a `% yield` column.

| | Before | After |
|---|---|---|
| Pack's own steps | 4 (2 always-on) | 2 to 4, none duplicating a module (two runs) |
| Parameters | 28 | 20 / 17 |
| Duplicate requests per paper | up to 3 | 0 |
| Chemistry step's compound vocabulary | none (check warning) | 16 compounds, no analysis reagents |
| Check problems | 1 warning | 0 |
| Draft cost | $0.084 | $0.082 / $0.087 |

## Extraction with the drafted pack (eder1994, which drafting didn't see)

- The live run was $0.22 and took 50 s.
- **First try:** the pack's conditions step returned its list as a JSON string with stray words after it ("...]\nthe
  rows"), twice, and the run failed. The client's repair (`api_client._decoded`) now takes the complete JSON at the
  start of such a string. This affects every pack.
- **Result:** 42 rows, the same as the hand-checked reference. The durations, temperatures, starting glycine, the salts
  in the vocabulary (NaCl, KCl, CaCl2) and 14 RP-HPLC settings were right.
- **Product yields:** Gly-Gly and Gly3 % yields were extracted correctly, but at first they waited in the review,
  because the vocabulary had no `% yield` columns. With the measure fix, replaying the recorded answers through the
  rebuilt vocabulary gives 150 of 150 compared values equal to the reference (starting glycine, both yields, the
  calculated total peptide yield).
- **Not captured, as expected:**
  - Five salts none of the sample papers used (BaCl2, CsCl, CuCl2, MgCl2, NH4Cl). They were extracted and are offered in
    the review.
  - Condition columns the hand-made pack has but this design didn't include (vessel, headspace gas, solution type).
    Suggest additions, or drafting from more varied papers, adds them.

## Remaining limits

- The surveys vary between runs: one listed Gly2 to Gly13, the next only Gly2, Gly3 and Gly13. Two survey passes are
  the default; three would catch more.
- The design sometimes makes an always-on step for a few loosely related values ("results": equilibrium constant, fit
  RMSE, stereoselectivity). That costs a request per paper. The two-always-on limit holds, but such a step could be
  merged.
