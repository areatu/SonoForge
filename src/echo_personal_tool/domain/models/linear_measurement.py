"""Domain helpers for linear caliper measurements."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin, sqrt


@dataclass(frozen=True)
class LinearMeasurement:
    """A single linear measurement in pixels and millimeters."""

    label: str
    pixel_length: float
    millimeter_length: float | None
    frame_index: int | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None

    def display_text(self) -> str:
        if self.millimeter_length is None:
            return f"{self.label}: {self.pixel_length:.1f} px"
        return f"{self.label}: {self.millimeter_length:.1f} mm"


def pixel_to_mm_length(
    pixel_length: float,
    angle_degrees: float,
    pixel_spacing: tuple[float, float],
) -> float:
    """Convert a pixel length along a line angle into millimeters."""

    row_spacing, column_spacing = pixel_spacing
    angle_radians = radians(angle_degrees)
    x_pixels = pixel_length * cos(angle_radians)
    y_pixels = pixel_length * sin(angle_radians)
    return sqrt((x_pixels * column_spacing) ** 2 + (y_pixels * row_spacing) ** 2)
