"""Прогресс протокола по синтетической проекции (TP-3 PR-1).

Спека TP §8.4: ``progress()`` — чистая функция, тесты строятся на
синтетических проекциях без Qt.  Здесь — состояния шагов (§4.3, §6.1),
блокировки (§6.2 «Не тот контекст», A-08), агрегация «максимум из N»
(Q-05) и счётчики карточки.
"""

from __future__ import annotations

from echo_personal_tool.domain.protocols import (
    AGGREGATE_MAX,
    ProjectionValue,
    ProtocolSpec,
    StepSpec,
    StepState,
    StudyProjection,
    pick_aggregate,
    progress,
    step_lock_reason,
)


def _spec() -> ProtocolSpec:
    return ProtocolSpec(
        id="unit",
        labels={"ru": "Тестовый", "en": "Unit"},
        steps=(
            StepSpec(
                tool_id="tool.first",
                labels={"ru": "Первый", "en": "First"},
                contexts=frozenset({"2d"}),
                satisfied_by=("k.first",),
            ),
            StepSpec(
                tool_id="tool.second",
                labels={"ru": "Второй", "en": "Second"},
                contexts=frozenset({"cw"}),
                satisfied_by=("k.second",),
                aggregate=AGGREGATE_MAX,
            ),
            StepSpec(
                tool_id="",
                labels={"ru": "Третий", "en": "Third"},
                contexts=frozenset({"2d"}),
                satisfied_by=("k.third",),
                optional=True,
            ),
        ),
        derived=("k.derived",),
    )


def test_satisfied_keys_fall_back_to_result_keys_and_tool_id() -> None:
    from echo_personal_tool.domain.measurement_catalog import CATALOG

    series = StepSpec(
        tool_id="lv.linear_ed",
        labels={"ru": "МЖП · КДР ЛЖ · ЗСЛЖ", "en": "IVSD · LVEDD · LVPWD"},
        contexts=frozenset({"2d"}),
    )
    assert series.satisfied_keys == ("lv.ivsd", "lv.lvedd", "lv.lvpwd")
    assert CATALOG.get("lv.linear_ed").result_keys == series.satisfied_keys

    single = StepSpec(tool_id="mv.e", labels={"ru": "E", "en": "E"}, contexts=frozenset({"pw"}))
    assert single.satisfied_keys == ("mv.e",)

    explicit = StepSpec(
        tool_id="",
        labels={"ru": "ДПП", "en": "RAP"},
        contexts=frozenset(),
        satisfied_by=("ra.rap",),
    )
    assert explicit.satisfied_keys == ("ra.rap",)


def test_pick_aggregate() -> None:
    assert pick_aggregate(AGGREGATE_MAX, [3.9, 4.3, 4.0]) == 4.3
    assert pick_aggregate(AGGREGATE_MAX, [3.9, None, 4.1]) == 4.1
    assert pick_aggregate(AGGREGATE_MAX, []) is None
    # Без правила последнее измерение заменяет прежнее (Q-08).
    assert pick_aggregate(None, [5.0, 6.5]) == 6.5
    assert pick_aggregate(None, []) is None


def test_lock_reason_mode_view_and_requirement() -> None:
    step = _spec().step(1)  # требуется cw
    assert step_lock_reason(step, StudyProjection(clip_modes=frozenset({"2d"}))) == "mode:cw"
    assert step_lock_reason(step, StudyProjection(clip_modes=frozenset({"cw"}))) == ""
    # Пустой контекст вкладки ничего не блокирует.
    assert step_lock_reason(step, StudyProjection()) == ""

    viewed = StepSpec(
        tool_id="lv.edv_a2c",
        labels={"ru": "КДО · 2-кам.", "en": "LVEDV A2C"},
        contexts=frozenset({"2d"}),
        view="A2C",
    )
    assert step_lock_reason(viewed, StudyProjection(clip_view="A4C")) == "view:A2C"
    assert step_lock_reason(viewed, StudyProjection(clip_view="A2C")) == ""
    assert step_lock_reason(viewed, StudyProjection()) == ""

    spacing = StepSpec(tool_id="lvot.d", labels={"ru": "Диаметр ВТЛЖ", "en": "LVOT diam"}, contexts=frozenset({"2d"}))
    # Известная незакрытая калибровка блокирует; без знания о проблеме — нет.
    unmet = StudyProjection(unmet=frozenset({"spatial_calibration"}))
    assert step_lock_reason(spacing, unmet) == "req:spatial_calibration"
    assert step_lock_reason(spacing, StudyProjection()) == ""


def test_empty_projection_is_all_todo_and_current_is_first_unmet() -> None:
    result = progress(_spec(), StudyProjection())
    assert [step.state for step in result.steps] == [StepState.CURRENT, StepState.TODO, StepState.TODO]
    assert result.current_index == 0
    assert result.done_count == 0
    assert result.total == 2  # третий шаг необязательный
    assert result.finished is False


def test_done_shared_and_stale_come_from_the_projection() -> None:
    spec = _spec()
    projection = StudyProjection(
        values={
            "k.first": ProjectionValue(value=1.0, origin="unit"),
            "k.second": ProjectionValue(value=2.0, origin=""),
        }
    )
    result = progress(spec, projection)
    assert result.step(0).state is StepState.DONE
    assert result.step(1).state is StepState.SHARED  # вне протокола — ↗
    assert result.done_count == 2

    other = StudyProjection(values={"k.second": ProjectionValue(value=2.0, origin="other")})
    assert progress(spec, other).step(1).state is StepState.SHARED

    stale = StudyProjection(values={"k.first": ProjectionValue(value=1.0, origin="unit", stale=True)})
    assert progress(spec, stale).step(0).state is StepState.STALE


def test_skipped_is_in_memory_and_satisfied_values_win() -> None:
    spec = _spec()
    result = progress(spec, StudyProjection(), skipped=frozenset({1}))
    assert result.step(1).state is StepState.SKIPPED
    assert result.skipped_count == 1
    # Значение появилось после пропуска — шаг засчитан (прогресс — функция
    # проекции), а «пропущено» остаётся только в памяти вкладки.
    projection = StudyProjection(values={"k.second": ProjectionValue(value=4.3, origin="unit")})
    assert progress(spec, projection, skipped=frozenset({1})).step(1).state is StepState.DONE


def test_satisfied_step_wins_over_locked_reason() -> None:
    # Шаг требует cw, но значение уже есть: блокировка контекста не стирает
    # результат (§6.1: шаг выполнен, если нужный результат есть).
    projection = StudyProjection(
        values={"k.second": ProjectionValue(value=4.3, origin="unit")},
        clip_modes=frozenset({"2d"}),
    )
    assert progress(_spec(), projection).step(1).state is StepState.DONE


def test_locked_step_keeps_reason_and_stays_the_current_pointer() -> None:
    projection = StudyProjection(clip_modes=frozenset({"2d"}))
    result = progress(_spec(), projection)
    assert result.current_index == 0
    # Первый шаг разрешён (2d) — current; второй заблокирован с причиной.
    assert result.step(0).state is StepState.CURRENT
    assert result.step(1).state is StepState.LOCKED
    assert result.step(1).reason == "mode:cw"

    # Если первый невыполненный шаг заблокирован — причина информативнее
    # «взведён»: состояние остаётся locked, указатель текущего на нём.
    only_cw = progress(_spec(), StudyProjection(clip_modes=frozenset({"cw"})))
    assert only_cw.current_index == 0
    assert only_cw.step(0).state is StepState.LOCKED
    assert only_cw.step(0).reason == "mode:2d"


def test_armed_step_is_current_even_when_repeated() -> None:
    spec = _spec()
    projection = StudyProjection(values={"k.first": ProjectionValue(value=1.0, origin="unit")})
    result = progress(spec, projection, armed=0)
    assert result.current_index == 0
    assert result.step(0).state is StepState.CURRENT  # повтор клика по выполненному (Q-08)
    assert result.step(1).state is StepState.TODO

    locked = progress(spec, StudyProjection(clip_modes=frozenset({"2d"})), armed=1)
    assert locked.current_index == 1
    assert locked.step(1).state is StepState.LOCKED  # причина информативнее «взведён»


def test_finished_when_required_steps_satisfied() -> None:
    spec = _spec()
    projection = StudyProjection(
        values={
            "k.first": ProjectionValue(value=1.0, origin="unit"),
            "k.second": ProjectionValue(value=2.0, origin="unit"),
        }
    )
    result = progress(spec, projection)
    assert result.finished is True
    assert result.done_count == 2

    # Необязательный шаг не мешает завершению.
    only_optional_missing = progress(
        spec,
        StudyProjection(
            values={
                "k.first": ProjectionValue(value=1.0, origin="unit"),
                "k.second": ProjectionValue(value=2.0, origin="unit"),
                "k.third": ProjectionValue(value=3.0, origin=""),
            }
        ),
    )
    assert only_optional_missing.finished is True
    assert only_optional_missing.step(2).state is StepState.SHARED


def test_derived_presence_and_staleness() -> None:
    projection = StudyProjection(values={"k.derived": ProjectionValue(value=3.0, stale=True)})
    result = progress(_spec(), projection)
    assert len(result.derived) == 1
    assert result.derived[0].key == "k.derived"
    assert result.derived[0].present is True
    assert result.derived[0].stale is True

    empty = progress(_spec(), StudyProjection())
    assert empty.derived[0].present is False
    assert empty.derived[0].stale is False
