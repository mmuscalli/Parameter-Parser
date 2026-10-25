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
                        help="Domain pack (research area) to extract with; see --list-packs")
    parser.add_argument("--list-packs", action="store_true", help="List the available domain packs and exit")
    parser.add_argument("--no-pubchem", action="store_true",
                        help="No online lookups: PubChem species names, NASA Exoplanet Archive check "
                             "(only names are sent)")
    parser.add_argument("--equations-latex", action="store_true",
                        help="Convert the paper's labelled equations to LaTeX (one small extra API call); "
                             "they're found and cropped either way")
    parser.add_argument("--models", choices=["standard", "economy"], default="standard",
                        help="standard: Claude Sonnet 5.5 for every step (most accurate); economy: Claude Haiku "
                             "5.5 for every step (roughly 4-20x cheaper; misses more on complex papers)")
    parser.add_argument("--batch", action="store_true",
                        help="Batch mode: every request at half price through Anthropic's Message Batches API; "
                             "each step waits in the batch queue (usually minutes, at most 24 h)")
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
                print(f"    stage {t.name:22} {t.label}" + (" (when the paper calls for it)" if t.conditional else ""))
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
    if args.focus:
        return _focused(args, parser)
    if not args.pdf and not args.paper:
        parser.error("--pdf or --paper is required")

    from parameter_extractor.registry import default_arxiv_cache_dir, default_pubchem_cache_path, default_registry_path
    overrides = {"paper_prefix": args.prefix, "registry_path": default_registry_path(),
                 "focus_terms": args.look_for, "use_pubchem": not args.no_pubchem,
                 "equations_to_latex": args.equations_latex, "pack": args.pack,
                 "online_checks": not args.no_pubchem,
                 "optional_stages": {name: "off" for name in args.skip_stage},
                 "model_profile": args.models, "prompt_caching": not args.no_cache,
                 "batch_mode": args.batch, "prefer_arxiv": args.arxiv,
                 "pubchem_cache_path": default_pubchem_cache_path(), "arxiv_cache_dir": default_arxiv_cache_dir()}
    if args.ads_token is not None:
        overrides["ads_token"] = args.ads_token
    if args.out:
        overrides["output_dir"] = args.out
    config = RunConfig.from_settings(**overrides)

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
    return 0


def _focused(args, parser) -> int:
    from parameter_extractor.focused_search import read_paper_list, run_focused_search
    items = list(read_paper_list(args.papers, only_failed=args.only_failed)) if args.papers else []
    items += [Path(args.pdf)] if args.pdf else []
    items += [args.paper] if args.paper else []
    if not items:
        parser.error("a focused search needs papers: --papers LIST, --paper ID or --pdf")
    from parameter_extractor.registry import default_arxiv_cache_dir
    overrides = {"pack": args.pack, "model_profile": args.models, "batch_mode": args.batch,
                 "prefer_arxiv": args.arxiv, "optional_stages": {name: "off" for name in args.skip_stage},
                 "arxiv_cache_dir": default_arxiv_cache_dir()}
    if args.ads_token is not None:
        overrides["ads_token"] = args.ads_token
    if args.out:
        overrides["output_dir"] = args.out
    config = RunConfig.from_settings(**overrides)
    try:
        run = run_focused_search(items, args.focus, config, search_words=args.search_word,
                                 whole_paper=args.whole_paper, whole_tables=not args.rows_only,
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
