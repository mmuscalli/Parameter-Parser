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

Then list the COMPOUNDS (`compounds`): every chemical compound the experiments use or form, wherever the paper names
it (tables, methods, figure captions, text) -- reactants, every salt separately by its formula as written (MgCl2,
NaCl, KCl -- not "Mg" or "chloride salts"), buffers, activating agents, catalysts in solution, and every product
separately, by its name -- never the paper's compound numbers ('nicotinamide 6' -> 'nicotinamide'; a compound the
paper only calls '4' gets its chemical name). Compounds used only to analyse the samples (HPLC mobile phases and ion-pair reagents, eluents, MALDI
matrices, calibration standards) get the role `analysis`. Use the paper's own short name or abbreviation as `name` and give the spelled-out chemical name in
`full_name` whenever the paper defines or implies one (ImpA -> adenosine 5'-phosphorimidazolide). Not instruments,
minerals, clays or other solid materials; not enzymes, dyes, kits or reagent mixtures ("Taq polymerase", "SYBR Green",
"PCR buffer"); not classes of molecules ("RNA oligomers", "amino acids") -- name the specific compounds instead.

Also say in a few words what one ROW of results is in this paper (`row_unit`, e.g. 'one time point of one reaction',
'one planet', 'one mineral sample') and what groups rows (`set_unit`, e.g. 'one reaction condition').
