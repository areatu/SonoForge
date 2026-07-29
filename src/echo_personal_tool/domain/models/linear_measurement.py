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
}


@dataclass(frozen=True)
class LinearMeasurement:
    """A single linear measurement in pixels and millimeters."""

    label: str
    pixel_length: float
    millimeter_length: float | None
    frame_index: int | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    sop_instance_uid: str = ""

    def display_text(self, *, length_unit: str = "mm") -> str:
        i18n_key = _LABEL_I18N_KEY.get(self.label)
        display_label = tr(i18n_key) if i18n_key else self.label
        if self.millimeter_length is None:
            return f"{display_label}: {self.pixel_length:.1f} px"
        if self.label == "%D":
            return f"{display_label}: {self.millimeter_length:.1f}%"
        return f"{display_label}: {format_length_mm(self.millimeter_length, length_unit)}"


def format_length_mm(millimeters: float, unit: str) -> str:
    if unit == "cm":
        return f"{millimeters / 10.0:.2f} cm"
    return f"{millimeters:.1f} mm"


def inline_caliper_text(measurement: LinearMeasurement, *, length_unit: str = "mm") -> str:
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
