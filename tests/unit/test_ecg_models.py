"""Unit tests for ECG domain models."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from echo_personal_tool.domain.models.ecg import (
    EcEDFrameMapping,
    EcgLead,
    EcgWaveform,
    RPeakResult,
)


class TestEcgLead:
    def test_creation(self) -> None:
        lead = EcgLead(
            name="II",
            samples=np.array([100, 200, 300], dtype=np.int16),
            sampling_frequency=500.0,
            baseline=0,
            bits_stored=16,
        )
        assert lead.name == "II"
        assert len(lead.samples) == 3
        assert lead.sampling_frequency == 500.0

    def test_frozen(self) -> None:
        lead = EcgLead(
            name="II",
            samples=np.zeros(10),
            sampling_frequency=500.0,
            baseline=0,
            bits_stored=16,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            lead.name = "V1"  # type: ignore[misc]


class TestEcgWaveform:
    def test_primary_lead_ii(self) -> None:
        lead_i = EcgLead("I", np.zeros(10), 500.0, 0, 16)
        lead_ii = EcgLead("II", np.zeros(10), 500.0, 0, 16)
        wf = EcgWaveform(leads=[lead_i, lead_ii], waveform_frequency=500.0, number_of_waveform_channels=2)
        assert wf.primary_lead is lead_ii

    def test_primary_lead_first_if_no_ii(self) -> None:
        lead_v1 = EcgLead("V1", np.zeros(10), 500.0, 0, 16)
        wf = EcgWaveform(leads=[lead_v1], waveform_frequency=500.0, number_of_waveform_channels=1)
        assert wf.primary_lead is lead_v1

    def test_primary_lead_none_when_empty(self) -> None:
        wf = EcgWaveform(leads=[], waveform_frequency=500.0, number_of_waveform_channels=0)
        assert wf.primary_lead is None

    def test_as_voltage_mv(self) -> None:
        lead = EcgLead(
            "II", samples=np.array([0, 512, 1024], dtype=np.int16), sampling_frequency=500.0, baseline=0, bits_stored=16
        )
        wf = EcgWaveform(leads=[lead], waveform_frequency=500.0, number_of_waveform_channels=1)
        voltage = wf.as_voltage_mv(0)
        assert voltage.shape == (3,)
        # scale = 2.5 / 2^16 ≈ 0.0000381
        assert abs(voltage[1] - 512 * (2.5 / 65536)) < 1e-6

    def test_as_voltage_mv_empty_leads(self) -> None:
        wf = EcgWaveform(leads=[], waveform_frequency=500.0, number_of_waveform_channels=0)
        voltage = wf.as_voltage_mv(0)
        assert voltage.size == 0

    def test_as_voltage_mv_out_of_range(self) -> None:
        lead = EcgLead("II", np.zeros(5), 500.0, 0, 16)
        wf = EcgWaveform(leads=[lead], waveform_frequency=500.0, number_of_waveform_channels=1)
        voltage = wf.as_voltage_mv(5)  # out of range
        assert voltage.size == 0

    def test_duration_ms(self) -> None:
        lead = EcgLead("II", np.zeros(500), 500.0, 0, 16)
        wf = EcgWaveform(leads=[lead], waveform_frequency=500.0, number_of_waveform_channels=1)
        assert wf.duration_ms == 1000.0  # 500 samples / 500 Hz * 1000

    def test_duration_ms_empty(self) -> None:
        wf = EcgWaveform(leads=[], waveform_frequency=500.0, number_of_waveform_channels=0)
        assert wf.duration_ms == 0.0


class TestRPeakResult:
    def test_creation(self) -> None:
        result = RPeakResult(
            r_peak_indices=np.array([100, 300, 500]),
            r_peak_times_ms=np.array([200.0, 600.0, 1000.0]),
            heart_rate_bpm=75.0,
            rr_intervals_ms=np.array([400.0, 400.0]),
            confidence=0.95,
        )
        assert result.heart_rate_bpm == 75.0
        assert result.confidence == 0.95
        assert len(result.r_peak_indices) == 3


class TestEcEDFrameMapping:
    def test_creation(self) -> None:
        mapping = EcEDFrameMapping(
            ed_frame_index=5,
            es_frame_index=20,
            cycle_start_frame=5,
            cycle_end_frame=45,
        )
        assert mapping.ed_frame_index == 5
        assert mapping.es_frame_index == 20
        assert mapping.source == "ecg"

    def test_image_fallback(self) -> None:
        mapping = EcEDFrameMapping(
            ed_frame_index=0,
            es_frame_index=10,
            cycle_start_frame=0,
            cycle_end_frame=29,
            source="image_fallback",
        )
        assert mapping.source == "image_fallback"
