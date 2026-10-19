"""Карточка протокола панели 2.0 (TP-3 PR-3, спека TP §4.2, §6).

Карточка заменяет мигание кнопки «следующий шаг» (§4.2 «Заменяет мигание»):
выбор протокола в шапке, список шагов с глифом состояния и производные
результаты.  Когда протокол не запущен, карточка свёрнута до выбора.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.protocol_definitions import PROTOCOLS, PROTOCOLS_BY_ID
from echo_personal_tool.domain.protocols import (
    ProjectionValue,
    StepState,
    StudyProjection,
    progress,
)
from echo_personal_tool.presentation.tool_panel_v2.protocol_card import ProtocolCard

pytestmark = pytest.mark.gui


def _labels() -> dict:
    return {
        "title": "Протокол",
        "none": "— без протокола —",
        "stop": "Остановить",
        "derived": "Производные",
        "skipped": "пропущен",
        "stale": "устарело",
        "lock_mode": "нужен режим {modes}",
        "lock_view": "нужна проекция {view}",
        "lock_req": "нужно: {req}",
    }


def _card(qtbot) -> ProtocolCard:
    card = ProtocolCard("ru")
    qtbot.addWidget(card)
    card.set_labels(_labels())
    card.set_protocols(PROTOCOLS)
    card.show()
    return card


def _lv_linear_progress(values: dict, *, skipped=frozenset(), armed=None):
    spec = PROTOCOLS_BY_ID["lv_linear"]
    return progress(spec, StudyProjection(values=values), skipped, armed=armed)


def test_chooser_lists_all_protocols_with_a_none_entry(qtbot) -> None:
    card = _card(qtbot)
    assert card._combo.count() == len(PROTOCOLS) + 1
    assert card._combo.itemData(0) == ""
    assert card._combo.itemData(1) == PROTOCOLS[0].id
    assert card._combo.itemText(0) == "— без протокола —"
    assert card.selected_protocol_id() == ""


def test_chooser_emits_the_selected_protocol(qtbot) -> None:
    card = _card(qtbot)
    seen: list[str] = []
    card.protocol_selected.connect(seen.append)
    card._combo.setCurrentIndex(2)
    assert seen == [PROTOCOLS[1].id]


def test_no_progress_collapses_to_the_chooser(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    assert card._steps_host.isVisibleTo(card) is True

    card.set_progress(None)
    assert card._steps_host.isVisibleTo(card) is False
    assert card._stop.isVisibleTo(card) is False
    assert card._derived.isVisibleTo(card) is False
    assert card.selected_protocol_id() == ""


def test_progress_lists_the_steps_with_state_glyphs(qtbot) -> None:
    card = _card(qtbot)
    values = {key: ProjectionValue(value=1.0, origin="lv_linear") for key in ("lv.ivsd", "lv.lvedd", "lv.lvpwd")}
    card.set_progress(_lv_linear_progress(values))
    rows = card._steps_host.findChildren(type(card._stop))
    assert card._progress.text() == "1 / 2"
    assert len(rows) == 2
    assert rows[0].text().startswith("✓")
    assert rows[1].text().startswith("◉")
    assert rows[1].property("state") == StepState.CURRENT.value


def test_clicking_a_step_arms_it(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    rows = card._steps_host.findChildren(type(card._stop))
    seen: list[int] = []
    card.step_activated.connect(seen.append)
    rows[0].click()
    assert seen == [0]


def test_locked_step_explains_itself_and_is_disabled(qtbot) -> None:
    card = _card(qtbot)
    projection = StudyProjection(values={}, clip_modes=frozenset({"m"}), unmet=frozenset())
    spec = PROTOCOLS_BY_ID["tr_pasp"]
    card.set_protocols((spec,))
    card.set_progress(progress(spec, projection, frozenset()))
    rows = card._steps_host.findChildren(type(card._stop))
    # Шаг Vmax ТР требует контекст CW — открыт М-режим.
    assert rows[0].property("state") == StepState.LOCKED.value
    assert rows[0].isEnabled() is False
    assert "нужен режим cw" in rows[0].text()


def test_stop_button_asks_the_window(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    seen: list[bool] = []
    card.stop_requested.connect(lambda: seen.append(True))
    card._stop.click()
    assert seen == [True]
