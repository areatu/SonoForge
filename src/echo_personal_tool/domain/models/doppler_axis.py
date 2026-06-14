"""Doppler spectrogram axis mapping (plot coords ↔ physical units)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DopplerAxisMapping:
    """Linear map from plot coordinates to time (ms) and velocity (cm/s)."""

    time_origin_ms: float = 0.0
    time_span_ms: float = 1000.0
    velocity_min_cm_s: float = -100.0
    velocity_max_cm_s: float = 100.0
    plot_width: float = 1000.0
    plot_height: float = 200.0

    @classmethod
    def poc_default(cls) -> DopplerAxisMapping:
        return cls()

    def time_ms_from_x(self, x: float) -> float:
        if self.plot_width <= 0.0:
            return x
        return self.time_origin_ms + (x / self.plot_width) * self.time_span_ms

    def velocity_cm_s_from_y(self, y: float) -> float:
        if self.plot_height <= 0.0:
            return y
        span = self.velocity_max_cm_s - self.velocity_min_cm_s
        return self.velocity_max_cm_s - (y / self.plot_height) * span
