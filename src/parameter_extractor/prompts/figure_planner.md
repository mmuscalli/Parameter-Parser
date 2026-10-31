A user is about to digitize a figure from a paper by hand: they will calibrate
its axes and click the data points. Your job is to tell them what they're
looking at, so each clicked point can become a row of the {{RESEARCH_AREA}}
dataset whose columns are listed below. Every suggestion is shown to them as
an editable default -- be accurate, and say so in `notes` when unsure.

The attached image shows the figure and its caption (the image is
authoritative; the caption text below is extracted text and may be garbled).

Return a FigurePlan:

- `is_data_plot`: true only if the figure plots numeric data on numeric axes.
  Diagrams, schemes, images or photos, spectra without usable data -> false.
- `plot_kind`: scatter, line, scatter_with_fit, bar, or other.
- `panels`: one entry per coordinate system the user must calibrate
  separately -- each sub-panel ((a), (b), ...), and a second y-axis (or
  second x-axis) that a set of points is read against. Name them clearly
  ("main", "(a)", "right y-axis", "top x-axis").
  - `x`, `y`: the axis title as printed, and the `column` from the list
    below that the value belongs in. Use null when no column fits (e.g. a
    derived quantity the dataset doesn't record). `tick_labels`: the numbers
    printed at the axis's labelled ticks, low end first, exactly as printed
    (read them carefully from the image -- they place the calibration
    markers). `multiplier` converts axis values to the column's unit (e.g.
    an axis labelled "10^3 x Q" feeding a column for Q -> 0.001). Note log
    axes as `scale: "log"`.
  - `series`: one per distinguishable data set (marker, line style, or
    labelled point group), using the legend or caption to identify it. If a
    series is the same object or experiment as a set in the structure plan
    below, give that `set_label` exactly.
  - Put EVERY stated condition of a series in `conditions` -- whatever the
    caption, legend, axis titles or passages state for it and isn't on an
    axis: the column it belongs in from the list below, and the value
    exactly as printed with its unit ("22.2 MPa") -- don't convert it, the
    app does. A condition that applies to a whole panel or figure ("(a) at
    22.2 MPa, (b) at 40.0 MPa") goes on every series it applies to.
    Conditions are physical settings with values: a number with its unit,
    or for a few columns a name (a gas, a material, an instrument). Never put
    a description of the apparatus or method into a condition -- mention it
    in `notes` instead.
  - One y-axis can carry several quantities: give the axis the column of
    one of them and every series that plots a DIFFERENT quantity its own
    `y_column`.
  - Points that represent different conditions within one series (e.g. one
    point per separate experiment) are still one series; describe that in
    `notes`.
  - Bar charts whose bars are categories (one mineral, salt or condition per
    bar): one series per bar, labelled by its category, with the category as a
    condition when a column fits (e.g. a solid material's name); the x axis
    gets `column` null -- the user clicks each bar's top.
  - `average` on an axis: true when its values are averages over several runs
    or replicates (an axis label "avg.", "mean", or a caption saying values
    are averaged across triplicates). Its column then holds averages.
  - `initial_species` and `concentrations` are for chemical compositions;
    leave them empty if the research area's rules below don't ask for them.
- `data_source`: '' if the plotted data was measured in this paper. If the
  figure reproduces another publication's data ("redrawn from", "data from",
  a reference number in the caption), give that original reference as the
  reference list states it.
- `duplicates_tabulated_data`: true if the plotted values appear to be the
  same numbers already given in one of the paper's tables (then the user may
  prefer to skip the figure). Explain in `duplicate_note`.
{{PACK_RULES}}
---
STRUCTURE PLAN (sets and rows already planned from text and tables):

{{STRUCTURE_PLAN_JSON}}

---
CONTROLLED VOCABULARY (species names, if any -- use these spellings where a species is listed; a
species that isn't listed is still given, under the paper's name -- the user reviews it):

{{CONTROLLED_VOCAB_JSON}}

---
COLUMNS (choose axis and condition columns from these):

{{TEMPLATE_COLUMNS_JSON}}

---
PASSAGES THAT STATE AMOUNTS OR CONCENTRATIONS, from anywhere in the paper:

{{COMPOSITION_PASSAGES}}
{{THIS_FIGURE}}
---
THE FIGURE TO DESCRIBE: {{FIGURE_ID}} (page {{PAGE}}) -- its image is attached above.

CAPTION (extracted text):
{{CAPTION}}

---
PASSAGES THAT MENTION THIS FIGURE (extracted text; two-column pages may run
side by side on one line):

{{FIGURE_PASSAGES}}
