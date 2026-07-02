"""Compact GE-style measurement results text for on-image overlay."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.chamber_simpson import (
    biplane_es_volume_ml,
    es_volume_from_view,
)
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.indexed_results_formatter import (
    append_indexed_for_overlay,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.profiler import profiled as _prof


@_prof
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
        _append(lines, tr("result.mv_e"), dop.e_cm_s, "cm/s")
        _append(lines, tr("result.mv_a"), dop.a_cm_s, "cm/s")
        _append(lines, tr("result.mv_ea_ratio"), dop.e_a_ratio, "")
        if time_calibrated:
            _append(lines, tr("result.mv_dt"), dop.dt_ms, "ms")
            _append(lines, tr("result.ivrt"), dop.ivrt_ms, "ms")
            _append(lines, tr("result.at"), dop.at_ms, "ms")
        _append(lines, tr("result.e_prime_sept"), dop.e_prime_sept_cm_s, "cm/s")
        _append(lines, tr("result.e_prime_lat"), dop.e_prime_lat_cm_s, "cm/s")
        _append(lines, tr("result.e_prime_avg"), dop.e_prime_avg_cm_s, "cm/s")
        _append(lines, tr("result.e_over_e_prime"), dop.e_over_e_prime, "")
        _append(lines, tr("result.e_over_e_prime_sept"), dop.e_over_e_prime_sept, "")
        _append(lines, tr("result.e_over_e_prime_lat"), dop.e_over_e_prime_lat, "")
        _append(lines, tr("result.e_prime_over_a_prime"), dop.e_prime_over_a_prime, "")
        _append(lines, tr("result.vpeak"), dop.vpeak_cm_s, "cm/s")
        _append(lines, tr("result.pgpeak"), dop.pgpeak_mmhg, "mmHg")
        _append(lines, tr("result.tr_vmax"), dop.tr_vmax_cm_s, "cm/s")
        if time_calibrated:
            _append(lines, tr("result.vti"), dop.vti_cm, "cm")
            _append(lines, tr("result.vmean"), dop.vmean_cm_s, "cm/s")
            _append(lines, tr("result.pgmean"), dop.pgmean_mmhg, "mmHg")

    volume_unit = "mL" if snapshot.spacing_calibrated else "px³"

    lvef = snapshot.lvef
    if lvef is not None:
        if lvef.a4c and lvef.a4c.edv_ml is not None:
            _append(lines, tr("panel.kdo_lv", view="4C"), lvef.a4c.edv_ml, volume_unit)
        if lvef.a4c and lvef.a4c.esv_ml is not None:
            _append(lines, tr("panel.kso_lv", view="4C"), lvef.a4c.esv_ml, volume_unit)
        if lvef.a2c and lvef.a2c.edv_ml is not None:
            _append(lines, tr("panel.kdo_lv", view="2C"), lvef.a2c.edv_ml, volume_unit)
        if lvef.a2c and lvef.a2c.esv_ml is not None:
            _append(lines, tr("panel.kso_lv", view="2C"), lvef.a2c.esv_ml, volume_unit)
        _append(lines, tr("panel.lvef"), lvef.lvef_percent, "%")

    teich = snapshot.teichholz
    if teich is not None:
        _append(lines, tr("result.lvedv_teich"), teich.edv_ml, volume_unit)
        _append(lines, tr("result.lvesv_teich"), teich.esv_ml, volume_unit)
        _append(lines, tr("result.lvef_teich"), teich.lvef_percent, "%")

    if snapshot.lvm_g is not None:
        _append(lines, tr("panel.lv_mass"), snapshot.lvm_g, "g")

    if snapshot.rwt is not None:
        _append(lines, tr("result.rwt"), snapshot.rwt, "", decimals=2)

    la = snapshot.la_simpson
    if la is not None:
        lav_4c = es_volume_from_view(la.a4c)
        if lav_4c is not None:
            _append(lines, tr("panel.lav_4c_short"), lav_4c, volume_unit)
        lav_bi = biplane_es_volume_ml(la.a4c, la.a2c)
        if lav_bi is not None:
            _append(lines, tr("panel.lav_bi_short"), lav_bi, volume_unit)
        if la.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _append(lines, tr("panel.s_la"), la.area_cm2, area_unit, decimals=2)
    elif snapshot.la_volume and snapshot.la_volume.volume_ml is not None:
        _append(lines, tr("result.lvedv"), snapshot.la_volume.volume_ml, volume_unit)

    ra = snapshot.ra_simpson
    if ra is not None:
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        if rav is not None:
            _append(lines, tr("result.rav_4c"), rav, volume_unit)
        if ra.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _append(lines, tr("panel.s_ra"), ra.area_cm2, area_unit, decimals=2)

    if snapshot.rv_fac_percent is not None:
        _append(lines, tr("result.fac"), snapshot.rv_fac_percent, "%")

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
