You are planning the row structure for one paper BEFORE extracting any
parameter values. Do not fill in concentrations, yields, or any measured
values yet -- this step only determines how many distinct experiments/samples
the paper reports and how they group together.

A paper commonly reports a SWEEP: multiple conditions (e.g. different salts,
concentrations, temperatures), each sampled at multiple time points. Each
distinct condition is a "set"; each time point or replicate within a set is a
"sample". Getting this grouping right matters more than any individual value,
because every later stage builds rows on top of this skeleton.

Guidance:
- A table with repeated sub-blocks (e.g. "Conditions: Na+ 3.33 mol dm-3, 81 C"
  followed by several rows of t/h and yield) is one "set" per sub-block, with
  one "sample" per row in that sub-block.
- set_type "Time Series" when samples within a set differ only by elapsed
  time/duration under otherwise-fixed conditions. "Independent" when each row
  is its own self-contained condition with no shared sweep. "Evaporation
  Cycle" for wet-dry cycling.
- Only plan rows for data given as explicit text or table values. Data that
  only exists as a point read off a scatter plot/figure is OUT OF SCOPE for
  this pass -- list it under `excluded_data` instead of planning a row for it.
- If you are not confident a figure doesn't duplicate tabulated data, say so
  in `notes` rather than guessing.
- If page images are attached, they are rasterized renders of the pages
  containing a "Table N" caption, given alongside (not instead of) the
  OCR'd/pdftotext text below. Plain-text extraction routinely garbles a
  two-column table layout (interleaving rows from the left and right
  sub-tables in an unpredictable order). When the text and an attached image
  disagree about which values go together, TRUST THE IMAGE and use it to
  resolve the grouping -- the text is a lossy fallback for this, not the
  source of truth, whenever both are available.

Return a StructurePlan. `total_planned_rows` must equal the sum of all
`samples` across all `experiment_sets` -- this is a cheap self-check, not
extra work.

---
PAPER TEXT:

{{PAPER_TEXT}}
