"""Domain helpers for linear caliper measurements."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin, sqrt

from echo_personal_tool.infrastructure.i18n import tr

_LABEL_I18N_KEY: dict[str, str] = {
    "IVSd": "result.ivsd",
    "IVSD": "result.ivsd",
    "LVEDD": "result.lvedd",
    "LVPWd": "result.lvpwd",
    "LVPWD": "result.lvpwd",
    "LVESD": "result.lvesd",
    "LA": "menu.la_lavir",
    "%D": "result.percent_d",
    "%S": "result.percent_s",
    "%D стеноз": "result.percent_d_stenosis",
    "%S стеноз": "result.percent_s_stenosis",
    "S1": "result.s1",
    "S2": "result.s2",
}

#: Labels whose ``millimeter_length`` holds a percentage, not a length.
#:
#: The comparison tools store a ratio under ``%D``/``%S``; the vessel stenosis
#: tools store a stenosis degree under ``%D стеноз``/``%S стеноз``. All four are
#: percentages and must never be formatted as a length.
PERCENT_LABELS = frozenset({"%D", "%S", "%D стеноз", "%S стеноз"})


@dataclass(frozen=True)
class LinearMeasurement:
    """A single linear measurement in pixels and millimeters.

    Inside a calibrated Doppler ROI the same caliper measures the spectral
    axes instead of a distance: ``doppler`` marks such a measurement,
    ``time_ms`` holds the interval between the caliper points (Δt) and
    ``velocity_cm_s`` the velocity amplitude at the end point (relative to
    the Doppler baseline when known).
    """

    label: str
    pixel_length: float
    millimeter_length: float | None
    frame_index: int | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    sop_instance_uid: str = ""
    time_ms: float | None = None
    velocity_cm_s: float | None = None
    doppler: bool = False

    def doppler_value_parts(self) -> list[str]:
        """Formatted Δt / velocity parts of a Doppler caliper (may be empty)."""
        parts: list[str] = []
        if self.time_ms is not None:
            parts.append(f"{self.time_ms:.1f} ms")
        if self.velocity_cm_s is not None:
            parts.append(format_velocity_cm_s(self.velocity_cm_s))
        return parts

    def display_text(self, *, length_unit: str = "mm") -> str:
        i18n_key = _LABEL_I18N_KEY.get(self.label)
        display_label = tr(i18n_key) if i18n_key else self.label
        if self.doppler:
            parts = self.doppler_value_parts()
            if parts:
                return f"{display_label}: {'  '.join(parts)}"
        if self.time_ms is not None:
            hr = 60000.0 / self.time_ms if self.time_ms > 0 else 0.0
            return f"{display_label}: {self.time_ms:.1f} ms  {tr('mmode.label_hr')} {hr:.0f}"
        if self.millimeter_length is None:
            return f"{display_label}: {self.pixel_length:.1f} px"
        if self.label in PERCENT_LABELS:
            return f"{display_label}: {self.millimeter_length:.1f}%"
        if self.label in ("S1", "S2"):
            return f"{display_label}: {self.millimeter_length:.2f} cm²"
        return f"{display_label}: {format_length_mm(self.millimeter_length, length_unit)}"


def format_length_mm(millimeters: float, unit: str) -> str:
    if unit == "cm":
        return f"{millimeters / 10.0:.2f} cm"
    return f"{millimeters:.1f} mm"


def format_velocity_cm_s(velocity_cm_s: float) -> str:
    """Format a Doppler velocity, switching to m/s for high velocities.

    Scanners report low spectral velocities in cm/s and high jets in m/s;
    100 cm/s is the conventional switch-over point.
    """
    if abs(velocity_cm_s) >= 100.0:
        return f"{velocity_cm_s / 100.0:.2f} m/s"
    return f"{velocity_cm_s:.1f} cm/s"


def inline_caliper_text(measurement: LinearMeasurement, *, length_unit: str = "mm") -> str:
    if measurement.doppler:
        parts = measurement.doppler_value_parts()
        if parts:
            return f"{measurement.label} {' '.join(parts)}"
    if measurement.millimeter_length is None:
        return f"{measurement.label} {measurement.pixel_length:.1f} px"
    return f"{measurement.label} {format_length_mm(measurement.millimeter_length, length_unit)}"


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
