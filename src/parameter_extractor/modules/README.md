# Modules

A **module** is a shared part of data packs: a step, calculations, columns, rules or a vocabulary that several
data packs use. Packs **link** modules by id (`"modules": [...]` in their pack.json); nothing is copied, so a module
improved here reaches every pack that links it. A pack changes how a module works for itself only through its
`module_settings` (see the template pack's README, or the editor's *Module settings* tab).

| Word | Meaning |
|---|---|
| step | one request to the AI model for each paper it runs for |
| built-in step | a step written in the app's code (`chemistry`, `analysis`, `fit_models`) |
| configurable step | a step described in a JSON file (`stages/*.json`) |
| calculation | done on your computer from the model's answers; no model requests |

## A module's folder

| File | What it holds |
|---|---|
| `module.json` | id, label, description, and what the module brings (below) |
| `stages/*.json` | its configurable steps, in the same format as a pack's |
| `prompts/*.md` | a prompt one of its built-in steps needs (the chemistry step's) |
| `analysis_vocab.json` | the analysis step's techniques and instrument settings |
| `compounds.json`, `species_cids.json` | compounds (species names and their dataset columns) and their PubChem identities a pack linking the module gets when it lacks them, after its own (peptides_oligomers, solution_chemistry: from the prebiotic pack's vocabulary, `scripts/build_module_compounds.py`) |

`module.json` keys:

| Key | What it does in a pack that links the module |
|---|---|
| `builtin_stages` | switches these built-in steps on |
| `postprocess` | adds these calculations |
| `needs` | links these modules too (product totals brings solution chemistry) |
| `variable_categories`, `category_columns` | column blocks for its columns (a pack's own category of the same id wins) |
| `standard_columns` | columns it fills that aren't step parameters (calculation results) |
| `pack_parameters` | parameters added to the pack's first always-running step when no step has the column |
| `stage_rules` | rules added to each of the pack's own steps |
| `stage_hints` | hints for the pack's open-ended steps depending on whether a step runs |
| `row_rules` | rules added to the pack's row planning |
| `fixed` | columns the app's calculations read by name: a pack can't change their unit |
| `prompt_rules` | `{"chemistry": [...]}`: rules added to a built-in step's prompt (its `{{MODULE_RULES}}` slot) |
| `compound_series` | compound setup fills in every length of an oligomer series between the shortest and longest found |
| `column_pairs` | value pairs one fills from the other (sampled <- initial temperature); added when the pack has no pair for those columns |
| `label_columns`, `category_fill`, `fill_columns` | a set label's values, and how far a value is shared (paper / set / none); the pack's own settings win |
| `row_values` | values the row plan records for every row, as columns: `[{column, plan_field, plan_key, unit, description}]` (`sample_time`'s `duration_hr`); a pack's module settings can describe one its own way (it reaches the row planning as a rule) or switch it off |
| `formulas` | calculations written as formulas, as in pack.json (`peptides_oligomers`' peptide totals, `sample_time`'s `is_last_sample`); the pack's own formula for a column wins |
| `joins_first_step` | its steps join the pack's first always-running step (parameters and rules) instead of being requests of their own; a step of their own only when the pack has none (`lab_experiment`) |
| `covers` | what the module records, in a sentence: drafting a pack leaves that to the module |
| `evidence` | `{"words": [...]}`: drafting links the module when a paper's survey uses them (the app's first modules have code rules instead) |

`sample_time` brings each row's time point (`duration_hr`, in hours, as the row plan records it), the label and fill
settings for it and the `is_last_sample` formula; new packs link it (the template), drafted lab packs too (also through
`lab_experiment`'s `needs`); its name and unit stay (`fixed`), its description can be the pack's own. A module's column
placement (`category_columns`) applies only to columns the pack doesn't place itself.

A module's step leaves out the columns the pack's own steps record, and a step with nothing left is dropped. So
`lab_experiment` (the general conditions of a laboratory experiment: temperatures, pressures, pH, vessel, solvent,
suppliers, controls, replicates; linked to every drafted lab pack) adds nothing to a pack that has its own conditions step.

A step's trigger can need several mentions (`"min_hits": 3` in its `trigger`): a passing mention of a word isn't enough.
Modules can be drafted from sample papers: *Data Packs > All data packs and modules > Modules > Suggest modules from
papers...* (or `--draft-modules`), reviewed, and written to your modules folder.

Renamed ids keep working (`modules.ALIASES`: `product_totals` -> `peptides_oligomers`).

The app's modules are in this folder; your own go in `<app data>/modules/<id>/` (*Data Packs › All data packs and
modules… › Modules › Open my modules folder*). An id the app already uses can't be replaced.
