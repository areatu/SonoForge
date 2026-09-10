"""Phase 2 — clinical strain metrics over a full cardiac cycle (issues #C10/#C6).

The module used to report one number: the strain at the end of the ED…ES
window. That is end-systolic strain, not the global longitudinal strain the
guidelines and the vendors report, it hides post-systolic shortening, and the
baseline drift was "compensated" (a linear ramp that also moved the systolic
peak) instead of being measured.

These tests pin the corrected behaviour:

* GLS is the peak of the *global* curve over the whole cycle — never the mean of
  per-segment peaks taken at different instants (#C6);
* ESS (the value at AVC) is reported next to GLS, and AVC always carries the
  source it came from;
* the analysis window is a whole cycle, so time-to-peak and the post-systolic
  index are defined at all;
* drift is measured and reported.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.strain_metrics import (
    AVC_SOURCE_AREA,
    AVC_SOURCE_ECG,
    AVC_SOURCE_ES,
    AVC_SOURCE_MANUAL,
    AVC_SOURCE_STRAIN_PEAK,
    compute_strain_metrics,
    detect_avc_frame,
    estimate_cycle_length_frames,
    metrics_by_segment,
    time_to_peak_map,
)


def _systolic_curve() -> np.ndarray:
    """Normal beat: peak at ES (frame 4), return to baseline (frame 10)."""
    return np.array([0.0, -5.0, -12.0, -18.0, -20.0, -19.0, -17.0, -12.0, -6.0, -2.0, -0.5], dtype=np.float64)


def _post_systolic_curve() -> np.ndarray:
    """Peak *after* AVC (frame 3): post-systolic shortening."""
    return np.array([0.0, -8.0, -12.0, -13.0, -12.0, -16.0, -19.0, -14.0, -6.0, -1.0], dtype=np.float64)


class TestStrainMetrics:
    def test_peak_is_systolic_and_post_systolic_shortening_is_reported(self) -> None:
        """The reported value is the peak *systolic* strain (EACVI/ASE).

        Was: the whole-cycle extremum, which promoted any post-systolic (or
        diastolic artefact) excursion to the GLS. The deeper late extremum is
        still measured — as post-systolic shortening, never as the peak.
        """
        metrics = compute_strain_metrics(_post_systolic_curve(), ed_index=0, avc_index=3, frame_time_ms=33.3)
        assert metrics.ess == pytest.approx(-13.0)  # value at AVC
        assert metrics.peak == pytest.approx(-16.0)  # peak systolic strain, frame 5
        assert metrics.peak_frame == 5
        assert metrics.post_systolic_peak == pytest.approx(-19.0)
        assert metrics.post_systolic_index == pytest.approx(abs(16.0 - 19.0) / 16.0 * 100.0, abs=1e-6)  # positive
        assert metrics.is_post_systolic

    def test_normal_beat_has_no_post_systolic_shortening(self) -> None:
        metrics = compute_strain_metrics(_systolic_curve(), ed_index=0, avc_index=4, frame_time_ms=33.3)
        assert metrics.peak == pytest.approx(-20.0)
        assert metrics.ess == pytest.approx(-20.0)
        assert not metrics.is_post_systolic

    def test_time_to_peak_is_measured_from_ed(self) -> None:
        metrics = compute_strain_metrics(_systolic_curve(), ed_index=0, avc_index=4, frame_time_ms=40.0)
        assert metrics.peak_frame == 4
        assert metrics.time_to_peak_ms == pytest.approx(160.0)

    def test_drift_is_reported_not_removed(self) -> None:
        curve = _systolic_curve().copy()
        curve += np.linspace(0.0, 4.0, curve.size)  # baseline creep
        metrics = compute_strain_metrics(curve, ed_index=0, avc_index=4, frame_time_ms=33.3)
        assert np.isfinite(metrics.drift)
        assert any("drift" in note for note in metrics.notes)
        # The peak is still read from the measured curve — no detrending. The
        # creep makes the diastolic tail rise, which must not become the peak.
        assert metrics.peak == pytest.approx(-18.4, abs=1e-6)

    def test_diastolic_dive_is_not_the_peak(self) -> None:
        """A late downward artefact must not be reported as a peak systolic value."""
        curve = np.array([0.0, -4.0, -9.0, -13.0, -14.0, -13.0, -11.0, -8.0, -22.0, -25.0], dtype=np.float64)
        metrics = compute_strain_metrics(curve, ed_index=0, avc_index=4, frame_time_ms=33.3)
        assert metrics.peak == pytest.approx(-14.0)
        assert metrics.post_systolic_peak == pytest.approx(-25.0)
        assert metrics.is_post_systolic

    def test_window_end_limits_the_peak_search(self) -> None:
        curve = _systolic_curve()
        metrics = compute_strain_metrics(curve, ed_index=0, avc_index=4, window_end=3, frame_time_ms=33.3)
        assert metrics.peak == pytest.approx(-18.0)

    def test_nan_samples_are_skipped(self) -> None:
        curve = np.array([np.nan, -4.0, np.nan, -14.0, np.nan], dtype=np.float64)
        metrics = compute_strain_metrics(curve, ed_index=0, avc_index=3, frame_time_ms=33.3)
        assert metrics.peak == pytest.approx(-14.0)
        assert metrics.ess == pytest.approx(-14.0)

    def test_empty_curve_is_reported_not_guessed(self) -> None:
        metrics = compute_strain_metrics(np.array([np.nan, np.nan]), ed_index=0, avc_index=1)
        assert not np.isfinite(metrics.peak)
        assert metrics.notes

    def test_avc_equal_ed_is_flagged(self) -> None:
        metrics = compute_strain_metrics(_systolic_curve(), ed_index=2, avc_index=2, frame_time_ms=33.3)
        assert any("AVC equals ED" in note for note in metrics.notes)


class TestAvcDetection:
    def test_manual_wins(self) -> None:
        frame, source, confidence = detect_avc_frame(
            ed_frame=0, es_frame=12, manual_avc=9, ecg_avc_frame=10, strain_curve=_systolic_curve()
        )
        assert (frame, source) == (9, AVC_SOURCE_MANUAL)
        assert confidence == pytest.approx(1.0)

    def test_ecg_wins_over_the_area_curve(self) -> None:
        frame, source, _ = detect_avc_frame(
            ed_frame=0,
            es_frame=12,
            ecg_avc_frame=11,
            area_curve=((0, 100.0), (5, 70.0), (12, 60.0)),
        )
        assert (frame, source) == (11, AVC_SOURCE_ECG)

    def test_area_curve_nadir_is_used_when_no_ecg(self) -> None:
        frame, source, _ = detect_avc_frame(
            ed_frame=0,
            es_frame=12,
            area_curve=((0, 100.0), (4, 90.0), (9, 61.0), (15, 98.0)),
        )
        assert (frame, source) == (9, AVC_SOURCE_AREA)

    def test_strain_peak_is_the_last_resort_before_es(self) -> None:
        frame, source, _ = detect_avc_frame(ed_frame=0, es_frame=12, strain_curve=_post_systolic_curve())
        assert (frame, source) == (6, AVC_SOURCE_STRAIN_PEAK)

    def test_image_es_is_the_fallback_and_is_labelled_as_such(self) -> None:
        frame, source, confidence = detect_avc_frame(ed_frame=0, es_frame=12)
        assert (frame, source) == (12, AVC_SOURCE_ES)
        assert confidence < 0.5


class TestCycleLength:
    def test_uses_the_measured_rr_interval(self) -> None:
        assert estimate_cycle_length_frames(4, 12, 40, rr_frames=30.0) == 30

    def test_falls_back_to_heart_rate(self) -> None:
        # 60 bpm at 40 ms per frame → 25 frames per cycle
        assert estimate_cycle_length_frames(0, 10, 40, heart_rate_bpm=60.0, frame_time_ms=40.0) == 25

    def test_falls_back_to_a_normal_systole_ratio(self) -> None:
        assert estimate_cycle_length_frames(0, 7, 40) == 20  # 7 / 0.35

    def test_never_shorter_than_systole_and_never_longer_than_the_clip(self) -> None:
        assert estimate_cycle_length_frames(0, 8, 40, rr_frames=3.0) == 9
        assert estimate_cycle_length_frames(30, 35, 40, rr_frames=100.0) == 10


class TestSegmentMetrics:
    def test_time_to_peak_map_covers_every_segment(self) -> None:
        curves = {
            3: np.array([0.0, -8.0, -16.0, -10.0, -2.0]),
            9: np.array([0.0, -14.0, -10.0, -5.0, -1.0]),
        }
        ttp = time_to_peak_map(curves, ed_index=0, avc_index=2, frame_time_ms=30.0)
        assert ttp[3] == pytest.approx(60.0)
        assert ttp[9] == pytest.approx(30.0)

    def test_segment_metrics_expose_ess_per_segment(self) -> None:
        curves = {3: np.array([0.0, -18.0, -20.0]), 9: np.array([0.0, -12.0, -16.0])}
        metrics = metrics_by_segment(curves, ed_index=0, avc_index=1, frame_time_ms=30.0)
        assert metrics[3].ess == pytest.approx(-18.0)
        assert metrics[9].peak == pytest.approx(-16.0)

    def test_missing_segment_is_not_invented(self) -> None:
        curves = {3: np.array([np.nan, np.nan]), 9: np.array([0.0, -12.0])}
        ttp = time_to_peak_map(curves, ed_index=0, avc_index=1, frame_time_ms=30.0)
        assert 3 not in ttp
        assert 9 in ttp
