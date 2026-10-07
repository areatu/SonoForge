"""Experimental detector for structures that look like a line of burned-in text.

Burned-in patient data on an ultrasound frame is a row of small glyphs on a
nearly uniform background, and that is the only thing this detector looks for.
It never reads the text: no OCR, no dictionary, no PHI ever enters or leaves —
the output is geometry (where the row is, how many glyphs, how sure the
heuristic is).  That is deliberate: the task is "did anything text-like survive
the mask", not "what does it say" (design doc §8).

How it works, in one paragraph: burned-in text sits on a line of its own, and
the glyphs are a minority of the pixels in the rows they occupy, so the median of
a row is that line's background and ``|pixel - row median|`` is the ink map — of
either polarity, whether the letters are bright on a dark bar or dark on a white
info strip.  The map is thresholded (Otsu, floored, so a flat band yields
nothing); connected components that look like glyphs (sane height, not a solid
panel, not a speck) are grouped into rows by their vertical centres, and a row is
reported only if several similarly sized glyphs sit on a flat background with
character-like spacing between them — those last two tests are what keeps speckle
and caliper marks out of the report.

Everything here is pure: numpy in, dataclasses out, no Qt, no I/O.  The detector
is behind a setting (``phi_text_detector``) because it is calibrated on the
corpus, not proven: §9 of the design doc describes how its output is compared
with the profile band before anything is automated.

Known limits, from probing synthetic frames: text painted straight onto the
image (no bar under it) is missed, because the flat-background filter rejects
it; a name that is a single two-glyph blob is missed too; and a row of identical
evenly spaced marks (a dotted grid, a tick ruler) still passes, because no
geometry-only test tells it from a word.  The first two are false negatives,
which the design accepts — the layer-2 check may stay silent, it must not cry
wolf on speckle.  What the detector must never do is fail a frame that has no
text at all, and the corpus evaluation of §9 is what decides the grid case.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: Ink below this level is noise, not text.  Roughly the smallest contrast that
#: reads as a glyph on the measured corpus.
INK_FLOOR = 12

#: A glyph must be at least this many pixels tall to be considered at all.
MIN_GLYPH_HEIGHT = 4

#: ...and at most this tall.  Taller blobs are anatomy, calipers or UI panels.
MAX_GLYPH_HEIGHT = 64

#: Glyphs are wider than they are tall only by a factor (an underscore or a
#: dash); anything broader is a line of the sector border.
MAX_GLYPH_ASPECT = 4.0

#: A glyph's bounding box has to be filled roughly like a character: the low end
#: drops single-pixel noise, the high end drops solid panels and border lines.
MIN_GLYPH_FILL = 0.05
MAX_GLYPH_FILL = 0.92

#: ...but a *small* solid mark is not a panel: a two-pixel stroke of a low
#: resolution glyph is a filled blob, and at that size no font is resolvable, so
#: rejecting it would only blind the "did anything survive the mask" check.
MAX_SOLID_AREA = 40

#: Ink also has to stand out against the strongest ink of the analysed region.
#: Text is high contrast by construction (it has to be readable on top of the
#: image), while speckle and gradients produce plenty of weak edges; without the
#: relative floor those weak edges would be thresholded into "glyphs" whenever
#: the region contains no real text at all.
RELATIVE_INK_FLOOR = 0.4

#: A row is called text when it has this many glyphs, or fewer but spans this
#: many pixels (a wide word rendered in one connected component).
MIN_ROW_GLYPHS = 3
MIN_ROW_SPAN = 24

#: A text line is printed on a flat background: the pixels between the glyphs of
#: a header bar or an info strip vary by a few levels, while the speckle of the
#: sector varies by tens.  Measured as the 5th-95th percentile spread of the
#: non-ink pixels inside the row, which is robust to a few ringing pixels around
#: a glyph.  Without this the detector reports "text" inside plain speckle.
MAX_BACKGROUND_SPREAD = 45

#: ...and its glyphs are pitched like characters.  A space is about one glyph
#: wide, so a median gap of more than this many glyph widths means the marks are
#: not a word: they are calipers, a dotted grid or a row of ticks.
MAX_GAP_RATIO = 3.0


@dataclass(frozen=True)
class TextRow:
    """One horizontal line of glyph-like components, in frame coordinates."""

    x0: int
    y0: int
    x1: int
    y1: int
    glyphs: int

    @property
    def width(self) -> int:
        return max(self.x1 - self.x0, 0)

    @property
    def height(self) -> int:
        return max(self.y1 - self.y0, 0)


@dataclass(frozen=True)
class TextReport:
    """What the detector found in one analysed region."""

    rows: tuple[TextRow, ...] = ()
    glyphs: int = 0
    confidence: float = 0.0
    #: Rows of the frame that were analysed, half-open ``(y0, y1)``.
    analysed_rows: tuple[int, int] = (0, 0)
    #: ``ok``, or why nothing was found: ``empty-frame``, ``flat``,
    #: ``region-too-small``, ``no-glyphs``.
    reason: str = ""

    @property
    def found(self) -> bool:
        return bool(self.rows)

    @property
    def band(self) -> tuple[int, int] | None:
        """Vertical extent of everything found, half-open ``(y0, y1)``."""
        if not self.rows:
            return None
        return (min(row.y0 for row in self.rows), max(row.y1 for row in self.rows))

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        """Bounding box of everything found, ``(y0, y1, x0, x1)``.

        The order matches what the evaluation log of §9 records, so the caller
        does not have to rebuild it from ``rows``.
        """
        if not self.rows:
            return None
        return (
            min(row.y0 for row in self.rows),
            max(row.y1 for row in self.rows),
            min(row.x0 for row in self.rows),
            max(row.x1 for row in self.rows),
        )


def _as_gray(frame: np.ndarray) -> np.ndarray:
    """Luminance of a frame as float32, independent of the channel order."""
    array = np.asarray(frame)
    if array.ndim == 3:
        # The mean does not care whether the channels are RGB or BGR.
        return array[..., :3].astype(np.float32, copy=False).mean(axis=2)
    return array.astype(np.float32, copy=False)


def _ink_map(gray: np.ndarray) -> np.ndarray:
    """Contrast of every pixel against the background of its own line, as uint8.

    The background of a text line is the median of that line: glyphs cover a
    minority of the row they sit in (eight characters are ~100 px of a 400 px
    row), and a median ignores a minority by definition.  Using per-row medians
    instead of a morphological estimate keeps two properties that matter here —
    no kernel can smear a glyph into its neighbour, and the value of a glyph
    pixel is the real contrast of the glyph, so the floors are in grey levels.
    """
    background = np.median(gray, axis=1, keepdims=True)
    return np.clip(np.abs(gray - background), 0.0, 255.0).astype(np.uint8)


def _glyph_components(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of components that could be glyphs."""
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    boxes: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if height < MIN_GLYPH_HEIGHT or height > MAX_GLYPH_HEIGHT:
            continue
        if width <= 0 or width > MAX_GLYPH_ASPECT * height:
            continue
        fill = area / float(width * height)
        if fill < MIN_GLYPH_FILL:
            continue
        if fill > MAX_GLYPH_FILL and area > MAX_SOLID_AREA:
            # A solid panel or a border line; a solid mark too small to carry a
            # legible character is left alone (see MAX_SOLID_AREA).
            continue
        boxes.append((x, y, x + width, y + height))
    return boxes


def _group_rows(boxes: list[tuple[int, int, int, int]]) -> list[TextRow]:
    """Group glyph boxes into rows by their vertical centres."""
    if not boxes:
        return []

    heights = sorted(box[3] - box[1] for box in boxes)
    median_height = heights[len(heights) // 2]
    tolerance = max(2.0, 0.6 * median_height)

    groups: list[list[tuple[int, int, int, int]]] = []
    centres: list[float] = []
    for box in sorted(boxes, key=lambda item: (item[1] + item[3]) / 2.0):
        centre = (box[1] + box[3]) / 2.0
        for index, group_centre in enumerate(centres):
            if abs(centre - group_centre) <= tolerance:
                groups[index].append(box)
                centres[index] = (group_centre * (len(groups[index]) - 1) + centre) / len(groups[index])
                break
        else:
            groups.append([box])
            centres.append(centre)

    rows: list[TextRow] = []
    for group in groups:
        group_heights = [box[3] - box[1] for box in group]
        if max(group_heights) > 3 * max(min(group_heights), 1):
            # Mixed sizes: the grouping glued unrelated blobs together.
            continue
        row = TextRow(
            x0=min(box[0] for box in group),
            y0=min(box[1] for box in group),
            x1=max(box[2] for box in group),
            y1=max(box[3] for box in group),
            glyphs=len(group),
        )
        if row.glyphs >= MIN_ROW_GLYPHS or row.width >= MIN_ROW_SPAN:
            rows.append(row)
    return sorted(rows, key=lambda row: (row.y0, row.x0))


def _line_is_flat(gray: np.ndarray, binary: np.ndarray, row: TextRow) -> bool:
    """Does the row sit on a background flat enough to be printed text?"""
    window = gray[row.y0 : row.y1, row.x0 : row.x1]
    ink = binary[row.y0 : row.y1, row.x0 : row.x1]
    background = window[ink == 0]
    if background.size < 8:  # a solid run of ink is a panel, not a line of text
        return False
    low, high = np.percentile(background, (5, 95))
    return bool(high - low <= MAX_BACKGROUND_SPREAD)


def _glyphs_are_pitched_like_text(boxes: list[tuple[int, int, int, int]], row: TextRow) -> bool:
    """Are the row's glyphs spaced like letters instead of like ticks?"""
    members = sorted(
        (box for box in boxes if row.x0 <= box[0] and box[2] <= row.x1 and row.y0 <= box[1] and box[3] <= row.y1),
        key=lambda box: box[0],
    )
    if len(members) < 2:
        return True  # a single wide component: nothing to compare
    widths = sorted(box[2] - box[0] for box in members)
    gaps = sorted(members[index + 1][0] - members[index][2] for index in range(len(members) - 1))
    median_width = max(widths[len(widths) // 2], 1)
    median_gap = gaps[len(gaps) // 2]
    return bool(median_gap <= MAX_GAP_RATIO * median_width)


def _confidence(rows: list[TextRow], glyphs: int, ink_mean: float) -> float:
    """Heuristic 0..1 ranking value; only "found" is used as a hard signal."""
    if not rows:
        return 0.0
    glyph_factor = min(1.0, glyphs / 8.0)
    strength = min(1.0, max(0.0, (ink_mean - INK_FLOOR) / 32.0))
    heights = [row.height for row in rows if row.height]
    regularity = 1.0
    if heights:
        mean = float(np.mean(heights))
        regularity = 1.0 - min(1.0, float(np.std(heights)) / max(mean, 1.0))
    return round(glyph_factor * (0.5 + 0.5 * strength) * (0.5 + 0.5 * regularity), 3)


def detect_text_rows(
    frame: np.ndarray,
    *,
    rows: tuple[int, int] | None = None,
) -> TextReport:
    """Find text-like rows in ``frame``, optionally only within ``rows``.

    ``rows`` is a half-open ``(y0, y1)`` window in frame coordinates; the
    returned rows are absolute.  The frame is never modified.
    """
    array = np.asarray(frame)
    if array.ndim < 2 or array.size == 0:
        return TextReport(reason="empty-frame")

    height = int(array.shape[0])
    y0, y1 = (0, height) if rows is None else (max(int(rows[0]), 0), min(int(rows[1]), height))
    analysed = (y0, y1)
    if y1 - y0 < 2 * MIN_GLYPH_HEIGHT:
        return TextReport(analysed_rows=analysed, reason="region-too-small")

    gray = _as_gray(array[y0:y1])
    ink = _ink_map(gray)
    ink_max = int(ink.max())
    if ink_max < INK_FLOOR:
        return TextReport(analysed_rows=analysed, reason="flat")

    threshold, _binary = cv2.threshold(ink, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    effective = max(int(threshold), INK_FLOOR, int(round(RELATIVE_INK_FLOOR * ink_max)))
    binary = (ink >= effective).astype(np.uint8)

    boxes = _glyph_components(binary)
    found = [
        row
        for row in _group_rows(boxes)
        if _line_is_flat(gray, binary, row) and _glyphs_are_pitched_like_text(boxes, row)
    ]
    if not found:
        return TextReport(analysed_rows=analysed, reason="no-glyphs")

    glyph_count = sum(row.glyphs for row in found)
    ink_mean = float(np.mean(ink[binary > 0])) if np.any(binary) else 0.0
    shifted = tuple(TextRow(x0=row.x0, y0=row.y0 + y0, x1=row.x1, y1=row.y1 + y0, glyphs=row.glyphs) for row in found)
    return TextReport(
        rows=shifted,
        glyphs=glyph_count,
        confidence=_confidence(found, glyph_count, ink_mean),
        analysed_rows=analysed,
        reason="ok",
    )
