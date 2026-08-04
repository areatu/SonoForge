"""Unit tests for domain/services/cardiac_cycle_service.py."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform
from echo_personal_tool.domain.services.cardiac_cycle_service import (
    CardiacCycle,
    CardiacCycleService,
    align_spectrogram_to_ecg,
    derive_psv_edv_indices_with_cycles,
)


def _synthetic_ecg(
    r_peak_abs_ms: tuple[float, ...] = (500.0, 1500.0, 2500.0, 3500.0),
    fs: float = 250.0,
    duration_ms: float = 4000.0,
) -> EcgWaveform:
    n = int(duration_ms * fs / 1000.0)
    signal = np.zeros(n)
    for t in r_peak_abs_ms:
        idx = int(t * fs / 1000.0)
        if idx < n:
            signal[idx] = 10.0
    lead = EcgLead(name="II", samples=signal, sampling_frequency=fs, baseline=0, bits_stored=0)
    return EcgWaveform(leads=[lead], waveform_frequency=fs, number_of_waveform_channels=1)


def _synthetic_profile(
    local_ms: tuple[float, ...] = (500.0, 1500.0),
    span_ms: float = 2000.0,
    n: int = 400,
) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, span_ms, n)
    profile = np.zeros(n)
    for center in local_ms:
        profile += np.exp(-0.5 * ((t - center) / 60.0) ** 2)
    return t, profile


class TestAlignSpectrogramToEcg:
    def test_recovers_true_offset(self) -> None:
        ecg = _synthetic_ecg()
        t, profile = _synthetic_profile()
        align = align_spectrogram_to_ecg(ecg, t, profile, max_shift_ms=1500.0)
        assert align is not None
        # offset is congruent to 1000 ms modulo the 1000 ms RR interval
        assert min(abs(align.offset_ms - off) for off in (-1000.0, 0.0, 1000.0, 2000.0)) < 50.0
        assert align.source == "ecg"

    def test_returns_none_without_r_peaks(self) -> None:
        ecg = _synthetic_ecg(r_peak_abs_ms=())
        t, profile = _synthetic_profile()
        assert align_spectrogram_to_ecg(ecg, t, profile) is None

    def test_returns_none_for_flat_profile(self) -> None:
        ecg = _synthetic_ecg()
        t = np.linspace(0.0, 2000.0, 400)
        flat = np.full(400, 0.5)
        align = align_spectrogram_to_ecg(ecg, t, flat, max_shift_ms=1500.0)
        assert align is None or align.confidence < 0.4

    def test_mismatched_sizes_returns_none(self) -> None:
        ecg = _synthetic_ecg()
        t = np.linspace(0.0, 2000.0, 400)
        profile = np.ones(200)
        assert align_spectrogram_to_ecg(ecg, t, profile) is None


class TestGetCycles:
    def test_returns_cycles_in_local_ms(self) -> None:
        ecg = _synthetic_ecg()
        t, profile = _synthetic_profile()
        cycles = CardiacCycleService().get_cycles(
            ecg=ecg,
            spectrogram_time_axis_ms=t,
            fallback_signal=profile,
        )
        assert len(cycles) >= 1
        starts = [c.start_ms for c in cycles]
        assert min(abs(s - 500.0) for s in starts) < 50.0 or min(abs(s - 1500.0) for s in starts) < 50.0
        cycle = cycles[0]
        assert cycle.source == "ecg"
        assert cycle.rr_ms == pytest.approx(1000.0, abs=50.0)
        assert cycle.confidence > 0.4

    def test_cycle_span_and_phases(self) -> None:
        ecg = _synthetic_ecg()
        t, profile = _synthetic_profile()
        cycles = CardiacCycleService().get_cycles(
            ecg=ecg,
            spectrogram_time_axis_ms=t,
            fallback_signal=profile,
        )
        cycle = cycles[0]
        assert cycle.end_ms > cycle.start_ms
        assert cycle.r_peak_ms == pytest.approx(cycle.start_ms, abs=1.0)
        assert cycle.es_ms > cycle.ed_ms
        assert cycle.es_ms - cycle.ed_ms == pytest.approx(0.35 * cycle.rr_ms, rel=0.05)

    def test_cycles_clipped_to_spectrogram_window(self) -> None:
        ecg = _synthetic_ecg()
        t, profile = _synthetic_profile(span_ms=1000.0, n=200)
        cycles = CardiacCycleService().get_cycles(
            ecg=ecg,
            spectrogram_time_axis_ms=t,
            fallback_signal=profile,
        )
        assert cycles
        for cycle in cycles:
            assert cycle.start_ms >= 0.0
            assert cycle.end_ms <= 1000.0

    def test_returns_empty_without_ecg(self) -> None:
        t, profile = _synthetic_profile()
        assert (
            CardiacCycleService().get_cycles(
                ecg=None,
                spectrogram_time_axis_ms=t,
                fallback_signal=profile,
            )
            == []
        )

    def test_returns_empty_without_signal(self) -> None:
        ecg = _synthetic_ecg()
        assert (
            CardiacCycleService().get_cycles(
                ecg=ecg,
                spectrogram_time_axis_ms=None,
                fallback_signal=None,
            )
            == []
        )

    def test_returns_empty_for_flat_profile(self) -> None:
        ecg = _synthetic_ecg()
        t = np.linspace(0.0, 2000.0, 400)
        flat = np.full(400, 0.5)
        assert (
            CardiacCycleService().get_cycles(
                ecg=ecg,
                spectrogram_time_axis_ms=t,
                fallback_signal=flat,
            )
            == []
        )


def _cycle(start_ms: float, end_ms: float) -> CardiacCycle:
    return CardiacCycle(
        start_ms=start_ms,
        end_ms=end_ms,
        r_peak_ms=start_ms,
        ed_ms=start_ms,
        es_ms=end_ms,
        source="ecg",
        confidence=0.9,
    )


def _time_mapping(span_ms: float) -> DopplerAxisMapping:
    return DopplerAxisMapping(plot_width=1000.0, time_span_ms=span_ms)


class TestDerivePsvEdvIndicesWithCycles:
    def test_snaps_edv_to_selected_cycle_diastole(self) -> None:
        mapping = _time_mapping(4000.0)
        times = [
            0.0, 200.0, 400.0, 600.0, 800.0, 1000.0, 1200.0, 1400.0, 1600.0, 1800.0,
            2000.0, 2200.0, 2400.0, 2600.0, 2800.0, 3000.0, 3200.0, 3400.0, 3600.0, 3800.0,
        ]
        ys = [
            70.0, 60.0, 45.0, 30.0, 18.0, 8.0, 30.0, 55.0, 68.0, 62.0,
            50.0, 40.0, 55.0, 70.0, 80.0, 85.0, 90.0, 92.0, 95.0, 88.0,
        ]
        envelope = tuple((t / 4.0, y) for t, y in zip(times, ys))
        cycles = (_cycle(200.0, 1800.0), _cycle(2000.0, 3800.0))
        psv_idx, edv_idx = derive_psv_edv_indices_with_cycles(envelope, cycles, mapping)
        # PSV at time 1000 (y=8); EDV in last 25% of the SAME cycle (y=68 at t=1600),
        # not the global end-of-envelope minimum velocity (y=95 at t=3600).
        assert psv_idx == 5
        assert edv_idx == 8

    def test_returns_none_without_cycles(self) -> None:
        mapping = _time_mapping(4000.0)
        envelope = tuple((i * 100.0, float(i)) for i in range(10))
        assert derive_psv_edv_indices_with_cycles(envelope, (), mapping) is None

    def test_returns_none_when_psv_outside_all_cycles(self) -> None:
        mapping = _time_mapping(4000.0)
        envelope = tuple((i * 100.0, float(i)) for i in range(10))
        cycles = (_cycle(2000.0, 3000.0),)
        assert derive_psv_edv_indices_with_cycles(envelope, cycles, mapping) is None

    def test_empty_envelope_returns_none(self) -> None:
        mapping = _time_mapping(4000.0)
        assert derive_psv_edv_indices_with_cycles((), (_cycle(0.0, 4000.0),), mapping) is None

    def test_sparse_cycle_returns_none(self) -> None:
        mapping = _time_mapping(4000.0)
        # Only two points inside the cycle -> too sparse to derive PSV/EDV.
        envelope = tuple((i * 100.0, float(i)) for i in range(10))
        cycles = (_cycle(1500.0, 1700.0),)
        assert derive_psv_edv_indices_with_cycles(envelope, cycles, mapping) is None
