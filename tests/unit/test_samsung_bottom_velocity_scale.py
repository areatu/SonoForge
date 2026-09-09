"""Unit tests for Samsung bottom velocity scale detection.

``detect_bottom_velocity_scale`` finds the velocity axis encoded as vertical
marks that CROSS the horizontal bottom ruler on Samsung Doppler frames. It is
the discriminator that separates a real velocity axis from the time ruler's
own ticks, which hang BELOW the ruler line and must never be mistaken for it.

Geometry of a Samsung Doppler bottom edge::

    ...spectral panel (dark)...
        |     |     |     |        <- velocity marks, bright ABOVE the ruler
    ====+=====+=====+=====+====    <- ruler line (bright, full width)
        |     |     |     |        <- ... and bright BELOW it (crossing)
      | | | | | | | | | | | |      <- time ruler ticks (below only)
"""

from __future__ import annotations

import numpy as np

from echo_personal_tool.infrastructure.samsung_tick_detector import (
    detect_bottom_velocity_scale,
    detect_samsung_doppler_scales,
)

_HEIGHT = 884
_WIDTH = 1180
_RULER_Y = 856
_PANEL_TOP = 300


def _blank_doppler_panel() -> np.ndarray:
    """Dark spectral panel with a bright full-width ruler line at ``_RULER_Y``."""
    gray = np.zeros((_HEIGHT, _WIDTH), dtype=np.float32)
    gray[_PANEL_TOP:_RULER_Y, :] = 40.0  # dark spectral band
    gray[_RULER_Y, :] = 255.0  # continuous ruler line
    return gray


def _with_crossing_marks(
    gray: np.ndarray,
    *,
    spacing: int = 100,
    first_x: int = 90,
    last_x: int = 1091,
    half_height: int = 14,
) -> np.ndarray:
    """Velocity marks: bright bars extending above AND below the ruler."""
    for x in range(first_x, last_x, spacing):
        gray[_RULER_Y - half_height : _RULER_Y + half_height + 1, x : x + 2] = 220.0
    return gray


def _with_marks_below_only(gray: np.ndarray, *, spacing: int = 100) -> np.ndarray:
    """Time-ruler style ticks: short marks hanging below the ruler only."""
    for x in range(90, 1091, spacing):
        gray[_RULER_Y + 3 : _RULER_Y + 16, x : x + 2] = 220.0
    return gray


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detects_uniform_crossing_marks() -> None:
    """Evenly spaced marks crossing the ruler are a velocity scale."""
    gray = _with_crossing_marks(_blank_doppler_panel(), spacing=100)

    result = detect_bottom_velocity_scale(gray, ruler_y=_RULER_Y)

    assert len(result.tick_positions) == 11
    assert result.spacing_px == 100.0
    assert result.confidence >= 0.3
    assert result.band_y == float(_RULER_Y)
    assert result.tick_positions == sorted(result.tick_positions)


def test_confidence_scales_with_tick_count() -> None:
    """More detected marks → higher confidence (count_factor saturates at 15)."""
    sparse = detect_bottom_velocity_scale(_with_crossing_marks(_blank_doppler_panel(), spacing=160), ruler_y=_RULER_Y)
    dense = detect_bottom_velocity_scale(_with_crossing_marks(_blank_doppler_panel(), spacing=60), ruler_y=_RULER_Y)

    assert len(dense.tick_positions) > len(sparse.tick_positions)
    assert dense.confidence > sparse.confidence


def test_relocates_ruler_from_offset_hint() -> None:
    """``ruler_y`` is only a hint; the true ruler line is found within +/-60 px."""
    gray = _with_crossing_marks(_blank_doppler_panel())

    # Offsets stay inside the frame-edge guard (ruler_y < height - 5).
    for offset in (-50, -40, -15, 10, 20):
        result = detect_bottom_velocity_scale(gray, ruler_y=_RULER_Y + offset)

        assert result.band_y == float(_RULER_Y), f"offset {offset} lost the ruler"
        assert len(result.tick_positions) == 11


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------


def test_rejects_time_ruler_ticks_below_the_line() -> None:
    """The time ruler's own ticks do not cross the line → not a velocity scale.

    This is the core discriminator: without it every Doppler frame would report
    a bottom velocity scale built from its time axis.
    """
    gray = _with_marks_below_only(_blank_doppler_panel())

    result = detect_bottom_velocity_scale(gray, ruler_y=_RULER_Y)

    assert result.tick_positions == []
    assert result.confidence == 0.0


def test_rejects_too_few_marks() -> None:
    """Fewer than 5 marks is not a scale (stray annotations, calipers)."""
    gray = _with_crossing_marks(_blank_doppler_panel(), spacing=300, first_x=90, last_x=800)

    result = detect_bottom_velocity_scale(gray, ruler_y=_RULER_Y)

    assert result.tick_positions == []
    assert result.confidence == 0.0


def test_rejects_bare_ruler_without_marks() -> None:
    """A ruler line alone carries no velocity information."""
    result = detect_bottom_velocity_scale(_blank_doppler_panel(), ruler_y=_RULER_Y)

    assert result.tick_positions == []
    assert result.confidence == 0.0


def test_rejects_ruler_hint_at_frame_edges() -> None:
    """Out-of-range hints must return an empty result, not raise/index-error."""
    gray = _with_crossing_marks(_blank_doppler_panel())

    for ruler_y in (0, 4, _HEIGHT - 5, _HEIGHT - 1):
        result = detect_bottom_velocity_scale(gray, ruler_y=ruler_y)

        assert result.tick_positions == []
        assert result.confidence == 0.0


def test_rejects_dark_frame_without_ruler() -> None:
    """No bright ruler and no marks → nothing detected."""
    gray = np.zeros((_HEIGHT, _WIDTH), dtype=np.float32)

    result = detect_bottom_velocity_scale(gray, ruler_y=_RULER_Y)

    assert result.tick_positions == []
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Integration through detect_samsung_doppler_scales
# ---------------------------------------------------------------------------


def _rgb_doppler_frame() -> np.ndarray:
    """RGB Samsung-like frame carrying both a time ruler and a velocity scale."""
    frame = np.zeros((_HEIGHT, _WIDTH, 3), dtype=np.uint8)
    frame[_PANEL_TOP:_RULER_Y, :, :] = 40  # dark spectral panel
    frame[_RULER_Y, :, :] = 255  # ruler line
    for x in range(90, 1091, 100):  # velocity marks (crossing)
        frame[_RULER_Y - 14 : _RULER_Y + 15, x : x + 2, :] = 220
    for x in range(60, 1130, 36):  # time ruler ticks (below only)
        frame[_RULER_Y + 4 : _RULER_Y + 18, x, :] = 200
    return frame


def test_scales_expose_bottom_velocity_scale() -> None:
    """detect_samsung_doppler_scales surfaces the bottom scale alongside time."""
    scales = detect_samsung_doppler_scales(_rgb_doppler_frame())

    assert scales.time_scale.confidence >= 0.3
    assert len(scales.time_scale.tick_positions) >= 5

    bottom = scales.bottom_velocity_scale
    assert bottom is not None
    assert len(bottom.tick_positions) >= 5
    assert bottom.confidence >= 0.3
    assert bottom.spacing_px == 100.0


def test_bottom_scale_skipped_without_time_ruler() -> None:
    """No time ruler → no ruler hint → bottom scale is not attempted."""
    frame = np.zeros((_HEIGHT, _WIDTH, 3), dtype=np.uint8)
    frame[: int(_HEIGHT * 0.62), :, :] = 140  # plain B-mode tissue
    frame[int(_HEIGHT * 0.62) :, :, :] = 40

    scales = detect_samsung_doppler_scales(frame)

    assert scales.bottom_velocity_scale is None or not scales.bottom_velocity_scale.tick_positions
