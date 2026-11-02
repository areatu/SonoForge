"""Tests for the evidence-fusion Doppler baseline detector."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_baseline_evidence import (
    BaselineCue,
    cue_envelope_foot,
    cue_static_row,
    cue_tag,
    detect_baseline_robust,
    fuse_cues,
    snap_to_grid,
)

ROI = DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=120)


def _samsung_like_frame(baseline_row: int = 70, *, draw_line: bool = False, seed: int = 0) -> np.ndarray:
    """Dark spectral panel with a systolic envelope rooted at the baseline."""
    rng = np.random.RandomState(seed)
    frame = rng.randint(0, 8, size=(120, 200)).astype(np.uint8)
    x = np.arange(200)
    envelope = (35 * np.abs(np.sin(x / 18.0))).astype(int)
    for c in x:
        top = baseline_row - envelope[c]
        if top < baseline_row:
            frame[top:baseline_row, c] = rng.randint(120, 240, size=baseline_row - top)
    if draw_line:
        frame[baseline_row, :] = 200
    return frame


class TestEnvelopeFootCue:
    def test_finds_baseline_without_drawn_line(self):
        frame = _samsung_like_frame(baseline_row=70, draw_line=False)
        cue = cue_envelope_foot(frame, ROI)
        assert cue is not None
        assert abs(cue.y - 70) <= 2.0
        assert cue.strength > 0.2

    def test_returns_none_on_empty_panel(self):
        frame = np.zeros((120, 200), dtype=np.uint8)
        assert cue_envelope_foot(frame, ROI) is None

    def test_rgb_input_supported(self):
        gray = _samsung_like_frame(baseline_row=55)
        rgb = np.stack([gray] * 3, axis=-1)
        cue = cue_envelope_foot(rgb, ROI)
        assert cue is not None
        assert abs(cue.y - 55) <= 2.5


class TestStaticRowCue:
    def test_picks_the_drawn_static_line(self):
        frames = []
        for i in range(6):
            f = _samsung_like_frame(baseline_row=70, draw_line=True, seed=i)
            # Make the spectrum flicker strongly frame-to-frame.
            noise_rows = slice(20, 69)
            f[noise_rows] = (f[noise_rows] * ((i % 3) / 2.0 + 0.2)).astype(np.uint8)
            frames.append(f)
        cue = cue_static_row(frames, ROI)
        assert cue is not None
        assert abs(cue.y - 70) <= 2.0

    def test_requires_multiple_frames(self):
        assert cue_static_row([_samsung_like_frame()], ROI) is None


class TestTagCue:
    def test_rejects_edge_values(self):
        assert cue_tag(0.0, ROI) is None
        assert cue_tag(ROI.y1, ROI) is None

    def test_accepts_interior_value(self):
        cue = cue_tag(60.0, ROI)
        assert cue is not None and cue.y == 60.0


class TestFusion:
    def test_concordant_cues_raise_confidence(self):
        weak = fuse_cues([BaselineCue("foot", 70.0, 0.6)], ROI)
        strong = fuse_cues(
            [BaselineCue("foot", 70.0, 0.6), BaselineCue("line", 70.0, 1.0)],
            ROI,
        )
        assert strong.confidence > weak.confidence
        assert abs(strong.y - 70.0) <= 1.0

    def test_conflicting_cues_lower_confidence(self):
        conflicting = fuse_cues(
            [BaselineCue("foot", 40.0, 1.0), BaselineCue("line", 90.0, 1.0)],
            ROI,
        )
        agreeing = fuse_cues(
            [BaselineCue("foot", 40.0, 1.0), BaselineCue("line", 40.0, 1.0)],
            ROI,
        )
        assert conflicting.confidence < agreeing.confidence

    def test_no_cues_falls_back_to_centre(self):
        est = fuse_cues([], ROI)
        assert est.confidence == 0.0
        assert est.y == ROI.y0 + ROI.height / 2.0

    def test_weak_tag_alone_cannot_be_confident(self):
        est = fuse_cues([BaselineCue("tag", 60.0, 1.0)], ROI)
        assert not est.is_confident

    def test_grid_snapping(self):
        y, snapped = snap_to_grid(69.0, [30.0, 50.0, 70.0, 90.0], 4.0)
        assert snapped and y == 70.0
        y, snapped = snap_to_grid(60.0, [30.0, 70.0], 4.0)
        assert not snapped and y == 60.0


class TestEndToEnd:
    def test_samsung_like_frame_without_tags(self):
        frame = _samsung_like_frame(baseline_row=70, draw_line=False)
        est = detect_baseline_robust(frame, ROI)
        assert abs(est.y - 70) <= 3.0
        assert est.confidence > 0.0

    def test_bogus_tag_does_not_override_pixels(self):
        frame = _samsung_like_frame(baseline_row=70, draw_line=True)
        est = detect_baseline_robust(frame, ROI, tag_baseline_y=0.0)
        assert abs(est.y - 70) <= 3.0

    def test_multiframe_improves_confidence(self):
        frames = [_samsung_like_frame(baseline_row=70, draw_line=True, seed=i) for i in range(6)]
        single = detect_baseline_robust(frames[0], ROI)
        multi = detect_baseline_robust(frames[0], ROI, frames=frames)
        assert multi.confidence >= single.confidence
        assert abs(multi.y - 70) <= 3.0
