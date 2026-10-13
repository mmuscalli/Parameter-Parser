"""
Draws the app icon (a page with a data table being pulled out of it) and
writes packaging/icons/app.png, app.icns (macOS) and app.ico (Windows).

    python packaging/make_icon.py

Placeholder art -- replace freely; the build only needs the three files.
app.icns needs macOS's `iconutil`; it's skipped elsewhere.
"""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "icons"
S = 1024  # master size; everything below is in these units

BG_TOP, BG_BOTTOM = (31, 107, 117), (17, 61, 82)   # deep teal gradient
PAGE, INK, ACCENT = (250, 250, 247), (60, 72, 82), (244, 179, 66)


def draw_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # background: rounded square with a vertical gradient (macOS-style margin)
    margin, radius = 100, 185
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, S - margin, S - margin], radius, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # the paper: a page with a folded corner and lines of text
    px0, py0, px1, py1, fold = 250, 215, 640, 735, 95
    d.polygon([(px0, py0), (px1 - fold, py0), (px1, py0 + fold), (px1, py1), (px0, py1)], fill=PAGE)
    d.polygon([(px1 - fold, py0), (px1 - fold, py0 + fold), (px1, py0 + fold)], fill=(214, 218, 214))
    for i, y in enumerate(range(330, 700, 52)):
        right = px1 - 50 if i % 3 != 2 else px1 - 150
        d.rounded_rectangle([px0 + 45, y, right, y + 18], 9, fill=(196, 203, 205))

    # the extracted data: a table card overlapping the page's lower right
    tx0, ty0, tx1, ty1 = 455, 500, 805, 810
    d.rounded_rectangle([tx0 + 14, ty0 + 18, tx1 + 14, ty1 + 18], 34, fill=(0, 0, 0, 70))  # shadow
    d.rounded_rectangle([tx0, ty0, tx1, ty1], 34, fill=PAGE)
    d.rounded_rectangle([tx0, ty0, tx1, ty0 + 78], 34, fill=ACCENT)
    d.rectangle([tx0, ty0 + 44, tx1, ty0 + 78], fill=ACCENT)
    rows = [ty0 + 78 + k * 77 for k in range(1, 4)]
    for y in rows[:-1] + [ty1 - 1]:
        if y < ty1 - 5:
            d.line([(tx0 + 24, y), (tx1 - 24, y)], fill=(200, 205, 205), width=6)
    for x in (tx0 + 128, tx0 + 238):
        d.line([(x, ty0 + 78), (x, ty1 - 22)], fill=(200, 205, 205), width=6)
    for r, y in enumerate([ty0 + 116, ty0 + 193, ty0 + 270]):
        for c, (x0, x1) in enumerate([(tx0 + 38, tx0 + 100), (tx0 + 150, tx0 + 212), (tx0 + 260, tx1 - 40)]):
            d.rounded_rectangle([x0, y - 10, x1 - (18 if (r + c) % 2 else 0), y + 10], 10, fill=INK)
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    master = draw_master()
    master.save(OUT / "app.png")
    # the running app's window icon (Windows/Linux title bar & taskbar; macOS uses the .icns)
    master.resize((256, 256), Image.LANCZOS).save(
        Path(__file__).resolve().parents[1] / "src/parameter_extractor/gui/resources/app.png")
    master.save(OUT / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                        (128, 128), (256, 256)])
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "app.iconset"
            iconset.mkdir()
            for size in (16, 32, 128, 256, 512):
                master.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
                master.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "app.icns")], check=True)
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
