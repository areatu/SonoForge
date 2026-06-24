"""Study-wide measurement report text (latest value per parameter)."""

from __future__ import annotations

from dataclasses import replace

from echo_personal_tool.domain.calculations.chamber_simpson import (
    biplane_es_volume_ml,
    es_volume_from_view,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    LvViewMetrics,
    MeasurementSnapshot,
)


def dedupe_linear_measurements_latest(
    measurements: tuple[LinearMeasurement, ...],
) -> tuple[LinearMeasurement, ...]:
    """Keep the last measurement for each label (study report)."""
    by_label: dict[str, LinearMeasurement] = {}
    for measurement in measurements:
        by_label[measurement.label] = measurement
    return tuple(by_label.values())


def format_measurement_report(
    snapshot: MeasurementSnapshot | None,
    *,
    length_display_unit: str = "mm",
) -> str:
    """Return multi-section study report; duplicate labels show latest only."""
    if snapshot is None:
        return "Нет измерений."

    report_snapshot = snapshot
    if snapshot.linear_measurements:
        report_snapshot = replace(
            snapshot,
            linear_measurements=dedupe_linear_measurements_latest(snapshot.linear_measurements),
        )

    sections: list[list[str]] = []
    for section in (
        _format_doppler_section(report_snapshot),
        _format_lvef_section(report_snapshot, length_display_unit=length_display_unit),
        _format_teichholz_section(report_snapshot),
        _format_la_section(report_snapshot),
        _format_ra_section(report_snapshot),
        _format_rv_section(report_snapshot),
        _format_lvm_section(report_snapshot),
        _format_diastology_section(report_snapshot),
        _format_planimeter_section(report_snapshot),
        _format_linear_section(report_snapshot, length_display_unit=length_display_unit),
        _format_indexed_section(report_snapshot),
    ):
        if section:
            sections.append(section)

    if not sections:
        return "Нет измерений."

    lines: list[str] = ["Результаты измерений", ""]
    for index, section in enumerate(sections):
        if index > 0:
            lines.append("")
        lines.extend(section)
    return "\n".join(lines)


def _format_doppler_section(snapshot: MeasurementSnapshot) -> list[str]:
    doppler = snapshot.doppler
    if doppler is None:
        return []

    field_lines = [
        _optional_line("E", doppler.e_cm_s, " cm/s"),
        _optional_line("A", doppler.a_cm_s, " cm/s"),
        _optional_line("E/A", doppler.e_a_ratio, decimals=2),
        _optional_line("DT", doppler.dt_ms, " ms"),
        _optional_line("IVRT", doppler.ivrt_ms, " ms"),
        _optional_line("AT", doppler.at_ms, " ms"),
        _optional_line("e' sept", doppler.e_prime_sept_cm_s, " cm/s"),
        _optional_line("e' lat", doppler.e_prime_lat_cm_s, " cm/s"),
        _optional_line("e' mean", doppler.e_prime_avg_cm_s, " cm/s"),
        _optional_line("E/e'", doppler.e_over_e_prime, decimals=2),
        _optional_line("E/e' sept", doppler.e_over_e_prime_sept, decimals=2),
        _optional_line("E/e' lat", doppler.e_over_e_prime_lat, decimals=2),
        _optional_line("e'/a'", doppler.e_prime_over_a_prime, decimals=2),
        _optional_line("Vpeak", doppler.vpeak_cm_s, " cm/s"),
        _optional_line("PGpeak", doppler.pgpeak_mmhg, " mmHg"),
        _optional_line("TR Vmax", doppler.tr_vmax_cm_s, " cm/s"),
        _optional_line("VTI", doppler.vti_cm, " cm"),
        _optional_line("Vmean", doppler.vmean_cm_s, " cm/s"),
        _optional_line("PGmean", doppler.pgmean_mmhg, " mmHg"),
    ]
    lines = [line for line in field_lines if line is not None]
    if not lines:
        return []
    return ["Допплер", *lines]


def _format_lvef_section(
    snapshot: MeasurementSnapshot,
    *,
    length_display_unit: str = "mm",
) -> list[str]:
    lvef = snapshot.lvef
    if lvef is None:
        return []

    volume_suffix = " mL" if snapshot.spacing_calibrated else " px³"
    if snapshot.spacing_calibrated:
        length_suffix = " cm" if length_display_unit == "cm" else " mm"
        length_scale = 0.1 if length_display_unit == "cm" else 1.0
    else:
        length_suffix = " px"
        length_scale = 1.0
    lines = ["Объёмы ЛЖ (Симпсон)"]
    if not snapshot.spacing_calibrated:
        lines.append("  (нет PixelSpacing — длина в px, объём в px³)")

    for view_label, metrics in (("4C", lvef.a4c), ("2C", lvef.a2c)):
        if metrics is None:
            continue
        length = metrics.length_ed_mm if metrics.length_ed_mm is not None else metrics.length_es_mm
        if length is not None:
            length = length * length_scale
        length_line = _optional_line(f"Длина ЛЖ {view_label}", length, length_suffix)
        if length_line:
            lines.append(length_line)
        kdo = _optional_line(f"КДО ЛЖ {view_label}", metrics.edv_ml, volume_suffix)
        if kdo:
            lines.append(kdo)
        kso = _optional_line(f"КСО ЛЖ {view_label}", metrics.esv_ml, volume_suffix)
        if kso:
            lines.append(kso)

    lvef_line = _optional_line("ФВ ЛЖ", lvef.lvef_percent, " %")
    if lvef_line:
        lines.append(lvef_line)
    if lvef.method is not None:
        lines.append(f"  Метод: {lvef.method}")
    return lines if len(lines) > 1 else []


def _format_teichholz_section(snapshot: MeasurementSnapshot) -> list[str]:
    teichholz = snapshot.teichholz
    if teichholz is None:
        return []
    return [
        "Объёмы ЛЖ (Teichholz)",
        _line("КДО", teichholz.edv_ml, " mL"),
        _line("КСО", teichholz.esv_ml, " mL"),
        _line("ФВ", teichholz.lvef_percent, " %"),
    ]


def _format_la_section(snapshot: MeasurementSnapshot) -> list[str]:
    la = snapshot.la_simpson
    if la is None and (snapshot.la_volume is None or snapshot.la_volume.volume_ml is None):
        return []

    volume_suffix = " mL" if snapshot.spacing_calibrated else " px³"
    area_suffix = " cm²" if snapshot.spacing_calibrated else " px²"
    lines = ["Левое предсердие"]
    if la is not None:
        lav_4c = es_volume_from_view(la.a4c)
        lav_4c_line = _optional_line("LAV 4C", lav_4c, volume_suffix)
        if lav_4c_line:
            lines.append(lav_4c_line)
        lav_bi = biplane_es_volume_ml(la.a4c, la.a2c)
        lav_bi_line = _optional_line("LAV Bi", lav_bi, volume_suffix)
        if lav_bi_line:
            lines.append(lav_bi_line)
        area_line = _optional_line("S ЛП", la.area_cm2, area_suffix, decimals=2)
        if area_line:
            lines.append(area_line)
    elif snapshot.la_volume and snapshot.la_volume.volume_ml is not None:
        lines.append(_line("LAV", snapshot.la_volume.volume_ml, volume_suffix))
    return lines if len(lines) > 1 else []


def _format_ra_section(snapshot: MeasurementSnapshot) -> list[str]:
    ra = snapshot.ra_simpson
    if ra is None:
        return []

    volume_suffix = " mL" if snapshot.spacing_calibrated else " px³"
    area_suffix = " cm²" if snapshot.spacing_calibrated else " px²"
    lines = ["Правое предсердие"]
    area_line = _optional_line("S ПП", ra.area_cm2, area_suffix, decimals=2)
    if area_line:
        lines.append(area_line)
    rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
    rav_line = _optional_line("RAV 4C", rav, volume_suffix)
    if rav_line:
        lines.append(rav_line)
    return lines if len(lines) > 1 else []


def _format_rv_section(snapshot: MeasurementSnapshot) -> list[str]:
    lines = ["Правый желудочек"]
    if snapshot.rv_fac_percent is not None:
        lines.append(_line("FAC", snapshot.rv_fac_percent, " %"))
    rv = snapshot.rv_simpson
    if rv and rv.max_volume_ml is not None:
        lines.append(_line("Объём ПЖ", rv.max_volume_ml, " mL"))
    return lines if len(lines) > 1 else []


def _format_lvm_section(snapshot: MeasurementSnapshot) -> list[str]:
    if snapshot.lvm_g is None:
        return []
    lines = ["Масса ЛЖ", _line("LVM", snapshot.lvm_g, " g")]
    if snapshot.rwt is not None:
        lines.append(_line("ОТС", snapshot.rwt, "", decimals=2))
    return lines


def _format_diastology_section(snapshot: MeasurementSnapshot) -> list[str]:
    if not snapshot.diastology_grade:
        return []
    return ["Диастолическая функция", f"  {snapshot.diastology_grade}"]


def _format_planimeter_section(snapshot: MeasurementSnapshot) -> list[str]:
    if not snapshot.planimeter:
        return []
    lines = ["Планиметрия"]
    for item in snapshot.planimeter:
        decimals = 2 if item.kind == "area" else 1
        value_line = _optional_line(item.label, item.value, f" {item.unit}", decimals=decimals)
        if value_line:
            lines.append(value_line)
    return lines if len(lines) > 1 else []


def _format_linear_section(
    snapshot: MeasurementSnapshot,
    *,
    length_display_unit: str = "mm",
) -> list[str]:
    if not snapshot.linear_measurements:
        return []
    return [
        "Линейные измерения",
        *(
            f"  {measurement.display_text(length_unit=length_display_unit)}"
            for measurement in snapshot.linear_measurements
        ),
    ]


def _format_indexed_section(snapshot: MeasurementSnapshot) -> list[str]:
    indexed = snapshot.indexed
    if indexed is None:
        return []

    lines = ["Индексированные (BSA)"]
    lines.append(_line("BSA", indexed.bsa_m2, " m²", decimals=2))
    if snapshot.height_cm is not None and snapshot.weight_kg is not None:
        lines.append(
            f"  Рост: {snapshot.height_cm:.0f} cm, Вес: {snapshot.weight_kg:.0f} kg"
        )

    volume_fields = (
        ("LVMI", indexed.lvmi_g_m2, " g/m²"),
        ("КДО idx (Simpson)", indexed.simpson_edvi_ml_m2, " mL/m²"),
        ("КСО idx (Simpson)", indexed.simpson_esvi_ml_m2, " mL/m²"),
        ("EDVi 4C", indexed.simpson_a4c_edvi_ml_m2, " mL/m²"),
        ("ESVi 4C", indexed.simpson_a4c_esvi_ml_m2, " mL/m²"),
        ("EDVi 2C", indexed.simpson_a2c_edvi_ml_m2, " mL/m²"),
        ("ESVi 2C", indexed.simpson_a2c_esvi_ml_m2, " mL/m²"),
        ("EDVi (Teichholz)", indexed.teichholz_edvi_ml_m2, " mL/m²"),
        ("ESVi (Teichholz)", indexed.teichholz_esvi_ml_m2, " mL/m²"),
        ("LAV 4C idx", indexed.lav_4c_index_ml_m2, " mL/m²"),
        ("LAV Bi idx", indexed.lav_bi_index_ml_m2, " mL/m²"),
        ("LAV idx", indexed.lav_area_length_index_ml_m2, " mL/m²"),
        ("RAV idx", indexed.rav_index_ml_m2, " mL/m²"),
    )
    for label, value, suffix in volume_fields:
        line = _optional_line(label, value, suffix)
        if line:
            lines.append(line)

    for label, value in indexed.linear_index_mm_m2:
        line = _optional_line(f"{label} idx", value, " mm/m²", decimals=2)
        if line:
            lines.append(line)

    return lines if len(lines) > 1 else []


def _optional_line(
    label: str,
    value: float | None,
    suffix: str = "",
    *,
    decimals: int = 1,
) -> str | None:
    if value is None:
        return None
    return _line(label, value, suffix, decimals=decimals)


def _line(
    label: str,
    value: float | None,
    suffix: str = "",
    *,
    decimals: int = 1,
) -> str:
    if value is None:
        return f"  {label}: —"
    return f"  {label}: {value:.{decimals}f}{suffix}"
