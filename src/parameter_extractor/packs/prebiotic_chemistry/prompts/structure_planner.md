You are planning the row structure for one paper BEFORE extracting any
parameter values. Do not fill in concentrations, yields, or any measured
values yet -- this step only determines how many distinct experiments/samples
the paper reports and how they group together.

A paper commonly reports a SWEEP: multiple conditions (e.g. different salts,
concentrations, temperatures), each sampled at multiple time points. Each
distinct condition is a "set"; each time point or replicate within a set is a
"sample". Getting this grouping right matters more than any individual value,
because every later stage builds rows on top of this skeleton.

Answer format (short field names): `kind` what the paper is (below), `sets` -- one entry per set: `set` its
label, `type` the set type, `varies` what distinguishes it from the other
sets, `src` the table or section it comes from, `ds` the original reference
when the data is reproduced from another publication ('' otherwise), and
`samples` -- one per row: `label`, `hr` its duration in hours (`hi` the upper
end when the duration is a range), `src` where it is, briefly ('Table 1, row
3'). Then `n_rows`, `excluded` (each a short reason) and `notes`.

Guidance:
- A table with repeated sub-blocks (e.g. "Conditions: Na+ 3.33 mol dm-3, 81 C"
  followed by several rows of t/h and yield) is one "set" per sub-block, with
  one "sample" per row in that sub-block.
- `type` "Time Series" when samples within a set differ only by elapsed
  time/duration under otherwise-fixed conditions. "Independent" when each row
  is its own self-contained condition with no shared sweep. "Evaporation
  Cycle" for wet-dry cycling (name each sample by its cycle, e.g. "Cycle 3").
- Averages: a result reported only as an average over several runs (replicates,
  "triplicate experiments", "mean of n = 3") whose individual values the paper
  doesn't give is a row of its own in a set with `type` "Average" (one set per
  averaged condition, or one set for a table of averages with one row per
  condition). When the individual runs ARE given, each run is its own row in one
  set with `type` "Independent", and the average goes with that set's rows.
  An average stated only in the running text never gets a row of its own (see
  the tables rule below); the chemistry step puts it on the rows of its set.
- `hr`: give every sample's duration, including a duration stated once for
  the whole table or experiment (a caption's "heated at 90 °C for 3 hours").
  For wet-dry cycles it is the TOTAL time up to the end of that cycle: 24 h
  cycles -> Cycle 1 = 24, Cycle 2 = 48, Cycle 3 = 72 (cycles of different
  lengths add up). A duration printed as a range ("3-7 days", "20-144 h"):
  `hr` the lower end and `hi` the upper end, both in hours -- never one end
  alone or the midpoint.
- `ds`: for each set, '' if the data was measured in this paper.
  If the paper presents data from another publication -- a review, a
  comparison table, a redrawn figure, or results quoted from earlier work
  (often marked by a reference number, "adapted from", "data from") -- give
  the original reference as the paper's reference list states it (authors,
  year, journal, reference number). This matters: those values aren't this
  paper's measurements.
- Plan rows for results given in the paper's TABLES. Results stated only in
  the running text or in a figure caption get rows too, but ONLY when the
  paper gives that experiment's conditions completely enough for a useful row:
  its starting composition (what reacted, at what concentration or amount)
  AND its temperature AND its duration (or a sampling time), stated for that
  experiment or for all of the paper's experiments. "Over 12 h, the CMP yield
  was 1.1 % ± 0.73 % (12 repeats) at 60 °C with 240 mM cytidine & ammonium
  dihydrogen phosphate, 2.4 M urea" is a row (an Average set when repeats are
  averaged); "after 10 cycles at 70% RH the total yield was 17.33%" with no
  composition is not. A text result's `src` is its section and paragraph or
  the caption ('Figure 7 caption'). List text results without complete
  conditions in `excluded` with a short reason. Results that only exist as
  points in a figure are out of scope for this pass -- the user digitizes
  figures separately -- so list them in `excluded` as well.
- Kinetics are results: a table (or a text result with complete conditions)
  of reaction rates, rate constants, half-lives or activation energies
  measured for the paper's experiments gets rows like any other result --
  one per condition, or per time interval when the table gives rates per
  interval (`hr` the interval's start, `hi` its end). Rates from a fitted
  model of several reactions (k1, k2, ... for one experiment) are one row for
  that experiment.
- Tables of properties of single molecules (diffusion or Soret coefficients,
  pKa values, extinction coefficients) and compositions of product fractions
  analysed after a reaction (% of each isomer within the dimer fraction) are
  not rows: list them in `excluded`.
- `kind`: "experimental" when the paper reports experiments of its own (even
  if only in figures); "review", "perspective", "theory" (models or
  calculations only), "abstract" (a short conference abstract without data)
  or "other" otherwise. Data a review (or any paper) reproduces from other
  publications in its tables IS planned as sets like any results, with `ds`
  naming the original publication -- the rows are marked with their source.
  Only a paper with no results of any kind gets no sets; its extraction steps
  are then skipped.
- Compound numbers and citations: a bold number after a compound name is its label ("nicotinamide
  6"), and digits printed inline after a word are usually reference citations ("ammonia.14") -- not
  conditions or samples. In set labels name compounds by name, not by number.
- If no table or text result qualifies (e.g. all results are in figures),
  return no sets; the user can still digitize the figures.
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

Return a StructurePlan. `n_rows` must equal the sum of all
`samples` across all `sets` -- this is a cheap self-check, not
extra work.

---
PAPER TEXT:

{{PAPER_TEXT}}
