"""Behavioral tests for the view-recognition UI glue (#639 step 4).

``ViewRecognitionUi`` binds the badge and override dialog to the
coordinator's signals; these tests drive it directly.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from echo_personal_tool.domain.models.view_recognition import (
    UNKNOWN_VIEW,
    ViewDecision,
    ViewDecisionSource,
    view_category,
)
from echo_personal_tool.domain.services.view_recognition_workflow import ViewSuggestion
from echo_personal_tool.presentation.system_bar import SystemBar
from echo_personal_tool.presentation.view_recognition_ui import ViewRecognitionUi

pytestmark = pytest.mark.gui


class _SignalledCoordinator(QObject):
    suggestion_ready = Signal(object)
    decision_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.chosen: list[str] = []

    def choose_view(self, view: str):  # noqa: ANN201, D102
        self.chosen.append(view)


def _suggestion(view: str = "A4C", confidence: float = 0.91) -> ViewSuggestion:
    return ViewSuggestion(
        view=view,
        confidence=confidence,
        category="apical",
        profile_id="builtin.adult_echo",
        source=ViewDecisionSource.AUTO,
    )


def _ui(qtbot, coordinator: _SignalledCoordinator):
    bar = SystemBar()
    qtbot.addWidget(bar)
    statuses: list[str] = []
    ui = ViewRecognitionUi(coordinator, bar, statuses.append)
    return ui, bar, statuses


def test_confident_suggestion_shows_badge_and_status(qtbot) -> None:
    coordinator = _SignalledCoordinator()
    ui, _, statuses = _ui(qtbot, coordinator)

    coordinator.suggestion_ready.emit(_suggestion())

    assert ui._badge.text() == "A4C · 91%"  # noqa: SLF001
    assert len(statuses) == 1
    assert "A4C" in statuses[0] and "builtin.adult_echo" in statuses[0]


def test_low_confidence_suggestion_opens_override(qtbot, monkeypatch) -> None:
    coordinator = _SignalledCoordinator()
    ui, _, statuses = _ui(qtbot, coordinator)

    opened: list[object] = []
    monkeypatch.setattr(
        "echo_personal_tool.presentation.view_recognition_ui.ViewOverrideDialog",
        lambda suggestion, parent: _FakeDialog(suggestion, opened),
    )

    coordinator.suggestion_ready.emit(_suggestion(view="A4C", confidence=0.4))

    assert len(opened) == 1
    assert statuses == []


def test_override_accept_calls_coordinator(qtbot, monkeypatch) -> None:
    coordinator = _SignalledCoordinator()
    ui, _, _ = _ui(qtbot, coordinator)
    monkeypatch.setattr(
        "echo_personal_tool.presentation.view_recognition_ui.ViewOverrideDialog",
        lambda suggestion, parent: _FakeDialog(suggestion, [], chosen="A2C"),
    )

    coordinator.suggestion_ready.emit(_suggestion(confidence=0.4))

    assert coordinator.chosen == ["A2C"]


def test_decision_changed_updates_badge(qtbot) -> None:
    coordinator = _SignalledCoordinator()
    ui, _, _ = _ui(qtbot, coordinator)

    decision = ViewDecision(
        view="A2C",
        confidence=1.0,
        profile_id="builtin.adult_echo",
        source=ViewDecisionSource.MANUAL,
        study_uid="study-1",
        series_uid="series-1",
    )
    coordinator.decision_changed.emit(decision)

    assert ui._badge.text() == "A2C · 100%"  # noqa: SLF001
    assert view_category("A2C") == "apical"


def test_unknown_suggestion_shows_question_mark(qtbot, monkeypatch) -> None:
    coordinator = _SignalledCoordinator()
    ui, _, _ = _ui(qtbot, coordinator)
    monkeypatch.setattr(
        "echo_personal_tool.presentation.view_recognition_ui.ViewOverrideDialog",
        lambda suggestion, parent: _FakeDialog(suggestion, []),
    )

    coordinator.suggestion_ready.emit(_suggestion(view=UNKNOWN_VIEW, confidence=0.0))

    assert ui._badge.text() == "?"  # noqa: SLF001


class _FakeDialog:
    def __init__(self, suggestion, opened, *, chosen=None) -> None:  # noqa: ANN001
        self._opened = opened
        self._chosen = chosen

    def exec(self):  # noqa: ANN201, D102
        self._opened.append(1)
        return 1  # QDialog.DialogCode.Accepted

    def chosen_view(self):  # noqa: ANN201, D102
        return self._chosen
