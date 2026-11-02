"""Шесть протоколов: сверка с каталогом и прогресс (TP-3 PR-1).

Спека TP §6.3 описывает шаги П1–П6; здесь проверяется, что описания
ссылаются на существующие инструменты и ключи каталога, а прогресс на
синтетических проекциях ведёт себя как в приёмке A-04, A-07, A-08 и Q-05.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.measurement_catalog import CATALOG, MEASUREMENTS
from echo_personal_tool.domain.protocol_definitions import (
    AORTIC_STENOSIS,
    DIASTOLIC,
    LA_VOLUME,
    LV_LINEAR,
    PROTOCOLS,
    PROTOCOLS_BY_ID,
    SIMPSON_BIPLANE,
    TR_PASP,
)
from echo_personal_tool.domain.protocols import (
    AGGREGATE_MAX,
    ProjectionValue,
    StepState,
    StudyProjection,
    pick_aggregate,
    progress,
)


def _projection(spec_id: str, keys: tuple[str, ...], **fields) -> StudyProjection:
    return StudyProjection(values={key: ProjectionValue(origin=spec_id, **fields) for key in keys})


def test_six_protocols_with_labels_and_unique_ids() -> None:
    assert len(PROTOCOLS) == 6
    assert len(PROTOCOLS_BY_ID) == 6
    for spec in PROTOCOLS:
        assert spec.id
        assert spec.labels.get("ru") and spec.labels.get("en")
        assert spec.notes.get("ru") and spec.notes.get("en")
        assert spec.steps
        for step in spec.steps:
            assert step.labels.get("ru") and step.labels.get("en")
            assert step.satisfied_keys


def test_steps_reference_catalog_tools_and_measurement_keys() -> None:
    for spec in PROTOCOLS:
        for step in spec.steps:
            for tool_id in step.tool_ids:
                assert tool_id in CATALOG, f"{spec.id}: нет инструмента {tool_id}"
            for key in step.satisfied_keys:
                assert key in MEASUREMENTS, f"{spec.id}: нет ключа {key}"
        for key in spec.derived:
            assert key in MEASUREMENTS, f"{spec.id}: нет производного {key}"


def test_p1_series_step_has_both_linear_tools_and_one_key_set() -> None:
    series = LV_LINEAR.step(0)
    assert series.tool_ids == ("lv.linear_ed", "lv.linear_ed.m")
    assert series.satisfied_keys == ("lv.ivsd", "lv.lvedd", "lv.lvpwd")
    assert series.frame_hint == "ed"
    assert LV_LINEAR.step(1).satisfied_keys == ("lv.lvesd",)


def test_p2_simpson_steps_cover_four_view_phase_cells() -> None:
    cells = [(step.view, step.frame_hint) for step in SIMPSON_BIPLANE.steps]
    assert cells == [("A4C", "ed"), ("A4C", "es"), ("A2C", "ed"), ("A2C", "es")]
    assert [step.tool_id for step in SIMPSON_BIPLANE.steps] == [
        "lv.edv_a4c",
        "lv.esv_a4c",
        "lv.edv_a2c",
        "lv.esv_a2c",
    ]


def test_p4_lavi_step_links_to_la_volume_protocol() -> None:
    lavi = DIASTOLIC.steps[6]
    assert lavi.tool_id == ""
    assert lavi.satisfied_keys == ("la.lavi",)
    assert lavi.open_protocol == "la_volume"
    assert PROTOCOLS_BY_ID[lavi.open_protocol] is LA_VOLUME


def test_p6_rap_step_is_a_manual_input() -> None:
    rap = TR_PASP.steps[1]
    assert rap.tool_id == ""
    assert rap.satisfied_keys == ("ra.rap",)
    assert TR_PASP.derived == ("tr.pg", "pa.pasp")


def test_q05_vmax_steps_aggregate_the_maximum() -> None:
    # Vmax АК и Vmax ТР из нескольких окон — максимум (Q-05).
    assert AORTIC_STENOSIS.steps[2].aggregate == AGGREGATE_MAX
    assert TR_PASP.steps[0].aggregate == AGGREGATE_MAX
    assert pick_aggregate(AORTIC_STENOSIS.steps[2].aggregate, [3.9, 4.3]) == 4.3


@pytest.mark.parametrize("spec", PROTOCOLS, ids=lambda spec: spec.id)
def test_full_projection_completes_every_protocol(spec) -> None:
    keys = tuple(key for step in spec.steps for key in step.satisfied_keys)
    result = progress(spec, _projection(spec.id, keys))
    assert result.finished is True
    assert all(step.state is StepState.DONE for step in result.steps)
    assert result.done_count == result.total + sum(1 for step in spec.steps if step.optional)


@pytest.mark.parametrize("spec", PROTOCOLS, ids=lambda spec: spec.id)
def test_empty_projection_has_no_progress(spec) -> None:
    result = progress(spec, StudyProjection())
    assert result.finished is False
    assert result.done_count == 0
    assert result.steps[0].state is StepState.CURRENT


def test_a04_simpson_monoplane_is_not_finished_until_biplane() -> None:
    a4c = _projection(SIMPSON_BIPLANE.id, ("lv.edv_a4c", "lv.esv_a4c"))
    mono = progress(SIMPSON_BIPLANE, a4c)
    assert mono.done_count == 2
    assert mono.finished is False
    assert mono.steps[2].state is StepState.CURRENT

    biplane = progress(
        SIMPSON_BIPLANE,
        _projection(SIMPSON_BIPLANE.id, ("lv.edv_a4c", "lv.esv_a4c", "lv.edv_a2c", "lv.esv_a2c")),
    )
    assert biplane.finished is True


def test_a07_values_from_other_protocols_are_shared() -> None:
    projection = StudyProjection(
        values={
            "mv.e": ProjectionValue(origin="diastolic"),
            "mv.a": ProjectionValue(origin="diastolic"),
            "mv.dt": ProjectionValue(origin="diastolic"),
            "tdi.e_sept": ProjectionValue(origin="diastolic"),
            "tdi.e_lat": ProjectionValue(origin="diastolic"),
            "tr.vmax": ProjectionValue(origin="tr_pasp"),
            "la.lavi": ProjectionValue(origin="la_volume"),
        }
    )
    result = progress(DIASTOLIC, projection)
    assert result.step(5).state is StepState.SHARED  # Vmax ТР из П6 — ↗
    assert result.step(6).state is StepState.SHARED  # иОЛП из П3 — ↗
    assert result.finished is True


def test_a08_cw_step_is_locked_on_a_2d_clip() -> None:
    spec = AORTIC_STENOSIS
    on_2d = progress(spec, StudyProjection(clip_modes=frozenset({"2d"})), armed=2)
    assert on_2d.step(2).state is StepState.LOCKED
    assert on_2d.step(2).reason == "mode:cw"

    on_cw = progress(spec, StudyProjection(clip_modes=frozenset({"cw"})), armed=2)
    assert on_cw.step(2).state is StepState.CURRENT
    assert on_cw.step(2).reason == ""


def test_p2_step_on_the_wrong_view_is_locked() -> None:
    on_a4c = progress(
        SIMPSON_BIPLANE,
        StudyProjection(clip_modes=frozenset({"2d"}), clip_view="A4C"),
    )
    assert on_a4c.step(2).state is StepState.LOCKED
    assert on_a4c.step(2).reason == "view:A2C"
    assert on_a4c.step(0).state is StepState.CURRENT
