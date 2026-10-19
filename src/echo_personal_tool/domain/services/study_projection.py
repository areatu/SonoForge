"""Сборка проекции исследования из снимка измерений (TP-3 PR-2b/PR-4, §8.6, S-11).

Чистая функция: снимок измерений (тот же агрегат, что читает отчёт) плюс
контекст вкладки превращаются в :class:`StudyProjection` для ``progress()`` и
``ToolStatusProvider``.

Контракт входа. Проекция не имеет отдельного DTO: её единственный вход —
:class:`MeasurementSnapshot`, потому что он уже несёт все срезы исследования,
которые читает отчёт (``TP-3 PR-4``):

* линейные измерения → ключи калиперов (:data:`CALIPER_TO_MEASUREMENT`);
* ``lvef`` → объёмы Симпсона по позициям и биплан;
* ``la_simpson`` / ``la_volume`` → объёмы ЛП и иОЛП;
* ``doppler`` → спектральные и тканевые скорости, интервалы и VTI по сайтам;
* ``calculations`` → производные (FS, SV/SVi, AVA, AVAi, DVI, градиент ТР, PASP)
  и вход ``rap`` чипов ДПП.

Сознательно не собираемые ключи перечислены в :data:`UNMAPPED_KEYS` с причиной;
сейчас список пуст — все ключи шести протоколов сведены к источнику.
Тест ``test_protocol_keys_are_all_classified`` не даёт этому списку молча
устареть и не пропускает ключ без источника.

Происхождение значения: ключ, который текущий протокол «заработал» (передан в
``authored``), получает ``origin = protocol_id`` — тогда шаг считается
выполненным. Всё остальное — вне протокола (``↗``).  Метка калипера → id
измерения берётся из единого источника :data:`CALIPER_TO_MEASUREMENT`
(``domain.measurement_catalog``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from ..calculations.chamber_simpson import biplane_es_volume_ml, es_volume_from_view
from ..measurement_catalog import REQ_SPATIAL, measurement_for_caliper
from ..models.measurements import DopplerResults, MeasurementSnapshot
from ..protocols import ProjectionValue, StudyProjection

#: Ключи каталога, которые этот срез кладёт в проекцию из снимка. Полный
#: список ключей шести протоколов: шаги, их ``satisfied_by`` и ``derived``.
MAPPED_KEYS: frozenset[str] = frozenset(
    {
        # П1 — линейные размеры ЛЖ (метки калиперов) и производные.
        "lv.ivsd",
        "lv.lvedd",
        "lv.lvpwd",
        "lv.lvesd",
        "lv.mass",
        "lv.rwt",
        "lv.mass_i",
        "lv.fs",
        # П2 — объёмы Симпсона по позициям, биплан и индексы.
        "lv.edv_a4c",
        "lv.esv_a4c",
        "lv.edv_a2c",
        "lv.esv_a2c",
        "lv.edv_bp",
        "lv.esv_bp",
        "lv.ef_bp",
        "lv.edvi_bp",
        "lv.esvi_bp",
        "lv.sv",
        "lv.svi",
        # П3 (и шаг иОЛП П4) — объёмы ЛП, ПЗР, биплан и индекс.
        "la.lav_a4c",
        "la.lav_a2c",
        "la.ap",
        "la.lav_bp",
        "la.lavi",
        # П4 — диастолическая функция (допплер и производные).
        "mv.e",
        "mv.a",
        "mv.dt",
        "lv.ivrt",
        "tdi.e_sept",
        "tdi.e_lat",
        "mv.ea",
        "tdi.e_avg",
        "mv.e_e_avg",
        "tdi.e_e_sept",
        "tdi.e_e_lat",
        "tr.vmax",
        # П5 — аортальный стеноз и производные непрерывности.
        "lvot.d",
        "lvot.vti",
        "av.vmax",
        "av.vti",
        "av.pg_peak",
        "av.pg_mean",
        "av.ava_vti",
        "av.avai",
        "av.dvi",
        # П6 — ТР / Сист. ДЛА.
        "ra.rap",
        "tr.pg",
        "pa.pasp",
    }
)

#: Ключи протоколов, которые срез сознательно не собирает, с причиной.
#: Пусто: каждый ключ шести протоколов имеет источник (см. модуль-докстринг).
UNMAPPED_KEYS: Mapping[str, str] = MappingProxyType({})


def _calculator_input(snapshot: MeasurementSnapshot, input_id: str) -> float | None:
    """Разрешённый вход калькуляторов (``rap`` для чипов ДПП)."""
    calculations = snapshot.calculations
    if calculations is None:
        return None
    value = calculations.input(input_id)
    return value.value if value is not None else None


def _calculator_output(
    snapshot: MeasurementSnapshot,
    calculator_id: str,
    output_id: str,
) -> float | None:
    """Значение выхода калькулятора как производная протокола."""
    calculations = snapshot.calculations
    if calculations is None:
        return None
    result = calculations.result(calculator_id)
    if result is None:
        return None
    output = result.output(output_id)
    return output.value if output is not None else None


def _flow_value(doppler: DopplerResults | None, site: str, field: str) -> float | None:
    """Поле потока одного сайта (``vmax_cm_s``, ``pgmax_mmhg``, ``vti_cm``)."""
    if doppler is None:
        return None
    flow = doppler.flow(site)
    return getattr(flow, field) if flow is not None else None


def _add_linear(snapshot: MeasurementSnapshot, add: Callable[[str, float | None], None]) -> None:
    for measurement in snapshot.linear_measurements:
        key = measurement_for_caliper(measurement.label)
        if key is not None:
            add(key, measurement.millimeter_length)


def _add_lvef(snapshot: MeasurementSnapshot, add: Callable[[str, float | None], None]) -> None:
    lvef = snapshot.lvef
    if lvef is None:
        return
    if lvef.a4c is not None:
        add("lv.edv_a4c", lvef.a4c.edv_ml)
        add("lv.esv_a4c", lvef.a4c.esv_ml)
    if lvef.a2c is not None:
        add("lv.edv_a2c", lvef.a2c.edv_ml)
        add("lv.esv_a2c", lvef.a2c.esv_ml)
    add("lv.edv_bp", lvef.edv_bi_ml)
    add("lv.esv_bp", lvef.esv_bi_ml)
    add("lv.ef_bp", lvef.lvef_percent)
    indexed = snapshot.indexed
    if indexed is not None:
        add("lv.edvi_bp", _ratio(lvef.edv_bi_ml, indexed.bsa_m2))
        add("lv.esvi_bp", _ratio(lvef.esv_bi_ml, indexed.bsa_m2))


def _add_lv_derived(snapshot: MeasurementSnapshot, add: Callable[[str, float | None], None]) -> None:
    add("lv.mass", snapshot.lvm_g)
    add("lv.rwt", snapshot.rwt)
    indexed = snapshot.indexed
    if indexed is not None:
        add("lv.mass_i", indexed.lvmi_g_m2)


def _add_chambers(snapshot: MeasurementSnapshot, add: Callable[[str, float | None], None]) -> None:
    la = snapshot.la_simpson
    if la is not None:
        add("la.lav_a4c", es_volume_from_view(la.a4c))
        add("la.lav_a2c", es_volume_from_view(la.a2c))
        add("la.lav_bp", biplane_es_volume_ml(la.a4c, la.a2c))
    indexed = snapshot.indexed
    if indexed is not None:
        lavi = indexed.lav_bi_index_ml_m2 or indexed.lav_4c_index_ml_m2 or indexed.lav_area_length_index_ml_m2
        add("la.lavi", lavi)


def _add_doppler(snapshot: MeasurementSnapshot, add: Callable[[str, float | None], None]) -> None:
    doppler = snapshot.doppler
    if doppler is None:
        return
    add("mv.e", doppler.e_cm_s)
    add("mv.a", doppler.a_cm_s)
    add("mv.dt", doppler.dt_ms)
    add("lv.ivrt", doppler.ivrt_ms)
    add("tdi.e_sept", doppler.e_prime_sept_cm_s)
    add("tdi.e_lat", doppler.e_prime_lat_cm_s)
    add("tr.vmax", doppler.tr_vmax_cm_s or _flow_value(doppler, "TR", "vmax_cm_s"))
    add("lvot.vti", _flow_value(doppler, "LVOT", "vti_cm"))
    add("av.vmax", _flow_value(doppler, "AV", "vmax_cm_s") or doppler.vpeak_cm_s)
    add("av.vti", _flow_value(doppler, "AV", "vti_cm") or doppler.vti_cm)


def _add_derived(snapshot: MeasurementSnapshot, add: Callable[[str, float | None], None]) -> None:
    add("lv.fs", _calculator_output(snapshot, "teichholz", "fs"))
    add("lv.sv", _calculator_output(snapshot, "stroke_volume", "sv"))
    add("lv.svi", _calculator_output(snapshot, "stroke_volume", "svi"))
    add("av.ava_vti", _calculator_output(snapshot, "aortic_valve_area", "ava_vti"))
    add("av.avai", _calculator_output(snapshot, "aortic_valve_area", "avai"))
    add("av.dvi", _calculator_output(snapshot, "aortic_valve_area", "dvi_vti"))
    add("tr.pg", _calculator_output(snapshot, "pulmonary_pressure", "tr_pg"))
    add("pa.pasp", _calculator_output(snapshot, "pulmonary_pressure", "pasp"))
    add("ra.rap", _calculator_input(snapshot, "rap"))

    doppler = snapshot.doppler
    if doppler is None:
        return
    add("mv.ea", doppler.e_a_ratio)
    add("tdi.e_avg", doppler.e_prime_avg_cm_s)
    add("mv.e_e_avg", doppler.e_over_e_prime)
    add("tdi.e_e_sept", doppler.e_over_e_prime_sept)
    add("tdi.e_e_lat", doppler.e_over_e_prime_lat)
    add("av.pg_peak", _flow_value(doppler, "AV", "pgmax_mmhg"))
    add("av.pg_mean", _flow_value(doppler, "AV", "pgmean_mmhg"))


def _ratio(value: float | None, denominator: float | None) -> float | None:
    if value is None or not denominator:
        return None
    return value / denominator


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

    _add_linear(snapshot, add)
    _add_lvef(snapshot, add)
    _add_lv_derived(snapshot, add)
    _add_chambers(snapshot, add)
    _add_doppler(snapshot, add)
    _add_derived(snapshot, add)

    return StudyProjection(
        values=values,
        clip_modes=clip_modes,
        clip_view=clip_view,
        unmet=unmet_requirements(snapshot) if unmet is None else unmet,
    )
