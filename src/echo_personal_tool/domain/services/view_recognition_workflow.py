"""View-recognition workflow (domain service, no IO / no Qt).

Orchestrates the step-4 decision flow on top of the PR-A pieces:

* :class:`~echo_personal_tool.domain.ports.IViewRecognizer` produces a raw
  :class:`~echo_personal_tool.domain.models.view_recognition.RecognizedView`;
* :class:`ViewRecognitionWorkflow` turns it into a :class:`ViewSuggestion`
  (view + confidence + proposed study profile) and applies the confidence
  threshold;
* a user override becomes a persisted
  :class:`~echo_personal_tool.domain.models.view_recognition.ViewDecision`
  through the :class:`~echo_personal_tool.domain.ports.IViewDecisionStore`
  port, so the next load of the same series restores the manual choice
  instead of running the classifier again.

The workflow is deliberately Qt-free and IO-free: persistence goes through the
port, inference through the recognizer port, so both are testable with stubs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.view_recognition import (
    ALL_RECOGNIZABLE_VIEWS,
    RECOGNITION_CONFIDENCE_THRESHOLD,
    UNKNOWN_VIEW,
    RecognizedView,
    ViewDecision,
    ViewDecisionSource,
    view_category,
)
from echo_personal_tool.domain.ports import IViewDecisionStore, IViewRecognizer
from echo_personal_tool.domain.services.study_view_resolver import StudyViewClip, StudyViewCue, resolve_study_views


@dataclass(frozen=True)
class ViewSuggestion:
    """A view proposal shown by the UI badge / override dialog.

    ``profile_id`` is the study profile the recognised view suggests
    (``None`` when no profile mapping applies, e.g. ``UNKNOWN``); the UI
    proposes it but never applies it without the user.
    """

    view: str
    confidence: float
    category: str
    profile_id: str | None
    source: ViewDecisionSource
    threshold: float = RECOGNITION_CONFIDENCE_THRESHOLD

    @property
    def is_confident(self) -> bool:
        """True when confidence meets the auto-apply threshold."""
        return float(self.confidence) >= float(self.threshold)


def view_profile_id(view: str) -> str | None:
    """Map a canonical view to the study profile it suggests.

    Cardiac views all belong to the adult-echo profile; ``UNKNOWN`` (and any
    unmapped label) proposes nothing. Imported lazily inside the function to
    keep this module import-light for the pure-core lane.
    """
    from echo_personal_tool.domain.study_profiles import STUDY_PROFILE_ECHO

    if view == UNKNOWN_VIEW or view not in ALL_RECOGNIZABLE_VIEWS:
        return None
    return STUDY_PROFILE_ECHO


class ViewRecognitionWorkflow:
    """Run recognition and manage the suggest / override / restore flow."""

    def __init__(
        self,
        recognizer: IViewRecognizer,
        decision_store: IViewDecisionStore,
        *,
        threshold: float = RECOGNITION_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._recognizer = recognizer
        self._store = decision_store
        self._threshold = float(threshold)

    def suggest(
        self,
        frames: Sequence[np.ndarray],
        *,
        study_uid: str,
        series_uid: str,
    ) -> ViewSuggestion:
        """Produce a view suggestion for ``frames``.

        A persisted manual decision for the series wins: it is restored with
        ``MANUAL`` source and confidence ``1.0`` (the user already accepted
        the choice, so the classifier is not re-run). Otherwise the recognizer
        runs and its raw result is mapped to a suggestion.
        """
        restored = self._store.load(study_uid, series_uid)
        if restored is not None and restored.source is ViewDecisionSource.MANUAL:
            return self._to_suggestion(restored)

        recognized = self._recognizer.recognize(frames)
        return self._to_suggestion_from_recognized(recognized)

    def suggest_study(
        self,
        clips: Sequence[StudyViewClip],
        *,
        study_uid: str,
        cues: Sequence[StudyViewCue] = (),
    ) -> tuple[ViewDecision, ...]:
        """Non-mutating study suggestions; the UI must opt in separately.

        Manual decisions are restored from the port, never inferred from an
        automatically predicted view or silently written back as manual.
        """
        decisions = {}
        for clip in clips:
            decision = self._store.load(study_uid, clip.series_uid)
            if decision is not None:
                if decision.study_uid != study_uid or decision.series_uid != clip.series_uid:
                    raise ValueError("view decision identity mismatch")
                decisions[clip.series_uid] = decision
        resolved = resolve_study_views(clips, manual_decisions=decisions, cues=cues, threshold=self._threshold)
        return tuple(
            decisions[result.series_uid]
            if result.source is ViewDecisionSource.MANUAL
            else ViewDecision(
                study_uid,
                result.series_uid,
                result.view,
                result.source,
                result.confidence,
                view_profile_id(result.view),
            )
            for result in resolved
        )

    def apply_override(
        self,
        view: str,
        *,
        study_uid: str,
        series_uid: str,
        confidence: float = 1.0,
    ) -> ViewDecision:
        """Persist a user-chosen view for the series and return the decision."""
        decision = ViewDecision(
            study_uid=study_uid,
            series_uid=series_uid,
            view=view,
            source=ViewDecisionSource.MANUAL,
            confidence=float(confidence),
            profile_id=view_profile_id(view),
        )
        self.save_decision(decision)
        return decision

    def save_decision(self, decision: ViewDecision) -> None:
        """Persist an already-built decision through the store port."""
        if decision.source is not ViewDecisionSource.MANUAL:
            restored = self._store.load(decision.study_uid, decision.series_uid)
            if restored is not None and restored.source is ViewDecisionSource.MANUAL:
                return
        self._store.save(decision)

    def _to_suggestion(self, decision: ViewDecision) -> ViewSuggestion:
        return ViewSuggestion(
            view=decision.view,
            confidence=decision.confidence,
            category=view_category(decision.view),
            profile_id=decision.profile_id,
            source=decision.source,
            threshold=self._threshold,
        )

    def _to_suggestion_from_recognized(self, recognized: RecognizedView) -> ViewSuggestion:
        return ViewSuggestion(
            view=recognized.view,
            confidence=float(recognized.confidence),
            category=view_category(recognized.view),
            profile_id=view_profile_id(recognized.view),
            source=ViewDecisionSource.AUTO,
            threshold=self._threshold,
        )
