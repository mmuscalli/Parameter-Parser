"""
A paper's data as a tree of levels and facets (record_tree.py, branch levels-and-facets step 1): values sit as high as
their facet allows when every row under a node agrees (value AND provenance), and flattening gives back exactly what
the tree was built from. Gate: for every reference run, the tree reproduces its expected dataset CSV and observations
CSV byte for byte, and the JSON written beside them reproduces the dataset CSV byte for byte (and the same
observations; JSON keeps no order within a row). No API calls.

Run with: python tests/test_record_tree.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs, record_tree  # noqa: E402
from parameter_extractor.column_order import ColumnOrder  # noqa: E402
from parameter_extractor.ingestion.observations import Observation  # noqa: E402


def _obs(full_id, column, value, **kw):
    return Observation(full_id=full_id, set_id=full_id[:6], sample_id=full_id[6:], entry_number=int(full_id[6:]),
                       column=column, value=value, **kw)


def _facets():
    packs.activate("prebiotic_chemistry")
    order = ColumnOrder()
    return record_tree.Facets(order, record_tree.levels()), order


def test_values_sit_as_high_as_their_facet_allows_and_their_rows_agree():
    facets, order = _facets()
    meta = dict(origin="metadata", source="title page")
    obs = []
    for fid, yld in (("001001001", 2.5), ("001001002", 3.0), ("001002001", 1.0)):
        obs += [_obs(fid, "paper_title", "A paper", **meta),
                _obs(fid, "initial_temperature_C", 81.0 if fid < "001002" else 90.0, origin="structure", source="T1"),
                _obs(fid, "sampled_Gly-Gly_aq_%yield", 2.0, origin="chemistry", source=f"row {fid}"),
                _obs(fid, "vessel_material", "glass", origin="methodology", source="Methods")]
    obs.append(_obs("001001002", "initial_pH", 7.0, origin="structure", source="T1"))       # one row only
    paper = record_tree.build(obs, facets)
    s1, s2 = paper.children
    assert paper.id == "001" and set(paper.values) == {"paper_title"}           # metadata: up to the paper
    assert "initial_temperature_C" in s1.values and "initial_temperature_C" in s2.values   # differs between sets
    assert "vessel_material" in s1.values and "vessel_material" not in paper.values   # methodology: at most the set
    # same value, different provenance: stays on each row; a measured product never goes above its row
    assert all("sampled_Gly-Gly_aq_%yield" in r.values for r in s1.children)
    assert "initial_pH" in s1.children[1].values and "initial_pH" not in s1.values      # not every row has it
    # each row keeps its own order of values: flattening gives back the very list
    by_row = {}
    for o in obs:
        by_row.setdefault(o.full_id, []).append(o)
    assert record_tree.flatten(paper) == [o for fid in by_row for o in by_row[fid]]


def test_a_number_and_its_text_are_not_one_value():
    facets, _ = _facets()
    obs = [_obs("001001001", "initial_temperature_C", 81.0), _obs("001001002", "initial_temperature_C", 81)]
    paper = record_tree.build(obs, facets)
    assert not paper.children[0].values and record_tree.flatten(paper) == obs


def test_the_json_round_trip_and_its_shape():
    facets, order = _facets()
    obs = [_obs("001001001", "paper_title", "T", origin="metadata"), _obs("001001001", "initial_pH", 7.0, unit="pH"),
           _obs("001001002", "paper_title", "T", origin="metadata"), _obs("001001002", "initial_pH", 8.0, unit="pH",
                                                                          quote="pH 8", page=3, confidence="high")]
    data = record_tree.to_json(record_tree.build(obs, facets, {"001001": "Table 1 block", "001001002": "run 2"}),
                               facets)
    json.dumps(data)                                                              # plain JSON
    assert data["format"] == record_tree.FORMAT and [lv["id"] for lv in data["levels"]] == ["paper", "set", "sample"]
    assert {f["id"]: f["level"] for f in data["facets"]}["metadata"] == "paper"
    p = data["paper"]
    assert p["facets"] == {"metadata": {"paper_title": {"value": "T", "origin": "metadata"}}}
    row2 = p["children"][0]["children"][1]
    assert p["children"][0]["label"] == "Table 1 block" and row2["label"] == "run 2"
    assert row2["facets"]["conditions"]["initial_pH"] == {"value": 8.0, "unit": "pH", "page": 3, "quote": "pH 8",
                                                         "confidence": "high"}
    back = record_tree.flatten(record_tree.from_json(json.loads(json.dumps(data))), order)
    assert sorted(map(repr, back)) == sorted(map(repr, obs))


def test_a_correction_changes_only_its_row():
    facets, _ = _facets()
    obs = [_obs(f"00100100{i}", "initial_temperature_C", 81.0, source="T1") for i in (1, 2, 3)]
    paper = record_tree.build(obs, facets)
    assert "initial_temperature_C" in paper.children[0].values
    assert record_tree.set_value(paper, "001001002", "initial_temperature_C", dict(obs[0].model_dump(
        include=set(record_tree.PAYLOAD)), value=85.0))
    values = [o.value for o in record_tree.flatten(paper)]
    assert values == [81.0, 85.0, 81.0]
    assert record_tree.set_value(paper, "001001003", "initial_temperature_C", None)
    assert [o.full_id for o in record_tree.flatten(paper)] == ["001001001", "001001002"]
    assert not record_tree.set_value(paper, "009009009", "x", None)


def test_levels_and_their_limit():
    assert record_tree.check_levels([{"id": "paper", "label": "paper"}, {"id": "set", "label": "set"},
                                     {"id": "run", "label": "run"}, {"id": "obs", "label": "observation"}]) == []
    five = [{"id": f"l{i}", "label": f"level {i}"} for i in range(5)]
    assert any("at most 4" in p for p in record_tree.check_levels(five))
    assert record_tree.check_levels(five, limit=5) == []                         # the pack's level_limit
    assert record_tree.check_levels([{"id": "paper", "label": "paper"}])
    packs.activate("exoplanets")
    assert [lv.label for lv in record_tree.levels()][1:] == [packs.current().manifest.units["set"],
                                                             packs.current().manifest.units["sample"]]
    packs.activate("prebiotic_chemistry")


def test_runs_within_a_set_are_a_level_of_their_own():
    """Step 4: a row plan whose samples name a run (several experiments in one set, each sampled more than once) puts
    a run level between the set and its samples; without runs the tree is as before. Values a run's samples share
    sit on the run."""
    from types import SimpleNamespace
    packs.activate("prebiotic_chemistry")
    order = ColumnOrder()
    obs = []
    for fid, start, t in (("001001001", "G", 1.0), ("001001002", "G", 2.0), ("001001003", "GG", 1.0),
                          ("001001004", "GG", 2.0), ("001002001", "G", 5.0)):
        obs += [_obs(fid, "initial_Gly_aq_mM", 10.0 if start == "G" else 0.0, source=f"Fig. 5 {start}"),
                _obs(fid, "duration_hr", t, source=f"row {fid}")]
    sample = lambda label, run="": SimpleNamespace(sample_label=label, run=run)       # noqa: E731
    plan = SimpleNamespace(experiment_sets=[
        SimpleNamespace(set_label="160 C", samples=[sample("1 min", "starting with G"), sample("2 min", "starting with G"),
                                                    sample("1 min", "starting with GG"), sample("2 min", "starting with GG")]),
        SimpleNamespace(set_label="other", samples=[sample("5 min")])])
    runs = record_tree.plan_runs(plan, obs)
    assert runs == {"001001001": "starting with G", "001001002": "starting with G", "001001003": "starting with GG",
                    "001001004": "starting with GG"}
    facets = record_tree.Facets(order, record_tree.levels(runs=True))
    assert [lv.id for lv in facets.levels] == ["paper", "set", "run", "sample"]
    paper = record_tree.build(obs, facets, record_tree.plan_labels(plan, obs), runs)
    s1, s2 = paper.children
    assert [c.label for c in s1.children] == ["starting with G", "starting with GG"] and s1.children[0].level == 2
    assert "initial_Gly_aq_mM" in s1.children[0].values                 # shared by the run's samples: on the run
    assert s2.children[0].level == 3 and not s2.children[0].children     # a set without runs: samples under it
    assert record_tree.flatten(paper) == obs
    data = record_tree.to_json(paper, facets)
    assert [lv["id"] for lv in data["levels"]] == ["paper", "set", "run", "sample"]
    back = record_tree.flatten(record_tree.from_json(json.loads(json.dumps(data))), order)
    assert sorted(map(repr, back)) == sorted(map(repr, obs))
    assert [lv.id for lv in record_tree.levels()] == ["paper", "set", "sample"]          # no runs: as before
    from parameter_extractor.schemas.structure_plan import PlannedSample
    assert PlannedSample.model_validate({"label": "t = 1 h"}).run == ""                  # older plans load


def test_runs_read_from_row_labels():
    """A pack with runs_from_labels (exoplanets): rows labelled 'name [which]' that share a name are a run."""
    from types import SimpleNamespace
    smp = lambda label: SimpleNamespace(sample_label=label)                      # noqa: E731
    pset = SimpleNamespace(samples=[smp("HD 14067 b [RV fit, Table 3]"), smp("HD 14067 b [joint fit, Table 4]"),
                                    smp("HD 14067 c"), smp("HD 99 b [only one]")])
    assert record_tree.label_runs(pset) == {0: "HD 14067 b", 1: "HD 14067 b"}


def test_every_reference_run_is_reproduced_by_its_tree_and_its_json():
    from parameter_extractor.compound_names import renames_for
    from parameter_extractor.ingestion.flatten_to_template import write_template_csv
    from parameter_extractor.ingestion.observations import (observations_to_records, rows_to_observations,
                                                            write_observations_csv)
    from test_reference_runs import REFERENCES, replay_reference
    refs = sorted(p for p in REFERENCES.iterdir() if (p / "reference.json").is_file())
    assert refs
    for ref in refs:
        with tempfile.TemporaryDirectory() as tmp:
            result = replay_reference(ref, Path(tmp) / "run")
            assert result is not None, f"{ref.name}: its PDF isn't on this computer"
            packs.activate(result.pack or json.loads((ref / "reference.json").read_text())["pack"])
            chosen = {a["column"]: a.get("category", "") for a in result.accepted_variables}
            order = ColumnOrder(chosen=chosen)
            observations = rows_to_observations(result.rows)
            facets = record_tree.Facets(order, record_tree.levels())
            flat = record_tree.flatten(record_tree.build(observations, facets))
            assert flat == observations, ref.name
            wide, long = Path(tmp) / "wide.csv", Path(tmp) / "long.csv"
            write_template_csv(observations_to_records(flat), wide, column_categories=chosen)
            write_observations_csv(flat, long, order, renames=renames_for({o.column for o in flat}, None))
            assert wide.read_text() == (ref / "expected_extracted.csv").read_text(), ref.name
            assert long.read_text() == (ref / "expected_observations.csv").read_text(), ref.name
            # the JSON the run wrote
            data = json.loads(result.record_path.read_text())
            back = record_tree.flatten(record_tree.from_json(data), order)
            assert sorted(map(repr, back)) == sorted(map(repr, observations)), ref.name
            write_template_csv(observations_to_records(back), wide, column_categories=chosen)
            assert wide.read_text() == (ref / "expected_extracted.csv").read_text(), ref.name
            if json.loads((ref / "reference.json").read_text())["pack"] == "exoplanets":
                # a planet's fit solutions are a run of their own, read from the row labels ('TOI-3862 b [...]')
                assert [lv["label"] for lv in data["levels"]][2:] == ["planet", "fit solution"], data["levels"]
                runs = [c for s in data["paper"]["children"] for c in s.get("children", []) if c["level"] == "run"]
                assert runs and all(len(r["children"]) >= 2 for r in runs), runs
            rows = sum(1 for _ in _leaves(data["paper"]))
            print(f"  {ref.name}: {len(observations)} values, {rows} rows; "
                  f"{len(observations) - _stored(data['paper'])} copies saved by the tree")
            packs.activate("prebiotic_chemistry")


def _leaves(node):
    if not node.get("children"):
        yield node
    for c in node.get("children", []):
        yield from _leaves(c)


def _stored(node):
    return sum(len(v) for v in node.get("facets", {}).values()) + sum(_stored(c) for c in node.get("children", []))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All record tree tests passed.")
