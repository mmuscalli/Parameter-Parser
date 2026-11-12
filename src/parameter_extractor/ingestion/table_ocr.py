"""
Text recognition on a table image (Mickey, 2026-11-12: Cleaves2008's Table 1 is drawn as shapes -- its PDF has no text
for the values, so the Flagged values window couldn't box '25 °C' or '5×10-34'). macOS only: the system's Vision
framework (pyobjc), offline and free; elsewhere `available()` is False and such tables stay unmarked, as before.

`words(image)` -> table_locate.Word list in the image's own pixels, one per space-separated word of each recognized
line (its box from Vision's range boxes). Lookalike characters Vision returns for digits in small print are mapped
back ('З' -> '3', 'O' between digits -> '0', '~' / '–' -> '-'). Superscripts are sometimes lost ('3×10* M') -- such a
cell just isn't found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

_LOOKALIKE = str.maketrans({"З": "3", "з": "3", "О": "0", "о": "0", "~": "-", "–": "-", "—": "-", "−": "-",
                            "х": "x", "Х": "x"})


def available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
        return True
    except Exception:
        return False


def _clean(text: str) -> str:
    text = text.translate(_LOOKALIKE)
    return re.sub(r"(?<=\d)[Oo](?=\d)", "0", text)


def words(image: Path):
    """The recognized words of an image file, positioned in its pixels."""
    from parameter_extractor.ingestion.table_locate import Word
    import Quartz
    import Vision
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(image)), None)
    if src is None:
        return []
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        return []
    width, height = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)                 # numbers and units, not prose
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, _err = handler.performRequests_error_([request], None)
    if not ok:
        return []

    def box(bb):
        x0 = bb.origin.x * width
        y0 = (1 - bb.origin.y - bb.size.height) * height        # Vision's origin is bottom-left
        return (x0, y0, x0 + bb.size.width * width, y0 + bb.size.height * height)

    out: List[Word] = []
    for observation in request.results() or []:
        candidate = observation.topCandidates_(1)[0]
        text = str(candidate.string())
        whole = box(observation.boundingBox())
        for m in re.finditer(r"\S+", text):
            part = None
            try:
                rect, _err = candidate.boundingBoxForRange_error_((m.start(), m.end() - m.start()), None)
                if rect is not None:
                    part = box(rect.boundingBox())
            except Exception:
                part = None
            out.append(Word(_clean(m.group(0)), part or whole))
    return out
