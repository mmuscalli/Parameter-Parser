"""
A data pack's structure as one picture (gui/structure_canvas.py, branch levels-and-facets): the steps that read a
paper, where they come from, the kinds of value they fill, the levels as lanes with the kinds at their level. Built
from the app's packs (facts from tests/pack_facts.py where they matter); drawn offscreen. No API calls.

Run with: python tests/test_structure_canvas.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from parameter_extractor import packs  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_the_structure_of_the_apps_packs():
    from parameter_extractor.gui.structure_canvas import build_scene, render_png, structure_of
    import pack_facts as pf
    for pid in ("prebiotic_chemistry", "exoplanets"):
        pack = packs.activate(pid)
        s = structure_of(pack)
        assert [lv[0] for lv in s.levels] == ["paper", "set", "run", "sample"]
        names = [st.name for st in s.steps]
        assert names[:2] == ["structure_planner", "metadata"] and s.steps[0].makes_rows
        assert set(pf.step_names(pid)) <= set(names)                       # every configurable step is drawn
        kinds = {k.id: k for k in s.kinds}
        assert kinds["metadata"].level == "paper" and "metadata" in s.steps[1].kinds
        assert all(k.level in {lv[0] for lv in s.levels} for k in s.kinds)
        assert any(st.kinds for st in s.steps[2:])                         # steps fill kinds of value
        scene = build_scene(pack)
        assert scene.items() and scene.sceneRect().width() > 1000
        with tempfile.TemporaryDirectory() as tmp:
            render_png(pack, Path(tmp) / "x.png", scale=1.0)
            assert (Path(tmp) / "x.png").stat().st_size > 10000
    pack = packs.activate("exoplanets")
    s = structure_of(pack)
    assert s.levels[2][1] == "planet" and "fit solution" in s.levels[3][1]
    assert "several fit solutions" in s.levels[2][2]
    packs.activate("prebiotic_chemistry")


def test_hovering_highlights_a_step_and_what_it_fills():
    from parameter_extractor.gui.structure_canvas import FADED, KEY, TAGS, StructureCanvas
    pack = packs.activate("prebiotic_chemistry")
    canvas = StructureCanvas(pack)
    scene = canvas.scene()
    key = "step:metadata"
    related = scene.relations[key]
    assert "kind:metadata" in related
    canvas.highlight(key)
    for item in scene.items():
        own, tags = item.data(KEY), item.data(TAGS)
        if own == key or own in related:
            assert item.opacity() == 1.0
        elif tags and key in tags:
            assert item.opacity() == 1.0                                   # its lines stay
        elif own or tags:
            assert item.opacity() == FADED                                 # everything else fades
    from parameter_extractor.gui.structure_canvas import LANE
    lanes = {item.data(LANE): item.opacity() for item in scene.items() if item.data(LANE)}
    assert lanes["paper"] == 1.0 and lanes["sample"] == FADED              # a level holding nothing it fills fades
    canvas.highlight(None)
    assert all(item.opacity() == 1.0 for item in scene.items())
    canvas.highlight("step:structure_planner")                             # the row plan makes the groups and rows
    lanes = {item.data(LANE): item.opacity() for item in scene.items() if item.data(LANE)}
    assert lanes["set"] == lanes["sample"] == 1.0 and lanes["paper"] == FADED
    canvas.highlight(None)


def test_steps_are_grouped_by_where_they_come_from():
    from parameter_extractor.gui.structure_canvas import structure_of
    s = structure_of(packs.activate("prebiotic_chemistry"))
    order = [0 if st.source == "app" else 1 if st.source == "pack" else 2 for st in s.steps]
    assert order == sorted(order) and [st.name for st in s.steps[:2]] == ["structure_planner", "metadata"]
    modules = [st.source for st in s.steps if order[s.steps.index(st)] == 2]
    assert all(modules.index(m) == i or modules[i - 1] == m for i, m in enumerate(modules))   # a module's together
    assert not any("(built-in step)" in st.label for st in s.steps) and any(st.built_in for st in s.steps[2:])


def test_clicking_opens_a_step_or_kind_in_place():
    from parameter_extractor.gui.structure_canvas import BODY, KEY, StructureCanvas
    pack = packs.activate("prebiotic_chemistry")
    canvas = StructureCanvas(pack)

    def height(key):
        return next(i.sceneBoundingRect().height() for i in canvas.scene().items()
                    if i.data(KEY) == key and i.data(BODY))
    for key in ("step:metadata", "kind:metadata"):
        shut = height(key)
        canvas.toggle(key)
        assert key in canvas.opened and height(key) > shut                 # opened: everything it says
        canvas.toggle(key)
        assert key not in canvas.opened and height(key) == shut
    assert not any(i.toolTip() for i in canvas.scene().items())            # no tooltips over the picture
    from parameter_extractor.gui.structure_canvas import OPEN_LINES, brief, opened_lines, _font
    lines = opened_lines("A long description " * 20, ["8 columns · Level: Set", "Fills in: within each set"],
                         _font(10), 160)
    assert len(lines) <= OPEN_LINES and lines[0].endswith("…") and lines[-1].startswith("Fills in")
    assert brief("Rate constants (kobs). More text.") == "Rate constants"
    assert brief("Reference names like 'Teng et al. 2023'. More.") == "Reference names like 'Teng et al. 2023'"


def test_the_pack_editor_has_a_map():
    from parameter_extractor.gui.pack_windows import PackEditor
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "mine"
        shutil.copytree(packs.available()["exoplanets"].folder, folder)
        editor = PackEditor(folder)
        assert editor.map_canvas.scene() is not None and editor.map_canvas.scene().items()
        editor.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All structure canvas tests passed.")
