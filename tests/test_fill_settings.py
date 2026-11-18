"""
Step 3 of branch levels-and-facets: values only some rows give, set per kind of value (calculators/shared_values.py
fill settings, the data pack editor's Structure tab) instead of the pack.json lists shared_columns / group_columns --
the prebiotic pack fills exactly the columns it did; an older pack keeps its lists until a fill setting is changed;
and the record holds a value stated by some rows and assumed for the others once, on its set (record_tree.py). No
API calls.

Run with: python tests/test_fill_settings.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import packs, record_tree  # noqa: E402
from parameter_extractor.calculators.shared_values import selectors, shared_columns, uses_fill_settings  # noqa: E402
from parameter_extractor.column_order import ColumnOrder  # noqa: E402
from parameter_extractor.ingestion.observations import Observation  # noqa: E402
from parameter_extractor.registry import standard_columns  # noqa: E402

# the prebiotic pack's lists before step 3
OLD_SHARED = {"categories": ["analysis", "methodology"], "columns": ["reagent_suppliers", "pH_buffer"],
              "exclude": ["set_type"]}
OLD_GROUP = {"categories": ["analysis", "methodology", "conditions", "flow_reactor", "mineral_surfaces"],
             "columns": ["reagent_suppliers", "pH_buffer"], "exclude": ["set_type", "duration_hr", "cycle_number"]}


def test_the_prebiotic_pack_fills_what_it_did():
    pack = packs.activate("prebiotic_chemistry")
    assert uses_fill_settings(pack.own_manifest)
    columns = sorted(set(pack.template_columns) | set(standard_columns(pack))
                     | {"analysis_HPLC_column_temperature_C", "stirring_rate_rpm", "reagent_suppliers", "pH_buffer"})
    order = ColumnOrder(pack=pack)
    shared, group = selectors(pack)
    assert shared_columns(columns, shared, order) == shared_columns(columns, OLD_SHARED, order)
    assert shared_columns(columns, group, order) == shared_columns(columns, OLD_GROUP, order)
    assert "duration_hr" not in shared_columns(columns, group, order)


def test_an_older_pack_keeps_its_lists_until_a_fill_changes():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = packs.create_pack("older", "Older", base=Path(tmp))              # from the template: the lists
        legacy = packs.Pack(pack.folder)
        assert not uses_fill_settings(legacy.own_manifest)
        assert selectors(legacy) == (legacy.manifest.shared_columns, legacy.manifest.group_columns)
        e = PackEditor(pack.folder)
        page = e.structure_page
        rows = {k["id"]: r for r, k in enumerate(page._kinds)}
        assert page.table.cellWidget(rows["methodology"], 2).currentData() == "paper"     # read from the lists
        with patch("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None):
            e.collect()
            assert e.save()
        saved = json.loads((pack.folder / "pack.json").read_text())
        assert "shared_columns" in saved and "category_fill" not in saved     # nothing changed: kept as it was
        # a fill changed: the settings replace the lists
        page.table.cellWidget(rows["methodology"], 2).setCurrentIndex(1)       # within its set only
        page.new_column.setText("stirring_rate_rpm")
        page._add_column()
        with patch("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None):
            e.collect()
            assert e.save()
        saved = json.loads((pack.folder / "pack.json").read_text())
        assert "shared_columns" not in saved and "group_columns" not in saved
        assert saved["category_fill"] == {"methodology": "set"}
        assert saved["fill_columns"]["stirring_rate_rpm"] == "none" and saved["fill_columns"]["set_type"] == "none"
        shared, group = selectors(packs.Pack(pack.folder))
        assert shared == {} and group["categories"] == ["methodology"] and "set_type" in group["exclude"]
        e.close()


def _obs(fid, value, origin="conditions", source="Methods", **kw):
    return Observation(full_id=fid, set_id=fid[:6], sample_id=fid[6:], entry_number=int(fid[6:]),
                       column="initial_temperature_C", value=value, origin=origin, source=source, **kw)


ASSUMED = dict(origin="conditions -- assumed shared (same experiment set or figure)",
               source="Methods [assumed the same as the 2 other row(s) of its set / figure that state it]",
               confidence="low")


def test_a_value_assumed_for_some_rows_is_held_once_on_its_set():
    packs.activate("prebiotic_chemistry")
    order = ColumnOrder()
    facets = record_tree.Facets(order, record_tree.levels())
    obs = [_obs("001001001", 81.0), _obs("001001002", 81.0), _obs("001001003", 81.0, **ASSUMED),
           _obs("001002001", 90.0)]
    paper = record_tree.build(obs, facets)
    s1 = paper.children[0]
    held = s1.values["initial_temperature_C"]
    assert held["source"] == "Methods" and held[record_tree.ASSUMED]["rows"] == ["001001003"]
    assert not any(c.values for c in s1.children)
    assert record_tree.flatten(paper) == obs                                   # exactly what it was built from
    data = record_tree.to_json(paper, facets)
    j = data["paper"]["children"][0]["facets"]["conditions"]["initial_temperature_C"]
    assert j["assumed_for"]["rows"] == ["001001003"] and j["assumed_for"]["confidence"] == "low"
    back = record_tree.flatten(record_tree.from_json(json.loads(json.dumps(data))), order)
    assert sorted(map(repr, back)) == sorted(map(repr, obs))
    # a correction of the assumed row hands the value down: the others keep theirs
    record_tree.set_value(paper, "001001003", "initial_temperature_C", dict(
        obs[0].model_dump(include=set(record_tree.PAYLOAD)), value=85.0))
    flat = {o.full_id: o for o in record_tree.flatten(paper)}
    assert flat["001001003"].value == 85.0 and flat["001001001"].source == "Methods"
    assert flat["001001002"].origin == "conditions"
    # values stated with different provenance aren't merged
    differing = [_obs("001001001", 81.0, source="Table 1, row 1"), _obs("001001002", 81.0, source="Table 1, row 2"),
                 _obs("001001003", 81.0, **ASSUMED)]
    p2 = record_tree.build(differing, facets)
    assert not p2.children[0].values and record_tree.flatten(p2) == differing


def test_the_results_tab_says_what_was_assumed():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.record_view import RecordView
    packs.activate("prebiotic_chemistry")
    facets = record_tree.Facets(ColumnOrder(), record_tree.levels())
    obs = [_obs("001001001", 81.0), _obs("001001002", 81.0), _obs("001001003", 81.0, **ASSUMED)]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x_record.json"
        path.write_text(json.dumps(record_tree.to_json(record_tree.build(obs, facets), facets,
                                                       {"data_pack": "prebiotic_chemistry"})))
        view = RecordView()
        view.show_result(SimpleNamespace(record_path=path, row_flags={}, run_dir=None, pack="prebiotic_chemistry"))
        paper = view.tree.topLevelItem(0)
        texts = {}
        for item in (paper.child(0), paper.child(0).child(0), paper.child(0).child(2)):
            view.tree.setCurrentItem(item)
            for i in range(view.values.topLevelItemCount()):
                v = view.values.topLevelItem(i)
                if v.data(0, 257) is not None:
                    texts[item.text(0)] = v.text(3)
        assert "assumed for 1 of them" in texts[paper.child(0).text(0)]
        assert "assumed" not in texts[paper.child(0).child(0).text(0)]
        assert "assumed: the others state it" in texts[paper.child(0).child(2).text(0)]
        view.values.setCurrentItem(next(view.values.topLevelItem(i) for i in range(view.values.topLevelItemCount())
                                        if view.values.topLevelItem(i).data(0, 257) is not None))
        assert "Assumed" in view.source.toPlainText()


def test_the_results_tab_shows_runs():
    """Step 4: a set holding several runs shows them between the set and its samples, each by its own name."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.record_view import RecordView
    packs.activate("prebiotic_chemistry")
    obs = [_obs(f"00100100{i}", 81.0, source=f"row {i}") for i in (1, 2, 3, 4)]
    runs = {"001001001": "Run 13", "001001002": "Run 13", "001001003": "Run 14", "001001004": "Run 14"}
    facets = record_tree.Facets(ColumnOrder(), record_tree.levels(runs=True))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x_record.json"
        path.write_text(json.dumps(record_tree.to_json(record_tree.build(obs, facets, None, runs), facets,
                                                       {"data_pack": "prebiotic_chemistry"})))
        view = RecordView()
        view.show_result(SimpleNamespace(record_path=path, row_flags={}, run_dir=None, pack="prebiotic_chemistry"))
        s1 = view.tree.topLevelItem(0).child(0)
        assert s1.text(0).startswith("Experiment set 1") and "(4 samples)" in s1.text(0)
        assert [s1.child(i).text(0) for i in range(s1.childCount())] == ["Run 13  (2 samples)", "Run 14  (2 samples)"]
        assert s1.child(0).child(1).text(0).startswith("Sample 2")
        view.tree.setCurrentItem(s1.child(0).child(0))
        texts = [view.values.topLevelItem(i).text(3) for i in range(view.values.topLevelItemCount())]
        assert "this sample" in texts


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All fill-setting tests passed.")
