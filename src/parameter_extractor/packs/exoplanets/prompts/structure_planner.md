You are planning the row structure for one astronomy paper BEFORE extracting
any parameter values. This step only decides which planets the paper reports
parameters for, grouped by their host star. Don't extract any values yet.

The dataset has one row per planet:
- each "set" is one planetary system, named by its host star exactly as the
  paper names it (e.g. "11 Com", "HD 5608", "75 Cet");
- each "sample" is one planet (or substellar companion such as a brown
  dwarf) in that system, named as the paper names it, star name plus letter
  (e.g. "11 Com b", "75 Cet c").

Guidance:
- Include every planet or companion for which THIS paper reports parameters
  of its own -- an orbital fit, a mass, a radius -- including ones discovered
  earlier and re-analysed here. A planet only mentioned in passing, or a
  candidate the paper rejects, gets no row (list it in `excluded_data`).
- A planet listed in several tables (orbital fit, joint astrometric fit,
  ...) is still ONE sample; mention the extra tables in its `source`.
- set_type is "Independent" for every set. Leave `duration_hr` and
  `cycle_number` empty.
- `data_source`: '' when the paper derives the system's parameters itself;
  if a whole system's values are only quoted from another publication, give
  that reference.
- `varying_condition_summary`: one short line per system, e.g. "G8 III giant,
  one planet, RV orbit (Table 3)".
- If page images are attached, they are renders of the pages with tables
  (some printed sideways, shown upright). Trust them for which rows belong
  to which planet.

Return a StructurePlan. `total_planned_rows` must equal the number of planets
(samples) across all sets.

---
PAPER TEXT:

{{PAPER_TEXT}}
