A user is about to digitize a figure from a paper by hand: they will calibrate
its axes and click the data points. Tell them what they're looking at, so
each clicked point can become a row of the dataset whose columns are listed
below. Every suggestion is shown to them as an editable default -- be
accurate, and say so in `notes` when unsure.

The attached image shows the figure and its caption (the image is
authoritative; the caption text below is extracted text and may be garbled).

Return a FigurePlan:

- `is_data_plot`: true only if the figure plots numeric data on numeric axes.
  Diagrams, schemes, images, spectra without usable data -> false.
- `plot_kind`: scatter, line, scatter_with_fit, bar, or other.
- `panels`: one entry per coordinate system the user must calibrate
  separately -- each sub-panel ((a), (b), ...), and a second y-axis (or
  x-axis) that a set of points is read against. Name them clearly ("main",
  "(a)", "right y-axis").
  - `x`, `y`: the axis title as printed, and the `column` from the list
    below that the value belongs in (null when none fits). `multiplier`
    converts axis values to the column's unit; `scale: "log"` for log axes.
    `tick_labels`: the numbers printed at the axis's labelled ticks, low end
    first, exactly as printed.
  - `series`: one per distinguishable data set (marker, line style, or
    labelled group), from the legend or caption. If a series is the same
    object or experiment as a set in the structure plan below, give that
    `set_label` exactly. Put every stated condition of the series in
    `conditions` (the column it belongs in, and the value AS PRINTED with
    its unit -- the app converts). If one axis carries several quantities,
    give each series that plots a different one its own `y_column`.
    `initial_species` and `concentrations` are for chemical compositions;
    leave them empty if the dataset has none.
- `data_source`: '' if the plotted data was measured in this paper;
  otherwise the original reference.
- `duplicates_tabulated_data`: true if the plotted values appear to be the
  same numbers already given in one of the paper's tables. Explain in
  `duplicate_note`.

---
FIGURE: {{FIGURE_ID}} (page {{PAGE}})

CAPTION:
{{CAPTION}}

---
STRUCTURE PLAN (sets and rows already planned from text and tables):

{{STRUCTURE_PLAN_JSON}}

---
CONTROLLED VOCABULARY (species names, if any):

{{CONTROLLED_VOCAB_JSON}}

---
COLUMNS (choose axis and condition columns from these):

{{TEMPLATE_COLUMNS_JSON}}

---
PASSAGES THAT MENTION THIS FIGURE:

{{FIGURE_PASSAGES}}

---
PASSAGES THAT STATE AMOUNTS OR CONCENTRATIONS:

{{COMPOSITION_PASSAGES}}
