"""
For replay tests: the nested record a run wrote (<paper>_record.json, record_tree.py) gives back its dataset CSV byte for
byte -- so every replayed fixture also checks the tree (branch levels-and-facets).
"""
import json
import tempfile
from pathlib import Path


def json_reproduces_csv(result) -> bool:
    from parameter_extractor import packs, record_tree
    from parameter_extractor.column_order import ColumnOrder
    from parameter_extractor.ingestion.flatten_to_template import write_template_csv
    from parameter_extractor.ingestion.observations import observations_to_records
    data = json.loads(Path(result.record_path).read_text())
    previous = packs.current().id
    packs.activate(data.get("data_pack") or result.pack or previous)
    try:
        chosen = {a["column"]: a.get("category", "") for a in result.accepted_variables}
        back = record_tree.flatten(record_tree.from_json(data), ColumnOrder(chosen=chosen))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "back.csv"
            write_template_csv(observations_to_records(back), out, column_categories=chosen)
            return out.read_text() == Path(result.csv_path).read_text()
    finally:
        packs.activate(previous)
