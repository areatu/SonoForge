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


def test_progress_shows_the_bar_and_the_footer(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    assert card._bar.isVisibleTo(card) is True
    assert card._bar.value() == 0
    assert card._footer.isVisibleTo(card) is True
    card.set_progress(None)
    assert card._bar.isVisibleTo(card) is False
    assert card._footer.isVisibleTo(card) is False


def test_step_tiles_fill_the_two_column_grid(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    rows = card._steps_host.findChildren(type(card._stop))
    assert len(rows) == 2
    assert card._steps_layout.columnCount() == 2
    assert card._steps_layout.count() == 2


def test_skip_button_asks_the_window(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    seen: list[bool] = []
    card.skip_requested.connect(lambda: seen.append(True))
    card._skip.click()
    assert seen == [True]


def test_auto_advance_toggle_emits_the_protocol_id(qtbot) -> None:
    card = _card(qtbot)
    card.set_labels({**_labels(), "auto_advance": "Авто-переход", "skip": "Пропустить"})
    progress = _lv_linear_progress({})
    card.set_progress(progress)
    seen: list[tuple[str, bool]] = []
    card.auto_advance_toggled.connect(lambda pid, on: seen.append((pid, on)))
    card._auto_toggle.setChecked(True)
    card._auto_toggle.toggle()
    assert seen == [(progress.protocol_id, False)]


def test_set_auto_advance_syncs_without_emitting(qtbot) -> None:
    card = _card(qtbot)
    seen: list[bool] = []
    card.auto_advance_toggled.connect(lambda _pid, on: seen.append(on))
    card.set_auto_advance("lv_linear", False)
    assert card._auto_toggle.isChecked() is False
    assert seen == []


# ── #277: norm dots and S2 hover cards on the protocol step tiles (§4.7) ──


def test_handbook_bound_steps_get_a_dot_and_a_hover_card(qtbot) -> None:
    card = _card(qtbot)
    values = {key: ProjectionValue(value=10.0, origin="lv_linear") for key in ("lv.ivsd", "lv.lvedd", "lv.lvpwd")}
    card.set_progress(_lv_linear_progress(values))
    # Every lv_linear step is bound to the handbook — derive the expectation
    # from the spec itself instead of hardcoding the keys.
    from echo_personal_tool.domain.services.reference_topics import PROJECTION_TO_HANDBOOK

    spec = PROTOCOLS_BY_ID["lv_linear"]
    # One dot per step: the first handbook-bound satisfied key of the step.
    expected = {
        next(k for k in st.satisfied_keys if k in PROJECTION_TO_HANDBOOK)
        for st in spec.steps
        if any(k in PROJECTION_TO_HANDBOOK for k in st.satisfied_keys)
    }
    assert expected, "the fixture protocol must have handbook-bound steps"
    assert set(card._step_keys.values()) == expected
    assert all(dot is not None for dot in card._step_dots.values())
    # Every bound tile has its own S2 model factory on the step hover host.
    tiles = card._steps_host.findChildren(type(card._stop))
    assert len(card._step_hover._factories) == len(tiles)  # noqa: SLF001
    # Dots stay hidden until the «Нормы» switch is on and a value exists.
    assert all(dot.isHidden() for dot in card._step_dots.values())
    card.set_norms_visible(True)
    measured = sorted(expected)[0]
    card.set_step_values({measured: (10.0, "мм")})
    dot = card._step_dots[[i for i, k in card._step_keys.items() if k == measured][0]]
    assert dot.isHidden() is False, "a measured step shows its gradation dot"
    card.set_norms_visible(False)
    assert dot.isHidden() is True, "the «Нормы» switch hides the step dots too"


def test_step_without_a_value_has_no_dot(qtbot) -> None:
    card = _card(qtbot)
    card.set_progress(_lv_linear_progress({}))
    card.set_norms_visible(True)
    measured = sorted(card._step_keys.values())[0]
    card.set_step_values({measured: (10.0, "мм")})
    assert all(dot.isHidden() for index, dot in card._step_dots.items() if card._step_keys[index] != measured), (
        "steps without values carry no dot"
    )
