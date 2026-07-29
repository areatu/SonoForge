"""Compact Clinical-style measurement results text for on-image overlay."""

from __future__ import annotations

import logging

from echo_personal_tool.domain.calculations.chamber_simpson import (
    biplane_es_volume_ml,
    es_volume_from_view,
)
from echo_personal_tool.domain.models.linear_measurement import _LABEL_I18N_KEY
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.indexed_results_formatter import (
    append_indexed_for_overlay,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.profiler import profiled as _prof

logger = logging.getLogger(__name__)

_COLOR_ABNORMAL = "#ff6b6b"  # light red for out-of-range values on dark background
_COLOR_NORMAL = "#e8eef4"  # default text color (light on dark)
_COLOR_LABEL = "#94a3b8"  # dimmed label color
_COLOR_UNIT = "#94a3b8"  # dimmed unit color


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
        _append(lines, tr("result.lav"), snapshot.la_volume.volume_ml, volume_unit)

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


_norm_store_cache: ReferenceDataStore | None = None


def _get_norm_store() -> ReferenceDataStore:
    global _norm_store_cache
    if _norm_store_cache is None:
        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore as _RDS,
        )

        _norm_store_cache = _RDS()
        _norm_store_cache.load()
    return _norm_store_cache


def invalidate_norm_cache() -> None:
    """Reset the norm store cache so next access re-reads YAML."""
    global _norm_store_cache
    _norm_store_cache = None


def _norm_for_param(param_id: str, sex_male: bool = True):
    """Look up norm range from ReferenceDataStore by param_id."""
    try:
        store = _get_norm_store()
        result = store.lookup(param_id)
        if result is None:
            return None
        _topic, _patho, grad = result
        if grad is not None and grad.parameters:
            for p in grad.parameters:
                if p.id == param_id:
                    return p.norm_male if sex_male else (p.norm_female or p.norm_male)
        if _patho.parameters:
            for p in _patho.parameters:
                if p.id == param_id:
                    return p.norm_male if sex_male else (p.norm_female or p.norm_male)
    except Exception:
        logger.debug("norm lookup failed for param_id=%s", param_id, exc_info=True)
    return None


def _is_outside(norm, value: float) -> bool:
    if norm is None:
        return False
    if norm.low is not None and value < norm.low:
        return True
    if norm.high is not None and value > norm.high:
        return True
    return False


def _best_lav_index(indexed) -> float | None:
    for candidate in (
        indexed.lav_bi_index_ml_m2,
        indexed.lav_area_length_index_ml_m2,
        indexed.lav_4c_index_ml_m2,
    ):
        if candidate is not None:
            return candidate
    return None


_CALIPER_PARAM_ID_MAP: dict[str, str] = {
    "ivsd": "ivsd",
    "lvedd": "lvedd",
    "lvpwd": "lvpwd",
    "lvesd": "lvesd",
    "la": "la_lax",
    "lal": "la_lax",
    "ra": "ra_area",
    "rv basal": "rvd1",
    "rv mid": "rvd2",
    "rvot": "pa_rvot",
    "tapse": "tapss",
    "s' rv": "s_prime_rv",
    "s'": "s_prime_rv",
    "av": "asc_aorta",
    "annulus": "sinotubular",
    "ao sinus": "asc_aorta",
    "ao junction": "sinotubular",
    "prox ao": "ascending_aorta",
    "lvot": "lvedd",
}


_INDEXED_LINEAR_I18N: dict[str, str] = {
    "ivsd": "indexed.linear_ivsd",
    "lvedd": "indexed.linear_lvedd",
    "lvpwd": "indexed.linear_lvpwd",
    "lvesd": "indexed.linear_lvesd",
    "la": "indexed.linear_la",
}


def _indexed_linear_label(measurement_label: str) -> str:
    key = measurement_label.casefold()
    i18n_key = _INDEXED_LINEAR_I18N.get(key)
    if i18n_key is not None:
        return tr(i18n_key)
    return f"{measurement_label}{tr('indexed.suffix')}"


def _html_append(
    parts: list[str],
    label: str,
    value: float | None,
    suffix: str,
    *,
    decimals: int = 1,
    param_id: str | None = None,
    sex_male: bool = True,
) -> None:
    """Append one HTML line: <a>label</a>: <span>value</span> unit."""
    if value is None:
        return
    unit = f" {suffix}" if suffix else ""
    val_str = f"{value:.{decimals}f}"

    # Link to reference
    if param_id:
        label_html = f'<a href="{param_id}" style="color:{_COLOR_LABEL}; text-decoration:none;">{label}</a>'
    else:
        label_html = f'<span style="color:{_COLOR_LABEL};">{label}</span>'

    # Check norm
    norm = _norm_for_param(param_id, sex_male) if param_id else None
    if _is_outside(norm, value):
        val_html = f'<span style="color:{_COLOR_ABNORMAL};">{val_str}</span>'
    else:
        val_html = f'<span style="color:{_COLOR_NORMAL};">{val_str}</span>'

    parts.append(f'{label_html}: {val_html} <span style="color:{_COLOR_UNIT};">{unit}</span>')


@_prof
def format_results_overlay_html(
    snapshot: MeasurementSnapshot | None,
    *,
    time_calibrated: bool = False,
    amplitude_only: bool | None = None,
    length_display_unit: str = "mm",
    sex_male: bool = True,
) -> str:
    """Return HTML summary with colored out-of-range values and clickable links."""
    if amplitude_only is not None:
        time_calibrated = not amplitude_only
    if snapshot is None:
        return ""

    parts: list[str] = []

    dop = snapshot.doppler
    if dop is not None:
        _html_append(parts, tr("result.mv_e"), dop.e_cm_s, "cm/s", param_id="ea_ratio", sex_male=sex_male)
        _html_append(parts, tr("result.mv_a"), dop.a_cm_s, "cm/s", param_id="ea_ratio", sex_male=sex_male)
        _html_append(parts, tr("result.mv_ea_ratio"), dop.e_a_ratio, "", param_id="ea_ratio", sex_male=sex_male)
        if time_calibrated:
            _html_append(parts, tr("result.mv_dt"), dop.dt_ms, "ms", param_id="dt", sex_male=sex_male)
            _html_append(parts, tr("result.ivrt"), dop.ivrt_ms, "ms", param_id="dt", sex_male=sex_male)
            _html_append(parts, tr("result.at"), dop.at_ms, "ms", param_id="dt", sex_male=sex_male)
        _html_append(
            parts, tr("result.e_prime_sept"), dop.e_prime_sept_cm_s, "cm/s", param_id="e_prime_sept", sex_male=sex_male
        )
        _html_append(
            parts, tr("result.e_prime_lat"), dop.e_prime_lat_cm_s, "cm/s", param_id="e_prime_lat", sex_male=sex_male
        )
        _html_append(
            parts, tr("result.e_prime_avg"), dop.e_prime_avg_cm_s, "cm/s", param_id="e_e_prime_avg", sex_male=sex_male
        )
        _html_append(
            parts, tr("result.e_over_e_prime"), dop.e_over_e_prime, "", param_id="e_e_prime_avg", sex_male=sex_male
        )
        _html_append(
            parts,
            tr("result.e_over_e_prime_sept"),
            dop.e_over_e_prime_sept,
            "",
            param_id="e_e_prime_avg",
            sex_male=sex_male,
        )
        _html_append(
            parts,
            tr("result.e_over_e_prime_lat"),
            dop.e_over_e_prime_lat,
            "",
            param_id="e_e_prime_avg",
            sex_male=sex_male,
        )
        _html_append(
            parts,
            tr("result.e_prime_over_a_prime"),
            dop.e_prime_over_a_prime,
            "",
            param_id="e_e_prime_avg",
            sex_male=sex_male,
        )
        _html_append(parts, tr("result.vpeak"), dop.vpeak_cm_s, "cm/s", sex_male=sex_male)
        _html_append(parts, tr("result.pgpeak"), dop.pgpeak_mmhg, "mmHg", sex_male=sex_male)
        _html_append(parts, tr("result.tr_vmax"), dop.tr_vmax_cm_s, "cm/s", param_id="tr_vmax", sex_male=sex_male)
        if time_calibrated:
            _html_append(parts, tr("result.vti"), dop.vti_cm, "cm", sex_male=sex_male)
            _html_append(parts, tr("result.vmean"), dop.vmean_cm_s, "cm/s", sex_male=sex_male)
            _html_append(parts, tr("result.pgmean"), dop.pgmean_mmhg, "mmHg", sex_male=sex_male)

    volume_unit = "mL" if snapshot.spacing_calibrated else "px³"

    lvef = snapshot.lvef
    if lvef is not None:
        if lvef.a4c and lvef.a4c.edv_ml is not None:
            _html_append(
                parts, tr("panel.kdo_lv", view="4C"), lvef.a4c.edv_ml, volume_unit, param_id="lvedvi", sex_male=sex_male
            )
        if lvef.a4c and lvef.a4c.esv_ml is not None:
            _html_append(
                parts, tr("panel.kso_lv", view="4C"), lvef.a4c.esv_ml, volume_unit, param_id="lvesvi", sex_male=sex_male
            )
        if lvef.a2c and lvef.a2c.edv_ml is not None:
            _html_append(
                parts, tr("panel.kdo_lv", view="2C"), lvef.a2c.edv_ml, volume_unit, param_id="lvedvi", sex_male=sex_male
            )
        if lvef.a2c and lvef.a2c.esv_ml is not None:
            _html_append(
                parts, tr("panel.kso_lv", view="2C"), lvef.a2c.esv_ml, volume_unit, param_id="lvesvi", sex_male=sex_male
            )
        _html_append(parts, tr("panel.lvef"), lvef.lvef_percent, "%", param_id="lvef", sex_male=sex_male)

    teich = snapshot.teichholz
    if teich is not None:
        _html_append(parts, tr("result.lvedv_teich"), teich.edv_ml, volume_unit, param_id="lvedvi", sex_male=sex_male)
        _html_append(parts, tr("result.lvesv_teich"), teich.esv_ml, volume_unit, param_id="lvesvi", sex_male=sex_male)
        _html_append(parts, tr("result.lvef_teich"), teich.lvef_percent, "%", param_id="lvef", sex_male=sex_male)

    if snapshot.lvm_g is not None:
        _html_append(parts, tr("panel.lv_mass"), snapshot.lvm_g, "g", param_id="lvm", sex_male=sex_male)

    if snapshot.rwt is not None:
        _html_append(parts, tr("result.rwt"), snapshot.rwt, "", decimals=2, param_id="rwt", sex_male=sex_male)

    la = snapshot.la_simpson
    if la is not None:
        lav_4c = es_volume_from_view(la.a4c)
        if lav_4c is not None:
            _html_append(
                parts, tr("panel.lav_4c_short"), lav_4c, volume_unit, param_id="la_vol_index", sex_male=sex_male
            )
        lav_bi = biplane_es_volume_ml(la.a4c, la.a2c)
        if lav_bi is not None:
            _html_append(
                parts, tr("panel.lav_bi_short"), lav_bi, volume_unit, param_id="la_vol_index", sex_male=sex_male
            )
        if la.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _html_append(
                parts, tr("panel.s_la"), la.area_cm2, area_unit, decimals=2, param_id="la_vol_index", sex_male=sex_male
            )
    elif snapshot.la_volume and snapshot.la_volume.volume_ml is not None:
        _html_append(
            parts,
            tr("result.lav"),
            snapshot.la_volume.volume_ml,
            volume_unit,
            param_id="la_vol_index",
            sex_male=sex_male,
        )

    ra = snapshot.ra_simpson
    if ra is not None:
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        if rav is not None:
            _html_append(parts, tr("result.rav_4c"), rav, volume_unit, param_id="ra_area", sex_male=sex_male)
        if ra.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _html_append(
                parts, tr("panel.s_ra"), ra.area_cm2, area_unit, decimals=2, param_id="ra_area", sex_male=sex_male
            )

    if snapshot.rv_fac_percent is not None:
        _html_append(parts, tr("result.fac"), snapshot.rv_fac_percent, "%", param_id="fac", sex_male=sex_male)

    if snapshot.diastology_grade:
        parts.append(f'<span style="color:{_COLOR_LABEL};">{snapshot.diastology_grade}</span>')

    # Indexed results with param links for norm checking
    indexed = snapshot.indexed
    if indexed is not None:
        bsa = indexed.bsa_m2
        if bsa is not None:
            _html_append(parts, tr("indexed.bsa"), bsa, "m²", decimals=2, param_id="lavi", sex_male=sex_male)
        lav_index = _best_lav_index(indexed)
        if lav_index is not None:
            _html_append(parts, tr("indexed.lav_line"), lav_index, "mL/m²", param_id="lavi", sex_male=sex_male)
        if indexed.rav_index_ml_m2 is not None:
            _html_append(
                parts, tr("indexed.rav_line"), indexed.rav_index_ml_m2, "mL/m²", param_id="ra_area", sex_male=sex_male
            )
        if indexed.lvmi_g_m2 is not None:
            _html_append(parts, tr("indexed.lvmi_line"), indexed.lvmi_g_m2, "g/m²", param_id="lvmi", sex_male=sex_male)
        lvef = snapshot.lvef
        if lvef is not None:
            if lvef.a4c and indexed.simpson_a4c_edvi_ml_m2 is not None:
                _html_append(
                    parts,
                    tr("indexed.edv_4c"),
                    indexed.simpson_a4c_edvi_ml_m2,
                    "mL/m²",
                    param_id="lvedvi",
                    sex_male=sex_male,
                )
            if lvef.a4c and indexed.simpson_a4c_esvi_ml_m2 is not None:
                _html_append(
                    parts,
                    tr("indexed.esv_4c"),
                    indexed.simpson_a4c_esvi_ml_m2,
                    "mL/m²",
                    param_id="lvesvi",
                    sex_male=sex_male,
                )
            if lvef.a2c and indexed.simpson_a2c_edvi_ml_m2 is not None:
                _html_append(
                    parts,
                    tr("indexed.edv_2c"),
                    indexed.simpson_a2c_edvi_ml_m2,
                    "mL/m²",
                    param_id="lvedvi",
                    sex_male=sex_male,
                )
            if lvef.a2c and indexed.simpson_a2c_esvi_ml_m2 is not None:
                _html_append(
                    parts,
                    tr("indexed.esv_2c"),
                    indexed.simpson_a2c_esvi_ml_m2,
                    "mL/m²",
                    param_id="lvesvi",
                    sex_male=sex_male,
                )
        teich = snapshot.teichholz
        if teich is not None:
            if indexed.teichholz_edvi_ml_m2 is not None:
                _html_append(
                    parts,
                    tr("indexed.teichholz_ed"),
                    indexed.teichholz_edvi_ml_m2,
                    "mL/m²",
                    param_id="lvedvi",
                    sex_male=sex_male,
                )
            if indexed.teichholz_esvi_ml_m2 is not None:
                _html_append(
                    parts,
                    tr("indexed.teichholz_es"),
                    indexed.teichholz_esvi_ml_m2,
                    "mL/m²",
                    param_id="lvesvi",
                    sex_male=sex_male,
                )
        from echo_personal_tool.domain.services.indexed_results_formatter import should_show_indexed_linear

        _INDEXED_PARAM_ID_MAP = {"ivsd": "ivsd", "lvedd": "lvedd", "lvpwd": "lvpwd", "lvesd": "lvesd"}
        for measurement in snapshot.linear_measurements:
            if measurement.millimeter_length is None:
                continue
            indexed_mm_m2 = next(
                (v for k, v in indexed.linear_index_mm_m2 if k.casefold() == measurement.label.casefold()),
                None,
            )
            if indexed_mm_m2 is None:
                continue
            if should_show_indexed_linear(measurement.label, measurement.millimeter_length):
                param_id = _INDEXED_PARAM_ID_MAP.get(measurement.label.casefold())
                label_text = _indexed_linear_label(measurement.label)
                _html_append(
                    parts, label_text, indexed_mm_m2, "mm/m²", decimals=2, param_id=param_id, sex_male=sex_male
                )

    for item in snapshot.planimeter:
        _html_append(parts, item.label, item.value, item.unit, decimals=2 if item.kind == "area" else 1)

    for measurement in snapshot.linear_measurements:
        if measurement.label == "%D":
            if measurement.millimeter_length is not None:
                display_label = tr(_LABEL_I18N_KEY.get("%D", "result.percent_d"))
                _html_append(
                    parts,
                    display_label,
                    measurement.millimeter_length,
                    "%",
                    decimals=1,
                    sex_male=sex_male,
                )
            continue
        if measurement.label == "%S":
            if measurement.millimeter_length is not None:
                display_label = tr(_LABEL_I18N_KEY.get("%S", "result.percent_s"))
                _html_append(
                    parts,
                    display_label,
                    measurement.millimeter_length,
                    "%",
                    decimals=1,
                    sex_male=sex_male,
                )
            continue
        if measurement.millimeter_length is not None:
            param_id = _CALIPER_PARAM_ID_MAP.get(measurement.label.casefold())
            display_label = measurement.label
            i18n_key = _LABEL_I18N_KEY.get(measurement.label)
            if i18n_key:
                display_label = tr(i18n_key)
            _html_append(
                parts,
                display_label,
                measurement.millimeter_length,
                length_display_unit,
                param_id=param_id,
                sex_male=sex_male,
            )
        else:
            text = measurement.display_text(length_unit=length_display_unit)
            parts.append(f'<span style="color:{_COLOR_NORMAL};">{text}</span>')

    return "<br>".join(parts)


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
