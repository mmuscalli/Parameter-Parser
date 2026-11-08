You are helping set up a dataset for a research area: {{AREA}}.
{{AREA_DESCRIPTION}}

Read the paper below and list the VARIABLES its experiments or observations report -- the quantities and properties
a dataset of this research area would need a column for. This is a survey of what kinds of values exist, not an
extraction: give each variable ONCE with one example value, however many rows of results report it.

What to list:
- conditions the experiments ran under (temperature, pressure, time, pH, concentrations, flow rates, ...),
- materials and their properties (what was studied, its source, form, amount, purity, ...),
- measured results (yields, rates, sizes, counts, spectral values, ...),
- how things were done when it matters for comparing papers (method, instrument, technique, setup), as short text.

What NOT to list: bibliographic details (title, authors, journal, year, DOI -- the app records those), page or figure
numbers, statistics about the paper itself, values quoted from other papers in the introduction, and the time point
of a sample in a time series (the app records that as duration_hr).

For each variable:
- `name`: as the paper calls it; `column`: a short snake_case name for the dataset column, WITHOUT a unit
  ('reaction_temperature', 'product_yield', 'grain_size'); general, not tied to this paper's specific substances
  unless the substance is what defines the variable.
- `unit`: the unit the values are given in ('°C', 'mM', 'h', '%', 'bar', 'nm', 'eV'); '' for text or unitless values.
- `kind`: number, integer (a count) or text.
- `role`: condition, material, composition, result, method or other.
- `level`: row (differs between the individual results), set (differs between groups of results, the same within a
  group) or paper (one value for the whole paper).
- `uncertainty`: true when the paper gives uncertainties or error bars for it.
- `where`: table, text or figure (where its values are mostly found).
- `example`: one value as printed, with its unit.

Also say in a few words what one ROW of results is in this paper (`row_unit`, e.g. 'one time point of one reaction',
'one planet', 'one mineral sample') and what groups rows (`set_unit`, e.g. 'one reaction condition').
