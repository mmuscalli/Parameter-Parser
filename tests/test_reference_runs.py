"""
Reference runs (runs/reference/<name>/, recorded with scripts/record_reference.py): every one is
replayed through the current code -- the model's recorded answers instead of API calls, arXiv texts
from the folder's cache seed, archive rows from the folder -- and must reproduce its expected CSV,
observations and archive check byte for byte. Free; a changed output means a changed behaviour:
check it, then re-record if the change is right.

Run with: python tests/test_reference_runs.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PaperSourceError
from parameter_extractor.ingestion import arxiv_source as ax
from parameter_extractor.validation import exoplanet_archive
from test_pipeline_offline import make_replay

REFERENCES = ROOT / "runs" / "reference"
PAPERS = ROOT.parent / "Paper Files"


def replay_reference(ref: Path, out: Path):
    """Replay one reference run into `out`; None when its PDF isn't on this computer."""
    from parameter_extractor.pipeline import run_pipeline
    m = json.loads((ref / "reference.json").read_text())
    cfg = dict(api_key="replay-not-a-real-key", output_dir=out, pack=m["pack"], online_checks=m["online_checks"],
               use_pubchem=False, registry_path=None)
    saved = json.loads((ref / "archive_rows.json").read_text()) if (ref / "archive_rows.json").is_file() else []
    def offline(*args, **kwargs):
        raise PaperSourceError("a reference replay doesn't use the network")
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", make_replay(ref)), \
            patch.object(ax, "_get", offline), \
            patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, r: saved):
        if m.get("arxiv"):
            shutil.copytree(ref / "arxiv_cache", Path(tmp) / "cache")
            cfg["arxiv_cache_dir"] = Path(tmp) / "cache"
            item = f"arXiv:{m['arxiv']}"
        else:
            item = PAPERS / m["pdf"]
            if not item.is_file():
                return None
        try:
            return run_pipeline(item, RunConfig.from_settings(**cfg))
        finally:
            packs.activate("prebiotic_chemistry")


def test_every_reference_run_reproduces_its_outputs():
    refs = sorted(p for p in REFERENCES.iterdir() if (p / "reference.json").is_file())
    assert refs, "no reference runs"
    for ref in refs:
        with tempfile.TemporaryDirectory() as tmp:
            result = replay_reference(ref, Path(tmp))
            if result is None:
                print(f"SKIP: {ref.name} -- its PDF isn't on this computer")
                continue
            assert result.csv_path.read_text() == (ref / "expected_extracted.csv").read_text(), ref.name
            assert result.observations_path.read_text() == (ref / "expected_observations.csv").read_text(), ref.name
            if (ref / "archive_validation.json").is_file():
                got = json.loads((result.run_dir / "archive_validation.json").read_text())
                assert got == json.loads((ref / "archive_validation.json").read_text()), ref.name
            print(f"  {ref.name}: {len(result.rows)} rows reproduced")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All reference runs reproduced.")
