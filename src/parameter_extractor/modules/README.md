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
| `covers` | what the module records, in a sentence: drafting a pack leaves that to the module |

Renamed ids keep working (`modules.ALIASES`: `product_totals` -> `peptides_oligomers`).

The app's modules are in this folder; your own go in `<app data>/modules/<id>/` (*Data Packs › All data packs and
modules… › Modules › Open my modules folder*). An id the app already uses can't be replaced.
