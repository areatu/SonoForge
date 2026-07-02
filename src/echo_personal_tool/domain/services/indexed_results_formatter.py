"""Append BSA-indexed values when ASE norms are exceeded."""

from __future__ import annotations

from echo_personal_tool.domain.models.measurements import IndexedMeasurements, MeasurementSnapshot
from echo_personal_tool.domain.services.ase_reference_norms import (
    LAVI_MLM2,
    LV_LVEDD_MM,
    LVEDVI_MLM2,
    LVESVI_MLM2,
    LVMI_GM2,
    RAV_ML,
    is_outside_norm,
    should_show_indexed_linear,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.profiler import profiled as _prof


@_prof
def append_indexed_for_overlay(
    lines: list[str],
    snapshot: MeasurementSnapshot,
) -> None:
    """Overlay: LAVi/RAVi always when BSA available; other indices only if abnormal."""
    indexed = snapshot.indexed
    if indexed is None:
        return

    always_lines: list[str] = []
    lav_index = _best_lav_index(indexed)
    if lav_index is not None:
        _append_line(always_lines, tr("indexed.lav_line"), lav_index, "mL/m²")
    if indexed.rav_index_ml_m2 is not None:
        _append_line(always_lines, tr("indexed.rav_line"), indexed.rav_index_ml_m2, "mL/m²")

    abnormal_lines: list[str] = []
    _append_abnormal_indexed(abnormal_lines, snapshot, skip_lav_rav=True)

    if not always_lines and not abnormal_lines:
        return

    _append_line(lines, tr("indexed.bsa"), indexed.bsa_m2, "m²", decimals=2)
    lines.extend(always_lines)
    lines.extend(abnormal_lines)


def append_indexed_when_abnormal(
    lines: list[str],
    snapshot: MeasurementSnapshot,
) -> None:
    """Add indexed metrics when height/weight set and values exceed ASE norms."""
    indexed = snapshot.indexed
    if indexed is None:
        return

    abnormal_lines: list[str] = []
    _append_abnormal_indexed(abnormal_lines, snapshot, skip_lav_rav=False)
    if not abnormal_lines:
        return

    _append_line(lines, tr("indexed.bsa"), indexed.bsa_m2, "m²", decimals=2)
    lines.extend(abnormal_lines)


def _append_abnormal_indexed(
    lines: list[str],
    snapshot: MeasurementSnapshot,
    *,
    skip_lav_rav: bool,
) -> None:
    indexed = snapshot.indexed
    if indexed is None:
        return

    if indexed.lvmi_g_m2 is not None and is_outside_norm(indexed.lvmi_g_m2, LVMI_GM2):
        _append_line(lines, tr("indexed.lvmi_line"), indexed.lvmi_g_m2, "g/m²")

    lvef = snapshot.lvef
    if lvef is not None:
        if (
            lvef.a4c
            and lvef.a4c.edv_ml is not None
            and indexed.simpson_a4c_edvi_ml_m2 is not None
            and (
                is_outside_norm(indexed.simpson_a4c_edvi_ml_m2, LVEDVI_MLM2)
                or _lvedd_abnormal(snapshot)
            )
        ):
            _append_line(lines, tr("indexed.edv_4c"), indexed.simpson_a4c_edvi_ml_m2, "mL/m²")
        if (
            lvef.a4c
            and lvef.a4c.esv_ml is not None
            and indexed.simpson_a4c_esvi_ml_m2 is not None
            and is_outside_norm(indexed.simpson_a4c_esvi_ml_m2, LVESVI_MLM2)
        ):
            _append_line(lines, tr("indexed.esv_4c"), indexed.simpson_a4c_esvi_ml_m2, "mL/m²")
        if (
            lvef.a2c
            and lvef.a2c.edv_ml is not None
            and indexed.simpson_a2c_edvi_ml_m2 is not None
            and (
                is_outside_norm(indexed.simpson_a2c_edvi_ml_m2, LVEDVI_MLM2)
                or _lvedd_abnormal(snapshot)
            )
        ):
            _append_line(lines, tr("indexed.edv_2c"), indexed.simpson_a2c_edvi_ml_m2, "mL/m²")
        if (
            lvef.a2c
            and lvef.a2c.esv_ml is not None
            and indexed.simpson_a2c_esvi_ml_m2 is not None
            and is_outside_norm(indexed.simpson_a2c_esvi_ml_m2, LVESVI_MLM2)
        ):
            _append_line(lines, tr("indexed.esv_2c"), indexed.simpson_a2c_esvi_ml_m2, "mL/m²")

    teich = snapshot.teichholz
    if teich is not None:
        if indexed.teichholz_edvi_ml_m2 is not None and (
            is_outside_norm(indexed.teichholz_edvi_ml_m2, LVEDVI_MLM2)
            or _lvedd_abnormal(snapshot)
        ):
            _append_line(lines, tr("indexed.teichholz_ed"), indexed.teichholz_edvi_ml_m2, "mL/m²")
        if (
            indexed.teichholz_esvi_ml_m2 is not None
            and is_outside_norm(indexed.teichholz_esvi_ml_m2, LVESVI_MLM2)
        ):
            _append_line(lines, tr("indexed.teichholz_es"), indexed.teichholz_esvi_ml_m2, "mL/m²")

    if not skip_lav_rav:
        lav_index = _best_lav_index(indexed)
        if lav_index is not None and is_outside_norm(lav_index, LAVI_MLM2):
            _append_line(lines, tr("indexed.lav_line"), lav_index, "mL/m²")

        rav_ml = _rav_absolute_ml(snapshot)
        if rav_ml is not None and indexed.rav_index_ml_m2 is not None and is_outside_norm(
            rav_ml, RAV_ML
        ):
            _append_line(lines, tr("indexed.rav_line"), indexed.rav_index_ml_m2, "mL/m²")

    indexed_linear = {label.casefold(): value for label, value in indexed.linear_index_mm_m2}
    for measurement in snapshot.linear_measurements:
        if measurement.millimeter_length is None:
            continue
        indexed_mm_m2 = indexed_linear.get(measurement.label.casefold())
        if indexed_mm_m2 is None:
            continue
        if should_show_indexed_linear(measurement.label, measurement.millimeter_length):
            _append_line(
                lines,
                _indexed_linear_label(measurement.label),
                indexed_mm_m2,
                "mm/m²",
                decimals=2,
            )


_INDEXED_LINEAR_I18N: dict[str, str] = {
    "ivsd": "indexed.linear_ivsd",
    "ivsi": "indexed.linear_ivsd",
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


def _lvedd_abnormal(snapshot: MeasurementSnapshot) -> bool:
    for measurement in snapshot.linear_measurements:
        if measurement.label.upper() != "LVEDD":
            continue
        if measurement.millimeter_length is None:
            return False
        return is_outside_norm(measurement.millimeter_length, LV_LVEDD_MM)
    return False


def _best_lav_index(indexed: IndexedMeasurements) -> float | None:
    for candidate in (
        indexed.lav_bi_index_ml_m2,
        indexed.lav_area_length_index_ml_m2,
        indexed.lav_4c_index_ml_m2,
    ):
        if candidate is not None:
            return candidate
    return None


def _rav_absolute_ml(snapshot: MeasurementSnapshot) -> float | None:
    if snapshot.ra_simpson and snapshot.ra_simpson.max_volume_ml is not None:
        return snapshot.ra_simpson.max_volume_ml
    return None


def _append_line(
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
