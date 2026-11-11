"""Compact clinical-style measurement results for on-image overlay (issue 482).

Plain-text and HTML overlays are rendered from a single shared row model
(:func:`build_overlay_rows`), and every numeric measurement formats its value
through :func:`echo_personal_tool.domain.measurement_catalog.format_measurement`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from echo_personal_tool.domain.calculations.chamber_simpson import (
    biplane_es_volume_ml,
    es_volume_from_view,
)
from echo_personal_tool.domain.doppler_catalog import scale_velocity_for_display
from echo_personal_tool.domain.measurement_catalog import (
    format_measurement,
    measurement_for_caliper,
)
from echo_personal_tool.domain.models.linear_measurement import (
    _LABEL_I18N_KEY,
    PERCENT_LABELS,
)
from echo_personal_tool.domain.models.measurements import (
    DopplerFlowResult,
    DopplerResults,
    IndexedMeasurements,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.indexed_results_formatter import (
    _indexed_linear_label as _indexed_linear_label,
)
from echo_personal_tool.domain.services.indexed_results_formatter import (
    build_indexed_overlay_rows,
)
from echo_personal_tool.domain.services.nomenclature import (
    flow_measurement_id,
    view_measurement_id,
)
from echo_personal_tool.domain.services.nomenclature import (
    overlay_label as _label,
)
from echo_personal_tool.domain.services.nomenclature import (
    view_label as _view,
)
from echo_personal_tool.domain.translation import tr

if TYPE_CHECKING:
    from echo_personal_tool.domain.services.reference_data_store import NormRange, ReferenceDataStore

logger = logging.getLogger(__name__)

_COLOR_ABNORMAL = "#ff6b6b"  # light red for out-of-range values on dark background
_COLOR_NORMAL = "#e8eef4"  # default text color (light on dark)
_COLOR_LABEL = "#94a3b8"  # dimmed label color
_COLOR_UNIT = "#94a3b8"  # dimmed unit color

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

_TIMED_DOPPLER_ROWS: tuple[tuple[str, str, str], ...] = (
    ("MV PHT", "mv_pht_ms", "mv.pht"),
    ("TV PHT", "tv_pht_ms", "tv.pht"),
    ("AR PHT", "ar_pht_ms", "ar.pht"),
    ("PR PHT", "pr_pht_ms", "pr.pht"),
    ("AV AT", "av_at_ms", "av.at"),
    ("AV ET", "av_et_ms", "av.et"),
    ("RVOT AT", "rvot_at_ms", "rvot.at"),
)


@dataclass(frozen=True)
class OverlayRow:
    """Single row of the shared overlay model, rendered to both text and HTML."""

    label: str = ""
    measurement_id: str = ""
    value: float | None = None
    unit: str = ""
    param_id: str | None = None
    norm_value: float | None = None
    indent: str = ""
    unit_attached: bool = False
    plain_override: str = ""
    html_override: str = ""
    in_text: bool = True
    in_html: bool = True

    def formatted_value(self) -> str:
        if self.value is None:
            return ""
        return format_measurement(self.measurement_id, self.value, self.unit)

    def render_text(self) -> str:
        if self.plain_override:
            return self.plain_override
        val_str = self.formatted_value()
        suffix = self.unit if self.unit_attached else (f" {self.unit}" if self.unit else "")
        return f"{self.indent}{self.label}: {val_str}{suffix}"

    def render_html(self, *, sex_male: bool = True) -> str:
        if self.html_override:
            return self.html_override
        val_str = self.formatted_value()
        return _format_html_line(
            self.label,
            val_str,
            self.unit,
            numeric_value=self.norm_value if self.norm_value is not None else (self.value or 0.0),
            param_id=self.param_id,
            sex_male=sex_male,
        )


def _flow_results_for_display(doppler: DopplerResults) -> tuple[DopplerFlowResult, ...]:
    """Use specific results, with a compatibility projection for old snapshots."""
    if doppler.flow_results:
        return doppler.flow_results
    fallback: list[DopplerFlowResult] = []
    if any(
        value is not None
        for value in (
            doppler.vpeak_cm_s,
            doppler.pgpeak_mmhg,
            doppler.vti_cm,
            doppler.vmean_cm_s,
            doppler.pgmean_mmhg,
        )
    ):
        fallback.append(
            DopplerFlowResult(
                site="AV",
                vmax_cm_s=doppler.vpeak_cm_s,
                pgmax_mmhg=doppler.pgpeak_mmhg,
                vti_cm=doppler.vti_cm,
                vmean_cm_s=doppler.vmean_cm_s,
                pgmean_mmhg=doppler.pgmean_mmhg,
            )
        )
    if doppler.tr_vmax_cm_s is not None:
        fallback.append(DopplerFlowResult(site="TR", vmax_cm_s=doppler.tr_vmax_cm_s))
    return tuple(fallback)


def _push(
    rows: list[OverlayRow],
    label: str,
    measurement_id: str,
    value: float | None,
    unit: str,
    *,
    param_id: str | None = None,
    norm_value: float | None = None,
    in_text: bool = True,
    in_html: bool = True,
) -> None:
    if value is None:
        return
    rows.append(
        OverlayRow(
            label=label,
            measurement_id=measurement_id,
            value=value,
            unit=unit,
            param_id=param_id,
            norm_value=norm_value,
            in_text=in_text,
            in_html=in_html,
        )
    )


def _push_velocity(
    rows: list[OverlayRow],
    label: str,
    measurement_id: str,
    velocity_cm_s: float | None,
    mode: str,
    *,
    param_id: str | None = None,
    norm_value: float | None = None,
) -> None:
    if velocity_cm_s is None:
        return
    scaled, unit, _ = scale_velocity_for_display(velocity_cm_s, mode, measurement_id=measurement_id)
    _push(
        rows,
        label,
        measurement_id,
        scaled,
        unit,
        param_id=param_id,
        norm_value=norm_value,
    )


def _build_doppler_rows(
    rows: list[OverlayRow],
    snapshot: MeasurementSnapshot,
    *,
    time_calibrated: bool,
) -> None:
    dop = snapshot.doppler
    if dop is None:
        return
    ddop = snapshot.display_doppler or dop
    _push(rows, _label("result.mv_e"), "mv.e", ddop.e_cm_s, "cm/s", param_id="ea_ratio")
    _push(rows, _label("result.mv_a"), "mv.a", ddop.a_cm_s, "cm/s", param_id="ea_ratio")
    _push(rows, _label("result.mv_ea_ratio"), "mv.ea", dop.e_a_ratio, "", param_id="ea_ratio")
    if time_calibrated:
        _push(rows, _label("result.doppler_heart_rate"), "hr", ddop.heart_rate_bpm, tr("unit.bpm"))
        _push(rows, _label("result.mv_dt"), "mv.dt", ddop.dt_ms, "ms", param_id="dt")
        _push(rows, _label("result.ivrt"), "lv.ivrt", ddop.ivrt_ms, "ms", param_id="dt")
        _push(rows, tr("result.at"), "mv.at", ddop.at_ms, "ms", param_id="dt")
    _push(rows, _label("result.e_prime_sept"), "tdi.e_sept", ddop.e_prime_sept_cm_s, "cm/s", param_id="e_prime_sept")
    _push(rows, _label("result.e_prime_lat"), "tdi.e_lat", ddop.e_prime_lat_cm_s, "cm/s", param_id="e_prime_lat")
    _push(rows, _label("result.e_prime_avg"), "tdi.e_avg", dop.e_prime_avg_cm_s, "cm/s", param_id="e_e_prime_avg")
    _push(rows, _label("result.e_over_e_prime"), "mv.e_e_avg", dop.e_over_e_prime, "", param_id="e_e_prime_avg")
    _push(
        rows,
        _label("result.e_over_e_prime_sept"),
        "tdi.e_e_sept",
        dop.e_over_e_prime_sept,
        "",
        param_id="e_e_prime_avg",
    )
    _push(
        rows,
        _label("result.e_over_e_prime_lat"),
        "tdi.e_e_lat",
        dop.e_over_e_prime_lat,
        "",
        param_id="e_e_prime_avg",
    )
    _push(
        rows,
        _label("result.e_prime_over_a_prime"),
        "tdi.e_a_prime",
        dop.e_prime_over_a_prime,
        "",
        param_id="e_e_prime_avg",
    )
    _push(
        rows, _label("result.s_prime_sept"), "tdi.s_prime_sept", ddop.s_prime_sept_cm_s, "cm/s", param_id="s_prime_sept"
    )
    _push(rows, _label("result.s_prime_lat"), "tdi.s_prime_lat", ddop.s_prime_lat_cm_s, "cm/s", param_id="s_prime_lat")
    _push(rows, _label("result.s_prime_rv"), "rv.s_prime", ddop.s_prime_rv_cm_s, "cm/s", param_id="s_prime_rv")

    for flow in _flow_results_for_display(ddop):
        param_id = "tr_vmax" if flow.site == "TR" else None
        _push_velocity(
            rows,
            f"{flow.site} Vmax",
            flow_measurement_id(flow.site, "Vmax"),
            flow.vmax_cm_s,
            flow.mode,
            param_id=param_id,
            norm_value=flow.vmax_cm_s / 100.0 if (flow.site == "TR" and flow.vmax_cm_s is not None) else None,
        )
        _push(rows, f"{flow.site} PGmax", flow_measurement_id(flow.site, "PGmax"), flow.pgmax_mmhg, "mmHg")
        if time_calibrated:
            _push(rows, f"{flow.site} VTI", flow_measurement_id(flow.site, "VTI"), flow.vti_cm, "cm")
            _push_velocity(
                rows,
                f"{flow.site} Vmean",
                flow_measurement_id(flow.site, "Vmean"),
                flow.vmean_cm_s,
                flow.mode,
            )
            _push(rows, f"{flow.site} PGmean", flow_measurement_id(flow.site, "PGmean"), flow.pgmean_mmhg, "mmHg")

    if time_calibrated:
        for row_label, attr, measurement_id in _TIMED_DOPPLER_ROWS:
            _push(rows, row_label, measurement_id, getattr(ddop, attr), "ms")


def _build_chamber_rows(rows: list[OverlayRow], snapshot: MeasurementSnapshot) -> None:
    volume_unit = "mL" if snapshot.spacing_calibrated else "px³"

    lvef = snapshot.lvef
    if lvef is not None:
        if lvef.a4c and lvef.a4c.edv_ml is not None:
            _push(
                rows,
                _view("kdo", "4C"),
                view_measurement_id("kdo", "4C"),
                lvef.a4c.edv_ml,
                volume_unit,
                param_id="lvedvi",
            )
        if lvef.a4c and lvef.a4c.esv_ml is not None:
            _push(
                rows,
                _view("kso", "4C"),
                view_measurement_id("kso", "4C"),
                lvef.a4c.esv_ml,
                volume_unit,
                param_id="lvesvi",
            )
        if lvef.a2c and lvef.a2c.edv_ml is not None:
            _push(
                rows,
                _view("kdo", "2C"),
                view_measurement_id("kdo", "2C"),
                lvef.a2c.edv_ml,
                volume_unit,
                param_id="lvedvi",
            )
        if lvef.a2c and lvef.a2c.esv_ml is not None:
            _push(
                rows,
                _view("kso", "2C"),
                view_measurement_id("kso", "2C"),
                lvef.a2c.esv_ml,
                volume_unit,
                param_id="lvesvi",
            )
        if lvef.edv_bi_ml is not None:
            _push(rows, _label("panel.kdo_lv_bp"), "lv.edv_bp", lvef.edv_bi_ml, volume_unit, param_id="lvedvi")
        if lvef.esv_bi_ml is not None:
            _push(rows, _label("panel.kso_lv_bp"), "lv.esv_bp", lvef.esv_bi_ml, volume_unit, param_id="lvesvi")
        _push(rows, tr("panel.lvef"), "lv.ef_bp", lvef.lvef_percent, "%", param_id="lvef")
        if lvef.sv_ml is not None:
            _push(rows, _label("result.lv_sv_simpson"), "lv.sv", lvef.sv_ml, volume_unit, param_id="lv.sv")

    teich = snapshot.teichholz
    if teich is not None:
        _push(rows, _label("result.lvedv_teich"), "lv.edv_teich", teich.edv_ml, volume_unit, param_id="lvedvi")
        _push(rows, _label("result.lvesv_teich"), "lv.esv_teich", teich.esv_ml, volume_unit, param_id="lvesvi")
        _push(rows, _label("result.lvef_teich"), "lv.ef_teich", teich.lvef_percent, "%", param_id="lvef")
        if teich.sv_ml is not None:
            _push(rows, _label("result.lv_sv_teich"), "lv.sv", teich.sv_ml, volume_unit, param_id="lv.sv")

    if snapshot.lvm_g is not None:
        _push(rows, _label("panel.lv_mass"), "lv.mass", snapshot.lvm_g, "g", param_id="lvm")

    if snapshot.rwt is not None:
        _push(rows, _label("result.rwt"), "lv.rwt", snapshot.rwt, "", param_id="rwt")

    la = snapshot.la_simpson
    if la is not None:
        lav_4c = es_volume_from_view(la.a4c)
        if lav_4c is not None:
            _push(rows, _label("panel.lav_4c_short"), "la.lav_a4c", lav_4c, volume_unit, param_id="la_vol_index")
        lav_bi = biplane_es_volume_ml(la.a4c, la.a2c)
        if lav_bi is not None:
            _push(rows, _label("panel.lav_bi_short"), "la.lav_bp", lav_bi, volume_unit, param_id="la_vol_index")
        if la.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _push(rows, _label("panel.s_la"), "la.area", la.area_cm2, area_unit, param_id="la_vol_index")
    elif snapshot.la_volume and snapshot.la_volume.volume_ml is not None:
        _push(rows, tr("result.lav"), "la.lav_al", snapshot.la_volume.volume_ml, volume_unit, param_id="la_vol_index")

    ra = snapshot.ra_simpson
    if ra is not None:
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        if rav is not None:
            _push(rows, _label("result.rav_4c"), "ra.vol", rav, volume_unit, param_id="ra_area")
        if ra.area_cm2 is not None:
            area_unit = "cm²" if snapshot.spacing_calibrated else "px²"
            _push(rows, _label("panel.s_ra"), "ra.area", ra.area_cm2, area_unit, param_id="ra_area")

    if snapshot.rv_fac_percent is not None:
        _push(rows, _label("result.fac"), "rv.fac", snapshot.rv_fac_percent, "%", param_id="fac")

    if snapshot.diastology_grade:
        rows.append(
            OverlayRow(
                plain_override=snapshot.diastology_grade,
                html_override=f'<span style="color:{_COLOR_LABEL};">{snapshot.diastology_grade}</span>',
            )
        )


def _build_indexed_rows(rows: list[OverlayRow], snapshot: MeasurementSnapshot) -> None:
    for item in build_indexed_overlay_rows(snapshot):
        rows.append(
            OverlayRow(
                label=item.label,
                measurement_id=item.measurement_id,
                value=item.value,
                unit=item.unit,
                param_id=item.param_id,
                in_text=item.always_in_text or item.abnormal,
                in_html=True,
            )
        )


def _build_custom_rows(
    rows: list[OverlayRow],
    snapshot: MeasurementSnapshot,
    *,
    length_display_unit: str,
) -> None:
    for item in snapshot.planimeter:
        measurement_id = (
            "planimeter.area"
            if item.kind == "area"
            else ("planimeter.volume" if item.kind == "volume" else "planimeter.length")
        )
        _push(rows, item.label, measurement_id, item.value, item.unit)

    last_index_by_label: dict[str, int] = {}
    for index, measurement in enumerate(snapshot.linear_measurements):
        last_index_by_label[measurement.label] = index

    for index, measurement in enumerate(snapshot.linear_measurements):
        is_latest_for_label = last_index_by_label.get(measurement.label) == index
        plain_line = f"  {measurement.display_text(length_unit=length_display_unit)}"

        if measurement.doppler or measurement.time_ms is not None or measurement.millimeter_length is None:
            text = measurement.display_text(length_unit=length_display_unit)
            rows.append(
                OverlayRow(
                    plain_override=plain_line,
                    html_override=f'<span style="color:{_COLOR_NORMAL};">{text}</span>',
                    in_text=True,
                    in_html=is_latest_for_label,
                )
            )
            continue

        display_label = measurement.label
        i18n_key = _LABEL_I18N_KEY.get(measurement.label)
        if i18n_key:
            display_label = tr(i18n_key)

        if measurement.label in PERCENT_LABELS:
            rows.append(
                OverlayRow(
                    label=display_label,
                    measurement_id="caliper.stenosis_pct",
                    value=measurement.millimeter_length,
                    unit="%",
                    indent="  ",
                    unit_attached=True,
                    in_text=True,
                    in_html=is_latest_for_label,
                )
            )
            continue

        if measurement.label in ("S1", "S2"):
            rows.append(
                OverlayRow(
                    label=display_label,
                    measurement_id="caliper.area",
                    value=measurement.millimeter_length,
                    unit="cm²",
                    indent="  ",
                    in_text=True,
                    in_html=is_latest_for_label,
                )
            )
            continue

        target_unit = "cm" if length_display_unit == "cm" else "mm"
        length_value = measurement.millimeter_length / 10.0 if target_unit == "cm" else measurement.millimeter_length
        caliper_id = (
            "caliper.length_submm"
            if measurement.submillimeter
            else (measurement_for_caliper(measurement.label) or "caliper.length")
        )
        caliper_param_id = _CALIPER_PARAM_ID_MAP.get(measurement.label.casefold())
        rows.append(
            OverlayRow(
                label=display_label,
                measurement_id=caliper_id,
                value=length_value,
                unit=target_unit,
                param_id=caliper_param_id,
                indent="  ",
                in_text=True,
                in_html=is_latest_for_label,
            )
        )

    for vessel in snapshot.vessel_measurements:
        _push(rows, "PSV", "vessel.psv", vessel.psv_cm_s, "cm/s", in_text=False)
        _push(rows, "EDV", "vessel.edv", vessel.edv_cm_s, "cm/s", in_text=False)
        _push(rows, "RI", "vessel.ri", vessel.ri, "", in_text=False)
        _push(rows, "S/D", "vessel.sd", vessel.sd, "", in_text=False)
        _push(rows, "MV≈", "vessel.mv", vessel.mv_approx, "cm/s", in_text=False)


def build_overlay_rows(
    snapshot: MeasurementSnapshot | None,
    *,
    time_calibrated: bool = False,
    amplitude_only: bool | None = None,
    length_display_unit: str = "mm",
) -> tuple[OverlayRow, ...]:
    """Build the shared overlay rows used by both text and HTML formatters."""
    if amplitude_only is not None:
        time_calibrated = not amplitude_only
    if snapshot is None:
        return ()

    rows: list[OverlayRow] = []
    _build_doppler_rows(rows, snapshot, time_calibrated=time_calibrated)
    _build_chamber_rows(rows, snapshot)
    _build_indexed_rows(rows, snapshot)
    _build_custom_rows(rows, snapshot, length_display_unit=length_display_unit)
    return tuple(rows)


def format_results_overlay(
    snapshot: MeasurementSnapshot | None,
    *,
    time_calibrated: bool = False,
    amplitude_only: bool | None = None,
    length_display_unit: str = "mm",
) -> str:
    """Return multi-line summary of session-computed values (study-wide)."""
    rows = build_overlay_rows(
        snapshot,
        time_calibrated=time_calibrated,
        amplitude_only=amplitude_only,
        length_display_unit=length_display_unit,
    )
    return "\n".join(row.render_text() for row in rows if row.in_text)


def format_results_overlay_html(
    snapshot: MeasurementSnapshot | None,
    *,
    time_calibrated: bool = False,
    amplitude_only: bool | None = None,
    length_display_unit: str = "mm",
    sex_male: bool = True,
) -> str:
    """Return HTML summary with colored out-of-range values and clickable links."""
    rows = build_overlay_rows(
        snapshot,
        time_calibrated=time_calibrated,
        amplitude_only=amplitude_only,
        length_display_unit=length_display_unit,
    )
    return "<br>".join(row.render_html(sex_male=sex_male) for row in rows if row.in_html)


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


def _norm_for_param(param_id: str, sex_male: bool = True) -> NormRange | None:
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
    except Exception as exc:  # noqa: BLE001
        logger.debug("norm lookup failed (%s)", type(exc).__name__)
    return None


def _is_outside(norm: NormRange | None, value: float) -> bool:
    if norm is None:
        return False
    if norm.low is not None and value < norm.low:
        return True
    if norm.high is not None and value > norm.high:
        return True
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


def _format_html_line(
    label: str,
    val_str: str,
    suffix: str,
    *,
    numeric_value: float,
    param_id: str | None = None,
    sex_male: bool = True,
) -> str:
    unit = f" {suffix}" if suffix else ""
    if param_id:
        label_html = f'<a href="{param_id}" style="color:{_COLOR_LABEL}; text-decoration:none;">{label}</a>'
    else:
        label_html = f'<span style="color:{_COLOR_LABEL};">{label}</span>'

    norm = _norm_for_param(param_id, sex_male) if param_id else None
    if _is_outside(norm, numeric_value):
        val_html = f'<span style="color:{_COLOR_ABNORMAL};">{val_str}</span>'
    else:
        val_html = f'<span style="color:{_COLOR_NORMAL};">{val_str}</span>'

    return f'{label_html}: {val_html} <span style="color:{_COLOR_UNIT};">{unit}</span>'


def _default_measurement_id_for_unit(suffix: str) -> str:
    return "mv.ea" if suffix == "" else "doppler.vmax"


def _append(
    lines: list[str],
    label: str,
    value: float | None,
    suffix: str,
    *,
    measurement_id: str | None = None,
) -> None:
    if value is None:
        return
    unit = f" {suffix}" if suffix else ""
    resolved_id = measurement_id or measurement_for_caliper(label) or _default_measurement_id_for_unit(suffix)
    val_str = format_measurement(resolved_id, value, suffix)
    lines.append(f"{label}: {val_str}{unit}")


def _html_append(
    parts: list[str],
    label: str,
    value: float | None,
    suffix: str,
    *,
    measurement_id: str | None = None,
    param_id: str | None = None,
    sex_male: bool = True,
    norm_value: float | None = None,
) -> None:
    if value is None:
        return
    resolved_id = measurement_id or measurement_for_caliper(label) or _default_measurement_id_for_unit(suffix)
    val_str = format_measurement(resolved_id, value, suffix)
    parts.append(
        _format_html_line(
            label,
            val_str,
            suffix,
            numeric_value=norm_value if norm_value is not None else value,
            param_id=param_id,
            sex_male=sex_male,
        )
    )
