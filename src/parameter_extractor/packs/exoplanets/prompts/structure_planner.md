You are planning the row structure for one astronomy paper BEFORE extracting
any parameter values. This step only decides which planets the paper reports
parameters for, grouped by their host star. Don't extract any values yet.

The dataset has one row per planet:
- each "set" is one planetary system, named by its host star exactly as the
  paper names it (e.g. "11 Com", "HD 5608", "75 Cet");
- each "sample" is one planet (or substellar companion such as a brown
  dwarf) in that system, named as the paper names it, star name plus letter
  (e.g. "11 Com b", "75 Cet c").

Answer format (short field names): `kind` what the paper is ("experimental"
when it reports parameters of its own -- observations, fits, measurements;
"review", "perspective", "theory", "abstract" or "other" otherwise -- a paper
that isn't experimental gets no sets and the extraction steps are skipped),
`sets` -- one entry per set: `set` its
label, `type` the set type, `varies` what distinguishes it from the other
sets, `src` the table or section it comes from, `ds` the original reference
when the data is reproduced from another publication ('' otherwise), and
`samples` -- one per row: `label`, `hr` its duration in hours, `src` where
it is, briefly ('Table 1, row 3'). Then `n_rows`, `excluded` (each a short
reason) and `notes`.

Guidance:
- Include every planet or companion for which THIS paper reports parameters
  of its own -- an orbital fit, a mass, a radius -- including ones discovered
  earlier and re-analysed here. A planet only mentioned in passing, or a
  candidate the paper rejects, gets no row (list it in `excluded`).
- ONE SAMPLE PER SOLUTION: if the paper reports more than one set of
  parameters for the same planet from different models -- e.g. an RV-only
  orbital fit (Table 3) AND a joint RV + astrometry fit (Table 4), a fit with
  and without a transit, circular vs eccentric -- each solution is its own
  sample (row). Then label every one of that planet's samples with the
  planet name followed by the solution in square brackets, e.g.
  "HD 14067 b [RV fit, Table 3]" and "HD 14067 b [joint RV + astrometry fit,
  Table 4]". Models that are joint in different ways are different
  solutions. A planet with a single solution gets just its name, no
  brackets. A table that only repeats or derives quantities from one
  solution (e.g. minimum masses computed from the same fit) is not a new
  solution; mention it in the sample's `src`.
- `type` is "Independent" for every set. Leave `hr` empty.
- `ds`: '' when the paper derives the system's parameters itself;
  if a whole system's values are only quoted from another publication, give
  that reference.
- `varies`: one short line per system, e.g. "G8 III giant,
  one planet, RV orbit (Table 3)".
- If page images are attached, they are renders of the pages with tables
  (some printed sideways, shown upright). Trust them for which rows belong
  to which planet.

Return a StructurePlan. `n_rows` must equal the number of
samples (planet solutions) across all sets.

---
PAPER TEXT:

{{PAPER_TEXT}}
