A user is about to digitize a figure from a paper by hand: they will calibrate
its axes and click the data points. Your job is to tell them what they're
looking at, so each clicked point can become a row in a database of
prebiotic peptide-synthesis experiments. Every suggestion is shown to them as
an editable default -- be accurate, and say so in `notes` when unsure.

The attached image shows the figure and its caption (the image is
authoritative; the caption text below is OCR and may be garbled).

Return a FigurePlan:

- `is_data_plot`: true only if the figure plots numeric data on numeric axes.
  Diagrams, reaction schemes, spectra without usable data, photos -> false.
- `plot_kind`: scatter, line, scatter_with_fit, bar, or other.
- `panels`: one entry per coordinate system the user must calibrate
  separately -- each sub-panel ((a), (b), ...), and a second y-axis (or
  second x-axis) that a set of points is read against. Name them clearly
  ("main", "(a)", "right y-axis", "top x-axis").
  - `x`, `y`: the axis title as printed, and the template `column` from the
    list below that the value belongs in. Use null when no column fits
    (derived quantities like rates, enthalpies, species-distribution
    percentages). `multiplier` converts axis values to the column's unit
    (e.g. an axis in mol dm-3 feeding an `_mM` column -> 1000; an axis
    labelled "10^3 (% Gly-Gly) per h" -> 0.001 to get % per h). Note log
    axes as `scale: "log"`.
  - `series`: one per distinguishable data set (marker, line style, or
    labelled point group), using the legend or caption to identify it. Give
    each series its COMPLETE initial composition in `initial_species`
    (controlled-vocabulary names, concentrations converted to mM, including
    components shared by all series such as a fixed CuCl2 or glycine
    background), plus temperature and pH when stated, and EVERY other
    experimental condition the caption, legend, axis titles or passages
    state for it in `conditions` -- pressure, flow rate, volumes, gas or
    atmosphere, residence or reaction time when not on an axis, and so on.
    A condition that applies to a whole panel or figure (e.g. "(a) at
    22.2 MPa, (b) at 40.0 MPa") goes on every series it applies to. Give the
    value exactly as printed with its unit ("22.2 MPa") -- don't convert it;
    the app does that -- and the column it belongs in from the list below
    (e.g. initial_pressure_bar for a reaction pressure). Conditions are
    physical settings with values; don't put descriptions of the apparatus
    or method into category columns such as experiment_type (only "Batch" or
    "Flowthrough") -- mention those in `notes`.
  - One y-axis can carry several quantities ("Concentration of Gly-Gly and
    diketopiperazine"): give the axis the column of one of them and every
    series that plots a DIFFERENT quantity its own `y_column`. If a series is the
    same experiment as a set in the structure plan below, give that
    `set_label` exactly.
  - Points that represent different conditions within one series (e.g. a
    plot of rate vs pH where each point is a separate experiment) are still
    one series; describe that in `notes`.
- `data_source`: '' if the plotted data was measured in this paper. If the
  figure reproduces another publication's data ("redrawn from", "data from",
  a reference number in the caption), give that original reference as the
  reference list states it.
- `duplicates_tabulated_data`: true if the plotted values appear to be the
  same numbers already given in one of the paper's tables (then the user may
  prefer to skip the figure). Explain in `duplicate_note`.

---
FIGURE: {{FIGURE_ID}} (page {{PAGE}})

CAPTION (OCR):
{{CAPTION}}

---
STRUCTURE PLAN (experiment sets already extracted from text and tables):

{{STRUCTURE_PLAN_JSON}}

---
CONTROLLED VOCABULARY (species names):

{{CONTROLLED_VOCAB_JSON}}

---
TEMPLATE COLUMNS (choose axis and condition columns from these):

{{TEMPLATE_COLUMNS_JSON}}

---
PASSAGES THAT MENTION THIS FIGURE (extracted text; two-column pages may run
side by side on one line):

{{FIGURE_PASSAGES}}
