"""
Chains the stages for ONE paper. Each stage's output is validated (Pydantic)
and written to runs/<paper_id>/ before the next stage runs, so a failure
partway through still leaves the earlier stages' work inspectable.
"""
from __future__ import annotations
import json
from pathlib import Path

from config import settings
from ingestion.pdf_parser import parse_pdf, rasterize_table_pages
from ingestion.flatten_to_template import build_rows, write_csv
from stages.triage import run_triage
from stages.structure_planner import run_structure_planner
from stages.metadata_extractor import run_metadata_extraction
from stages.methodology_extractor import run_methodology_extraction
from stages.chemistry_extractor import run_chemistry_extraction
from validation.plausibility_checks import check_row


def run_pipeline(pdf_path: str, paper_prefix: str = "001") -> Path:
    parsed = parse_pdf(pdf_path)
    run_dir = settings.RUNS_DIR / parsed.paper_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "parsed_paper.json").write_text(parsed.to_json())

    if not parsed.has_text_layer:
        raise RuntimeError(f"{parsed.paper_id}: no text layer -- OCR needed, not implemented.")

    table_images = []
    if settings.RASTERIZE_TABLE_PAGES and parsed.table_pages:
        images_by_page = rasterize_table_pages(
            parsed, run_dir / "page_images", dpi=settings.TABLE_RASTER_DPI
        )
        table_images = [images_by_page[p] for p in sorted(images_by_page)]
        print(f"[{parsed.paper_id}] rasterized {len(table_images)} table page(s): "
              f"{[str(p) for p in table_images]}")

    triage = run_triage(parsed.paper_id, parsed.text, run_dir)
    if triage.recommendation == "exclude":
        print(f"[{parsed.paper_id}] EXCLUDED at triage: {triage.reasoning}")
        return run_dir

    structure = run_structure_planner(parsed.paper_id, parsed.text, run_dir, table_images=table_images)
    metadata = run_metadata_extraction(parsed.paper_id, parsed.page_texts[0], run_dir)
    methodology = run_methodology_extraction(parsed.paper_id, parsed.text, structure, run_dir)

    vocab = json.loads((settings.SCHEMAS_DIR / "template_vocab.json").read_text())
    chemistry = run_chemistry_extraction(
        parsed.paper_id, parsed.text, structure, vocab["species_names"], run_dir,
        table_images=table_images,
    )

    rows = build_rows(metadata, structure, methodology, chemistry, paper_prefix)

    flags_by_row = {r.full_id: check_row(r) for r in rows}
    n_flagged = sum(1 for f in flags_by_row.values() if f)
    if n_flagged:
        print(f"[{parsed.paper_id}] {n_flagged}/{len(rows)} rows have plausibility flags -- see flags.json")
        (run_dir / "plausibility_flags.json").write_text(json.dumps(flags_by_row, indent=2))

    out_csv = run_dir / f"{parsed.paper_id}_extracted.csv"
    write_csv(rows, out_csv)
    print(f"[{parsed.paper_id}] wrote {len(rows)} rows -> {out_csv}")

    if settings.USE_GOLD_STANDARD:
        from validation.gold_standard_eval import load_gold_standard, score_paper
        gold = load_gold_standard()
        print(score_paper([r.model_dump() for r in rows], gold))
    else:
        print(f"[{parsed.paper_id}] gold-standard scoring is OFF (config.settings.USE_GOLD_STANDARD "
              f"= False) -- enable it once the curated subset is ready.")

    return run_dir
