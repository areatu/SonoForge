"""Pure domain snapshot of viewer playback state."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.metadata import InstanceMetadata


@dataclass(frozen=True)
class ViewerState:
    instance: InstanceMetadata | None
    current_frame_index: int
    total_frames: int
    frame_time_ms: float | None
    is_playing: bool
    doppler_measurement: DopplerMeasurementDTO | None = None
    contours: tuple[Contour, ...] = ()
    linear_measurements: tuple[LinearMeasurement, ...] = ()
    measurement_snapshot: MeasurementSnapshot | None = None
    decode_in_progress: bool = False
    manual_pixel_spacing: tuple[float, float] | None = None

    @property
    def effective_pixel_spacing(self) -> tuple[float, float] | None:
        if self.manual_pixel_spacing is not None:
            return self.manual_pixel_spacing
        if self.instance is None:
            return None
        return self.instance.pixel_spacing

    @property
    def pixel_spacing_source_label(self) -> str | None:
        if self.manual_pixel_spacing is not None:
            return "manual"
        if self.instance is None:
            return None
        return self.instance.pixel_spacing_source

    @property
    def fps(self) -> float:
        if self.frame_time_ms is None or self.frame_time_ms <= 0:
            return 0.0
        return 1000.0 / self.frame_time_ms
