"""Append BSA-indexed values using catalog precision (issue 482)."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.calculations.chamber_simpson import confirmed_biplane_es_volume_ml
from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.domain.models.measurements import IndexedMeasurements, MeasurementSnapshot
from echo_personal_tool.domain.services.ase_reference_norms import (
    LAVI_MLM2,
    LV_LVEDD_MM,
    LVEDVI_MLM2,
    LVESVI_MLM2,
    LVMI_GM2,
    RAV_ML,
    is_outside_norm,
)
from echo_personal_tool.domain.services.ase_reference_norms import (
    should_show_indexed_linear as should_show_indexed_linear,
)
from echo_personal_tool.domain.translation import tr

_INDEXED_PARAM_ID_MAP: dict[str, str] = {
    "ivsd": "ivsd",
    "lvedd": "lvedd",
    "lvpwd": "lvpwd",
    "lvesd": "lvesd",
}


@dataclass(frozen=True)
class IndexedOverlayRow:
    """Shared indexed row descriptor for plain-text and HTML overlays."""

    label: str
    measurement_id: str
    value: float
    unit: str
    param_id: str | None = None
    abnormal: bool = False
    always_in_text: bool = False

    def format_text(self) -> str:
        formatted = format_measurement(self.measurement_id, self.value, self.unit)
        suffix = f" {self.unit}" if self.unit else ""
        return f"{self.label}: {formatted}{suffix}"


def build_indexed_overlay_rows(snapshot: MeasurementSnapshot) -> tuple[IndexedOverlayRow, ...]:
    """Build indexed measurement rows once for both plain-text and HTML overlays."""
    indexed = snapshot.indexed
    if indexed is None:
        return ()

    rows: list[IndexedOverlayRow] = []

    lav_info = _best_lav_index_with_id(snapshot)
    if lav_info is not None:
        lav_id, lav_index = lav_info
        rows.append(
            IndexedOverlayRow(
                label=tr("indexed.lav_line"),
                measurement_id=lav_id,
                value=lav_index,
                unit="mL/m²",
                param_id="lavi",
                abnormal=is_outside_norm(lav_index, LAVI_MLM2),
                always_in_text=True,
            )
        )

    if indexed.rav_index_ml_m2 is not None:
        rav_ml = _rav_absolute_ml(snapshot)
        rows.append(
            IndexedOverlayRow(
                label=tr("indexed.rav_line"),
                measurement_id="ra.ravi",
                value=indexed.rav_index_ml_m2,
                unit="mL/m²",
                param_id="ra_area",
                abnormal=rav_ml is not None and is_outside_norm(rav_ml, RAV_ML),
                always_in_text=True,
            )
        )

    if indexed.lvmi_g_m2 is not None:
        rows.append(
            IndexedOverlayRow(
                label=tr("indexed.lvmi_line"),
                measurement_id="lv.mass_i",
                value=indexed.lvmi_g_m2,
                unit="g/m²",
                param_id="lvmi",
                abnormal=is_outside_norm(indexed.lvmi_g_m2, LVMI_GM2),
            )
        )

    lvef = snapshot.lvef
    if lvef is not None:
        lvedd_abn = _lvedd_abnormal(snapshot)
        if lvef.a4c and indexed.simpson_a4c_edvi_ml_m2 is not None:
            rows.append(
                IndexedOverlayRow(
                    label=tr("indexed.edv_4c"),
                    measurement_id="lv.edvi_a4c",
                    value=indexed.simpson_a4c_edvi_ml_m2,
                    unit="mL/m²",
                    param_id="lvedvi",
                    abnormal=(
                        lvef.a4c.edv_ml is not None
                        and (is_outside_norm(indexed.simpson_a4c_edvi_ml_m2, LVEDVI_MLM2) or lvedd_abn)
                    ),
                )
            )
        if lvef.a4c and indexed.simpson_a4c_esvi_ml_m2 is not None:
            rows.append(
                IndexedOverlayRow(
                    label=tr("indexed.esv_4c"),
                    measurement_id="lv.esvi_a4c",
                    value=indexed.simpson_a4c_esvi_ml_m2,
                    unit="mL/m²",
                    param_id="lvesvi",
                    abnormal=(
                        lvef.a4c.esv_ml is not None and is_outside_norm(indexed.simpson_a4c_esvi_ml_m2, LVESVI_MLM2)
                    ),
                )
            )
        if lvef.a2c and indexed.simpson_a2c_edvi_ml_m2 is not None:
            rows.append(
                IndexedOverlayRow(
                    label=tr("indexed.edv_2c"),
                    measurement_id="lv.edvi_a2c",
                    value=indexed.simpson_a2c_edvi_ml_m2,
                    unit="mL/m²",
                    param_id="lvedvi",
                    abnormal=(
                        lvef.a2c.edv_ml is not None
                        and (is_outside_norm(indexed.simpson_a2c_edvi_ml_m2, LVEDVI_MLM2) or lvedd_abn)
                    ),
                )
            )
        if lvef.a2c and indexed.simpson_a2c_esvi_ml_m2 is not None:
            rows.append(
                IndexedOverlayRow(
                    label=tr("indexed.esv_2c"),
                    measurement_id="lv.esvi_a2c",
                    value=indexed.simpson_a2c_esvi_ml_m2,
                    unit="mL/m²",
                    param_id="lvesvi",
                    abnormal=(
                        lvef.a2c.esv_ml is not None and is_outside_norm(indexed.simpson_a2c_esvi_ml_m2, LVESVI_MLM2)
                    ),
                )
            )

    teich = snapshot.teichholz
    if teich is not None:
        lvedd_abn = _lvedd_abnormal(snapshot)
        if indexed.teichholz_edvi_ml_m2 is not None:
            rows.append(
                IndexedOverlayRow(
                    label=tr("indexed.teichholz_ed"),
                    measurement_id="lv.edvi_teich",
                    value=indexed.teichholz_edvi_ml_m2,
                    unit="mL/m²",
                    param_id="lvedvi",
                    abnormal=is_outside_norm(indexed.teichholz_edvi_ml_m2, LVEDVI_MLM2) or lvedd_abn,
                )
            )
        if indexed.teichholz_esvi_ml_m2 is not None:
            rows.append(
                IndexedOverlayRow(
                    label=tr("indexed.teichholz_es"),
                    measurement_id="lv.esvi_teich",
                    value=indexed.teichholz_esvi_ml_m2,
                    unit="mL/m²",
                    param_id="lvesvi",
                    abnormal=is_outside_norm(indexed.teichholz_esvi_ml_m2, LVESVI_MLM2),
                )
            )

    indexed_linear = {label.casefold(): value for label, value in indexed.linear_index_mm_m2}
    for measurement in snapshot.linear_measurements:
        if measurement.millimeter_length is None:
            continue
        indexed_mm_m2 = indexed_linear.get(measurement.label.casefold())
        if indexed_mm_m2 is None:
            continue
        if should_show_indexed_linear(measurement.label, measurement.millimeter_length):
            rows.append(
                IndexedOverlayRow(
                    label=_indexed_linear_label(measurement.label),
                    measurement_id="indexed.linear",
                    value=indexed_mm_m2,
                    unit="mm/m²",
                    param_id=_INDEXED_PARAM_ID_MAP.get(measurement.label.casefold()),
                    abnormal=True,
                )
            )

    return tuple(rows)


def append_indexed_for_overlay(
    lines: list[str],
    snapshot: MeasurementSnapshot,
) -> None:
    """Overlay: LAVi/RAVi always when BSA available; other indices only if abnormal."""
    for row in build_indexed_overlay_rows(snapshot):
        if row.always_in_text or row.abnormal:
            lines.append(row.format_text())


def append_indexed_when_abnormal(
    lines: list[str],
    snapshot: MeasurementSnapshot,
) -> None:
    """Add indexed metrics when height/weight set and values exceed ASE norms."""
    for row in build_indexed_overlay_rows(snapshot):
        if row.abnormal:
            lines.append(row.format_text())


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


def _best_lav_index_with_id(snapshot: MeasurementSnapshot) -> tuple[str, float] | None:
    indexed: IndexedMeasurements | None = snapshot.indexed
    if indexed is None:
        return None
    # The biplane index is allowed only when a true biplane result confirms it;
    # a legacy averaged-monoplane index must fall through to area-length/4C.
    biplane = indexed.lav_bi_index_ml_m2 if confirmed_biplane_es_volume_ml(snapshot.la_simpson) else None
    for measurement_id, candidate in (
        ("la.lavi_bp", biplane),
        ("la.lavi_al", indexed.lav_area_length_index_ml_m2),
        ("la.lavi_a4c", indexed.lav_4c_index_ml_m2),
    ):
        if candidate is not None:
            return measurement_id, candidate
    return None


def _rav_absolute_ml(snapshot: MeasurementSnapshot) -> float | None:
    if snapshot.ra_simpson and snapshot.ra_simpson.max_volume_ml is not None:
        return snapshot.ra_simpson.max_volume_ml
    return None
