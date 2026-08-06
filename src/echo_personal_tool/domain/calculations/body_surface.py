"""Body surface area and indexed echocardiography measurements."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    IndexedMeasurements,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)

_INDEXED_LINEAR_LABELS = frozenset(
    {
        "lvedd",
        "lvesd",
        "la",
        "lal",
        "ra",
        "rv basal",
        "tapse",
        "lvot",
        "lvotd",
        "av",
        "annulus",
        "ao sinus",
        "ao junction",
        "prox ao",
    }
)


def bsa_du_bois_m2(height_cm: float, weight_kg: float) -> float | None:
    """Du Bois body surface area from height (cm) and weight (kg)."""
    if height_cm <= 0.0 or weight_kg <= 0.0:
        return None
    return 0.007184 * (height_cm**0.725) * (weight_kg**0.425)


def compute_indexed_measurements(
    snapshot: MeasurementSnapshot,
    *,
    height_cm: float | None,
    weight_kg: float | None,
) -> IndexedMeasurements | None:
    """Derive BSA-normalized volumes and diameters when height and weight are set."""
    if height_cm is None or weight_kg is None:
        return None
    bsa = bsa_du_bois_m2(height_cm, weight_kg)
    if bsa is None or bsa <= 0.0:
        return None

    simpson_edv, simpson_esv = _combined_simpson_volumes(snapshot.lvef)
    teich = snapshot.teichholz
    la = snapshot.la_simpson
    ra = snapshot.ra_simpson

    lav_4c = _chamber_es_volume(la.a4c) if la is not None else None
    lav_bi = _biplane_es_volume(la.a4c, la.a2c) if la is not None else None
    lav_area_length = (
        snapshot.la_volume.volume_ml if snapshot.la_volume and snapshot.la_volume.volume_ml is not None else None
    )
    rav = None
    if ra is not None:
        rav = _chamber_es_volume(ra.a4c) or ra.max_volume_ml

    linear_indexed = _indexed_linear_measurements(snapshot.linear_measurements, bsa)
    lvmi = _index_volume(snapshot.lvm_g, bsa) if snapshot.lvm_g is not None else None

    a4c_edvi = a4c_esvi = a2c_edvi = a2c_esvi = None
    if snapshot.lvef is not None:
        if snapshot.lvef.a4c is not None:
            a4c_edvi = _index_volume(snapshot.lvef.a4c.edv_ml, bsa)
            a4c_esvi = _index_volume(snapshot.lvef.a4c.esv_ml, bsa)
        if snapshot.lvef.a2c is not None:
            a2c_edvi = _index_volume(snapshot.lvef.a2c.edv_ml, bsa)
            a2c_esvi = _index_volume(snapshot.lvef.a2c.esv_ml, bsa)

    return IndexedMeasurements(
        bsa_m2=bsa,
        simpson_edvi_ml_m2=_index_volume(simpson_edv, bsa),
        simpson_esvi_ml_m2=_index_volume(simpson_esv, bsa),
        teichholz_edvi_ml_m2=_index_volume(teich.edv_ml, bsa) if teich else None,
        teichholz_esvi_ml_m2=_index_volume(teich.esv_ml, bsa) if teich else None,
        lav_4c_index_ml_m2=_index_volume(lav_4c, bsa),
        lav_bi_index_ml_m2=_index_volume(lav_bi, bsa),
        lav_area_length_index_ml_m2=_index_volume(lav_area_length, bsa),
        rav_index_ml_m2=_index_volume(rav, bsa),
        lvmi_g_m2=lvmi,
        simpson_a4c_edvi_ml_m2=a4c_edvi,
        simpson_a4c_esvi_ml_m2=a4c_esvi,
        simpson_a2c_edvi_ml_m2=a2c_edvi,
        simpson_a2c_esvi_ml_m2=a2c_esvi,
        linear_index_mm_m2=linear_indexed,
    )


def _index_volume(volume_ml: float | None, bsa_m2: float) -> float | None:
    if volume_ml is None or volume_ml <= 0.0:
        return None
    return volume_ml / bsa_m2


def _index_linear(length_mm: float, bsa_m2: float) -> float:
    return length_mm / bsa_m2


def _combined_simpson_volumes(lvef: LvefResult | None) -> tuple[float | None, float | None]:
    if lvef is None:
        return None, None
    edv_values: list[float] = []
    esv_values: list[float] = []
    for metrics in (lvef.a4c, lvef.a2c):
        if metrics is None:
            continue
        if metrics.edv_ml is not None and metrics.edv_ml > 0.0:
            edv_values.append(metrics.edv_ml)
        if metrics.esv_ml is not None and metrics.esv_ml > 0.0:
            esv_values.append(metrics.esv_ml)
    edv = sum(edv_values) / len(edv_values) if edv_values else None
    esv = sum(esv_values) / len(esv_values) if esv_values else None
    return edv, esv


def _chamber_es_volume(metrics: LvViewMetrics | None) -> float | None:
    if metrics is None:
        return None
    if metrics.esv_ml is not None and metrics.esv_ml > 0.0:
        return metrics.esv_ml
    if metrics.edv_ml is not None and metrics.edv_ml > 0.0:
        return metrics.edv_ml
    return None


def _biplane_es_volume(
    a4c: LvViewMetrics | None,
    a2c: LvViewMetrics | None,
) -> float | None:
    values: list[float] = []
    for metrics in (a4c, a2c):
        esv = _chamber_es_volume(metrics)
        if esv is not None:
            values.append(esv)
    if len(values) == 2:
        return sum(values) / 2.0
    return None


def _indexed_linear_measurements(
    measurements: tuple[LinearMeasurement, ...],
    bsa_m2: float,
) -> tuple[tuple[str, float], ...]:
    indexed: list[tuple[str, float]] = []
    for measurement in measurements:
        if measurement.millimeter_length is None:
            continue
        if measurement.label.casefold() not in _INDEXED_LINEAR_LABELS:
            continue
        indexed.append(
            (
                measurement.label,
                _index_linear(measurement.millimeter_length, bsa_m2),
            )
        )
    return tuple(indexed)
