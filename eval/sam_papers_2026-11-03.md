# "Sam Papers" test set through developer handoff (2026-11-03)

Eleven PDFs in `Paper Files/Test Paper List/Sam Papers` (prebiotic RNA / nucleotide chemistry), run one by one with
the prebiotic chemistry pack in developer handoff mode (answers written by Claude Code in the session, so no API
cost and no model comparison). Each paper was then finished with every suggested variable accepted as proposed
and evaluated against the PDF. Handoff folders: `runs/handoffs_sam/<paper>/` (local only).

## Per paper

| Paper | What it is | Tables | Rows | What the text/table path captured |
|---|---|---|---|---|
| Caimi 2025 (ACS Cent. Sci.) | 2',3'-cNMP polymerization, wet-dry | 1 (literature comparison) | 32 | Table 1: this work's best yields per nucleotide (single drying, 5-10 cycles) + 11 literature rows marked with their reference; max oligomer length; HPLC / LC-MS details; wet-dry cycle details |
| Calaça Serrão 2024 (JACS) | templated RNA ligation | 0 | 0 | starting solution (CHES, MgCl2, primers) and analysis details for when figures are digitized |
| Vázquez-Salazar 2026 (Life) | review | 1 (qualitative) | 0 | nothing (correct) |
| Ferris & Ertem 1993 (JACS) | ImpA on montmorillonite | 5 (Roman numerals) | 19 | Tables I-II: oligomer length distributions (1-11-mers) per reaction / exchangeable cation; salts per row; starting ImpA / A5'ppA / ADP / ATP split from the 14.5 mM total by ratio |
| Ferris 1986 (OLEB abstract) | 2-page abstract | 0 | 0 | year / journal / DOI filled by CrossRef (none printed) |
| Hirakawa 2025 (PNAS) | borate and RCP formation | 4 | 27 | Tables 1, 3: DAP / ACP / RCP over 0-288 h, three series (with borate, without, borate added at 120 h), as averages of triplicates |
| Liu 2026 (JPCL) | perspective | 1 (theory) | 0 | nothing (correct) |
| Matreux 2024 (Nature) | heat-flow enrichment | 1 (Extended Data) | 0 | setup details; Extended Data Table 1 is Soret coefficients (a property, not results) |
| Morasch 2019 (Nat. Chem., manuscript) | gas bubbles | 0 | 0 | journal / year / DOI filled by CrossRef |
| Schwintek 2024 (eLife) | isothermal PCR in gas flow | 0 | 0 | buffer only |
| Song 2024 (PNAS) | wet-dry nucleotide polymerization | 2 (sequencing) | 3 | Table 2: products detected per starting mixture after two cycles, longest read, cycle number and dry-phase duration |

Seven of the eleven put their results only in figures (or are reviews), so most of this set's data needs the digitizer.

## Fixed in this round

- **Roman-numeral tables** ("Table I"-"Table XX", older papers): not recognised at all before (Ferris 1993 sent no table
  images and had no Tables tab). Now in table-page detection, the table finder (crops named "Table IV"), image labels,
  `data_location` ("Table. IV") and the quote checks. Across all 99 PDFs in Paper Files this also found Inoue1994's Table I.
- **Nature "Extended Data Table N |" captions** recognised (Matreux).
- **Citations are no longer taken for table captions** ("see Supplementary Table 1. Nucleobases", "Table 1) in each",
  "are shown in Table 1. Dipeptide ..."): six papers in the corpus had text-only pages sent as table images.
- **Full-width tables whose columns gap at the page middle** were cropped to one column: Liu Table 1 (2 of 6 columns),
  Hirakawa Table 2, kumar2012 Tables 2-3 (glycine yields, in the original dataset), mitsuzawa2004 Table 2. Fixed in the
  table finder (rows that continue at the same heights in the other half, with no running text beside them).
- **Publisher margin stamps** ("Downloaded from ... by <reader> on <date> from IP address ...") were read backwards into the
  paper text on every page of 5 of the 11 papers (and eder1994) -- noise, and the downloader's name and IP address were
  sent to the API. Rotated characters are now left out of upright pages (the arXiv stamp is still read for identifiers).
- **A supplier taken for an abbreviation**: "200 mM d-ribose (Wako)" renamed ribose "Wako". An abbreviation's letters must
  now come from the name.
- **"detected" products were refused** by the new column data types (a `_mM` column defaults to Number): 'detected' passes
  number / whole-number types again (it's the agreed text for a product found without an amount).
- **Wet-dry details were lost** when wet-dry rows weren't typed "Evaporation Cycle" (Caimi's 5-10-cycle summary row, the
  cited Rajamani / Dagar rows). Stage triggers take `set_patterns` (regexes on a set's label / what varies); the wet-dry
  step matches "wet-dry", "dry-wet", "dehydration-rehydration", "evaporation cycl...".
- **Unprinted year / journal**: the metadata schema required a year, forcing a guess. The prompt now says 0 / '' when not
  printed; an accepted CrossRef match fills year and journal (Ferris 1986, Morasch 2019); a year of 0 is written blank.
- **Review clutter**: species named without any amount (KOH "used to set the pH", lipids in cited rows) were offered as
  new columns with no values; they're now only flagged (`concentration_not_stated`).
- **Grouped flags**: `concentration_not_stated` one per species (Caimi 26 -> 20 lines with all sets listed), `cited_data` one
  per publication (truman 8 -> 2), total-split `derived_value` one per ratio (Ferris 19 -> 6).
- **Ranges**: a chemistry range already formatted '68.6:79.1' (%) was refused as "not converted"; a range among single
  values of one suggestion (Verlander's "6-13 nt") now gets its own `_range_` column.
- **Units**: lengths µm / mm / cm keep a column in the unit printed (`_um`, `_mm`, `_cm`; Matreux's 170 µm chamber);
  `nt` (nucleotides) for oligomer lengths (`_nt`).

## Added to the prebiotic pack

- Variable category **Product Properties** (assignable, number or <= 12 words, table order 72, right after Products):
  "measured properties of the products as a whole rather than one species' amount: the longest product detected (in nt or
  residues), average or typical length, length distribution, linkage ratios (% 3'-5' bonds), sequence or composition
  features". The conditions step's open-ended hint asks for these (one entry per row). Caimi and Song now give
  `maximum_oligomer_length_detected_nt` as numbers (it had landed in Other as text).

## Persistent issues (for decisions later)

1. **Results only in figures or captions.** 7/11 papers. Under the tables-only rule, results stated with complete
   conditions in a caption or the text are dropped (Calaça 38% ligation yield at 5 °C / pH 10; Matreux GlyGly 3.6 ± 0.6%;
   Morasch CMP 1.1% vs 0.042% / 0.056% bulk with replicate counts; Song average lengths). Options: rows for
   caption-stated results with complete conditions; or the automatic figure parsing discussed earlier.
2. **Nucleic-acid products have no convention.** Peptides have `<n>peptide_<AA>` / sequence names and standard columns
   (`total_sampled_peptides_yield`, `max_peptide_length`). Oligonucleotides came out as "(pA)2"..."(pA)11", "RNA oligomers",
   "oligo(dT)"; the vocabulary's poly(A/C/G/U) are starting materials only. Candidates: a naming rule
   (`<n>mer_<nucleotide>`, `oligo(<base>)`), and standard columns for total oligomer yield and longest oligomer
   (`max_oligomer_length_nt`; the new category collects it meanwhile).
3. **Composition and property tables don't fit a row.** Fraction compositions (Ferris Tables III-V: % of the dimer
   fraction), kinetic rates per interval (Hirakawa Tables 2, 4), per-molecule properties (Matreux Soret coefficients).
   Left out with a reason in `excluded`.
4. **Uncertainties of species values are dropped** (Hirakawa's "29.18 ± 2.40" keeps 29.18). Conditions have err columns;
   chemistry doesn't.
5. **Durations as ranges** ("3-7 days", Ferris) can't go in `duration_hr`; they came through only as a suggested
   "reaction time" range.
6. **Averaged time series**: set type is one of Time Series or Average; Hirakawa is both (marked by `avg` columns).
7. **Reviews and perspectives cost a full run** (MDPI review, Liu perspective). A structure-plan field such as
   `paper_kind` could stop before the extraction steps.
8. **Abbreviations differ between papers** (RCP vs "ribose 1,2-cyclic phosphate" in kim2017; ImpA vs 5'-ImpA). The
   one-name-per-paper rule takes the paper's abbreviation, so columns diverge across papers until mapped as synonyms.
9. **Compositions differ between figures** in figure-only papers (Calaça 1 vs 10 µM, Matreux several mixtures); `set ''`
   holds only one -- the figure planner gives per-figure compositions.
10. **Summary tables of "best results"** (Caimi Table 1): one row per nucleotide's maximum over a pH range, each at its own
    pH. Kept, with the paper's per-nucleotide pH from the text where stated.
11. Vector-drawn structures in figures produce letter soup in the text layer (Hirakawa Fig. 1) -- tokens only.
