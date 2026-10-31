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
  Cycle" for wet-dry cycling (name each sample by its cycle, e.g. "Cycle 3").
- Averages: a result reported only as an average over several runs (replicates,
  "triplicate experiments", "mean of n = 3") whose individual values the paper
  doesn't give is a row of its own in a set with set_type "Average" (one set per
  averaged condition, or one set for a table of averages with one row per
  condition). When the individual runs ARE given, each run is its own row in one
  set with set_type "Independent", and the average goes with that set's rows.
  An average stated only in the running text never gets a row of its own (see
  the tables rule below); the chemistry step puts it on the rows of its set.
- `duration_hr`: give every sample's duration, including a duration stated once for
  the whole table or experiment (a caption's "heated at 90 °C for 3 hours").
- `data_source`: for each set, '' if the data was measured in this paper.
  If the paper presents data from another publication -- a review, a
  comparison table, a redrawn figure, or results quoted from earlier work
  (often marked by a reference number, "adapted from", "data from") -- give
  the original reference as the paper's reference list states it (authors,
  year, journal, reference number). This matters: those values aren't this
  paper's measurements.
- Plan rows ONLY for results given in the paper's TABLES. Results that
  appear only in the running text ("after 10 cycles at 70% RH the total
  yield was 17.33%") get no row: such statements usually lack most of the
  experimental context the paper's tabulated experiments have. List them in
  `excluded_data` with a short reason. Results that only exist as points in
  a figure are out of scope for this pass too -- the user digitizes figures
  separately -- so list them in `excluded_data` as well.
- Compound numbers and citations: a bold number after a compound name is its label ("nicotinamide
  6"), and digits printed inline after a word are usually reference citations ("ammonia.14") -- not
  conditions or samples. In set labels name compounds by name, not by number.
- If NO table in the paper reports results (e.g. all results are in
  figures), return no sets; the user can still digitize the figures.
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
