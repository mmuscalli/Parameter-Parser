You are reviewing the extraction setup ("research area") of a data-extraction app: {{AREA}}.
{{AREA_DESCRIPTION}}

The research area as it is now follows: its categories, its extraction stages with their parameters (each fills one
dataset column for every row), its rules for planning the rows{{COMPOUND_NOTE}}. Then surveys of {{N_PAPERS}} new sample
papers: the variables each paper reports, with unit, the level they vary at and an example.

Suggest ADDITIONS that would let the research area capture these papers -- and similar papers -- better:
- `parameters`: variables the papers report that NO existing parameter or column already covers (check the existing
  columns and descriptions: a different name for the same quantity is not new). Put each in an existing stage
  (`stage` = its name) or in a new stage you list in `new_stages`. `column` snake_case WITHOUT a unit (the app adds the
  unit suffix); `unit` the unit to store values in; `kind` number, integer or text; `description` one sentence saying
  exactly what belongs in the column; `category` an existing or new category id; `choices` for a text parameter with
  few values (else []); `uncertainties` when papers give them; `papers` how many sample papers report it; `reason` a
  few words.
- `new_stages`: only when the new parameters are read differently from every existing stage (else []). `keywords` []
  for a stage every paper needs, else words that trigger it.
- `categories`: new categories only when no existing one fits (else []); never 'metadata', 'methodology' or 'other'.
- `rules`: extraction or row-planning rules the papers show are missing (`target` 'rows' for planning the rows, else
  a stage name), one sentence each, with a reason. Not rules the existing ones already state.
- `compounds`: {{COMPOUND_INSTRUCTION}}
- Leave out bibliographic details, row identifiers, a sample's time point in a time series (duration_hr), and variables
  only one paper has that are unlikely to recur in the field. Suggest nothing rather than something weak: an empty list
  is a fine answer.
