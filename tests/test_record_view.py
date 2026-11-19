"""
The results by experiment set and the data pack's Structure tab (gui/record_view.py, gui/structure_page.py; branch
levels-and-facets step 2): the paper, its sets and samples in words; a value shared by a set corrected for all its
samples or one; undone; computed values not editable; the tab named after the pack's word; the Structure tab's
choices saved where they belong. eder1994 replay, no API.

Run with: python tests/test_record_view.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from parameter_extractor import api_client, packs  # noqa: E402
from parameter_extractor.column_labels import readable  # noqa: E402
from parameter_extractor.pipeline import run_pipeline  # noqa: E402
from test_pipeline_offline import PDF, _config, _have_inputs, _replay_send  # noqa: E402

app = QApplication.instance() or QApplication([])


def _pump(n=10):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _cells(path: Path, column: str) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        return {r["full_id"]: r.get(column, "") for r in csv.DictReader(f)}


def _values(view) -> dict:
    out = {}
    for i in range(view.values.topLevelItemCount()):
        item = view.values.topLevelItem(i)
        if item.data(0, 257) is not None:                  # VALUE_ROLE
            out[item.data(0, 257)[0]] = item
    return out


def test_column_names_in_words():
    assert readable("initial_Gly_aq_mM") == "Gly concentration (starting, dissolved)"
    assert readable("sampled_Gly-Gly_aq_%yield") == "Gly-Gly yield (measured, dissolved)"
    assert readable("initial_temperature_C") == "Initial temperature" and readable("initial_pH") == "Initial pH"
    assert readable("pl_orbper", "exoplanets") == "Orbital Period"            # the archive's own label
    from parameter_extractor.column_labels import unit
    assert unit("pl_orbper", "exoplanets") == "days" and unit("pl_orbperlim", "exoplanets") == ""
    assert readable("pl_bmassjerr1", "exoplanets").endswith("Upper Unc.") and "[" not in readable("pl_bmassjerr1",
                                                                                                   "exoplanets")
    assert readable("pl_orbinclmode1err1", "exoplanets") == "Inclination, mode 1, upper unc."   # made from its base
    assert unit("pl_orbinclmode1err1", "exoplanets") == "deg" and unit("pl_orbinclmode1desc", "exoplanets") == ""
    from parameter_extractor.gui.record_view import RecordView
    assert RecordView.title_for(packs.available()["prebiotic_chemistry"]) == "Experiment sets"
    exo = packs.available()["exoplanets"]
    assert RecordView.title_for(exo) == exo.manifest.units["set"][:1].upper() + exo.manifest.units["set"][1:] + "s"


def test_the_experiment_sets_tab_shows_and_corrects():
    if not _have_inputs():
        return
    from parameter_extractor.gui.main_window import MainWindow
    from parameter_extractor.gui.record_view import RecordView
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(api_client, "_send", _replay_send):
            result = run_pipeline(PDF, _config(Path(tmp)))
        w = MainWindow()
        w.resize(1200, 900)
        w.show()
        _pump()
        w.main_split.setSizes([600, 300])                                     # the inputs taking most of it
        w.show_result(result)
        for _ in range(60):                                                   # the results area glides up
            _pump(1)
            time.sleep(0.01)
        top, bottom = w.main_split.sizes()
        assert top <= 0.27 * (top + bottom), (top, bottom)
        view = w.record_view
        from parameter_extractor.gui.record_view import TIER_ROLE
        paper_item = view.tree.topLevelItem(0)
        assert paper_item.data(0, TIER_ROLE) == "paper" and paper_item.child(0).data(0, TIER_ROLE) == "set"
        assert paper_item.child(0).child(0).data(0, TIER_ROLE) == "row"
        tall = view.tree.visualItemRect(paper_item.child(0)).height()
        plain = view.tree.visualItemRect(paper_item.child(0).child(0)).height()
        assert tall > plain, (tall, plain)                                    # a set stands off more than a row
        index = w.tabs.indexOf(view)
        assert w.tabs.tabText(index) == "Experiment sets" and w.tabs.isTabEnabled(index)
        paper = view.tree.topLevelItem(0)
        record = json.loads(result.record_path.read_text())
        assert paper.childCount() == len(record["paper"]["children"])
        assert sum(paper.child(i).childCount() for i in range(paper.childCount())) == len(result.rows)
        assert "experiment sets and their 42 samples" in view.intro.text()
        first_set = paper.child(0)
        sample = first_set.child(0)
        assert first_set.text(0).startswith("Experiment set 1") and sample.text(0).startswith("Sample 1")
        view.tree.setCurrentItem(sample)
        _pump()
        values = _values(view)
        temp = values["initial_temperature_C"]
        assert temp.text(0) == "Initial temperature" and "all 3 samples" in temp.text(3)
        assert "paper_title" not in values                                     # the paper's own: on the paper
        assert any("recorded for the whole paper" in view.values.topLevelItem(i).text(0)
                   for i in range(view.values.topLevelItemCount()))
        assert "set_independent_variable" in values and not view._correctable("set_independent_variable")
        view.values.setCurrentItem(temp)
        assert "Initial temperature" in view.source.toPlainText() and "initial_temperature_C" in view.source.toPlainText()
        ids = [first_set.child(i).data(0, 256).id for i in range(first_set.childCount())]   # NODE_ROLE
        before = _cells(result.csv_path, "initial_temperature_C")

        # only this sample
        with patch.object(RecordView, "_targets", lambda self, holder: [ids[0]]):
            temp.setText(1, "90")
        _pump()
        now = _cells(result.csv_path, "initial_temperature_C")
        assert now[ids[0]] == "90.0" and all(now[i] == before[i] for i in ids[1:])
        table_col = [w.rows_table.horizontalHeaderItem(c).text() for c in range(w.rows_table.columnCount())]
        assert w.rows_table.item(0, table_col.index("initial_temperature_C")).text() == "90.0"   # the table follows
        assert "corrected" in _values(view)["initial_temperature_C"].text(3)

        # all three samples of the set: shared by the set again in the record
        view.tree.setCurrentItem(view.tree.topLevelItem(0).child(0).child(1))
        _pump()
        with patch.object(RecordView, "_targets", lambda self, holder: ids):
            _values(view)["initial_temperature_C"].setText(1, "95")
        _pump()
        now = _cells(result.csv_path, "initial_temperature_C")
        assert all(now[i] == "95.0" for i in ids)
        view.tree.setCurrentItem(view.tree.topLevelItem(0).child(0).child(2))
        _pump()
        assert "all 3 samples" in _values(view)["initial_temperature_C"].text(3)

        # a value that isn't one: refused
        with patch("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None):
            _values(view)["initial_temperature_C"].setText(1, "hot")
        _pump()
        assert _cells(result.csv_path, "initial_temperature_C") == now

        # undone
        from parameter_extractor import corrections as corr
        corr.restore(result.run_dir, [(i, "initial_temperature_C", None) for i in ids])
        view.refresh()
        _pump()
        assert _cells(result.csv_path, "initial_temperature_C") == before
        assert "corrected" not in _values(view)["initial_temperature_C"].text(3)
        w.close()


def test_exoplanet_rows_are_planets_or_fit_solutions():
    """A planet with several fit solutions is a run ('planet') of 'fit solution' rows; a planet alone is a 'planet'."""
    from types import SimpleNamespace
    from parameter_extractor import record_tree
    from parameter_extractor.column_order import ColumnOrder
    from parameter_extractor.gui.record_view import RecordView
    from parameter_extractor.ingestion.observations import Observation
    packs.activate("exoplanets")
    try:
        obs = [Observation(full_id=f, set_id=f[:6], sample_id=f[6:], entry_number=int(f[6:]), column="pl_orbper",
                           value=v, source=f"row {f}") for f, v in (("001001001", 10.0), ("001001002", 10.2),
                                                                   ("001002001", 3.0))]
        runs = {"001001001": "HD 1 b", "001001002": "HD 1 b"}
        facets = record_tree.Facets(ColumnOrder(), record_tree.levels(runs=True))
        assert [(lv.label, lv.alone) for lv in facets.levels][2:] == [("planet", ""), ("fit solution", "planet")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x_record.json"
            path.write_text(json.dumps(record_tree.to_json(record_tree.build(obs, facets, None, runs), facets,
                                                           {"data_pack": "exoplanets"})))
            view = RecordView()
            view.show_result(SimpleNamespace(record_path=path, row_flags={}, run_dir=None, pack="exoplanets"))
            paper = view.tree.topLevelItem(0)
            s1, s2 = paper.child(0), paper.child(1)
            assert s1.text(0).endswith("(2 fit solutions)") and s1.child(0).text(0).startswith("Planet 1")
            assert s1.child(0).child(0).text(0).startswith("Fit solution 1")
            assert s2.text(0).endswith("(1 planet)") and s2.child(0).text(0).startswith("Planet 1")
            assert "3 rows" in view.intro.text()
            view.tree.setCurrentItem(s2.child(0))
            period = next(view.values.topLevelItem(i) for i in range(view.values.topLevelItemCount())
                          if view.values.topLevelItem(i).data(0, 257) and view.values.topLevelItem(i).data(0, 257)[0]
                          == "pl_orbper")
            assert period.text(0) == "Orbital Period" and period.text(2) == "days" and period.text(3) == "this planet"
    finally:
        packs.activate("prebiotic_chemistry")


def test_an_opened_older_run_gets_its_record():
    """Feedback 2026-11-18: a run opened from its folder (File > Open a results folder…) made before the record
    existed left the tab greyed out -- its rows are read back as saved rows. Now its record is made from its
    observations file, its corrections marked."""
    if not _have_inputs():
        return
    from parameter_extractor import corrections as corr, run_folder
    from parameter_extractor.gui.main_window import MainWindow
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(api_client, "_send", _replay_send):
            result = run_pipeline(PDF, _config(Path(tmp)))
        fid = result.rows[0].full_id
        before = _cells(result.csv_path, "duration_hr")[fid]
        corr.correct(result.run_dir, fid, "duration_hr", before, "99.0")
        expected = json.loads(result.record_path.read_text())
        result.record_path.unlink()                                             # as before the record existed
        opened = run_folder.load_result(result.run_dir)
        w = MainWindow()
        w.show_result(opened)
        _pump()
        assert w.tabs.isTabEnabled(w.tabs.indexOf(w.record_view))
        made = json.loads(result.record_path.read_text())
        assert len(made["paper"]["children"]) == len(expected["paper"]["children"])
        assert made["made_from"] and made["paper"]["children"][0].get("label")      # labels from its row plan
        # a record made by an earlier version of this tab (no labels, no mark): made again when the folder opens
        stale = dict(made)
        stale.pop("made_from")
        for child in stale["paper"]["children"]:
            child.pop("label", None)
        result.record_path.write_text(json.dumps(stale))
        w0 = MainWindow()
        w0.show_result(run_folder.load_result(result.run_dir))
        _pump()
        assert w0.record_view.tree.topLevelItem(0).child(0).text(0).startswith("Experiment set 1: ")
        w0.close()
        view = w.record_view
        view.tree.setCurrentItem(view.tree.topLevelItem(0).child(0).child(0))
        _pump()
        duration = _values(view)["duration_hr"]
        assert duration.text(1) == "99.0" and "corrected" in duration.text(3)
        w.close()


def test_the_structure_tab_saves_levels():
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = packs.create_pack("my_area", "My area", base=Path(tmp), source=packs.available()["prebiotic_chemistry"])
        own = json.loads((pack.folder / "pack.json").read_text())["variable_categories"][0]["id"]
        e = PackEditor(pack.folder)
        page = e.structure_page
        rows = {page._kinds[r]["id"]: r for r in range(page.table.rowCount())}
        assert {"metadata", "methodology", own} <= set(rows)
        assert page.table.cellWidget(rows["metadata"], 1).currentData() == "paper"
        page.group_word.setText("reaction series")
        assert e.set_edit.text() == "reaction series"                          # the General tab's word too
        assert page.table.cellWidget(rows["metadata"], 1).itemText(1) == "each reaction series"
        page.table.cellWidget(rows["metadata"], 1).setCurrentIndex(1)            # a shared one: category_levels
        page.table.cellWidget(rows[own], 1).setCurrentIndex(0)                   # the pack's own: in its entry
        assert "Each reaction series" in page.picture.text()
        assert page.level_limit.value() == 4
        page.level_limit.setValue(5)                                             # the advanced override
        with patch("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None):
            e.collect()
            assert e.save()
        saved = json.loads((pack.folder / "pack.json").read_text())
        assert saved["level_limit"] == 5
        assert saved["units"]["set"] == "reaction series" and saved["category_levels"] == {"metadata": "set"}
        assert next(c for c in saved["variable_categories"] if c["id"] == own)["level"] == "paper"
        from parameter_extractor import record_tree
        from parameter_extractor.column_order import ColumnOrder
        p = packs.Pack(pack.folder)
        facets = record_tree.Facets(ColumnOrder(pack=p), record_tree.levels(p))
        assert facets.levels[facets.caps["metadata"]].id == "set" and facets.levels[facets.caps[own]].id == "paper"
        e.close()
    built_in = PackEditor(packs.available()["prebiotic_chemistry"].folder)              # read-only: locked
    assert not built_in.structure_page.table.cellWidget(0, 1).isEnabled()
    built_in.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All record view tests passed.")
