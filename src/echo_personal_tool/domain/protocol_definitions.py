"""Шесть протоколов измерений (спека TP §6.3) — TP-3 PR-1.

Описания ссылаются на инструменты каталога и ключи измерений
:mod:`echo_personal_tool.domain.measurement_catalog`; собственных копий строк
кроме подписей шагов здесь нет.  Идиомы:

* шаг с несколькими альтернативами (2D / М-режим у П1) перечисляет их в
  ``alt_tool_ids``; у всех альтернатив одни и те же ключи проекции;
* «максимум из N» (Q-05: Vmax АК, Vmax ТР из нескольких окон) —
  ``aggregate="max"``;
* шаг-ссылка на другой протокол (иОЛП в П4) и шаг-вход без инструмента
  (чипы ДПП в П6) имеют пустой ``tool_id`` и заполненный ``satisfied_by``.

Производные результаты карточки — те ключи, которые показывает и отчёт
(S-11); их значения считает application-слой, здесь только присутствие.
"""

from __future__ import annotations

from typing import Final

from echo_personal_tool.domain.measurement_catalog import CTX_2D, CTX_CW, CTX_M, CTX_PW, CTX_TDI
from echo_personal_tool.domain.protocols import AGGREGATE_MAX, ProtocolSpec, StepSpec

_2D_M: Final = frozenset({CTX_2D, CTX_M})
_2D: Final = frozenset({CTX_2D})
_PW: Final = frozenset({CTX_PW})
_CW: Final = frozenset({CTX_CW})
_TDI: Final = frozenset({CTX_TDI})

_LV_ED_KEYS: Final = ("lv.ivsd", "lv.lvedd", "lv.lvpwd")

# ── П1. ЛЖ линейно ──────────────────────────────────────────────────

LV_LINEAR: Final = ProtocolSpec(
    id="lv_linear",
    labels={"ru": "ЛЖ линейно", "en": "LV linear"},
    steps=(
        StepSpec(
            tool_id="lv.linear_ed",
            alt_tool_ids=("lv.linear_ed.m",),
            labels={
                "ru": "ЛЖ-диастола",
                "en": "LV-sequence",
            },
            contexts=_2D_M,
            satisfied_by=_LV_ED_KEYS,
            frame_hint="ed",
        ),
        StepSpec(
            tool_id="lv.lvesd",
            alt_tool_ids=("lv.lvesd.m",),
            labels={"ru": "КСР ЛЖ", "en": "LVESD"},
            contexts=_2D_M,
            satisfied_by=("lv.lvesd",),
            frame_hint="es",
        ),
    ),
    derived=("lv.rwt", "lv.mass", "lv.mass_i", "lv.fs"),
    notes={
        "ru": "ФВ по Тейхольцу в протоколе не показывается (ASE 2015) — она остаётся во вкладке «Расчёты».",
        "en": "Teichholz EF is not shown in the protocol (ASE 2015) — it stays on the Calculations tab.",
    },
)

# ── П2. Симпсон Биплан ──────────────────────────────────────────────

SIMPSON_BIPLANE: Final = ProtocolSpec(
    id="simpson_biplane",
    labels={"ru": "Симпсон Биплан", "en": "Simpson biplane"},
    steps=(
        StepSpec(
            tool_id="lv.edv_a4c",
            alt_tool_ids=("lv.edv_a4c.auto",),
            labels={"ru": "КДО · 4-кам.", "en": "LVEDV A4C"},
            contexts=_2D,
            view="A4C",
            frame_hint="ed",
        ),
        StepSpec(
            tool_id="lv.esv_a4c",
            alt_tool_ids=("lv.esv_a4c.auto",),
            labels={"ru": "КСО · 4-кам.", "en": "LVESV A4C"},
            contexts=_2D,
            view="A4C",
            frame_hint="es",
        ),
        StepSpec(
            tool_id="lv.edv_a2c",
            labels={"ru": "КДО · 2-кам.", "en": "LVEDV A2C"},
            contexts=_2D,
            view="A2C",
            frame_hint="ed",
        ),
        StepSpec(
            tool_id="lv.esv_a2c",
            labels={"ru": "КСО · 2-кам.", "en": "LVESV A2C"},
            contexts=_2D,
            view="A2C",
            frame_hint="es",
        ),
    ),
    derived=("lv.edv_bp", "lv.esv_bp", "lv.ef_bp", "lv.sv", "lv.edvi_bp", "lv.esvi_bp"),
    notes={
        "ru": "Пока есть только 4-кам., значения показываются и уходят в отчёт с пометкой «Моноплан».",
        "en": "While only A4C is measured the values are shown and reported with the «Monoplane» note.",
    },
)

# ── П3. Объём ЛП ────────────────────────────────────────────────────

LA_VOLUME: Final = ProtocolSpec(
    id="la_volume",
    labels={"ru": "Объём ЛП", "en": "LA volume"},
    steps=(
        StepSpec(
            tool_id="la.lav_a4c",
            alt_tool_ids=("la.lav_a4c.auto", "la.lav_a4c.ai_plus"),
            labels={"ru": "ОЛП · 4-кам.", "en": "LAV A4C"},
            contexts=_2D,
            frame_hint="es",
        ),
        StepSpec(
            tool_id="la.lav_a2c",
            labels={"ru": "ОЛП · 2-кам.", "en": "LAV A2C"},
            contexts=_2D,
            frame_hint="es",
        ),
        StepSpec(
            tool_id="la.ap",
            labels={"ru": "ЛП ПЗР", "en": "LA AP"},
            contexts=_2D,
            frame_hint="es",
            optional=True,
        ),
    ),
    derived=("la.lav_bp", "la.lavi"),
    notes={
        "ru": "Порог иОЛП > 34 мл/м² виден в справочной подсказке и не размечается цветом.",
        "en": "The LAVi > 34 mL/m² threshold is a reference hint only and is not colour-coded.",
    },
)

# ── П4. Диастолическая функция ──────────────────────────────────────

DIASTOLIC: Final = ProtocolSpec(
    id="diastolic",
    labels={"ru": "Диастолическая функция", "en": "Diastolic function"},
    steps=(
        StepSpec(
            tool_id="mv.e",
            labels={"ru": "E", "en": "E"},
            contexts=_PW,
        ),
        StepSpec(
            tool_id="mv.a",
            labels={"ru": "A", "en": "A"},
            contexts=_PW,
        ),
        StepSpec(
            tool_id="mv.dt",
            labels={"ru": "DT", "en": "DT"},
            contexts=_PW,
        ),
        StepSpec(
            tool_id="tdi.e_sept",
            labels={"ru": "e′ септ.", "en": "e′ septal"},
            contexts=_TDI,
        ),
        StepSpec(
            tool_id="tdi.e_lat",
            labels={"ru": "e′ лат.", "en": "e′ lateral"},
            contexts=_TDI,
        ),
        StepSpec(
            tool_id="tr.vmax",
            labels={"ru": "Vmax ТР", "en": "TRmax Vel"},
            contexts=_CW,
            aggregate=AGGREGATE_MAX,
        ),
        StepSpec(
            tool_id="",
            labels={"ru": "иОЛП", "en": "LAVi"},
            contexts=_2D,
            satisfied_by=("la.lavi",),
            open_protocol="la_volume",
        ),
        StepSpec(
            tool_id="lv.ivrt",
            labels={"ru": "IVRT", "en": "IVRT"},
            contexts=_PW,
            optional=True,
        ),
    ),
    derived=("mv.ea", "tdi.e_avg", "mv.e_e_avg", "tdi.e_e_sept", "tdi.e_e_lat"),
    notes={
        "ru": "Пороги ASE 2025 справочные: e′ септ. ≤ 6, e′ лат. ≤ 7 см/с, E/e′ ср. ≥ 14, Vmax ТР ≥ 2,8 м/с, иОЛП > 34 мл/м². Скорости сравниваются по модулю, знак сохраняется.",
        "en": "ASE 2025 thresholds are reference-only: septal e′ ≤ 6, lateral e′ ≤ 7 cm/s, average E/e′ ≥ 14, TR Vmax ≥ 2.8 m/s, LAVi > 34 mL/m². Velocities are compared by magnitude and keep their sign.",
    },
)

# ── П5. Аортальный стеноз ───────────────────────────────────────────

AORTIC_STENOSIS: Final = ProtocolSpec(
    id="as",
    labels={"ru": "Аортальный стеноз", "en": "Aortic stenosis"},
    steps=(
        StepSpec(
            tool_id="lvot.d",
            labels={"ru": "Диаметр ВТЛЖ", "en": "LVOT diam"},
            contexts=_2D,
            frame_hint="es",
        ),
        StepSpec(
            tool_id="lvot.vti",
            labels={"ru": "VTI ВТЛЖ", "en": "LVOT VTI"},
            contexts=_PW,
        ),
        StepSpec(
            tool_id="av.vmax",
            labels={"ru": "Vmax АК", "en": "AV Vmax"},
            contexts=_CW,
            aggregate=AGGREGATE_MAX,
        ),
        StepSpec(
            tool_id="av.vti",
            alt_tool_ids=("av.vti.auto",),
            labels={"ru": "VTI АК", "en": "AV VTI"},
            contexts=_CW,
        ),
    ),
    derived=("av.pg_peak", "av.pg_mean", "av.ava_vti", "av.avai", "av.dvi", "lv.sv", "lv.svi"),
    notes={
        "ru": "Градации EACVI/ASE 2017 (Vmax ≥ 4 м/с, Град. ср. ≥ 40, площадь < 1,0 см², индекс < 0,6, безразм. индекс < 0,25) — справочно по наведению.",
        "en": "EACVI/ASE 2017 grades (Vmax ≥ 4 m/s, mean gradient ≥ 40, area < 1.0 cm², index < 0.6, dimensionless index < 0.25) are hover reference only.",
    },
)

# ── П6. ТР / Сист. ДЛА ──────────────────────────────────────────────

TR_PASP: Final = ProtocolSpec(
    id="tr_pasp",
    labels={"ru": "ТР / Сист. ДЛА", "en": "TR / PASP"},
    steps=(
        StepSpec(
            tool_id="tr.vmax",
            labels={"ru": "Vmax ТР", "en": "TRmax Vel"},
            contexts=_CW,
            aggregate=AGGREGATE_MAX,
        ),
        StepSpec(
            tool_id="",
            labels={"ru": "ДПП", "en": "RAP"},
            contexts=_2D,
            satisfied_by=("ra.rap",),
        ),
    ),
    derived=("tr.pg", "pa.pasp"),
    notes={
        "ru": "Чипы ДПП 3 / 8 / 15 / «другое…» — выбор врача, не автоматическая оценка; категории НПВ по ASE 2025 — в подсказке. Сист. ДЛА = Град. ТР + ДПП («= Сист. ДПЖ при отсутствии обструкции ВТПЖ и стеноза клапана ЛА»).",
        "en": "The RAP chips 3 / 8 / 15 / «Other…» are the physician's choice, not an automatic estimate; ASE 2025 IVC categories are in the hint. PASP = TR gradient + RAP («= RVSP without RVOT obstruction or pulmonic stenosis»).",
    },
)

PROTOCOLS: Final[tuple[ProtocolSpec, ...]] = (
    LV_LINEAR,
    SIMPSON_BIPLANE,
    LA_VOLUME,
    DIASTOLIC,
    AORTIC_STENOSIS,
    TR_PASP,
)

PROTOCOLS_BY_ID: Final[dict[str, ProtocolSpec]] = {spec.id: spec for spec in PROTOCOLS}
