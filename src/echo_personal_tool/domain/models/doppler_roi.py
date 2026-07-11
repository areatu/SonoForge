"""Doppler spectrogram region and calibration state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DopplerKind(str, Enum):
    SPECTRAL = "spectral"
    TISSUE = "tissue"

    @property
    def default_velocity_span_cm_s(self) -> float:
        return 200.0 if self is DopplerKind.SPECTRAL else 40.0


@dataclass(frozen=True)
class DopplerSpectrogramRoi:
    """Spectrogram panel in plot pixel coordinates."""

    x0: float
    y0: float
    width: float
    height: float

    @property
    def x1(self) -> float:
        return self.x0 + self.width

    @property
    def y1(self) -> float:
        return self.y0 + self.height

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def normalized(self, frame_width: float, frame_height: float) -> DopplerSpectrogramRoi:
        if frame_width <= 0.0 or frame_height <= 0.0:
            return self
        return DopplerSpectrogramRoi(
            x0=max(0.0, min(self.x0, frame_width)),
            y0=max(0.0, min(self.y0, frame_height)),
            width=max(1.0, min(self.width, frame_width - self.x0)),
            height=max(1.0, min(self.height, frame_height - self.y0)),
        )


@dataclass(frozen=True)
class DopplerCalibrationState:
    """Per-instance Doppler axis calibration."""

    roi: DopplerSpectrogramRoi
    baseline_y_px: float
    time_origin_ms: float = 0.0
    time_span_ms: float = 1000.0
    velocity_span_cm_s: float = 200.0
    kind: DopplerKind = DopplerKind.SPECTRAL
    from_dicom_tags: bool = False
    velocity_from_dicom_tags: bool = False

    def is_complete(self) -> bool:
        return self.has_velocity_scale() and self.time_span_ms > 0.0

    def has_velocity_scale(self) -> bool:
        return (
            self.roi.width > 0.0
            and self.roi.height > 0.0
            and self.velocity_span_cm_s > 0.0
        )

    def has_time_scale_from_dicom(self) -> bool:
        return (
            self.from_dicom_tags
            and self.roi.width > 0.0
            and self.time_span_ms > 0.0
        )

    def has_velocity_scale_from_dicom(self) -> bool:
        return (
            self.velocity_from_dicom_tags
            and self.roi.height > 0.0
            and self.velocity_span_cm_s > 0.0
        )

    def is_dicom_trusted(self) -> bool:
        return self.from_dicom_tags and self.is_complete()
