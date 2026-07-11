"""Doppler spectrogram axis mapping (plot coords ↔ physical units)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


@dataclass(frozen=True)
class DopplerAxisMapping:
    """Linear map from plot coordinates to time (ms) and velocity (cm/s)."""

    time_origin_ms: float = 0.0
    time_span_ms: float = 1000.0
    velocity_min_cm_s: float = -100.0
    velocity_max_cm_s: float = 100.0
    plot_width: float = 1000.0
    plot_height: float = 200.0
    plot_origin_x: float = 0.0
    plot_origin_y: float = 0.0
    velocity_span_cm_s: float = 200.0
    roi: DopplerSpectrogramRoi | None = None
    baseline_y_px: float | None = None

    @classmethod
    def poc_default(cls) -> DopplerAxisMapping:
        return cls()

    @classmethod
    def from_frame_size(
        cls,
        width: float,
        height: float,
        *,
        velocity_span_cm_s: float = 200.0,
        time_span_ms: float = 1000.0,
    ) -> DopplerAxisMapping:
        """Uncalibrated mapping over the full frame (identity pixel grid)."""
        half = velocity_span_cm_s / 2.0
        return cls(
            time_span_ms=time_span_ms,
            velocity_span_cm_s=velocity_span_cm_s,
            velocity_min_cm_s=-half,
            velocity_max_cm_s=half,
            plot_width=max(1.0, float(width)),
            plot_height=max(1.0, float(height)),
        )

    @property
    def has_roi_calibration(self) -> bool:
        return (
            self.roi is not None
            and self.plot_width > 0.0
            and self.plot_height > 0.0
            and self.baseline_y_px is not None
        )

    def baseline_plot_y(self) -> float | None:
        return self.baseline_y_px

    def time_ms_from_x(self, x: float) -> float:
        if self.plot_width <= 0.0:
            return self.time_origin_ms
        local_x = x - self.plot_origin_x
        return self.time_origin_ms + (local_x / self.plot_width) * self.time_span_ms

    def x_from_time_ms(self, time_ms: float) -> float:
        if self.plot_width <= 0.0 or self.time_span_ms <= 0.0:
            return self.plot_origin_x
        fraction = (time_ms - self.time_origin_ms) / self.time_span_ms
        return self.plot_origin_x + fraction * self.plot_width

    def velocity_cm_s_from_y(self, y: float) -> float:
        if self.plot_height <= 0.0:
            return 0.0
        if self.baseline_y_px is not None and self.velocity_span_cm_s > 0.0:
            pixels_per_cm_s = self.plot_height / self.velocity_span_cm_s
            return -(y - self.baseline_y_px) / pixels_per_cm_s
        # Fallback: zero at ROI center
        local_y = y - self.plot_origin_y
        span = self.velocity_max_cm_s - self.velocity_min_cm_s
        return self.velocity_max_cm_s - (local_y / self.plot_height) * span

    def y_from_velocity_cm_s(self, velocity_cm_s: float) -> float:
        if self.plot_height <= 0.0:
            return self.plot_origin_y
        if self.baseline_y_px is not None and self.velocity_span_cm_s > 0.0:
            pixels_per_cm_s = self.plot_height / self.velocity_span_cm_s
            return self.baseline_y_px - velocity_cm_s * pixels_per_cm_s
        # Fallback: zero at ROI center
        span = self.velocity_max_cm_s - self.velocity_min_cm_s
        if span <= 0.0:
            return self.plot_origin_y + self.plot_height * 0.5
        fraction = (self.velocity_max_cm_s - velocity_cm_s) / span
        return self.plot_origin_y + fraction * self.plot_height
