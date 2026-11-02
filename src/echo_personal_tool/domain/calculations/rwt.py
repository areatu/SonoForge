"""Relative wall thickness (RWT / ОТС) from linear calipers."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def relative_wall_thickness(lvpwd_mm: float, lvedd_mm: float) -> float | None:
    """ASE: RWT = (2 × LVPWd) / LVEDD (dimensionless)."""
    if lvedd_mm <= 0.0:
        return None
    return (2.0 * lvpwd_mm) / lvedd_mm


def from_linear_measurements(
    measurements: tuple[LinearMeasurement, ...],
) -> float | None:
    lvpwd_mm: float | None = None
    lvedd_mm: float | None = None
    for measurement in measurements:
        label = measurement.label.upper()
        length = measurement.millimeter_length
        if length is None:
            continue
        if label == "LVPWD":
            lvpwd_mm = length
        elif label == "LVEDD":
            lvedd_mm = length
    if lvpwd_mm is None or lvedd_mm is None:
        return None
    return relative_wall_thickness(lvpwd_mm, lvedd_mm)
