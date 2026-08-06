"""Unit tests for ECG ED/ES frame mapper."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform, RPeakResult
from echo_personal_tool.domain.services.ecg_ed_es_mapper import (
    detect_ed_es_for_cine,
    map_rpeaks_to_frames,
)


def _impulse_ecg(
    r_peak_times_ms: tuple[float, ...] = (500.0, 1500.0, 2500.0),
    fs: float = 250.0,
    duration_ms: float = 4000.0,
) -> EcgWaveform:
    n = int(duration_ms * fs / 1000.0)
    signal = np.zeros(n)
    for t in r_peak_times_ms:
        idx = int(t * fs / 1000.0)
        if idx < n:
            signal[idx] = 10.0
    lead = EcgLead(name="II", samples=signal, sampling_frequency=fs, baseline=0, bits_stored=0)
    return EcgWaveform(leads=[lead], waveform_frequency=fs, number_of_waveform_channels=1)


class TestMapRpeaksToFrames:
    def test_none_rpeaks(self) -> None:
        result = map_rpeaks_to_frames(None, 33.3, 30)
        assert result.source == "image_fallback"
        assert result.ed_frame_index == 0
        assert result.es_frame_index == 10

    def test_empty_rpeaks(self) -> None:
        rpeaks = RPeakResult(
            r_peak_indices=np.array([], dtype=np.int64),
            r_peak_times_ms=np.array([], dtype=np.float64),
            heart_rate_bpm=0.0,
            rr_intervals_ms=np.array([], dtype=np.float64),
            confidence=0.0,
        )
        result = map_rpeaks_to_frames(rpeaks, 33.3, 30)
        assert result.source == "image_fallback"

    def test_low_confidence_fallback(self) -> None:
        rpeaks = RPeakResult(
            r_peak_indices=np.array([100, 500]),
            r_peak_times_ms=np.array([200.0, 1000.0]),
            heart_rate_bpm=75.0,
            rr_intervals_ms=np.array([800.0]),
            confidence=0.2,  # below threshold
        )
        result = map_rpeaks_to_frames(rpeaks, 33.3, 30)
        assert result.source == "image_fallback"

    def test_normal_ecg(self) -> None:
        # 72 BPM = 60/72 = 0.833s per cycle = 833ms
        rpeaks = RPeakResult(
            r_peak_indices=np.array([0, 417, 833]),
            r_peak_times_ms=np.array([0.0, 833.0, 1666.0]),
            heart_rate_bpm=72.0,
            rr_intervals_ms=np.array([833.0, 833.0]),
            confidence=0.9,
        )
        frame_time_ms = 33.3  # 30 fps
        n_frames = 60
        result = map_rpeaks_to_frames(rpeaks, frame_time_ms, n_frames)
        assert result.source == "ecg"
        assert result.ed_frame_index == 0  # frame closest to first R-peak
        # ES should be ~35% of cycle after ED
        # cycle = 833ms / 33.3ms ≈ 25 frames, 35% ≈ 9 frames
        assert result.es_frame_index > result.ed_frame_index
        assert result.es_frame_index < n_frames

    def test_single_rpeak(self) -> None:
        rpeaks = RPeakResult(
            r_peak_indices=np.array([100]),
            r_peak_times_ms=np.array([200.0]),
            heart_rate_bpm=60.0,
            rr_intervals_ms=np.array([], dtype=np.float64),
            confidence=0.5,
        )
        result = map_rpeaks_to_frames(rpeaks, 33.3, 30)
        assert result.source == "ecg"
        assert result.ed_frame_index == 6  # 200ms / 33.3ms ≈ 6
        assert result.es_frame_index > result.ed_frame_index

    def test_ed_equals_es_fallback(self) -> None:
        # Force ED == ES case
        rpeaks = RPeakResult(
            r_peak_indices=np.array([0]),
            r_peak_times_ms=np.array([0.0]),
            heart_rate_bpm=60.0,
            rr_intervals_ms=np.array([], dtype=np.float64),
            confidence=0.5,
        )
        result = map_rpeaks_to_frames(rpeaks, 33.3, 30)
        assert result.ed_frame_index != result.es_frame_index

    def test_cycle_boundaries(self) -> None:
        rpeaks = RPeakResult(
            r_peak_indices=np.array([0, 500]),
            r_peak_times_ms=np.array([0.0, 1000.0]),
            heart_rate_bpm=60.0,
            rr_intervals_ms=np.array([1000.0]),
            confidence=0.9,
        )
        result = map_rpeaks_to_frames(rpeaks, 33.3, 60)
        assert result.cycle_start_frame == result.ed_frame_index
        assert result.cycle_end_frame > result.cycle_start_frame


class TestDetectEdEsForCine:
    def test_no_ecg_uses_default(self) -> None:
        result = detect_ed_es_for_cine(None, 33.3, 30)
        assert result.source == "image"
        assert result.ed_frame_index == 0
        assert result.es_frame_index == 10

    def test_no_ecg_uses_image_fallback(self) -> None:
        result = detect_ed_es_for_cine(None, 33.3, 30, image_fallback=lambda: (5, 20))
        assert result.source == "image"
        assert result.ed_frame_index == 5
        assert result.es_frame_index == 20

    def test_ecg_high_confidence_used(self) -> None:
        ecg = _impulse_ecg()
        result = detect_ed_es_for_cine(ecg, 33.3, 60)
        assert result.source == "ecg"
        assert result.ed_frame_index == round(500.0 / 33.3)  # 15
        assert result.es_frame_index > result.ed_frame_index

    def test_ecg_low_confidence_falls_back_to_image(self) -> None:
        fake = RPeakResult(
            r_peak_indices=np.array([0, 500]),
            r_peak_times_ms=np.array([0.0, 1000.0]),
            heart_rate_bpm=60.0,
            rr_intervals_ms=np.array([1000.0]),
            confidence=0.1,
        )
        with patch(
            "echo_personal_tool.domain.services.ecg_ed_es_mapper.detect_r_peaks_from_waveform",
            return_value=fake,
        ):
            result = detect_ed_es_for_cine(
                _impulse_ecg(),
                33.3,
                30,
                image_fallback=lambda: (4, 18),
            )
        assert result.source == "image"
        assert result.ed_frame_index == 4
        assert result.es_frame_index == 18

    def test_ecg_unusable_falls_back_to_default(self) -> None:
        with patch(
            "echo_personal_tool.domain.services.ecg_ed_es_mapper.detect_r_peaks_from_waveform",
            return_value=None,
        ):
            result = detect_ed_es_for_cine(_impulse_ecg(), 33.3, 30)
        assert result.source == "image"
        assert result.ed_frame_index == 0
        assert result.es_frame_index == 10

    def test_precomputed_r_peak_result_used(self) -> None:
        rpeaks = RPeakResult(
            r_peak_indices=np.array([0, 500]),
            r_peak_times_ms=np.array([0.0, 1000.0]),
            heart_rate_bpm=60.0,
            rr_intervals_ms=np.array([1000.0]),
            confidence=0.9,
        )
        result = detect_ed_es_for_cine(None, 33.3, 30, r_peak_result=rpeaks)
        assert result.source == "ecg"

    def test_image_fallback_clipped(self) -> None:
        result = detect_ed_es_for_cine(None, 33.3, 30, image_fallback=lambda: (100, -5))
        assert result.ed_frame_index == 29
        assert result.es_frame_index == 0
