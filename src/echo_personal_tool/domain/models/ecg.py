"""Domain models for ECG waveform data and R-peak detection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EcgLead:
    """Single ECG lead extracted from DICOM."""

    name: str
    samples: np.ndarray
    sampling_frequency: float
    baseline: int
    bits_stored: int


@dataclass(frozen=True)
class EcgWaveform:
    """Complete ECG waveform record from a DICOM file."""

    leads: list[EcgLead]
    waveform_frequency: float
    number_of_waveform_channels: int
    acquisition_number: int | None = None
    raw_time_offset_ms: float = 0.0

    @property
    def primary_lead(self) -> EcgLead | None:
        """Return Lead II or first lead (standard for R-peak detection)."""
        for lead in self.leads:
            if lead.name in ("II", "MLII", "II ", "II\0"):
                return lead
        return self.leads[0] if self.leads else None

    def as_voltage_mv(self, lead_index: int = 0) -> np.ndarray:
        """Convert digital samples to millivolts for the given lead.

        Uses the standard DICOM waveform scaling:
        voltage_mv = (sample - baseline) * (nominal_range / (2 ** bits_stored))
        where nominal_range is approximated as 2.5 mV for standard ECG.
        """
        if lead_index >= len(self.leads):
            return np.array([], dtype=np.float64)
        lead = self.leads[lead_index]
        if lead.bits_stored <= 0:
            return lead.samples.astype(np.float64)
        scale = 2.5 / (2**lead.bits_stored)
        return (lead.samples.astype(np.float64) - lead.baseline) * scale

    @property
    def duration_ms(self) -> float:
        """Total duration of the waveform in milliseconds."""
        if not self.leads:
            return 0.0
        lead = self.leads[0]
        n_samples = len(lead.samples)
        if lead.sampling_frequency <= 0:
            return 0.0
        return (n_samples / lead.sampling_frequency) * 1000.0


@dataclass(frozen=True)
class RPeakResult:
    """Detected R-peak positions and derived timing."""

    r_peak_indices: np.ndarray
    r_peak_times_ms: np.ndarray
    heart_rate_bpm: float
    rr_intervals_ms: np.ndarray
    confidence: float


@dataclass(frozen=True)
class EcEDFrameMapping:
    """Maps R-peaks to ED/ES frame indices in a CINE sequence."""

    ed_frame_index: int
    es_frame_index: int
    cycle_start_frame: int
    cycle_end_frame: int
    source: str = "ecg"
