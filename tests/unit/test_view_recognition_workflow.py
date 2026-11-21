"""Tests for the view-recognition workflow (#639 step 4).

Suggestion / threshold / override / restore logic, exercised with a stub
recognizer and an in-memory decision store (no Qt, no IO).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from echo_personal_tool.domain.models.view_recognition import (
    RECOGNITION_CONFIDENCE_THRESHOLD,
    UNKNOWN_VIEW,
    RecognizedView,
    ViewDecision,
    ViewDecisionSource,
)
from echo_personal_tool.domain.services.view_recognition_workflow import (
    ViewRecognitionWorkflow,
    ViewSuggestion,
    view_profile_id,
)


class StubRecognizer:
    """Minimal :class:`IViewRecognizer` returning a fixed result."""

    def __init__(self, view: str, confidence: float) -> None:
        self._view = view
        self._confidence = confidence
        self.calls = 0

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        self.calls += 1
        return RecognizedView(self._view, self._confidence)


class InMemoryDecisionStore:
    """Minimal :class:`IViewDecisionStore` for tests."""

    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str], ViewDecision] = {}

    def load(self, study_uid: str, series_uid: str) -> ViewDecision | None:
        return self._decisions.get((study_uid, series_uid))

    def save(self, decision: ViewDecision) -> None:
        self._decisions[(decision.study_uid, decision.series_uid)] = decision


def _frames() -> list[np.ndarray]:
    return [np.zeros((4, 4), dtype=np.float32) for _ in range(3)]


def test_suggestion_from_confident_recognition() -> None:
    workflow = ViewRecognitionWorkflow(StubRecognizer("A4C", 0.91), InMemoryDecisionStore())
    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    assert suggestion.view == "A4C"
    assert suggestion.confidence == 0.91
    assert suggestion.is_confident is True
    assert suggestion.category == "apical"
    assert suggestion.profile_id == "builtin.adult_echo"
    assert suggestion.source is ViewDecisionSource.AUTO


def test_low_confidence_is_not_auto_confident() -> None:
    workflow = ViewRecognitionWorkflow(StubRecognizer("PLAX", 0.4), InMemoryDecisionStore())
    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    assert suggestion.is_confident is False
    assert suggestion.confidence < RECOGNITION_CONFIDENCE_THRESHOLD


def test_unknown_view_proposes_no_profile() -> None:
    workflow = ViewRecognitionWorkflow(StubRecognizer(UNKNOWN_VIEW, 0.0), InMemoryDecisionStore())
    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    assert suggestion.view == UNKNOWN_VIEW
    assert suggestion.profile_id is None
    assert suggestion.category == "unknown"


def test_override_persists_and_restore_skips_recognizer() -> None:
    recognizer = StubRecognizer("A4C", 0.91)
    store = InMemoryDecisionStore()
    workflow = ViewRecognitionWorkflow(recognizer, store)

    decision = workflow.apply_override("A2C", study_uid="s", series_uid="se")
    assert decision.source is ViewDecisionSource.MANUAL
    assert decision.confidence == 1.0
    assert decision.profile_id == "builtin.adult_echo"

    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    # The persisted manual choice wins; the classifier is not re-run.
    assert suggestion.view == "A2C"
    assert suggestion.source is ViewDecisionSource.MANUAL
    assert recognizer.calls == 0


def test_auto_decision_does_not_block_recognition() -> None:
    """Only MANUAL decisions are restored; auto results re-run the model."""
    recognizer = StubRecognizer("SAX", 0.8)
    store = InMemoryDecisionStore()
    workflow = ViewRecognitionWorkflow(recognizer, store)
    decision = ViewDecision(
        study_uid="s",
        series_uid="se",
        view="SAX",
        source=ViewDecisionSource.AUTO,
        confidence=0.8,
        profile_id="builtin.adult_echo",
    )
    store.save(decision)

    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    assert suggestion.source is ViewDecisionSource.AUTO
    assert recognizer.calls == 1


def test_apply_override_saves_through_store() -> None:
    store = InMemoryDecisionStore()
    workflow = ViewRecognitionWorkflow(StubRecognizer("A4C", 0.9), store)
    workflow.apply_override("TEE", study_uid="s1", series_uid="se1")
    assert store.load("s1", "se1") is not None
    assert store.load("s1", "se1").view == "TEE"
    assert store.load("s1", "other") is None


def test_view_profile_mapping() -> None:
    from echo_personal_tool.domain.study_profiles import STUDY_PROFILE_ECHO

    assert view_profile_id("A4C") == STUDY_PROFILE_ECHO
    assert view_profile_id("PSAX") == STUDY_PROFILE_ECHO
    assert view_profile_id(UNKNOWN_VIEW) is None
    assert view_profile_id("not-a-view") is None


def test_threshold_override() -> None:
    workflow = ViewRecognitionWorkflow(StubRecognizer("A4C", 0.5), InMemoryDecisionStore(), threshold=0.4)
    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    assert suggestion.is_confident is True


def test_suggestion_is_view_suggestion_instance() -> None:
    workflow = ViewRecognitionWorkflow(StubRecognizer("PLAX", 0.95), InMemoryDecisionStore())
    suggestion = workflow.suggest(_frames(), study_uid="s", series_uid="se")
    assert isinstance(suggestion, ViewSuggestion)
