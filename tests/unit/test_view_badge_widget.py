"""Tests for the view-recognition badge and override dialog (#639 step 4)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.view_recognition import (
    UNKNOWN_VIEW,
    ViewDecisionSource,
)
from echo_personal_tool.domain.services.view_recognition_workflow import ViewSuggestion
from echo_personal_tool.presentation.view_badge_widget import ViewBadgeWidget
from echo_personal_tool.presentation.view_override_dialog import ViewOverrideDialog

pytestmark = pytest.mark.gui


def _suggestion(view: str = "A4C", confidence: float = 0.91) -> ViewSuggestion:
    return ViewSuggestion(
        view=view,
        confidence=confidence,
        category="apical",
        profile_id="builtin.adult_echo",
        source=ViewDecisionSource.AUTO,
    )


def test_badge_shows_view_and_confidence(qtbot) -> None:
    badge = ViewBadgeWidget()
    qtbot.addWidget(badge)
    badge.set_suggestion(_suggestion())
    assert badge.text() == "A4C · 91%"
    assert badge.isEnabled()


def test_badge_shows_question_mark_for_unknown(qtbot) -> None:
    badge = ViewBadgeWidget()
    qtbot.addWidget(badge)
    badge.set_suggestion(_suggestion(view=UNKNOWN_VIEW, confidence=0.0))
    assert badge.text() == "?"


def test_badge_reset_disables_it(qtbot) -> None:
    badge = ViewBadgeWidget()
    qtbot.addWidget(badge)
    badge.set_suggestion(_suggestion())
    badge.reset()
    assert badge.text() == ""
    assert not badge.isEnabled()


def test_badge_click_emits_override_requested(qtbot) -> None:
    badge = ViewBadgeWidget()
    qtbot.addWidget(badge)
    badge.set_suggestion(_suggestion())
    with qtbot.waitSignal(badge.override_requested):
        badge.click()


def test_override_dialog_returns_chosen_view(qtbot) -> None:
    dialog = ViewOverrideDialog(_suggestion("A4C", 0.91))
    qtbot.addWidget(dialog)
    assert dialog.chosen_view() is None  # not accepted yet
    dialog.accept()
    assert dialog.chosen_view() == "A4C"


def test_override_dialog_returns_none_on_cancel(qtbot) -> None:
    dialog = ViewOverrideDialog(_suggestion("PLAX", 0.4))
    qtbot.addWidget(dialog)
    dialog.reject()
    assert dialog.chosen_view() is None


def test_override_dialog_preselects_suggestion(qtbot) -> None:
    dialog = ViewOverrideDialog(_suggestion("PSAX", 0.77))
    qtbot.addWidget(dialog)
    assert dialog._view_combo.currentText() == "PSAX"


@pytest.mark.parametrize("view", ["RV_A4C", "SUBCOSTAL"])
def test_override_dialog_accepts_extended_views(qtbot, view: str) -> None:
    dialog = ViewOverrideDialog(_suggestion(view))
    qtbot.addWidget(dialog)
    dialog.accept()
    assert dialog.chosen_view() == view
