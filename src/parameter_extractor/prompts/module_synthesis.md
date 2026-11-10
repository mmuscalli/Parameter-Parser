You are designing SHARED MODULES for a data-extraction app that turns research papers into datasets ({{AREA}}).

A data pack is the setup for one field: its columns, how rows are planned, its own extraction steps. A MODULE is a
part several data packs can link instead of each designing it again: one extraction step (one request to the AI model
for each paper that needs it, recognised by specific words), its columns, and optionally rules for planning rows. A
good module is a TOPIC that recurs across fields and papers -- e.g. "Mineral surfaces" (mineral identity, surface area,
cation exchange capacity, particle size, pretreatment) or "Irradiation" (light source, wavelength, photon flux, dose)
-- not one paper's peculiarity and not the core conditions every experiment has.

Surveys of {{N_PAPERS}} sample papers follow: for each paper, the variables it reports. Propose 0-6 modules.

These modules exist already -- don't propose anything they record, and don't propose a module that overlaps one of them:
{{EXISTING}}

Rules:
- A module needs values that at least TWO of the sample papers report (list them in `papers`), or that clearly
  recur across a field even if only one sample paper shows it -- then say so in `description`.
- At least 3 values of its own, at most 12. Values about the same thing only: a module is a topic, not a bag.
- Leave out the core conditions every data pack has itself: temperature, pH, pressure, reaction time, solvent,
  volumes, concentrations or amounts of compounds, yields of compounds (the Solution chemistry module records every
  compound's amount and yield). A module may still need one of them to make sense of its own values -- then include
  it; the app adds it to a pack only when the pack lacks it.
- Modules must not overlap EACH OTHER either: every value belongs to one module.
- `evidence_words`: 4-10 specific words or short phrases papers needing the module use and other papers don't
  ("montmorillonite", "photon flux", "light-gas gun"); never general words ("sample", "analysis", "temperature",
  "model"). The step runs only for papers containing one of them.
- Look at the experimental SETUPS and SAMPLES the papers share (reaction chambers, gradients, capture media, sample
  types, energy sources), not only at their conditions.
- `step`: `name` snake_case (the module id is fine), `per` "sample" unless the values are per experiment set,
  `keywords` [] (the evidence words are used), parameters as for a data pack: `column` snake_case WITHOUT a unit,
  `unit` the unit to store values in, `kind` number / integer / text -- a measured quantity is a number with a unit
  even when papers give ranges (the app keeps ranges), a one-sentence `description` the extraction model reads -- say
  what the value is, not which unit to give it in (the app converts whatever the paper prints), `category` the module's category id, `choices` for text values with a few fixed words, `uncertainties`
  when papers give them, `papers` how many sample papers report it; 0-3 `rules`; `other_hint` ''.
- `category`: the module's own column block (id snake_case, a label, value_type, description).
- `covers`: one sentence for designers of data packs saying what the module records, so their design leaves it out.
- A topic that belongs to an existing module (more values of the same kind, e.g. oligomer linkage for "Peptides and
  oligomers") is NOT a new module: set `extends` to that module's id; its step is added to that module.
- Fewer good modules are better than many weak ones; propose none if nothing recurs.
