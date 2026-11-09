You are designing the extraction setup ("research area") of a data-extraction app for: {{AREA}}.
{{AREA_DESCRIPTION}}

Surveys of {{N_PAPERS}} sample papers follow: for each paper, the variables its experiments report (with the unit,
the level they vary at and an example), what one row of results is and what groups rows. Merge them into ONE
research area that would capture these papers -- and similar papers of the field -- as a dataset with one row per
result.

Design:
- `set_word` / `sample_word`: what a group of rows and one row are called in this field (e.g. 'experiment set' /
  'sample', 'host star' / 'planet', 'reaction condition' / 'time point').
- `categories` (3-7): groups of columns for the dataset's column order and for new variables found later, e.g.
  Conditions, Materials, Composition, Results, Methods. `id` snake_case; `value_type` number (one number with a
  unit), text or any. Don't create ids 'metadata', 'methodology' or 'other' -- the app has those already.
- `stages` (1-4): each stage is one request that reads a paper and fills its parameters for every row. Group
  parameters that are read the same way (e.g. conditions and materials in one stage, measured results in another).
  `per`: sample (values can belong to single rows -- the usual choice) or set. Every stage is one more request on
  every paper it runs for: make a stage only for at least three parameters, and leave `keywords` EMPTY for at most
  two core stages every paper needs; every other stage needs 3-8 `keywords` (words found in the papers that need it)
  and then runs only for papers containing one of them.
- Each parameter: `column` snake_case WITHOUT a unit (the app adds the unit suffix); `unit` the unit to store values
  in (one standard unit per variable: °C for temperatures, h for times, mM for concentrations, bar for pressures, %
  for percentages, g for masses, mL for volumes, nm for wavelengths, or the field's own unit); `kind` number, integer
  or text; `description` one sentence saying exactly what belongs in the column (the extraction model reads it);
  `category` one of your category ids; `choices` a short fixed list of allowed words for a text parameter that only
  takes a few values (else []); `uncertainties` true when papers give uncertainties for it; `papers` how many of the
  sample papers report it.
- Merge variables that are the same quantity under different names into one parameter; keep different quantities
  apart (initial vs final temperature, yield vs conversion). Prefer general columns ('product_yield' with the product
  in another column) over one column per substance -- unless the field's papers always report the same few
  substances. Leave out variables that only one paper has AND that are unlikely to recur in the field. Don't add
  parameters for bibliographic details, row identifiers, the set type or a sample's time point in a time series
  (duration_hr) -- the app records those.
- `rules` per stage: 0-3 short extraction rules the descriptions don't cover. `other_hint`: what else the stage
  should list as possible new variables (one sentence), or ''.
- `row_rules`: 3-6 rules for planning the rows: what one row is, what makes two rows belong to the same group, and
  which results should NOT become rows.
- `description`: two sentences on what this research area extracts and what one row is.
