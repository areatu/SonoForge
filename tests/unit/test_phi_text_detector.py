"""Tests for the experimental burned-in text detector.

The detector is a heuristic without OCR, so the tests describe what it must and
must not call text: a row of similarly sized glyphs is text, a solid block, a
single dot, a flat area or a smooth gradient is not.
"""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.phi_text_detector import (
    INK_FLOOR,
    MIN_GLYPH_HEIGHT,
    TextRow,
    detect_text_rows,
)


def _glyphs(
    frame: np.ndarray,
    *,
    y0: int,
    y1: int,
    x0: int = 20,
    count: int = 6,
    step: int = 26,
    width: int = 14,
    value: int,
    solid: bool = False,
) -> np.ndarray:
    """Draw ``count`` glyph-like shapes in one row.

    Glyphs are outlines, not filled boxes: a real character has internal white
    space (fill 0.3-0.8 of its bounding box), while a filled rectangle is a UI
    panel or a border line and must stay out of the report.  ``solid=True``
    draws the filled version for the negative test.
    """
    for index in range(count):
        left = x0 + index * step
        right = left + width
        # The pixel just left of the glyph is the line's background (``step`` is
        # always wider than ``width``, so the previous glyph cannot be there).
        background = int(frame[y0, max(left - 1, 0)])
        frame[y0:y1, left:right] = value
        if solid or width < 3 or (y1 - y0) < 3:
            continue
        # Hollow it out: leaves a ring with realistic ink coverage.
        frame[y0 + 1 : y1 - 1, left + 1 : right - 1] = background
    return frame


def _glyph_geometry(height: int, width: int) -> tuple[int, int, int, int]:
    """Glyph box and spacing for a frame, sized like a real burned-in header.

    Corpus numbers: a Samsung header line is ~15 px tall on an 884-row frame
    (1.7 % of the height), so synthetic glyphs follow that proportion instead of
    a fixed pixel size.
    """
    glyph_h = max(4, int(round(0.018 * height)))
    glyph_w = max(3, int(round(glyph_h * 0.85)))
    step = max(glyph_w + 3, int(round(glyph_w * 1.9)))
    return 4, 4 + glyph_h, glyph_w, step


def _header_frame(
    height: int = 200,
    width: int = 400,
    *,
    band: int = 20,
    background: int = 24,
    glyph: int = 240,
) -> np.ndarray:
    """Dark header band with bright glyphs over a brighter "sector"."""
    frame = np.full((height, width), 96, dtype=np.uint8)
    frame[:band, :] = background
    y0, y1, glyph_w, step = _glyph_geometry(height, width)
    return _glyphs(frame, y0=y0, y1=y1, count=8, step=step, width=glyph_w, value=glyph)


def test_finds_a_row_of_glyphs_in_the_header_band() -> None:
    frame = _header_frame()
    report = detect_text_rows(frame)

    assert report.found
    assert report.reason == "ok"
    assert report.glyphs >= 6
    band = report.band
    assert band is not None
    assert band[0] >= 3 and band[1] <= 22
    assert report.confidence > 0.5


def test_reports_absolute_coordinates_when_a_region_is_given() -> None:
    frame = np.full((300, 400), 100, dtype=np.uint8)
    _, y1, glyph_w, step = _glyph_geometry(300, 400)
    _glyphs(frame, y0=204, y1=204 + y1, count=8, step=step, width=glyph_w, value=250)

    limited = detect_text_rows(frame, rows=(0, 80))
    assert not limited.found
    assert limited.analysed_rows == (0, 80)

    everything = detect_text_rows(frame, rows=(190, 260))
    assert everything.found
    band = everything.band
    assert band is not None
    assert band[0] >= 200  # absolute, not region-relative


def test_flat_frame_yields_nothing() -> None:
    report = detect_text_rows(np.full((120, 200), 40, dtype=np.uint8))
    assert not report.found
    assert report.reason == "flat"
    assert report.confidence == 0.0


def test_smooth_gradient_is_not_text() -> None:
    """The sector has smooth gradients; morphological ink cancels them out."""
    gradient = np.tile(np.linspace(20, 200, 300, dtype=np.uint8), (160, 1))
    report = detect_text_rows(gradient)
    assert not report.found


def test_solid_block_is_not_text() -> None:
    """A filled panel or a thick border line is not a row of glyphs."""
    frame = np.full((600, 400), 30, dtype=np.uint8)
    frame[10:60, 40:160] = 240  # 120x50 solid rectangle
    report = detect_text_rows(frame)
    assert not report.found


def test_tiny_solid_marks_still_count_as_glyphs() -> None:
    """At a few pixels per character the strokes merge: the row is still text.

    Rejecting solid marks outright would make the detector blind exactly where
    the preview downscales the header, so only marks big enough to hold a
    legible character are treated as panels (``MAX_SOLID_AREA``).
    """
    frame = np.full((200, 400), 30, dtype=np.uint8)
    y0, y1, glyph_w, step = _glyph_geometry(200, 400)
    _glyphs(frame, y0=y0, y1=y1, count=8, step=step, width=glyph_w, value=240, solid=True)
    assert detect_text_rows(frame).found


def test_solid_glyph_shapes_are_not_enough() -> None:
    """Filled boxes the size of a real character are rejected as a UI panel."""
    frame = np.full((600, 400), 30, dtype=np.uint8)
    _glyphs(frame, y0=4, y1=4 + 12, count=8, step=20, width=10, value=240, solid=True)
    assert not detect_text_rows(frame).found


def test_single_dot_is_not_text() -> None:
    frame = np.full((400, 400), 30, dtype=np.uint8)
    frame[10:20, 40:56] = 240
    report = detect_text_rows(frame)
    assert not report.found


def test_needs_a_wide_enough_run() -> None:
    """Two glyphs are not a word; the row must be several glyphs or wide."""
    frame = np.full((120, 200), 30, dtype=np.uint8)
    _glyphs(frame, y0=8, y1=14, count=2, step=11, width=8, value=240)
    assert not detect_text_rows(frame).found


def test_white_info_bar_with_dark_glyphs_is_found() -> None:
    """The inverse polarity: black text on the light info bar of some vendors."""
    frame = np.full((200, 400), 96, dtype=np.uint8)
    frame[:22, :] = 240
    y0, y1, glyph_w, step = _glyph_geometry(200, 400)
    _glyphs(frame, y0=y0, y1=y1, count=8, step=step, width=glyph_w, value=20)
    report = detect_text_rows(frame)
    assert report.found


def test_speckle_noise_is_not_text() -> None:
    """The sector is speckle: no bar, no glyphs, and no report.

    Per-row medians make speckle *contrast* (a blob differs from its row by
    tens of levels), so the row has to be rejected by the flat-background and
    character-pitch filters instead.
    """
    rng = np.random.default_rng(20261007)
    speckle = np.clip(rng.normal(90, 28, (300, 400)), 0, 255).astype(np.uint8)
    assert not detect_text_rows(speckle).found


def test_speckle_next_to_a_header_still_reports_only_the_header() -> None:
    rng = np.random.default_rng(11)
    frame = np.clip(rng.normal(90, 28, (300, 400)), 0, 255).astype(np.uint8)
    frame[:30, :] = 24
    _glyphs(frame, y0=8, y1=24, x0=30, count=10, step=24, width=14, value=235)
    report = detect_text_rows(frame, rows=(0, 120))
    assert report.found
    band = report.band
    assert band is not None and band[1] <= 30  # nothing from the speckle below


def test_caliper_marks_are_not_text() -> None:
    """Regular ticks with a gap of many glyph widths are a ruler, not a word."""
    frame = np.full((300, 400), 20, dtype=np.uint8)
    for index in range(6):
        left = 40 + index * 30
        frame[100:112, left : left + 2] = 250
    assert not detect_text_rows(frame).found


def test_colour_frame_is_accepted() -> None:
    """Colour Doppler frames reach the detector through a luminance mean."""
    gray = _header_frame()
    colour = np.stack([gray, gray, gray], axis=-1)
    colour[:, :, 2] = np.clip(colour[:, :, 2].astype(int) + 0, 0, 255).astype(np.uint8)
    report = detect_text_rows(colour)
    assert report.found


def test_detector_never_modifies_the_frame() -> None:
    frame = _header_frame()
    original = frame.copy()
    detect_text_rows(frame)
    np.testing.assert_array_equal(frame, original)


def test_region_too_small_and_empty_frame() -> None:
    frame = np.full((100, 100), 10, dtype=np.uint8)
    assert detect_text_rows(frame, rows=(0, MIN_GLYPH_HEIGHT)).reason == "region-too-small"
    assert detect_text_rows(np.zeros((0, 0), dtype=np.uint8)).reason == "empty-frame"


def test_row_geometry_is_reported_for_the_ui() -> None:
    report = detect_text_rows(_header_frame())
    row = report.rows[0]
    assert isinstance(row, TextRow)
    assert row.width > 0 and row.height > 0
    assert row.x0 >= 0 and row.y0 >= 0


def test_ink_floor_is_not_reachable_by_dither() -> None:
    """A band that differs from its background by a level or two is not ink."""
    frame = np.full((120, 200), 100, dtype=np.uint8)
    frame[:20, :] = 100 + INK_FLOOR - 5
    assert detect_text_rows(frame).reason == "flat"
