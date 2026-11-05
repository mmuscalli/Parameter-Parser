# Making a research area (a "pack")

A pack is everything that ties the app to one research area: the dataset's columns, how a paper's results are
divided into rows, what the model is asked to extract, and the calculations run afterwards. This folder is the
**template** every new pack is copied from. It's a complete, working pack with example content, so a copy runs
straight away. You then replace the examples with your own.

The template never appears in the app's lists (`"is_template": true` in pack.json). A new pack is made from it
with `packs.create_pack("my_area", "My research area")`, which copies this folder into your packs folder
(`<app data>/packs/my_area/`), sets the id and name, and makes it visible. The in-app editor will do the same.

Keys starting with `_about` in the JSON files explain the key that follows them. The app ignores them; you can
keep them or delete them.

## The files

| File | What it holds | Needed? |
|---|---|---|
| `pack.json` | id, name, which built-in steps and calculations run, what a set and a row are called, variable categories, which columns sit in which category | yes |
| `columns.json` | the dataset's columns in order; optionally a compound vocabulary | yes |
| `standard_columns.json` | extra columns with descriptions (rarely needed) | no |
| `stages/*.json` | the extraction steps: what the model reads from each paper | at least one |
| `prompts/structure_planner.rules.md` | your rules for dividing a paper's results into rows | recommended |
| `prompts/<name>.rules.md` | extra rules for any other shared prompt (`figure_planner`, `focused_search`, `metadata`, `term_search`) | no |
| `prompts/<name>.md` | a whole prompt of your own, replacing the app's (advanced) | no |
| `formulas` in `pack.json` | calculations without code (below) | no |

## How a paper goes through a pack

1. **Rows are planned.** The app's shared row-planning prompt (with your `structure_planner.rules.md` in it, and
   your words for a set and a row from `units`) decides which rows the paper's results make, grouped into sets.
2. **Stages extract values**, all at once. Each `stages/*.json` is one request to the model, which fills its
   parameters (columns) for every row. A value for the whole paper goes on every row, a value for a set on that
   set's rows, and a value for one row on that row only.
3. **Calculations** listed under `postprocess` run on the rows.
4. **Review.** Values the model found that have no column (open-ended stages) are offered as new variables;
   nothing new goes into the dataset unless you accept it.
5. **The CSV** is written with your columns, in category order, plus the shared columns (paper, authors, DOI,
   ...) and row identifiers.

Figures are digitized with the shared figure tools in every pack. `figure_planner.rules.md` adds your rules for
the suggestions (which columns a plot's axes usually go into).

## Columns (`columns.json`)

- **Put the unit at the end of the name**: `temperature_C`, `pressure_bar`, `mass_g`, `volume_mL`, `duration_hr`,
  `yield_pct`, `concentration_mM`. The app reads the unit from the name and converts every value into it (°F,
  K → °C; MPa → bar; min, days → hours; ...). A column without a unit suffix holds text or plain numbers.
- Every column is written in every paper's CSV, empty or not, so datasets from different papers line up.
- The shared columns and the row identifiers are added automatically: don't list them.
- Changing columns later is fine. Old CSVs keep their columns, and new runs use the new ones.

## Stages (`stages/*.json`)

A stage is one extraction request. Fields:

| Field | Meaning |
|---|---|
| `name` | id of the stage (lower case, `_`); also its file's stage name in a run folder |
| `label`, `description` | shown next to the stage's on/off switch in the app |
| `origin` | how values from it are labelled in provenance ("measurements") |
| `schema_name` | a name for the answer format (CamelCase, unique in the pack) |
| `system_prompt` | one sentence telling the model its job |
| `trigger` | when it runs: `{"always": true}`, or only for papers that need it: `set_types`, `keywords` (words in the paper text), `set_patterns` (regexes on set labels) |
| `per` | `"sample"`: values can belong to single rows; `"set"`: to whole sets |
| `set_word` | what the prompt calls a set |
| `intro` | the instruction the model reads first |
| `parameters` | the columns it fills (below) |
| `rules` | extra instructions, one sentence each |
| `table_images` | `true` sends pictures of the paper's tables too (more reliable reading of tables; costs more) |
| `open_ended`, `open_ended_hint` | also collect values that have no column, offered in the review |
| `error_suffixes`, `suffix_separator` | how uncertainty columns are named: `["_err_plus", "_err_minus"]` with `"_"` gives `temperature_C_err_plus` |
| `alternatives`, `alternatives_rule` | also record values a paper gives by other methods (e.g. two temperature readings) |
| `modes` | record each mode of a multimodal result separately (astronomy) |

Each parameter has these fields:

| Field | Meaning |
|---|---|
| `column` | the column it fills (one of `columns.json`, or a new one: then it's added to the dataset) |
| `unit` | the column's unit, matching the name's suffix (`°C`, `bar`, `%`, `mL`, `hr`, `''` for none) |
| `description` | what belongs there. The model reads it, so be exact: what counts, what doesn't, how to write it |
| `kind` | `"text"` for words instead of a number |
| `choices` | a fixed list of allowed words (e.g. `["Batch", "Flowthrough"]`). Anything else is left out and reported |
| `integer` | a count, written as a whole number |
| `uncertainties` | also fill the ± columns |

Several small stages are better than one large one. They run in parallel, and each can be switched off in the
app. Group parameters that are read from the same part of a paper.

## Rules for planning rows (`prompts/structure_planner.rules.md`)

Rows decide everything later, so say clearly:
- what ONE row of your dataset is (one measurement? one sample? one object?);
- what makes rows one set (same experiment, one condition varied);
- which results must NOT become rows.

A few lines are enough. The shared prompt already covers the general rules (tables, text results with
conditions, figures are digitized separately, quoted data from other papers).

## Calculations (`postprocess`)

Calculations are code in the app. A pack chooses which ones run. The ones that exist today were written for the
two built-in packs:

| Name | What it does | For |
|---|---|---|
| `normalize_species` | compound names → one name per compound (rules, PubChem); concentrations → mM | packs with the `chemistry` stage |
| `mixing`, `molar_ratios`, `amounts` | concentrations from stock solutions, ratios and amounts | `chemistry` |
| `peptide_totals`, `oligomer_totals` | total peptide / oligomer yields, longest oligomer | `chemistry` |
| `water_type`, `ambient_conditions`, `atmospheric_start` | solvent naming; 'ambient' = 25 °C / 1 bar; sealed batch starts at 1 bar | prebiotic chemistry |
| `results_check` | flags a paper with no measured results | prebiotic chemistry |
| `row_labels`, `exoplanet_masses`, `reference_names`, `archive_validation` | exoplanet names, mass conversions, NASA Exoplanet Archive check | exoplanets |

A new pack usually starts with none. Unit conversion into the column's unit, uncertainties, ranges ("5-10")
and the review work in every pack without any calculation listed here.

## Formulas (`formulas` in pack.json)

Calculations that need no code. Each formula fills its column on every row where its inputs have values. Formulas
run after the review, so accepted values count, and in list order, so a formula can use an earlier formula's
column.

```json
"formulas": [
  {"column": "temperature_K", "expression": "temperature_C + 273.15",
   "description": "the temperature in kelvin", "if_present": "check"},
  {"column": "total_yield_pct", "expression": "sum_of(\"^sampled_.*_aq_%yield$\")",
   "description": "all measured yields together"}
]
```

- **Columns** by name; a name with `-`, `%`, `(` or `)` goes in backticks: `` `sampled_Gly-Gly_aq_%yield` ``.
- **Arithmetic** `+ - * / **`, parentheses, comparisons `< <= > >= == !=`, `and`, `or`, `not`; constants `pi`, `e`.
- **Functions** `abs`, `min`, `max`, `round(x, digits)`, `sqrt`, `exp`, `ln`, `log10`;
  `first(a, b, ...)` (the first input that has a value), `ifelse(test, a, b)`;
  `sum_of("pattern")`, `mean_of`, `max_of`, `min_of`, `count_of` over the row's columns whose name matches the
  pattern (a regular expression).
- **Units**: the result is in the unit its column's name says. Inputs are in their own columns' units, so the
  formula converts.
- **Missing inputs**: a missing input leaves the result empty. `first()` and the pattern totals skip missing
  values. Text values such as "detected" count as missing.
- **`if_present`**, for when the paper already gives the column a value: `check` (the default) keeps the paper's
  value and flags a calculated value that differs; `keep` keeps it without checking; `replace` uses the formula's
  value.

Every calculated value is marked "calculated", with the formula and its inputs in the hover text. Each formula
adds one flag summarising what it filled. The editor's Formulas tab has a panel to try a formula on example
values.

## Testing a pack

1. Run one paper whose answers you know (Economy models cost a few cents).
2. Check the Rows tab and the flags. Missing values usually mean a parameter's description is unclear. Wrong rows
   mean `structure_planner.rules.md` needs a rule.
3. Change one thing at a time and run the paper again.

## Not yet possible without code

- **Calculations beyond formulas.** Anything one row's columns can express is a formula. Calculations across rows,
  lookups in outside data, or new extraction logic still need a developer.
- **Built-in stages other than `chemistry` and `fit_models`.** A new step written in code (its own answer
  format) needs a developer; everything a parameter list can express works as a `stages/*.json` file.
- **Checks against an outside database** (like the exoplanet archive check).
