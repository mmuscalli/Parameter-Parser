# New modules drafted from the test papers (2026-11-09)

Mickey asked for more modules, made from the papers we've been testing on with the app's own functionality, judged
against my standards (and the app's logic improved where it fell short), with no significant overlap between modules,
and with a running record of cost and performance.

## The functionality

There was no way to make a module from papers before this; data pack drafting made packs only. New
`module_drafting.py`, with the Data Packs window's Modules tab "Suggest modules from papers…" and the CLI
`--draft-modules --papers LIST [--write-modules] [--modules-out DIR] [--survey-cache DIR]`:

1. Surveys (as for drafting a data pack, two passes). They are cached, so later rounds don't pay for them again.
2. One design request is given every existing module's `covers` and columns, and proposes modules: topics that recur
   across papers.
3. Local checks run on each proposal:
   - the app's naming conventions;
   - values an existing module owns are left out;
   - core conditions become "added to a pack only when it lacks them";
   - unit instructions are removed from descriptions;
   - evidence words must fit the papers (not in nearly every paper, and mostly hitting the papers listed as
     reporting the values);
   - a value claimed by two proposals stays with the larger one;
   - fewer than 3 values: dropped;
   - an addition to an existing module is reported, not made into a new module.
4. Writing a module creates `module.json` with its evidence words, plus one step. Drafts link a module when a paper's
   survey uses its words. The step runs when its words occur at least 3 times in the paper.

## Rounds

40 papers:
- Test Paper List (6)
- Sam's papers (11)
- Organics in target (16: the ten used before, plus impact-hydrothermal, Stardust, catalysis and shock-chemistry papers)
- Initial Easy Papers (7: flow reactors, clays, minerals, kinetics)

| Round | What changed | Cost | Proposed |
|---|---|---|---|
| 1 | first version (37 papers surveyed; 3 lost to a paper-list bug) | $0.605 | mineral/clay, impact/shock, fluid inclusions, flow reactor, equilibrium thermodynamics |
| 2 | core columns, unit talk, evidence precision, prompt (units, setups); list bug fixed | $0.359 | mineral, impact, thermal-gradient chambers, impact hydrothermal deposits, phosphodiester linkage |
| 3 | `extends`, unit checks | $0.313 | mineral, impact, thermal-gradient chambers, flow reactor, fluid inclusions |

Costs:
- Surveys: about $0.008 per paper for two passes, Haiku.
- The design request: about $0.31 for 40 papers, Sonnet, 60K input tokens. It is most of a round's cost once the
  surveys are cached.
- Pack drafting, for comparison: $0.08 for 4 papers.

Problems found and fixed, by round:

- **Round 1.**
  - Core conditions owned by modules: `solid_material_name` / `_mass_g` and `flow_rate_mL_min`, which the Prebiotic
    pack's own step already fills.
  - Descriptions contradicting the stored unit: "`peak_shock_pressure_bar` ... in GPa", "`residence_time_hr` ...
    converted to seconds".
  - Generic evidence words: "flow rate" hit 10 papers, "clay", "ionic strength".
  - Numeric values asked as text ranges.
  - Paper lists split at commas in file names, which lost 3 of Sam's papers.
- **Round 2.** A real but unplaced topic (phosphodiester linkage) proposed as a separate module. It belongs to
  Peptides and oligomers, so proposals can now say they `extend` an existing module.
- **Round 3.** Units the app can't convert get a note. The design request varies from run to run: round 2 had
  linkage but no flow reactor, round 3 the reverse. The feature is a suggestion engine; a person reviews and ticks.
- **Testing.** A module's `pack_parameters` had counted as columns it owns, so a later proposal's core condition was
  dropped instead of treated as core.

## What went into the app (my selection, reviewed)

| Module | Values (step) | Core (only if the pack lacks them) | From |
|---|---|---|---|
| Mineral and clay surfaces | mineral class, formula, clay exchangeable cation, particle size, pretreatment, structural Fe3+ | solid material name, mass | Ferris ×2, Bujdak, mizuuchi, Riggi, Hirakawa |
| Impact and shock conditions | impact velocity, peak shock pressure, shock and post-shock temperature, shock duration, impact angle, projectile material and size, target material | -- | Takeuchi, tingle, kazemi, Burchell, DeLuca, chyba, Abramov, Sandford |
| Thermal gradient and gas-water interface chambers | warm / cold side temperature, difference, chamber thickness, liquid and gas flow, flow velocity, accumulation factor, Soret coefficient | -- | Matreux, Morasch, Schwintek |
| Hydrothermal flow reactor | residence time, quench temperature, injection volume, reactor description | flow rate | mitsuzawa, faisal, alargov |
| Fluid inclusions | homogenization and ice-melting temperature, salinity, size, degree of fill, composition, host mineral | -- | Osinski 2005, Naumov 2005, Parnell |
| + Oligomer linkage (a step of Peptides and oligomers) | 3'-5' and 2'-5' linkage shares, how determined | -- | Calaça Serrão, Ferris 1993, tapiero, Song |

My edits after the checks:
- Generic triggers out ("salinity", "host mineral", "quench", "sapphire", "meniscus").
- Metal-sulfide words added to Mineral surfaces after the held-out test.
- One rule reworded, and a duplicate rule removed.

Not added:
- Equilibrium thermodynamics: mostly one paper.
- Round 2's "impact hydrothermal deposits": a mixed bag of isotopes and alteration; the fluid-inclusion part was kept.

Overlap:
- No two modules fill the same column; a test checks it.
- Core conditions belong to no module.
- The linkage topic is a step of Peptides and oligomers, not a parallel module.

## Validation on held-out papers (surveys $0.065)

Linking from survey evidence, 10 papers none of the rounds saw:
- **Right:**
  - flow reactor for Islam2003 and Kawamura2009;
  - mineral surfaces for Bujdak1996, and for Huber1998 after adding the sulfide words;
  - nothing new for Rodriguez-Garcia2015, Sakata2014, Leman2015 and kim2019.
- **Plausible:** mineral surfaces for Kawamura2009 (hydroxyapatite).
- **False positive:** mineral surfaces for Naumov 2002 (impact geology: "clay minerals", "pyrite"). Kept: mineral names
  are the evidence for papers like Riggi's.
- **Not linked:** Osinski 2013, an impact review.

Live extractions with a copy of the Prebiotic pack that also links Flow reactor and Mineral surfaces (Standard):

| Paper | Cost | Module steps | What the modules added |
|---|---|---|---|
| Islam2003 (supercritical-water flow reactor) | $0.230 | flow reactor $0.013, mineral $0.010 | residence time 2 min, quench 0 °C, full reactor description (Hastelloy tube, IR furnace, 25 MPa back-pressure regulator) |
| Bujdak1996 (silica / alumina) | $0.230 | mineral $0.015 | nothing usable ("oxide" class inferred, correctly held back as assumed) |

Both mineral steps were triggered by one passing mention of "montmorillonite". Hence `min_hits`: a step's words must
occur at least 3 times outside the reference list. Mentions measured:
- Real topics: Ferris 43, Riggi 105, Huber 14, Islam (flow) 15, faisal 8, Kawamura (flow) 4, Matreux (heat flow) 56.
- Passing mentions: 1.

Existing steps keep the default of 1 mention.

## Running cost record

| Item | Cost |
|---|---|
| Round 1 (37 surveys ×2 passes + design) | $0.605 |
| Round 2 (3 surveys + design) | $0.359 |
| Round 3 (design only) | $0.313 |
| Held-out surveys (10 papers) | $0.065 |
| Validation extractions (2 papers) | $0.460 |
| **Total** | **$1.80** |

Module steps cost $0.01-0.015 each on a paper they run for: about 5-7% of a $0.23 extraction.
