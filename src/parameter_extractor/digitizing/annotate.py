"""
Audit trail for a digitized figure: <out_dir>/fig-<N>.digitized.json (the
calibration, every clicked pixel and its computed value, the suggestions the
user started from) and fig-<N>.digitized.png (the figure with the calibration
marks and clicked points drawn on it), so anyone can check what was read
from where.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw

from parameter_extractor.digitizing.calibration import try_pixel_to_data
from parameter_extractor.schemas.figures import DigitizedFigure

SERIES_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf",
                 "#e377c2", "#8c564b", "#bcbd22", "#7f7f7f"]
CALIBRATION_COLOR = "#0050c8"


def save_digitized(fig: DigitizedFigure, out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    record = fig.model_dump()
    for s_rec, series in zip(record["series"], fig.series):
        panel = fig.panels[series.panel]
        for p_rec, pt in zip(s_rec["points"], series.points):
            xy = try_pixel_to_data(panel, pt.px, pt.py)
            p_rec["x_axis_value"], p_rec["y_axis_value"] = xy if xy else (None, None)
    json_path = out_dir / f"fig-{fig.tag}.digitized.json"
    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    img = Image.open(fig.page_image).convert("RGB")
    draw = ImageDraw.Draw(img)
    xs, ys = [], []
    for i, panel in enumerate(fig.panels):
        for axis, cal in (("X", panel.x_cal), ("Y", panel.y_cal)):
            for k, cp in enumerate((cal.p1, cal.p2), start=1):
                if cp is None:
                    continue
                xs.append(cp.px); ys.append(cp.py)
                r = 14
                draw.line([(cp.px - r, cp.py), (cp.px + r, cp.py)], fill=CALIBRATION_COLOR, width=3)
                draw.line([(cp.px, cp.py - r), (cp.px, cp.py + r)], fill=CALIBRATION_COLOR, width=3)
                label = f"{axis}{k}" + (f"={cp.value:g}" if cp.value is not None else "")
                draw.text((cp.px + 8, cp.py + 6), label + (f" [{i + 1}]" if len(fig.panels) > 1 else ""),
                          fill=CALIBRATION_COLOR)
    for j, series in enumerate(fig.series):
        color = SERIES_COLORS[j % len(SERIES_COLORS)]
        for pt in series.points:
            xs.append(pt.px); ys.append(pt.py)
            draw.ellipse([pt.px - 7, pt.py - 7, pt.px + 7, pt.py + 7], outline=color, width=3)

    # crop to the detected figure area, widened to include every mark
    s = fig.render_scale
    box = [v * s for v in fig.figure_bbox] if fig.figure_bbox else [min(xs, default=0), min(ys, default=0),
                                                                     max(xs, default=img.width),
                                                                     max(ys, default=img.height)]
    if xs:
        box = [min(box[0], min(xs)), min(box[1], min(ys)), max(box[2], max(xs)), max(box[3], max(ys))]
    pad = 40
    box = [max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad)]
    crop = img.crop([int(v) for v in box])
    legend = ImageDraw.Draw(crop)
    for j, series in enumerate(fig.series):
        legend.text((8, 8 + 14 * j), f"● {series.label} ({len(series.points)} pts)",
                    fill=SERIES_COLORS[j % len(SERIES_COLORS)])
    png_path = out_dir / f"fig-{fig.tag}.digitized.png"
    crop.save(png_path)
    return json_path, png_path
