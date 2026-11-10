You are planning the row structure of a dataset for one paper ({{RESEARCH_AREA}})
BEFORE any values are extracted. This step only decides WHICH rows the paper's
results make and how they group. Don't extract any values yet.

The dataset has one row per {{SAMPLE_WORD}}, grouped into sets:
- a "set" is one {{SET_WORD}}: rows that share their conditions except for the
  one thing that varies along the set (a time series, a concentration sweep,
  the entries of one table block);
- a "sample" is one {{SAMPLE_WORD}}: one row of results.
{{PACK_RULES}}
Answer format (short field names): `kind` what the paper is ("experimental"
when it reports results of its own -- measurements, observations, fits;
"review", "perspective", "theory", "abstract" or "other" otherwise. A review or
other paper that reproduces results of earlier work in its tables plans them as
sets like any results, with `ds` naming the original publication; only a paper
with no results of any kind gets no sets, and its extraction steps are skipped),
`sets` -- one entry per set: `set` its label, `type` the set type, `varies`
what distinguishes it from the other sets, `src` the table or section it comes
from, `ds` the original reference when the data is reproduced from another
publication ('' otherwise), and `samples` -- one per row: `label`, `hr` its
duration in hours when the rows are time points (else leave it empty; `hi` the
upper end when a duration is given as a range), and `src` ONLY when the sample
is somewhere other than its set's `src` -- '' for a row of the set's table. Then
`n_rows`, `excluded` (each at most 8 words) and `notes` (one sentence, or '').

Guidance:
- Rows come from results the paper reports: table rows, and results stated in
  the text or a caption together with the conditions they were obtained under.
  A result with too little context to describe its conditions gets no row
  (list it in `excluded`). Results shown only in figures get no rows here
  (figures are digitized separately); list them in `excluded`.
- `type`: "Time Series" when a set's rows are time points of one experiment,
  "Average" when the rows are averages over runs whose individual values aren't
  given, "Independent" otherwise.
- Label sets and samples so a reader finds them in the paper: the table's own
  row and block names where it has them.
- Compound numbers ("compound 7") and citation numbers are never values or
  labels by themselves; use the names the paper gives.
- `ds`: '' when this paper produced the data; the reference as printed when a
  set is reproduced from another publication.
- If page images are attached, they are renders of the pages with tables.
  Trust them for which values belong to which row.

Return a StructurePlan. `n_rows` must equal the number of samples across all
sets.

---
PAPER TEXT:

{{PAPER_TEXT}}
