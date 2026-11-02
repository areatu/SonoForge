"""Left ventricular mass by ASE cube formula."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def lvm_grams(
    ivsd_mm: float,
    lvedd_mm: float,
    lvpwd_mm: float,
) -> float:
    """ASE 2015 cube formula (linear inputs in mm, converted to cm internally)."""
    ivsd_cm = ivsd_mm / 10.0
    lvedd_cm = lvedd_mm / 10.0
    lvpwd_cm = lvpwd_mm / 10.0
    inner_sum = ivsd_cm + lvedd_cm + lvpwd_cm
    return 0.8 * 1.04 * (inner_sum**3 - lvedd_cm**3) + 0.6


def from_linear_measurements(
    measurements: tuple[LinearMeasurement, ...],
) -> float | None:
    """Return LVM (g) when IVSd, LVEDD, LVPWd calipers are present."""
    values: dict[str, float] = {}
    for measurement in measurements:
        label = measurement.label.upper()
        if label in {"IVSD", "LVEDD", "LVPWD"} and measurement.millimeter_length is not None:
            values[label] = measurement.millimeter_length
    if len(values) < 3:
        return None
    return lvm_grams(values["IVSD"], values["LVEDD"], values["LVPWD"])
