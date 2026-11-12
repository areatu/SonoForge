"""Isolated contract tests for the ViewerLabelPicker owner (A4)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.viewer.label_picker_owner import (
    DEFAULT_CALIPER_LABELS,
    ViewerLabelPicker,
)


class _Harness:
    def __init__(self) -> None:
        self.parent = QWidget()
        self.applied: list[tuple[object, tuple[str, object]]] = []
        self.can_cycle = True
        self.cardiac = True
        self.owner = ViewerLabelPicker(
            parent=self.parent,
            apply_label=lambda option, target: self.applied.append((option, target)),
            can_cycle_label=lambda: self.can_cycle,
            cardiac_provider=lambda: self.cardiac,
        )


@pytest.fixture
def harness(qtbot) -> _Harness:
    h = _Harness()
    qtbot.addWidget(h.parent)
    return h


def test_picker_is_created_lazily_and_parented_to_the_viewer(qtbot, harness: _Harness) -> None:
    assert harness.owner.visible is False
    picker = harness.owner.picker()
    assert picker is harness.owner.picker()
    assert picker.parent() is harness.parent


def test_offer_opens_the_popup_and_hands_target_to_the_apply_callback(qtbot, harness: _Harness) -> None:
    target = ("caliper", ("Dist1", 0))
    assert harness.owner.offer(target=target, value_text="41 mm", context="2d") is True

    picker = harness.owner.picker()
    assert harness.owner.visible is True
    assert picker.value_text() == "41 mm"
    assert picker.context() == "2d"

    option = picker.options()[0]
    assert picker.select_index(0) is True

    assert harness.applied == [(option, target)]
    assert harness.owner.visible is False


def test_disabled_picker_refuses_to_open_and_closes_the_popup(qtbot, harness: _Harness) -> None:
    harness.owner.offer(target=("caliper", ("Dist1", 0)), value_text="", context="2d")
    assert harness.owner.visible is True

    harness.owner.set_enabled(False)

    assert harness.owner.enabled is False
    assert harness.owner.visible is False
    assert harness.owner.offer(target=("caliper", ("Dist2", 0)), value_text="", context="2d") is False
    assert harness.owner.visible is False


def test_dismiss_clears_the_target_and_a_late_selection_is_ignored(qtbot, harness: _Harness) -> None:
    harness.owner.offer(target=("trace", "m-1"), value_text="", context="doppler")
    picker = harness.owner.picker()

    assert harness.owner.dismiss() is True
    assert harness.owner.visible is False
    assert harness.owner.take_target() is None

    picker.label_selected.emit(picker.options()[0])
    assert harness.applied == []


def test_accept_and_dismiss_are_noops_when_hidden(qtbot, harness: _Harness) -> None:
    assert harness.owner.accept() is False
    assert harness.owner.dismiss() is False
    assert harness.owner.cycle_visible_selection() is False


def test_context_override_wins_until_reset_and_restyles_an_open_popup(qtbot, harness: _Harness) -> None:
    harness.owner.set_context(" Doppler ")
    assert harness.owner.context_override == "doppler"
    assert harness.owner.resolve_context("2d") == "doppler"

    harness.owner.offer(target=("caliper", ("Dist1", 0)), value_text="", context="2d")
    assert harness.owner.picker().context() == "doppler"

    harness.owner.set_context(None)
    assert harness.owner.context_override is None
    assert harness.owner.resolve_context("m") == "m"


def test_cardiac_override_falls_back_to_the_header_and_closes_a_non_cardiac_popup(qtbot, harness: _Harness) -> None:
    assert harness.owner.is_cardiac_context() is True

    harness.owner.offer(target=("caliper", ("Dist1", 0)), value_text="", context="2d")
    harness.owner.set_cardiac_context(False)
    assert harness.owner.is_cardiac_context() is False
    assert harness.owner.visible is False

    harness.cardiac = False
    harness.owner.set_cardiac_context(None)
    assert harness.owner.is_cardiac_context() is False


def test_tab_cycles_the_caliper_label_only_when_the_viewer_allows_it(qtbot, harness: _Harness) -> None:
    initial = harness.owner.current_label()
    harness.owner.picker().cycle_next(emit_tab=True)
    assert harness.owner.current_label() != initial

    harness.can_cycle = False
    frozen = harness.owner.current_label()
    harness.owner.picker().cycle_next(emit_tab=True)
    assert harness.owner.current_label() == frozen


def test_label_cycle_appends_new_names_and_wraps(qtbot, harness: _Harness) -> None:
    assert harness.owner.labels == list(DEFAULT_CALIPER_LABELS)

    harness.owner.set_label("CustomLabel")
    assert harness.owner.current_label() == "CustomLabel"
    assert harness.owner.labels[-1] == "CustomLabel"

    harness.owner.label_index = len(harness.owner.labels) - 1
    assert harness.owner.cycle_label() == harness.owner.labels[0]


def test_cycle_visible_selection_moves_the_popup_without_closing_it(qtbot, harness: _Harness) -> None:
    harness.owner.offer(target=("caliper", ("Dist1", 0)), value_text="", context="2d")
    picker = harness.owner.picker()
    before = picker.selected_index()

    assert harness.owner.cycle_visible_selection() is True
    assert picker.selected_index() != before
    assert harness.owner.visible is True
