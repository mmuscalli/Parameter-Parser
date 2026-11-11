#!/usr/bin/env python3
"""
Command-line front end. A thin wrapper over pipeline.run_pipeline() /
run_triage_only() -- the same calls a GUI makes -- so the CLI and any future
interface can't drift apart in behaviour.

    parameter-extract --pdf "/path/to/paper.pdf"                  # extract a pre-selected paper
    parameter-extract --pdf "/path/to/paper.pdf" --out results/   # choose where results go
    parameter-extract --pdf "/path/to/paper.pdf" --triage-only    # optional screening only
    parameter-extract --pdf paper.pdf --look-for "reaction volume" --look-for "stirring rate"
    parameter-extract --self-check [--pdf paper.pdf]             # check the installation (free)
    parameter-extract --resume RUN_OR_QUEUE_FOLDER               # a stopped run: only the missing steps asked
    parameter-extract --rebuild RUN_OR_QUEUE_FOLDER              # the dataset again from saved answers (free)

New variables (no column yet) are left out of the CSV from the command line --
the desktop app's review screen is where they're accepted. Variables accepted
there earlier (the local registry) ARE recognised here.

(From a source checkout without installing: python main.py ... does the same.)

The API key comes from config/.env or the ANTHROPIC_API_KEY environment
variable (see config/.env.example). Each run writes to its own timestamped
folder under --out (default: runs/).
"""
import argparse
import sys
from pathlib import Path

from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError
from parameter_extractor.pipeline import run_pipeline, run_triage_only
from parameter_extractor.pricing import format_usd
from parameter_extractor.run_context import ProgressEvent


def print_progress(event: ProgressEvent) -> None:
    print(f"[{event.step}/{event.total_steps}] {event.message}...", flush=True)


def main() -> int:
    if "--self-check" in sys.argv:
        from parameter_extractor.diagnostics import main as self_check
        return self_check(sys.argv[1:])

    parser = argparse.ArgumentParser(description="Extract experimental data from a paper PDF.")
    parser.add_argument("--pdf", help="Path to the paper PDF")
    parser.add_argument("--paper", metavar="ID",
                        help="A paper by arXiv ID, DOI or ADS bibcode instead of --pdf: read from arXiv")
    parser.add_argument("--arxiv", action="store_true",
                        help="Read the PDF's arXiv full text instead when arXiv has it (a preprint; ~40%% "
                             "fewer tokens, exact tables)")
    parser.add_argument("--ads-token", default=None,
                        help="NASA ADS API token, for journal ADS bibcodes (default: ADS_API_TOKEN in config/.env)")
    parser.add_argument("--queue", type=Path, metavar="LIST",
                        help="Full extraction of every paper in a list (CSV/text of PDF paths, arXiv IDs, DOIs, ADS "
                             "bibcodes or reference links): figures skipped and new variables left out of the CSV "
                             "(use the app's Paper queue to review them); one combined CSV")
    parser.add_argument("--resume", type=Path, metavar="FOLDER",
                        help="Run a stopped run (or paper queue) again from its folder: steps answered before are "
                             "reused at no cost, only the missing ones are asked. Writes a new folder next to it")
    parser.add_argument("--rebuild", type=Path, metavar="FOLDER",
                        help="Build a run's (or paper queue's) dataset again from the answers saved in its folder, "
                             "asking the model nothing -- after changing accepted variables, a data pack's formulas or "
                             "calculations. Writes a new folder next to it")
    parser.add_argument("--parallel", type=int, default=0, metavar="N",
                        help="With --queue: papers extracted at once (default 3, or 12 in batch mode)")
    focused = parser.add_argument_group(
        "focused search", "A few parameters across many papers, cheaply: --focus with --papers and/or --paper/--pdf")
    focused.add_argument("--focus", action="append", default=[], metavar="COLUMN",
                         help="A parameter (column) to search for (repeatable); --list-parameters shows them")
    focused.add_argument("--papers", type=Path, metavar="LIST",
                         help="A CSV or text file of papers: arXiv IDs, DOIs, ADS bibcodes or PDF paths")
    focused.add_argument("--search-word", action="append", default=[], metavar="WORD",
                         help="Screen papers for this word (repeatable), e.g. EXOFAST; default: words from "
                              "the parameters' descriptions")
    focused.add_argument("--whole-paper", action="store_true",
                         help="Send the whole paper, not only the passages around the search words")
    focused.add_argument("--only-failed", action="store_true",
                         help="With --papers pointing at an earlier search's papers.csv: search only the papers "
                              "whose status was 'error' (e.g. arXiv was busy)")
    focused.add_argument("--rows-only", action="store_true",
                         help="In passages mode, send only the table rows near the search words instead of "
                              "whole tables (a little cheaper; misses table values whose rows lack the words)")
    plan = focused.add_mutually_exclusive_group()
    plan.add_argument("--plan-rows", dest="plan_rows", action="store_true", default=None,
                      help="Plan each paper's rows like a full extraction first (the pack's row planner, with "
                           "table images): rows match a full run; more tokens. Default: the pack's setting")
    plan.add_argument("--no-plan-rows", dest="plan_rows", action="store_false",
                      help="Let the focused answer name the rows itself (cheapest)")
    focused.add_argument("--list-parameters", action="store_true",
                         help="List the parameters a focused search can look for (with --pack) and exit")
    parser.add_argument("--out", type=Path, help="Folder for run outputs (default: runs/)")
    parser.add_argument("--prefix", default="001", help="3-digit-ish paper prefix for full_id/set_id")
    parser.add_argument("--look-for", action="append", default=[], metavar="TERM",
                        help="A parameter you especially want found (repeatable); each gets an "
                             "explicit found / not-stated answer")
    parser.add_argument("--triage-only", action="store_true",
                        help="Only screen the paper against prompts/triage.md's inclusion "
                             "criteria; skip extraction")
    parser.add_argument("--pack", default="prebiotic_chemistry",
                        help="Domain pack (data pack) to extract with; see --list-packs")
    parser.add_argument("--list-packs", action="store_true", help="List the available domain packs and exit")
    parser.add_argument("--no-pubchem", action="store_true",
                        help="No online lookups: PubChem species names, NASA Exoplanet Archive check "
                             "(only names are sent)")
    parser.add_argument("--equations-latex", action="store_true",
                        help="Convert the paper's labelled equations to LaTeX (one small extra API call); "
                             "they're found and cropped either way")
    parser.add_argument("--models", default=None, metavar="PROFILE",
                        help="The model profile (Models window; --list-models lists them): standard (Claude Sonnet 5.5, "
                             "the default, most accurate), balanced (Sonnet plans the rows, Claude Haiku 5.5 extracts; "
                             "about half price), economy (Haiku; cheapest, best with --passes 3), or one of your own -- "
                             "on the Anthropic API or a model server")
    parser.add_argument("--list-models", action="store_true",
                        help="List the model profiles and connections (Models window), then exit")
    parser.add_argument("--provider", choices=["anthropic", "local"], default="anthropic",
                        help="anthropic: the Anthropic API (default); local: a model on your own server -- Ollama or "
                             "an OpenAI-compatible server, from the older local_models.json settings (or "
                             "--local-settings). No API key or cost; results aren't validated like the API's")
    parser.add_argument("--local-settings", type=Path, default=None,
                        help="local model settings file (default: the app's local_models.json)")
    parser.add_argument("--draft-pack", metavar="ID", default=None,
                        help="Draft a NEW data pack from sample papers (--papers LIST / --pdf / --paper): a cheap "
                             "survey of each paper's variables, then one request that designs columns, categories, "
                             "stages and row rules; written to your data packs folder (needs --area-name)")
    parser.add_argument("--area-name", default="", help="Name of the data pack to draft (--draft-pack)")
    parser.add_argument("--find-compounds", nargs="?", const="", default=None, metavar="ID",
                        help="Find the compounds named in a data pack's columns and examples (local + PubChem, no "
                             "model) and switch its chemistry step on for them. With --draft-pack: right after "
                             "drafting; else give the id of one of your data packs")
    parser.add_argument("--add-module", nargs=2, metavar=("MODULE", "ID"), default=None,
                        help="Add a shared module to one of your data packs: 'analysis' (the analysis step + a copy "
                             "of the technique vocabulary) or 'solution_chemistry' (the chemistry step + its "
                             "calculations). --draft-pack adds 'analysis' by itself when the papers name techniques")
    parser.add_argument("--no-modules", action="store_true",
                        help="--draft-pack: don't add shared modules (the analysis step) to the drafted pack")
    parser.add_argument("--suggest-additions", metavar="ID", default=None,
                        help="Survey sample papers (--papers / --pdf / --paper) and suggest what one of your research "
                             "areas lacks (parameters, steps, categories, rules, compounds); prints them")
    parser.add_argument("--draft-modules", action="store_true",
                        help="propose shared modules from sample papers (--papers / --pdf): surveys + one design "
                             "request; prints them and writes a report; --write-modules writes the ones that pass "
                             "the checks to your modules folder")
    parser.add_argument("--write-modules", action="store_true", help="with --draft-modules: write the modules")
    parser.add_argument("--modules-out", metavar="DIR", default=None,
                        help="with --write-modules: the folder to write them into (default: your modules folder)")
    parser.add_argument("--survey-cache", metavar="DIR", default=None,
                        help="reuse surveys made before (drafting / --draft-modules): the folder they're kept in "
                             "(default: <app data>/survey_cache)")
    parser.add_argument("--survey-passes", type=int, default=2, choices=[1, 2, 3],
                        help="--draft-pack / --suggest-additions: survey each paper this many times (cheap) and merge "
                             "(default 2)")
    parser.add_argument("--no-tidy", action="store_true",
                        help="--draft-pack / --suggest-additions / --find-compounds: keep the model's column names "
                             "instead of the app's conventions (initial_pH, initial_temperature_C, ...)")
    parser.add_argument("--apply-suggestions", action="store_true",
                        help="With --suggest-additions: write every suggestion into the data pack")
    parser.add_argument("--area-description", default="", help="A sentence on the field (--draft-pack)")
    parser.add_argument("--list-local-models", action="store_true",
                        help="List the local server's models and your local profiles, then exit")
    parser.add_argument("--passes", type=int, default=1, choices=[1, 2, 3],
                        help="Run the extraction steps 2 or 3 times and keep each value by vote (cheap runs: "
                             "use with --models economy); disagreements are flagged")
    parser.add_argument("--batch", action="store_true",
                        help="Batch mode: every request at half price through Anthropic's Message Batches API; "
                             "each step waits in the batch queue (usually minutes, at most 24 h)")
    parser.add_argument("--no-si", action="store_true",
                        help="Don't read a paper's supplementary information ('<paper>_SI.pdf' next to it) with it")
    parser.add_argument("--no-images", action="store_true",
                        help="Don't keep table crops (tables/) or figure images in the run folder")
    parser.add_argument("--all-figure-images", action="store_true",
                        help="Also keep the images of figures that weren't digitized (normally removed)")
    parser.add_argument("--auto-figures", action="store_true",
                        help="Digitize easy figures automatically: request suggestions for every figure and keep "
                             "the bar charts / scatter plots that parse cleanly (flagged for checking)")
    parser.add_argument("--no-suggestions", action="store_true",
                        help="Don't suggest new variables: no open-ended capture of conditions without a column "
                             "(new variables are listed in one flag and new_variables.json, never added)")
    from parameter_extractor import dev_features
    parser.add_argument("--handoff", metavar="DIR", default=None,
                        help=("Developer only: write the model requests to DIR for answers from a Claude Code "
                              "session instead of calling the API; run again once they're answered")
                        if dev_features.enabled() else argparse.SUPPRESS)
    parser.add_argument("--no-cache", action="store_true",
                        help="Don't share the cached paper between steps (costs more; for comparison)")
    parser.add_argument("--skip-stage", action="append", default=[], metavar="STAGE",
                        help="Don't run this optional extraction stage (repeatable; --list-packs shows each "
                             "pack's stages), e.g. --skip-stage fit_models")
    args = parser.parse_args()
    from parameter_extractor import packs
    from parameter_extractor.stages.optional import toggleable_stages
    if args.list_packs:
        for pack_id, pack in sorted(packs.available().items()):
            print(f"{pack_id:24} {pack.label} -- {pack.manifest.description}")
            for t in toggleable_stages(pack):
                print(f"    step  {t.name:22} {t.label}" + (" (when the paper calls for it)" if t.conditional else ""))
        return 0
    if args.pack not in packs.available():
        parser.error(f"unknown pack '{args.pack}' (see --list-packs)")
    known = [t.name for t in toggleable_stages(packs.available()[args.pack])]
    for name in args.skip_stage:
        if name not in known:
            parser.error(f"'{name}' isn't an optional stage of {args.pack}: {', '.join(known) or 'none'}")
    if args.list_parameters:
        from parameter_extractor.focused_search import available_parameters
        group = None
        for p in available_parameters(packs.available()[args.pack],
                                      {name: "off" for name in args.skip_stage}):
            if p.group != group:
                print(p.group)
                group = p.group
            print(f"    {p.column:26} {p.description[:90]}" + (f" [{p.unit}]" if p.unit else ""))
        return 0
    if args.list_local_models:
        return _list_local_models(args)
    if args.list_models:
        return _list_models()
    if args.draft_modules:
        return _draft_modules(args, parser)
    if args.draft_pack:
        return _draft_pack(args, parser)
    if args.add_module:
        from parameter_extractor import pack_modules
        module, pack_id = args.add_module
        try:
            for line in pack_modules.add_module(_user_pack(pack_id).folder, module):
                print(line)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0
    if args.suggest_additions:
        return _suggest_additions(args, parser)
    if args.find_compounds:
        return _find_compounds(args.find_compounds, args)
    if args.focus:
        return _focused(args, parser)
    if args.resume and args.rebuild:
        parser.error("--resume and --rebuild: choose one")
    if not args.pdf and not args.paper and not args.queue and not args.resume and not args.rebuild:
        parser.error("--pdf, --paper, --queue, --resume or --rebuild is required")

    from parameter_extractor.registry import default_arxiv_cache_dir, default_pubchem_cache_path, default_registry_path
    overrides = {"paper_prefix": args.prefix, "registry_path": default_registry_path(),
                 "focus_terms": args.look_for, "use_pubchem": not args.no_pubchem,
                 "equations_to_latex": args.equations_latex, "pack": args.pack,
                 "online_checks": not args.no_pubchem,
                 "optional_stages": {name: "off" for name in args.skip_stage},
                 "prompt_caching": not args.no_cache,
                 "batch_mode": args.batch, "prefer_arxiv": args.arxiv,
                 "suggest_new_variables": not args.no_suggestions, "passes": args.passes,
                 "include_supplements": not args.no_si,
                 "save_images": not args.no_images, "save_all_figure_images": args.all_figure_images,
                 "auto_digitize_figures": args.auto_figures,
                 "pubchem_cache_path": default_pubchem_cache_path(), "arxiv_cache_dir": default_arxiv_cache_dir()}
    if args.ads_token is not None:
        overrides["ads_token"] = args.ads_token
    if args.out:
        overrides["output_dir"] = args.out
    elif args.resume or args.rebuild:                    # the new folder next to the old one
        overrides["output_dir"] = Path(args.resume or args.rebuild).resolve().parent
    if args.handoff:
        if not dev_features.enabled():
            parser.error("--handoff is a developer-only option (set PARAMETER_EXTRACTOR_DEV=1 when running "
                         "from source)")
        overrides.update(handoff_dir=Path(args.handoff), batch_mode=False)
    overrides.update(_provider_overrides(args, parser))
    config = RunConfig.from_settings(**overrides)

    if args.queue:
        return _queue(args, config)
    if args.resume or args.rebuild:
        return _resume(args, config)
    try:
        if args.triage_only:
            triage = run_triage_only(args.pdf, config, on_progress=print_progress)
            print(f"\nTriage recommendation: {triage.recommendation}\n{triage.reasoning}")
            if triage.excluded_experiment_note:
                print(f"Excluded-experiment note: {triage.excluded_experiment_note}")
            return 0

        result = run_pipeline(args.paper or args.pdf, config, on_progress=print_progress)
    except PipelineError as e:
        print(f"\nError: {e}", file=sys.stderr)
        run_dir = getattr(e, "run_dir", None)          # e.g. out of credits: say so in the run folder too
        if run_dir and Path(run_dir).is_dir():
            with open(Path(run_dir) / "error.txt", "a") as f:
                f.write(f"{e}\n")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    _report(result)
    return 0


def _report(result) -> None:
    print(f"\nWrote {len(result.rows)} rows -> {result.csv_path}")
    if result.flags_path:
        print(f"{len(result.paper_flags)} paper-level flag(s), {len(result.row_flags)} row(s) "
              f"flagged -> {result.flags_path}")
    if result.new_variables:
        names = sorted({v.name for v in result.new_variables})
        print(f"{len(names)} new variable(s) left out of the CSV (accept them in the desktop app's "
              f"review screen): {', '.join(names)}")
    if result.unfound_terms:
        print(f"Not stated in the paper: {'; '.join(result.unfound_terms)}")
    if result.equations:
        print(f"{len(result.equations)} labelled equation(s) -> {result.run_dir / 'equations'} "
              f"(details in equations.json)")
        for e in result.equations:
            if e.latex:
                print(f"  ({e.label})  {e.latex}")
    print(f"Tokens: {result.input_tokens:,} in ({result.cached_tokens:,} from cache) / {result.output_tokens:,} out "
          f"(estimated cost {format_usd(result.cost_usd)})")
    reused = [u.stage for u in result.usage if getattr(u, "reused", False)]
    if reused:
        print(f"Reused from the earlier run (no cost): {', '.join(reused)}")


def _queue_progress():
    shown = {}
    def changed(paper):
        line = f"[{paper.prefix}] {paper.label}: {paper.status}" + (f" -- {paper.error}" if paper.error else "")
        if shown.get(paper.prefix) != line:
            shown[paper.prefix] = line
            print(line)
    return changed


def _resume(args, config) -> int:
    """--resume / --rebuild FOLDER (resume.py, W1): a run folder, or a paper queue's folder."""
    from parameter_extractor import resume
    from parameter_extractor.paper_queue import run_queue
    folder, rebuild = Path(args.resume or args.rebuild), bool(args.rebuild)
    what = "Rebuilding" if rebuild else "Resuming"
    try:
        if resume.is_queue_folder(folder) and not (folder / resume.CONFIG_FILE).is_file():
            print(f"{what} the paper queue in {folder}")
            queue = run_queue([], config, on_change=_queue_progress(), parallel=args.parallel, resume_from=folder,
                              rebuild=rebuild)
            finished = [p for p in queue.papers if p.result is not None]
            print(f"\n{len(finished)} of {len(queue.papers)} paper(s) assembled -> {queue.out_dir}")
            return 0 if finished else 1
        print(f"{what} {folder}")
        result = resume.resume_run(folder, config, rebuild=rebuild, on_progress=print_progress)
    except PipelineError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    _report(result)
    return 0


def _queue(args, config) -> int:
    from parameter_extractor.focused_search import read_paper_list
    from parameter_extractor.paper_queue import run_queue
    items = read_paper_list(args.queue)
    if not items:
        print(f"No papers found in {args.queue}.", file=sys.stderr)
        return 1
    try:
        queue = run_queue(items, config, on_change=_queue_progress(), parallel=args.parallel)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    finished = [p for p in queue.papers if p.result is not None]
    print(f"\n{len(finished)} of {len(queue.papers)} paper(s) assembled, {sum(len(p.result.rows) for p in finished)} rows "
          f"-> {queue.out_dir}")
    print(f"Combined CSV: {queue.out_dir / 'combined_extracted.csv'}\nPapers: {queue.out_dir / 'papers.csv'}")
    return 0 if finished else 1


def _focused(args, parser) -> int:
    from parameter_extractor.focused_search import read_paper_list, run_focused_search
    items = list(read_paper_list(args.papers, only_failed=args.only_failed)) if args.papers else []
    items += [Path(args.pdf)] if args.pdf else []
    items += [args.paper] if args.paper else []
    if not items:
        parser.error("a focused search needs papers: --papers LIST, --paper ID or --pdf")
    from parameter_extractor.registry import default_arxiv_cache_dir
    overrides = {"pack": args.pack, "batch_mode": args.batch,
                 "include_supplements": not args.no_si,
                 "prefer_arxiv": args.arxiv, "optional_stages": {name: "off" for name in args.skip_stage},
                 "arxiv_cache_dir": default_arxiv_cache_dir()}
    if args.ads_token is not None:
        overrides["ads_token"] = args.ads_token
    if args.out:
        overrides["output_dir"] = args.out
    if args.handoff:
        from parameter_extractor import dev_features
        if not dev_features.enabled():
            parser.error("--handoff is a developer-only option (set PARAMETER_EXTRACTOR_DEV=1 when running "
                         "from source)")
        overrides.update(handoff_dir=Path(args.handoff), batch_mode=False)
    overrides.update(_provider_overrides(args, parser))
    config = RunConfig.from_settings(**overrides)
    try:
        run = run_focused_search(items, args.focus, config, search_words=args.search_word,
                                 whole_paper=args.whole_paper, whole_tables=not args.rows_only,
                                 plan_rows=args.plan_rows,
                                 on_progress=lambda done, total, message: print(f"[{done}/{total}] {message}"))
    except PipelineError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    counts = {}
    for o in run.outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    print(f"\n{len(run.outcomes)} paper(s): " + ", ".join(f"{n} {s}" for s, n in counts.items()))
    print(f"Values -> {run.results_csv}\nPapers -> {run.papers_csv}")
    print(f"Estimated cost {format_usd(run.cost_usd)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


PROFILE_FIELDS = ("provider", "model_profile", "profile_roles", "local", "max_tokens", "temperature",
                  "max_parallel_stages", "max_retries", "prices", "prompt_caching")


def _provider_overrides(args, parser) -> dict:
    """--models PROFILE -> RunConfig fields (model_profiles.apply: the profile's connection, models and settings).
    --provider local (before profiles named their connection): the saved local_models.json and one of its profiles."""
    if args.provider != "local":
        import os
        from parameter_extractor import model_profiles as mp
        from parameter_extractor.errors import PipelineError
        store = mp.ModelStore()
        profile = args.models or "standard"
        found = store.profile(profile)
        if found is None:
            parser.error(f"--models {profile}: no such profile ({', '.join(p.id for p in store.profiles())}; "
                         f"--list-models describes them)")
        conn = store.connection(found.connection)
        key = os.environ.get("LOCAL_SERVER_API_KEY", "")
        if conn is not None and not conn.is_anthropic and not key:
            try:
                from parameter_extractor.gui import key_store
                key = key_store.load_key(conn.account) or ""
            except Exception:
                key = ""
        try:
            applied = mp.apply(RunConfig(api_key="", output_dir=Path(".")), profile, store, key=key)
        except PipelineError as e:
            parser.error(str(e))
        out = {k: getattr(applied, k) for k in PROFILE_FIELDS}
        out["prompt_caching"] = applied.prompt_caching and not getattr(args, "no_cache", False)
        return out
    import os
    from parameter_extractor import local_models
    local = local_models.load(args.local_settings)
    local.api_key = os.environ.get("LOCAL_SERVER_API_KEY", "")
    if not local.profiles:
        parser.error("no local model profiles yet: set up model servers in the app (Models > Connections) and use --models PROFILE, or write "
                     f"{args.local_settings or local_models.default_path()}")
    profile = args.models or next(iter(local.profiles))
    if profile not in local.profiles:
        parser.error(f"--models {profile}: not a local profile ({', '.join(local.profiles)})")
    return {"provider": "local", "local": local.to_dict(), "model_profile": profile}


def _list_models() -> int:
    from parameter_extractor import model_profiles as mp
    store = mp.ModelStore()
    print("Model profiles (--models PROFILE):")
    for p in store.profiles():
        conn = store.connection(p.connection)
        changed = " (changed from the default)" if store.is_changed(p.id) else ""
        print(f"  {p.id:20} {p.label}{changed} -- on {conn.name if conn else p.connection}")
        for role, label in mp.ROLES:
            print(f"      {label + ':':22} {p.roles.get(role) or '-'}")
        problems = store.problems(p)
        if problems:
            print(f"      can't run: {'; '.join(problems)}")
    print("Connections:")
    for c in store.all_connections():
        kind = "" if c.is_anthropic else f" ({mp.KINDS.get(c.kind, c.kind)}, {c.url})"
        print(f"  {c.name}{kind}: {len(c.models)} model(s)")
    return 0


def _list_local_models(args) -> int:
    from parameter_extractor import local_models
    from parameter_extractor.errors import PipelineError
    local = local_models.load(args.local_settings)
    print(f"{local_models.KINDS.get(local.kind, local.kind)} at {local.url}")
    try:
        for m in local_models.list_models(local):
            saved = local.models.get(m["name"])
            vision = {True: "reads images", False: "text only", None: "images: unknown"}[m["vision"]]
            print(f"    {m['name']:30} {vision:16} max context {m['max_context'] or '?'}"
                  + (f"  (set: {saved.context}, {'images' if saved.vision else 'no images'})" if saved else ""))
    except PipelineError as e:
        print(f"    {e}")
    for name, roles in local.profiles.items():
        print(f"profile {name}: " + "; ".join(f"{dict(local_models.PROFILE_ROLES)[r]}: {m}"
                                              for r, m in roles.items() if m))
    return 0


def _draft_modules(args, parser) -> int:
    from parameter_extractor import module_drafting
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.focused_search import read_paper_list
    from parameter_extractor.registry import default_registry_path
    items = list(read_paper_list(args.papers)) if args.papers else []
    items += [Path(args.pdf)] if args.pdf else []
    if not items:
        parser.error("--draft-modules needs sample papers: --papers LIST or --pdf")
    overrides = {"prefer_arxiv": args.arxiv, "include_supplements": not args.no_si}
    if args.out:
        overrides["output_dir"] = args.out
    overrides.update(_provider_overrides(args, parser))
    config = RunConfig.from_settings(**overrides)
    cache = Path(args.survey_cache) if args.survey_cache else default_registry_path().parent / "survey_cache"
    try:
        result = module_drafting.draft_modules(items, config, area=args.area_name or "the papers' research fields",
                                               on_progress=lambda d, n, m: print(f"[{d}/{n}] {m}"),
                                               passes=args.survey_passes, survey_cache=cache,
                                               write=args.write_modules,
                                               base=Path(args.modules_out) if args.modules_out else None)
    except (PipelineError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(module_drafting.report_text(result))
    print(f"Report: {result.work_dir / 'module_draft.md'}")
    for path in result.written:
        print(f"Module written: {path}")
    return 0


def _draft_pack(args, parser) -> int:
    from parameter_extractor import pack_drafting
    from parameter_extractor.errors import PipelineError
    from parameter_extractor.focused_search import read_paper_list
    items = list(read_paper_list(args.papers)) if args.papers else []
    items += [Path(args.pdf)] if args.pdf else []
    items += [args.paper] if args.paper else []
    if not items:
        parser.error("--draft-pack needs sample papers: --papers LIST, --pdf or --paper")
    if not args.area_name:
        parser.error("--draft-pack needs --area-name")
    overrides = {"prefer_arxiv": args.arxiv, "include_supplements": not args.no_si}
    if args.out:
        overrides["output_dir"] = args.out
    overrides.update(_provider_overrides(args, parser))
    config = RunConfig.from_settings(**overrides)
    from parameter_extractor.pubchem import PubChem
    from parameter_extractor.registry import default_pubchem_cache_path
    pubchem = None if args.no_pubchem else PubChem(default_pubchem_cache_path())
    try:
        result = pack_drafting.draft_pack(items, args.draft_pack, args.area_name, args.area_description, config,
                                          on_progress=lambda d, n, m: print(f"[{d}/{n}] {m}"),
                                          passes=args.survey_passes, tidy=not args.no_tidy,
                                          modules_on=not args.no_modules,
                                          compounds=True if args.find_compounds is not None else None,
                                          pubchem=pubchem)
        if pubchem is not None:
            pubchem.save()
    except (PipelineError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Data pack written to {result.pack.folder} (report: drafted_from.md; work files: {result.work_dir})")
    for module, lines in result.modules.items():
        print(f"Module '{module}' added (" + "; ".join(f"{p}: {', '.join(t[:4])}" for p, t in
                                                     result.module_evidence.get(module, {}).items()) + "):")
        for line in lines:
            print(f"  {line}")
    for line in result.left_to_modules:
        print(f"  left to a module: {line}")
    for line in result.compound_lines:
        print(f"  compounds: {line}")
    for p in result.problems:
        print(f"  {p}")
    return 0


def _user_pack(pack_id: str):
    from parameter_extractor import packs
    pack = packs.available().get(pack_id)
    if pack is None or not str(pack.folder).startswith(str(packs.user_packs_dir())):
        raise SystemExit(f"'{pack_id}' isn't one of your data packs (the app's own can't be changed: copy one "
                         f"first). Yours: {', '.join(p for p, x in packs.available().items() if str(x.folder).startswith(str(packs.user_packs_dir()))) or 'none'}")
    return pack


def _find_compounds(pack_id: str, args) -> int:
    from parameter_extractor import compound_setup
    from parameter_extractor.pubchem import PubChem
    from parameter_extractor.registry import default_pubchem_cache_path
    pack = _user_pack(pack_id)
    plan, done, problems = compound_setup.set_up_compounds(
        pack.folder, None if args.no_pubchem else PubChem(default_pubchem_cache_path()), tidy=not args.no_tidy)
    for c in plan.compounds:
        print(f"  {c.name:30} CID {c.cid or '-':<10} {', '.join(c.columns())}   ({'; '.join(c.sources)})")
    for line in done:
        print(line)
    if plan.not_identified:
        print("not identified: " + ", ".join(plan.not_identified))
    for p in problems:
        print(f"  {p}")
    return 0


def _suggest_additions(args, parser) -> int:
    from parameter_extractor import pack_drafting
    from parameter_extractor.errors import PipelineError
    from parameter_extractor.focused_search import read_paper_list
    from parameter_extractor.pubchem import PubChem
    from parameter_extractor.registry import default_pubchem_cache_path
    pack = _user_pack(args.suggest_additions)
    items = list(read_paper_list(args.papers)) if args.papers else []
    items += [Path(args.pdf)] if args.pdf else []
    items += [args.paper] if args.paper else []
    if not items:
        parser.error("--suggest-additions needs sample papers: --papers LIST, --pdf or --paper")
    overrides = {"prefer_arxiv": args.arxiv, "include_supplements": not args.no_si}
    if args.out:
        overrides["output_dir"] = args.out
    overrides.update(_provider_overrides(args, parser))
    try:
        result = pack_drafting.suggest_additions(pack.folder, items, RunConfig.from_settings(**overrides),
                                                 on_progress=lambda d, n, m: print(f"[{d}/{n}] {m}"),
                                                 passes=args.survey_passes, tidy=not args.no_tidy)
    except PipelineError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    for s in result.suggestions:
        print(f"  [{s.kind}] {s.title}: {s.detail}" + (f"  ({s.reason})" if s.reason else ""))
    if result.left_out:
        print("already covered: " + ", ".join(result.left_out))
    if args.apply_suggestions and result.suggestions:
        done, problems = pack_drafting.apply_additions(pack.folder, result.suggestions,
                                                       None if args.no_pubchem else PubChem(default_pubchem_cache_path()))
        print("\n".join(done))
        for p in problems:
            print(f"  {p}")
    return 0
