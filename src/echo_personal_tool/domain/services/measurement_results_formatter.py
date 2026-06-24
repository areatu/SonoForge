"""Compact GE-style measurement results text for on-image overlay."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import format_length_mm
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.calculations.chamber_simpson import (
    biplane_es_volume_ml,
    es_volume_from_view,
)
from echo_personal_tool.domain.services.indexed_results_formatter import (
    append_indexed_for_overlay,
)


def format_results_overlay(
    snapshot: MeasurementSnapshot | None,
    *,
    time_calibrated: bool = False,
    amplitude_only: bool | None = None,
    length_display_unit: str = "mm",
) -> str:
    """Return multi-line summary of session-computed values (study-wide)."""
    if amplitude_only is not None:
        time_calibrated = not amplitude_only
    if snapshot is None:
        return ""

    lines: list[str] = []

    dop = snapshot.doppler
    if dop is not None:
        _append(lines, "E", dop.e_cm_s, "cm/s")
        _append(lines, "A", dop.a_cm_s, "cm/s")
        _append(lines, "E/A", dop.e_a_ratio, "")
        if time_calibrated:
            _append(lines, "DT", dop.dt_ms, "ms")
            _append(lines, "IVRT", dop.ivrt_ms, "ms")
            _append(lines, "AT", dop.at_ms, "ms")
        _append(lines, "e' sept", dop.e_prime_sept_cm_s, "cm/s")
        _append(lines, "e' lat", dop.e_prime_lat_cm_s, "cm/s")
        _append(lines, "e' mean", dop.e_prime_avg_cm_s, "cm/s")
        _append(lines, "E/e'", dop.e_over_e_prime, "")
        _append(lines, "E/e' sept", dop.e_over_e_prime_sept, "")
        _append(lines, "E/e' lat", dop.e_over_e_prime_lat, "")
        _append(lines, "e'/a'", dop.e_prime_over_a_prime, "")
        _append(lines, "Vpeak", dop.vpeak_cm_s, "cm/s")
        _append(lines, "PGpeak", dop.pgpeak_mmhg, "mmHg")
        _append(lines, "TR Vmax", dop.tr_vmax_cm_s, "cm/s")
        if time_calibrated:
            _append(lines, "VTI", dop.vti_cm, "cm")
            _append(lines, "Vmean", dop.vmean_cm_s, "cm/s")
            _append(lines, "PGmean", dop.pgmean_mmhg, "mmHg")

    volume_unit = "mL" if snapshot.spacing_calibrated else "px³"

    lvef = snapshot.lvef
    if lvef is not None:
        if lvef.a4c and lvef.a4c.edv_ml is not None:
            _append(lines, "EDV 4C", lvef.a4c.edv_ml, volume_unit)
        if lvef.a4c and lvef.a4c.esv_ml is not None:
            _append(lines, "ESV 4C", lvef.a4c.esv_ml, volume_unit)
        if lvef.a2c and lvef.a2c.edv_ml is not None:
            _append(lines, "EDV 2C", lvef.a2c.edv_ml, volume_unit)
        if lvef.a2c and lvef.a2c.esv_ml is not None:
            _append(lines, "ESV 2C", lvef.a2c.esv_ml, volume_unit)
        _append(lines, "LVEF", lvef.lvef_percent, "%")

    teich = snapshot.teichholz
    if teich is not None:
        _append(lines, "EDV (T)", teich.edv_ml, volume_unit)
        _append(lines, "ESV (T)", teich.esv_ml, volume_unit)
        _append(lines, "LVEF (T)", teich.lvef_percent, "%")

    if snapshot.lvm_g is not None:
        _append(lines, "LVM", snapshot.lvm_g, "g")

    if snapshot.rwt is not None:
        _append(lines, "ОТС", snapshot.rwt, "", decimals=2)

    la = snapshot.la_simpson
    if la is not None:
        lav_4c = es_volume_from_view(la.a4c)
        if lav_4c is not None:
            _append(lines, "LAV 4C", lav_4c, volume_unit)
        lav_bi = biplane_es_volume_ml(la.a4c, la.a2c)
        if lav_bi is not None:
            _append(lines, "LAV Bi", lav_bi, volume_unit)
        if la.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _append(lines, "S ЛП", la.area_cm2, area_unit, decimals=2)
    elif snapshot.la_volume and snapshot.la_volume.volume_ml is not None:
        _append(lines, "LAV", snapshot.la_volume.volume_ml, volume_unit)

    ra = snapshot.ra_simpson
    if ra is not None:
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        if rav is not None:
            _append(lines, "RAV 4C", rav, volume_unit)
        if ra.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _append(lines, "S ПП", ra.area_cm2, area_unit, decimals=2)

    if snapshot.rv_fac_percent is not None:
        _append(lines, "FAC", snapshot.rv_fac_percent, "%")

    if snapshot.diastology_grade:
        lines.append(snapshot.diastology_grade)

    append_indexed_for_overlay(lines, snapshot)

    for item in snapshot.planimeter:
        _append(lines, item.label, item.value, item.unit, decimals=2 if item.kind == "area" else 1)

    for measurement in snapshot.linear_measurements:
        lines.append(f"  {measurement.display_text(length_unit=length_display_unit)}")

    return "\n".join(lines)


def _append(
    lines: list[str],
    label: str,
    value: float | None,
    suffix: str,
    *,
    decimals: int = 1,
) -> None:
    if value is None:
        return
    unit = f" {suffix}" if suffix else ""
    lines.append(f"{label}: {value:.{decimals}f}{unit}")
