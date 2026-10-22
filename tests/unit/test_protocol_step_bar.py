"""Полоса шага под снимком (UI-3, TP §4.4 / §6.2, UD-04, Q-04, Q-07).

Статичная полоса: шаг, счётчик, инструкция, три кнопки и — для шага ДПП (П6.2)
— чипы 3 / 8 / 15 / «другое…».  Уведомление автоперехода держится не меньше
``minimum_ms``, чтобы не превратиться в мигание.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from echo_personal_tool.presentation.protocol_step_bar import (
    RAP_CHIPS,
    ProtocolStepBar,
)

pytestmark = pytest.mark.gui


def _labels(**overrides) -> dict:
    base = dict(
        cancel="Отменить точку",
        skip="Пропустить (S)",
        done="Готово (Enter)",
        rap_hint="ДПП",
        notification_hint="Esc — остановить автопереход",
    )
    base.update(overrides)
    return base


def _bar(qtbot) -> ProtocolStepBar:
    bar = ProtocolStepBar()
    qtbot.addWidget(bar)
    bar.set_labels(**_labels())
    return bar


def _step(bar: ProtocolStepBar, **overrides) -> None:
    base = dict(protocol_label="Симпсон Биплан", index=0, total=4, step_label="КДО · 4-кам.")
    base.update(overrides)
    bar.set_step(**base)


def test_bar_starts_hidden_and_shows_for_a_step(qtbot) -> None:
    bar = _bar(qtbot)
    assert bar.is_active() is False
    assert bar.isVisible() is False

    _step(bar)
    assert bar.is_active() is True
    assert bar.isVisible() is True

    bar.clear()
    assert bar.is_active() is False
    assert bar.isVisible() is False


def test_skip_done_and_cancel_buttons_emit(qtbot) -> None:
    bar = _bar(qtbot)
    _step(bar)
    seen: list[str] = []
    bar.skip_requested.connect(lambda: seen.append("skip"))
    bar.done_requested.connect(lambda: seen.append("done"))
    bar.cancel_point_requested.connect(lambda: seen.append("cancel"))

    for button in (bar._skip_button, bar._done_button, bar._cancel_button):
        button.click()
    assert seen == ["skip", "done", "cancel"]


def test_rap_chips_replace_the_instruction_and_emit_mmhg(qtbot) -> None:
    bar = _bar(qtbot)
    _step(bar, step_label="ДПП", rap=True)
    assert bar.rap_active is True
    assert bar._rap_values.isVisible() is True
    assert bar._instruction.isVisible() is False
    assert [button.text() for button in bar._rap_values.findChildren(type(bar._skip_button))] != []

    chosen: list[float] = []
    bar.rap_chosen.connect(chosen.append)
    other: list[bool] = []
    bar.rap_other_requested.connect(lambda: other.append(True))

    chips = [button for button in bar._rap_values.findChildren(type(bar._skip_button))]
    assert [chip.text() for chip in chips] == ["3", "8", "15", "…"]
    chips[1].click()
    assert chosen == [8.0]
    assert RAP_CHIPS == (3, 8, 15)
    chips[3].click()
    assert other == [True]


def test_frame_hint_appends_to_the_instruction(qtbot) -> None:
    bar = _bar(qtbot)
    _step(bar, step_label="КДО · 4-кам.", frame_hint="фаза КД")
    assert bar._instruction.text() == "КДО · 4-кам. · фаза КД"


def test_notification_is_kept_for_at_least_the_minimum(qtbot) -> None:
    bar = _bar(qtbot)
    _step(bar)
    bar.show_notification("✓ КДО → далее: КСО", hint="Esc — остановить автопереход", minimum_ms=300)
    assert bar.notification_active() is True

    QTest.qWait(120)
    assert bar.notification_active() is True, "уведомление не должно мигать"

    QTest.qWait(300)
    assert bar.notification_active() is False


def test_showing_a_step_keeps_a_live_notification(qtbot) -> None:
    """Q-07: смена шага (любой прогресс) не обрывает минимальное время уведомления."""
    bar = _bar(qtbot)
    _step(bar)
    bar.show_notification("✓ шаг", minimum_ms=10_000)
    _step(bar, index=1, step_label="КСО · 4-кам.")
    assert bar.notification_active() is True

    # Остановка протокола убирает уведомление сразу, не дожидаясь таймера.
    bar.clear()
    assert bar.notification_active() is False
    assert bar._notify_timer.isActive() is False


def test_cancel_button_is_hidden_until_a_step_is_armed(qtbot) -> None:
    bar = _bar(qtbot)
    _step(bar, can_cancel=False)
    assert bar._cancel_button.isVisible() is False
    _step(bar, can_cancel=True)
    assert bar._cancel_button.isVisible() is True


def test_rap_chip_is_a_plain_button_with_the_right_cursor(qtbot) -> None:
    bar = _bar(qtbot)
    _step(bar, rap=True)
    chips = [button for button in bar._rap_values.findChildren(type(bar._skip_button))]
    assert chips[0].cursor().shape() == Qt.CursorShape.PointingHandCursor
