"""Unit tests for the burned-ECG strip mask (plan А.5, issue #643).

The acceptance metric is *locating*: IoU of the located band against the
annotated strip must be ≥ 0.9.  Locating deliberately shares no gate with
reading the trace as a signal — the user's 4CC:301 clip (noisy strip, no QRS,
implausible HR) yields no usable ECG, and the mask must still fire.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.burned_ecg_mask import (
    BurnedEcgStrip,
    detect_burned_ecg_strip,
    get_burned_ecg_override,
    store_burned_ecg_override,
    strip_from_rect,
    strip_rect_iou,
)
from echo_personal_tool.domain.services.cine_phase_timeline import burned_ecg_signal


@pytest.fixture(autouse=True)
def _reset_override():
    store_burned_ecg_override("auto")
    yield
    store_burned_ecg_override("auto")


def strip_cine(
    *,
    height: int = 200,
    width: int = 300,
    row: int = 180,
    col_start: int = 40,
    col_end: int = 280,
    n: int = 24,
    noise_px: int = 0,
    seed: int = 7,
) -> np.ndarray:
    """A vendor-style clip: sector above, green strip (trace + grid) at ``row``.

    The strip spans ``row ± 8``: a Samsung-style band carries the trace line
    plus green grid rows, so the annotated rect in the IoU tests has the same
    extent a human annotation would outline.  ``noise_px`` replaces the clean
    trace with a jittering one (the 4CC:301-style unreadable strip).
    """
    rng = np.random.default_rng(seed)
    image = np.full((n, height, width, 3), 60, dtype=np.uint8)
    image[:, :150, :, :] = 120  # a bright sector in the upper part
    for t in range(n):
        for x in range(col_start, col_end):
            if noise_px:
                jitter = abs(int(rng.integers(-noise_px, noise_px + 1)))
                image[t, row - jitter, x, 1] = 200
            else:
                image[t, row, x, 1] = 200
        image[t, row - 8, col_start:col_end, 1] = 200  # green grid rows
        image[t, row + 8, col_start:col_end, 1] = 200
    return image


class TestLocate:
    """The detector finds the strip: IoU ≥ 0.9 against the annotated rect."""

    def test_strip_below_the_sector_is_located(self) -> None:
        # 4CC:74-style: the strip sits in the black zone below the sector.
        frames = strip_cine()
        strip = detect_burned_ecg_strip(frames)
        assert strip is not None
        annotated = (172, 189, 40, 280)  # the drawn band's own extent
        assert strip_rect_iou(strip, annotated) >= 0.9

    def test_strip_over_the_sector_is_located(self) -> None:
        # 4CC:301-style: the strip is drawn OVER the lower sector pixels.
        frames = strip_cine(height=200, width=300, row=124, col_start=30, col_end=270)
        strip = detect_burned_ecg_strip(frames)
        assert strip is not None
        assert strip_rect_iou(strip, (116, 133, 30, 270)) >= 0.9

    def test_noisy_unreadable_strip_still_fires(self) -> None:
        """The negative fixture: no QRS, implausible HR — mask fires anyway."""
        frames = strip_cine(row=170, noise_px=3)
        strip = detect_burned_ecg_strip(frames)
        assert strip is not None
        assert strip.mask_for(frames.shape[1:3]).any()

    def test_half_width_trace_with_green_annotation_is_located(self) -> None:
        """The annotation glyphs stay out: the located span is the trace's."""
        n, height, width = 24, 120, 200
        image = np.zeros((n, height, width, 3), dtype=np.uint8)
        for t in range(n):
            for x in range(20, 90):  # trace covers 35% of the width
                image[t, 110, x, 1] = 200
            image[t, 84:88, 5:41, 1] = 180  # green annotation above the trace
        strip = detect_burned_ecg_strip(image)
        assert strip is not None
        assert strip.col_start == 20
        assert strip.col_end == 90
        assert strip_rect_iou(strip, (110, 111, 20, 90)) == pytest.approx(1.0)

    def test_grayscale_frames_find_nothing(self) -> None:
        gray = np.zeros((12, 200, 300), dtype=np.uint8)
        gray[:, 180, 40:280] = 200
        assert detect_burned_ecg_strip(gray) is None

    def test_no_strip_finds_nothing(self) -> None:
        assert detect_burned_ecg_strip(np.zeros((12, 200, 300, 3), dtype=np.uint8)) is None

    def test_a_green_frame_is_not_a_strip(self) -> None:
        # A green overlay covers everything: the fraction gate refuses.
        frames = np.full((12, 200, 300, 3), 0, dtype=np.uint8)
        frames[..., 1] = 200
        assert detect_burned_ecg_strip(frames) is None

    def test_confidence_reflects_multi_frame_support(self) -> None:
        strip = detect_burned_ecg_strip(strip_cine(n=24))
        assert strip is not None and strip.confidence == pytest.approx(0.9)
        single = detect_burned_ecg_strip(strip_cine(n=1))
        assert single is not None and single.confidence == pytest.approx(0.6)


class TestMaskSemantics:
    """The mask marks the band as unknown — never a restore, never a crop."""

    def test_mask_for_is_the_whole_band_rect(self) -> None:
        strip = strip_from_rect((178, 182, 40, 280))
        mask = strip.mask_for((200, 300))
        assert mask.shape == (200, 300)
        assert mask[178:182, 40:280].all()
        assert not mask[:178].any()
        assert not mask[182:].any()
        assert not mask[:, :40].any()

    def test_mask_out_of_bounds_is_clipped(self) -> None:
        strip = strip_from_rect((190, 220, 280, 400))
        mask = strip.mask_for((200, 300))
        assert mask.shape == (200, 300)
        assert mask[190:200, 280:300].all()
        assert int(mask.sum()) == 10 * 20

    def test_scaled_keeps_the_rect_shape(self) -> None:
        strip = strip_from_rect((178, 182, 40, 280))
        small = strip.scaled(0.5, (100, 150))
        assert (small.row_start, small.row_end, small.col_start, small.col_end) == (89, 91, 20, 140)
        assert small.mask_for((100, 150)).sum() == 2 * 120

    def test_round_trip_dict(self) -> None:
        strip = strip_from_rect((178, 182, 40, 280), confidence=0.7)
        restored = BurnedEcgStrip.from_dict(strip.to_dict())
        assert restored.rect == strip.rect
        assert restored.confidence == pytest.approx(0.7)
        assert restored.source == "manual"
        with pytest.raises(ValueError):
            BurnedEcgStrip.from_dict({"row_start": -1})


class TestOverride:
    """The user's override: the mask can be switched off for the session."""

    def test_default_is_auto(self) -> None:
        assert get_burned_ecg_override() == "auto"

    def test_off_is_stored_and_invalid_resets(self) -> None:
        store_burned_ecg_override("off")
        assert get_burned_ecg_override() == "off"
        store_burned_ecg_override("banana")
        assert get_burned_ecg_override() == "auto"

    def test_manual_strip_says_so(self) -> None:
        strip = strip_from_rect((1, 2, 3, 4))
        assert strip.source == "manual"
        assert strip_rect_iou(strip, (1, 2, 3, 4)) == pytest.approx(1.0)
        assert strip_rect_iou(strip, (10, 12, 30, 40)) == 0.0


class TestLocateIsNotRead:
    """One locate step serves the mask and the ECG reader; gates stay apart."""

    def test_signal_none_mask_fires(self) -> None:
        """4CC:301 contract: no readable ECG, the strip is still masked."""
        frames = strip_cine(row=170, noise_px=3)
        strip = detect_burned_ecg_strip(frames)
        assert strip is not None
        assert burned_ecg_signal(frames, 33.3, frames.shape[0]) is None

    def test_signal_reads_what_the_mask_locates(self) -> None:
        frames = strip_cine(n=48, noise_px=0)
        # A static line has no rhythm — both the mask and the reader agree
        # there is nothing to read, but for different reasons: the mask is
        # still located (geometry), the signal refuses (no peaks).
        strip = detect_burned_ecg_strip(frames)
        assert strip is not None
        assert burned_ecg_signal(frames, 33.3, frames.shape[0]) is None


def pulsating_cine(*, height: int = 128, width: int = 160, n: int = 24, period: int = 12) -> np.ndarray:
    """A gray cine with a bright tissue sector and a pulsating dark cavity."""
    yy, xx = np.mgrid[:height, :width]
    frames = np.empty((n, height, width), dtype=np.float64)
    for t in range(n):
        radius = 18 + 6 * np.cos(2 * np.pi * (t - 2) / period)
        cavity = ((xx - 80) / radius) ** 2 + ((yy - 60) / (radius * 1.3)) ** 2 < 1
        frames[t] = np.where(cavity, 20.0, 170.0)
    return frames


def flickering_strip_overlay(
    gray_cine: np.ndarray, *, row_start: int, row_end: int, col_start: int, col_end: int
) -> np.ndarray:
    """Burn a flickering strip band over the cine: bright when drawn, black when off.

    The bright phase matters: a vendor trace is *brighter* than the tissue, so
    without the mask its pixels enter the ROI foreground and the strip's
    redraw flicker is read as contraction.
    """
    color = np.repeat(gray_cine[..., None], 3, axis=3)
    band = color[:, row_start:row_end, col_start:col_end]
    band[:] = 0  # the "off" phase: the vendor erased the line
    band[::2] = 255  # the "on" phase: a bright redraw over the tissue
    return color


def gray_with_strip(
    gray_cine: np.ndarray, *, row_start: int, row_end: int, col_start: int, col_end: int
) -> tuple[np.ndarray, np.ndarray]:
    """The cine with a flickering strip burned in, averaged to gray like the callers do.

    Returns the gray stack and the full-frame strip mask.
    """
    color = flickering_strip_overlay(
        gray_cine, row_start=row_start, row_end=row_end, col_start=col_start, col_end=col_end
    )
    mask = np.zeros(color.shape[1:3], dtype=bool)
    mask[row_start:row_end, col_start:col_end] = True
    return color.mean(axis=3), mask


class TestPhaseSignalsSubtract:
    """А.5: the strip must not vote in the ROI/flow/phase signals."""

    def test_motion_ignores_the_strip_with_the_mask(self) -> None:
        from echo_personal_tool.domain.services.cine_phase_timeline import motion_signal

        gray = pulsating_cine()
        # The strip sits inside the ROI's default rows (0.12h..0.82h).
        polluted, mask = gray_with_strip(gray, row_start=96, row_end=104, col_start=20, col_end=150)
        without = motion_signal(polluted)
        with_mask = motion_signal(polluted, exclude_mask=mask)
        clean = motion_signal(gray)
        assert without.size == clean.size
        # The redraw flicker lifts the whole motion level ~10×; the mask
        # restores the tissue-only signal.
        assert float(np.mean(without)) > 8 * float(np.mean(with_mask))
        assert np.allclose(with_mask, clean, atol=0.02)

    def test_dark_pool_keeps_the_cavity_phase(self) -> None:
        from echo_personal_tool.domain.services.cine_phase_timeline import dark_pool_signal

        gray = pulsating_cine()
        polluted, mask = gray_with_strip(gray, row_start=96, row_end=104, col_start=20, col_end=150)
        dark = dark_pool_signal(polluted, exclude_mask=mask)
        clean = dark_pool_signal(gray)
        assert dark.size == clean.size
        # ED = cavity maximum: the strip's dark flicker must not move it.
        assert int(np.argmax(dark[:12])) == int(np.argmax(clean[:12]))

    def test_flow_ignores_the_strip_with_the_mask(self) -> None:
        from echo_personal_tool.domain.services.phase_field import optical_flow_magnitude_signal

        gray = pulsating_cine()
        polluted, mask = gray_with_strip(gray, row_start=96, row_end=104, col_start=20, col_end=150)
        without = optical_flow_magnitude_signal(polluted)
        with_mask = optical_flow_magnitude_signal(polluted, exclude_mask=mask)
        clean = optical_flow_magnitude_signal(gray)
        # The strip's redraw flicker is motion no tissue has: without the
        # mask the flow level explodes (~25× the clean mean); with the mask
        # the level returns within noise of the strip-free control.
        assert float(np.max(np.abs(without - clean))) > 5 * float(np.max(np.abs(with_mask - clean)))
        bias_without = abs(float(np.mean(without)) - float(np.mean(clean)))
        bias_with = abs(float(np.mean(with_mask)) - float(np.mean(clean)))
        assert bias_with < 0.2 * bias_without

    def test_mismatched_mask_is_ignored_not_guessed(self) -> None:
        from echo_personal_tool.domain.services.cine_phase_timeline import motion_signal

        gray = pulsating_cine()
        polluted, _mask = gray_with_strip(gray, row_start=96, row_end=104, col_start=20, col_end=150)
        plain = motion_signal(polluted)
        with_wrong = motion_signal(polluted, exclude_mask=np.ones((17, 17), dtype=bool))
        assert np.allclose(plain, with_wrong)

    def test_phase_field_threading(self) -> None:
        from echo_personal_tool.domain.services.phase_field import extract_phase_candidates

        gray = pulsating_cine()
        polluted, mask = gray_with_strip(gray, row_start=96, row_end=104, col_start=20, col_end=150)
        clean_dark = extract_phase_candidates(frames=gray)["dark_pool"]
        excluded_dark = extract_phase_candidates(frames=polluted, exclude_mask=mask)["dark_pool"]
        assert np.allclose(excluded_dark, clean_dark, atol=0.02)
