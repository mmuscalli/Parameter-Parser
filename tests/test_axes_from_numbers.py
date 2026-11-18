"""
Axes read from their tick numbers (digitizing/auto_axes.py, Mickey 2026-11-18: about 30 figures per pack weren't
calibrated automatically -- one misread or stray number spoiled an axis, or axis lines too faint or broken to find
as a frame). Synthetic numbers and images only; no API calls, no papers.

Run with: python tests/test_axes_from_numbers.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from parameter_extractor.digitizing.auto_axes import (Frame, calibrate_axis, fit_number_axis,  # noqa: E402
                                                      number_axes, number_frames, reading_order, with_number_frames)


def test_a_misread_number_doesnt_spoil_the_axis():
    # 0.2 .. 5.0 every 0.4, 62 px apart; '1.4' read as '1.0', '2.2' as '220', '1.8' as '1.09' (BF01808134 Fig. 2)
    values = [0.2, 0.6, 1.0, 1.0, 1.09, 220.0, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0]
    points = [(342 + 62 * k, v) for k, v in enumerate(values)]
    positions, found, is_log, used = fit_number_axis(points, horizontal=True)
    assert found[0] == 0.2 and found[-1] == 5.0 and not is_log and 1.09 not in found and 220.0 not in found
    assert positions[0] == 342 and positions[-1] == 342 + 62 * 12


def test_numbers_of_different_panels_dont_make_an_axis():
    # one number from each of three panels side by side happens to fit 0, 10, 20 -- other numbers lie between
    row = [(371, 0.0), (757, 10.0), (1141, 20.0), (500, 45.0), (880, 15.0)]
    found = fit_number_axis(row, horizontal=True)
    assert found is None or found[1] != [0.0, 10.0, 20.0], found
    # two panels side by side, same numbers: one axis each, the left one first
    two = [(100 + 60 * k, 5.0 * k) for k in range(6)] + [(600 + 60 * k, 5.0 * k) for k in range(6)]
    axes = number_axes([(x, 500.0, v) for x, v in two])
    assert [(a.horizontal, a.positions[0], a.values[-1]) for a in axes] == [(True, 100, 25.0), (True, 600, 25.0)]


def test_numbers_side_by_side_or_far_apart_are_not_one_axis():
    assert fit_number_axis([(1385, 5.0), (1385, 1.0), (1384, 2.0)], horizontal=False) is None
    # a '2' of the text above sits where the axis would put 2.0, five ticks past the last number (fuchida2014 Fig. 3)
    column = [(1695 - 58 * k, round(0.2 * k, 1)) for k in range(6)] + [(1695 - 58 * 10, 2.0)]
    positions, values, _log, _used = fit_number_axis(column, horizontal=False)
    assert values == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], values


def test_the_x_axis_zero_is_not_the_y_axis_zero():
    # Takaoka1991 Fig. 2b: two y numbers only; the x axis' '0' under the corner must not make it three
    numbers = [(292 + 190 * k, 1189.0, 5.0 * k) for k in range(6)] + [(270, 982.0, 0.05), (270, 785.0, 0.1)]
    axes = number_axes(numbers)
    assert [a.horizontal for a in axes] == [True], axes


def _plot(box: bool, broken_axes: bool = True):
    """A white page with a plot: axes from (100, 400) to (600, 50), numbers 0..50 under the x axis (every 100 px)
    and 0..3 left of the y axis (every 80 px, the plot going on to y = 50 above the last number)."""
    img = Image.new("L", (700, 500), 255)
    d = ImageDraw.Draw(img)
    for y in range(50, 401, 1 if not broken_axes else 1):
        if not broken_axes or (y // 12) % 3:                  # a scanned axis, broken every few pixels
            d.point((100, y), 60)
    for x in range(100, 601):
        if not broken_axes or (x // 12) % 3:
            d.point((x, 400), 60)
    if box:                                                   # thin anti-aliased grey box sides
        d.line([(100, 50), (600, 50)], fill=180)
        d.line([(600, 50), (600, 400)], fill=180)
    numbers = [(100 + 100 * k, 425.0, 10.0 * k) for k in range(6)] + [(70, 400.0 - 80 * k, float(k)) for k in range(4)]
    return np.asarray(img), numbers


def test_a_frame_is_read_from_its_numbers_and_its_box():
    gray, numbers = _plot(box=True)
    frames = number_frames(gray, numbers)
    assert len(frames) == 1
    f = frames[0]
    assert f.from_numbers and f.has_top_axis and f.has_right_axis
    assert abs(f.left - 100) <= 2 and abs(f.bottom - 400) <= 2 and abs(f.right - 600) <= 2 and abs(f.top - 50) <= 2, f
    # calibrated from the numbers, through the frame
    (x1, _, v1), (x2, _, v2), _log = calibrate_axis(gray, f, "bottom", [], numbers)
    assert (x1, v1, x2, v2) == (100, 0.0, 600, 50.0)
    (_, y1, w1), (_, y2, w2), _log = calibrate_axis(gray, f, "left", [], numbers)
    assert (y1, w1, y2, w2) == (400, 0.0, 160, 3.0)


def test_without_a_box_the_frame_is_marked_estimated():
    gray, numbers = _plot(box=False)
    f = number_frames(gray, numbers)[0]
    assert f.from_numbers and not f.has_top_axis and not f.has_right_axis


def test_a_box_around_the_figure_is_not_the_plot():
    gray, numbers = _plot(box=True)
    outer = Frame(left=20, right=680, top=10, bottom=480, has_right_axis=True, has_top_axis=True)
    frames = with_number_frames([outer], gray, numbers)
    assert len(frames) == 1 and frames[0].from_numbers and abs(frames[0].left - 100) <= 2
    # a frame found from its lines is kept when the numbers agree with it
    plot = Frame(left=100, right=600, top=50, bottom=400, has_right_axis=True, has_top_axis=True)
    assert with_number_frames([plot], gray, numbers) == [plot]


def test_panels_side_by_side_read_left_to_right():
    a = Frame(left=760, right=1176, top=1054, bottom=1700, has_right_axis=False, has_top_axis=False)
    b = Frame(left=216, right=636, top=1408, bottom=1697, has_right_axis=False, has_top_axis=False)
    c = Frame(left=216, right=636, top=1900, bottom=2200, has_right_axis=False, has_top_axis=False)
    assert reading_order([c, a, b]) == [b, a, c]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All axes-from-numbers tests passed.")
