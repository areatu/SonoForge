"""Сборка проекции исследования из снимка измерений (TP-3 PR-2b, §8.6, S-11).

Чистая функция: снимок измерений (тот же агрегат, что читает отчёт) плюс
контекст вкладки превращаются в :class:`StudyProjection` для ``progress()`` и
``ToolStatusProvider``.

Происхождение значения: ключ, который текущий протокол «заработал» (передан в
``authored``), получает ``origin = protocol_id`` — тогда шаг считается
выполненным. Всё остальное — вне протокола (``↗``).  Метка калипера → id
измерения берётся из единого источника :data:`CALIPER_TO_MEASUREMENT`
(``domain.measurement_catalog``).

Срез не выдумывает клинические соответствия: ключи, которые он собирает,
перечислены в :data:`MAPPED_KEYS`; остальные ключи шести протоколов —
в :data:`UNMAPPED_KEYS` с причиной (допплер, объёмы полостей и производные
калькуляторов придут отдельными срезами). Тест
``test_protocol_keys_are_all_classified`` не даёт этому списку молча устареть.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ..measurement_catalog import REQ_SPATIAL, measurement_for_caliper
from ..models.measurements import MeasurementSnapshot
from ..protocols import ProjectionValue, StudyProjection

#: Ключи каталога, которые этот срез кладёт в проекцию из снимка.
MAPPED_KEYS: frozenset[str] = frozenset(
    {
        # П1 — линейные размеры ЛЖ (метки калиперов).
        "lv.ivsd",
        "lv.lvedd",
        "lv.lvpwd",
        "lv.lvesd",
        # П2 — объёмы Симпсона по позициям и биплан.
        "lv.edv_a4c",
        "lv.esv_a4c",
        "lv.edv_a2c",
        "lv.esv_a2c",
        "lv.edv_bp",
        "lv.esv_bp",
        "lv.ef_bp",
        # П1 — производные карточки (масса, ОТС, индекс).
        "lv.mass",
        "lv.rwt",
        "lv.mass_i",
    }
)

_UNMAPPED_DOPPLER = "спектральные допплер-значения — маппинг потоков снимка отдельным срезом"
_UNMAPPED_CHAMBER = "объёмы полостей (ЛП/ПП) — отдельный срез"
_UNMAPPED_DERIVED = "производные результатов — снимок калькуляторов отдельным срезом"

#: Ключи протоколов, которые срез сознательно не собирает, с причиной.
UNMAPPED_KEYS: Mapping[str, str] = MappingProxyType(
    {
        "la.lav_a4c": _UNMAPPED_CHAMBER,
        "la.lav_a2c": _UNMAPPED_CHAMBER,
        "la.lav_bp": _UNMAPPED_CHAMBER,
        "la.ap": _UNMAPPED_CHAMBER,
        "la.lavi": _UNMAPPED_CHAMBER,
        "ra.rap": _UNMAPPED_CHAMBER,
        "mv.e": _UNMAPPED_DOPPLER,
        "mv.a": _UNMAPPED_DOPPLER,
        "mv.dt": _UNMAPPED_DOPPLER,
        "lv.ivrt": _UNMAPPED_DOPPLER,
        "tdi.e_sept": _UNMAPPED_DOPPLER,
        "tdi.e_lat": _UNMAPPED_DOPPLER,
        "tr.vmax": _UNMAPPED_DOPPLER,
        "lvot.d": _UNMAPPED_DOPPLER,
        "lvot.vti": _UNMAPPED_DOPPLER,
        "av.vmax": _UNMAPPED_DOPPLER,
        "av.vti": _UNMAPPED_DOPPLER,
        "lv.fs": _UNMAPPED_DERIVED,
        "lv.sv": _UNMAPPED_DERIVED,
        "lv.svi": _UNMAPPED_DERIVED,
        "lv.edvi_bp": _UNMAPPED_DERIVED,
        "lv.esvi_bp": _UNMAPPED_DERIVED,
        "mv.ea": _UNMAPPED_DERIVED,
        "tdi.e_avg": _UNMAPPED_DERIVED,
        "mv.e_e_avg": _UNMAPPED_DERIVED,
        "tdi.e_e_sept": _UNMAPPED_DERIVED,
        "tdi.e_e_lat": _UNMAPPED_DERIVED,
        "av.pg_peak": _UNMAPPED_DERIVED,
        "av.pg_mean": _UNMAPPED_DERIVED,
        "av.ava_vti": _UNMAPPED_DERIVED,
        "av.avai": _UNMAPPED_DERIVED,
        "av.dvi": _UNMAPPED_DERIVED,
        "tr.pg": _UNMAPPED_DERIVED,
        "pa.pasp": _UNMAPPED_DERIVED,
    }
)


def unmet_requirements(snapshot: MeasurementSnapshot) -> frozenset[str]:
    """Известные незакрытые требования снимка (``StudyProjection.unmet``).

    Пока снимок не откалиброван по масштабу, шаг, требующий пространственной
    калибровки (``REQ_SPATIAL``), получает ``locked`` с причиной.  Пустой
    набор ничего не блокирует — блокировка требует знания о проблеме.
    """
    if not snapshot.spacing_calibrated:
        return frozenset({REQ_SPATIAL})
    return frozenset()


def build_study_projection(
    snapshot: MeasurementSnapshot,
    *,
    protocol_id: str = "",
    authored: frozenset[str] = frozenset(),
    clip_modes: frozenset[str] = frozenset(),
    clip_view: str = "",
    unmet: frozenset[str] | None = None,
) -> StudyProjection:
    """Проекция исследования по снимку измерений.

    ``authored`` — ключи, заработанные активным протоколом (``protocol_id``);
    они получают его как ``origin``.  ``clip_modes`` / ``clip_view`` описывают
    открытую вкладку; ``unmet`` — незакрытые требования (``None`` → выводятся
    из снимка через :func:`unmet_requirements`).
    """
    values: dict[str, ProjectionValue] = {}

    def add(key: str, value: float | None) -> None:
        if value is None:
            return
        origin = protocol_id if key in authored else ""
        values[key] = ProjectionValue(value=value, origin=origin)

    for measurement in snapshot.linear_measurements:
        key = measurement_for_caliper(measurement.label)
        if key is not None:
            add(key, measurement.millimeter_length)

    lvef = snapshot.lvef
    if lvef is not None:
        if lvef.a4c is not None:
            add("lv.edv_a4c", lvef.a4c.edv_ml)
            add("lv.esv_a4c", lvef.a4c.esv_ml)
        if lvef.a2c is not None:
            add("lv.edv_a2c", lvef.a2c.edv_ml)
            add("lv.esv_a2c", lvef.a2c.esv_ml)
        add("lv.edv_bp", lvef.edv_bi_ml)
        add("lv.esv_bp", lvef.esv_bi_ml)
        add("lv.ef_bp", lvef.lvef_percent)

    add("lv.mass", snapshot.lvm_g)
    add("lv.rwt", snapshot.rwt)
    if snapshot.indexed is not None:
        add("lv.mass_i", snapshot.indexed.lvmi_g_m2)

    return StudyProjection(
        values=values,
        clip_modes=clip_modes,
        clip_view=clip_view,
        unmet=unmet_requirements(snapshot) if unmet is None else unmet,
    )
