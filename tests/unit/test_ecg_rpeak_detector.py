"""Unit tests for ECG R-peak detector."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform
from echo_personal_tool.domain.services.ecg_rpeak_detector import (
    _adaptive_threshold_detect,
    _bandpass_filter,
    _moving_average,
    detect_r_peaks,
    detect_r_peaks_from_waveform,
    primary_ecg_signal,
)


class TestBandpassFilter:
    def test_filters_signal(self) -> None:
        fs = 500.0
        t = np.arange(0, 1.0, 1.0 / fs)
        # 10 Hz signal (within passband)
        signal = np.sin(2 * np.pi * 10.0 * t)
        result = _bandpass_filter(signal, fs, low=5.0, high=15.0)
        assert result.shape == signal.shape

    def test_removes_low_frequency(self) -> None:
        fs = 500.0
        t = np.arange(0, 1.0, 1.0 / fs)
        # 1 Hz signal (below passband)
        signal = np.sin(2 * np.pi * 1.0 * t)
        result = _bandpass_filter(signal, fs, low=5.0, high=15.0)
        # Power should be reduced
        power_in = np.sum(signal**2)
        power_out = np.sum(result**2)
        assert power_out < power_in

    def test_passthrough_on_error(self) -> None:
        signal = np.array([1.0, 2.0, 3.0])
        result = _bandpass_filter(signal, 100.0, low=50.0, high=10.0)  # invalid
        np.testing.assert_array_equal(result, signal)


class TestMovingAverage:
    def test_identity(self) -> None:
        signal = np.array([1.0, 2.0, 3.0])
        result = _moving_average(signal, 1)
        np.testing.assert_array_equal(result, signal)

    def test_smoothing(self) -> None:
        signal = np.array([0.0, 0.0, 10.0, 0.0, 0.0])
        result = _moving_average(signal, 3)
        assert result[2] < 10.0  # smoothed peak is lower


class TestAdaptiveThresholdDetect:
    def test_empty_signal(self) -> None:
        result = _adaptive_threshold_detect(np.array([]), 10)
        assert len(result) == 0

    def test_single_peak(self) -> None:
        signal = np.array([0.0, 0.0, 10.0, 0.0, 0.0])
        result = _adaptive_threshold_detect(signal, 1)
        assert len(result) >= 1

    def test_refractory_period(self) -> None:
        # Two peaks very close together
        signal = np.zeros(50)
        signal[10] = 10.0
        signal[12] = 10.0  # only 2 samples apart
        result = _adaptive_threshold_detect(signal, min_rr_samples=5)
        # Should keep only the stronger (or first) peak
        assert len(result) <= 2


class TestDetectRPeaks:
    def test_empty_signal(self) -> None:
        result = detect_r_peaks(np.array([]), 500.0)
        assert result.confidence == 0.0
        assert len(result.r_peak_indices) == 0

    def test_short_signal(self) -> None:
        result = detect_r_peaks(np.array([1.0, 2.0]), 500.0)
        assert result.confidence == 0.0

    def test_synthetic_ecg(self) -> None:
        # Create synthetic ECG with R-peaks at 72 BPM (1.2 Hz)
        fs = 500.0
        duration = 5.0
        t = np.arange(0, duration, 1.0 / fs)
        # Simulate R-peaks as narrow pulses
        signal = np.zeros_like(t)
        r_peak_times = np.arange(0, duration, 60.0 / 72.0)  # 72 BPM
        for r_time in r_peak_times:
            idx = int(r_time * fs)
            if idx < len(signal):
                signal[idx] = 1.0

        result = detect_r_peaks(signal, fs)
        assert len(result.r_peak_indices) > 0
        assert result.heart_rate_bpm > 0
        assert result.confidence > 0

    def test_high_confidence_for_regular(self) -> None:
        # Very regular signal
        fs = 500.0
        signal = np.zeros(2500)
        for i in range(0, 2500, 500):  # every 500 samples = 60 BPM
            signal[i] = 10.0
        result = detect_r_peaks(signal, fs)
        assert result.confidence > 0.5


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


class TestPrimaryEcgSignal:
    def test_returns_primary_lead_voltage(self) -> None:
        lead0 = EcgLead(name="I", samples=np.zeros(1000), sampling_frequency=250.0, baseline=0, bits_stored=0)
        lead1 = EcgLead(name="II", samples=np.zeros(1000), sampling_frequency=250.0, baseline=0, bits_stored=0)
        ecg = EcgWaveform(leads=[lead0, lead1], waveform_frequency=250.0, number_of_waveform_channels=2)
        signal = primary_ecg_signal(ecg)
        assert signal is not None
        voltage, fs = signal
        assert fs == 250.0
        assert voltage.ndim == 1
        assert voltage.size == 1000

    def test_prefers_lead_ii_over_first_lead(self) -> None:
        lead0 = EcgLead(name="I", samples=np.ones(1000), sampling_frequency=250.0, baseline=0, bits_stored=0)
        lead1 = EcgLead(name="II", samples=np.zeros(1000), sampling_frequency=250.0, baseline=0, bits_stored=0)
        ecg = EcgWaveform(leads=[lead0, lead1], waveform_frequency=250.0, number_of_waveform_channels=2)
        signal = primary_ecg_signal(ecg)
        assert signal is not None
        voltage, _fs = signal
        assert voltage[0] == 0.0  # Lead II chosen, not lead I

    def test_empty_leads_none(self) -> None:
        ecg = EcgWaveform(leads=[], waveform_frequency=250.0, number_of_waveform_channels=0)
        assert primary_ecg_signal(ecg) is None

    def test_zero_sampling_frequency_none(self) -> None:
        lead = EcgLead(name="II", samples=np.zeros(1000), sampling_frequency=0.0, baseline=0, bits_stored=0)
        ecg = EcgWaveform(leads=[lead], waveform_frequency=0.0, number_of_waveform_channels=1)
        assert primary_ecg_signal(ecg) is None


class TestDetectRPeaksFromWaveform:
    def test_detects_r_peaks_from_waveform(self) -> None:
        result = detect_r_peaks_from_waveform(_impulse_ecg())
        assert result is not None
        assert len(result.r_peak_indices) >= 2

    def test_unusable_waveform_none(self) -> None:
        ecg = EcgWaveform(leads=[], waveform_frequency=250.0, number_of_waveform_channels=0)
        assert detect_r_peaks_from_waveform(ecg) is None
