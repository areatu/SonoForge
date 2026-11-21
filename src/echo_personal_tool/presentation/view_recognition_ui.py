"""View-recognition UI glue for the system bar (issue 639, step 4).

``ViewRecognitionUi`` owns the badge, the override dialog and the
controller/coordinator connections, so ``MainWindow`` stays thin. It binds
to the coordinator's signals directly; the recognition trigger itself is
wired once from the entrypoint.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog

from echo_personal_tool.application.view_recognition_coordinator import (
    ViewRecognitionCoordinator,
)
from echo_personal_tool.domain.models.view_recognition import (
    UNKNOWN_VIEW,
    ViewDecision,
    ViewDecisionSource,
    view_category,
)
from echo_personal_tool.domain.services.view_recognition_workflow import (
    ViewSuggestion,
)
from echo_personal_tool.presentation.system_bar import SystemBar
from echo_personal_tool.presentation.view_badge_widget import ViewBadgeWidget
from echo_personal_tool.presentation.view_override_dialog import ViewOverrideDialog


class ViewRecognitionUi(QObject):
    """Badge + override dialog for the loaded series' view suggestion."""

    def __init__(
        self,
        coordinator: ViewRecognitionCoordinator,
        system_bar: SystemBar,
        show_status: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._show_status = show_status
        self._badge = ViewBadgeWidget(system_bar)
        self._badge.override_requested.connect(self._open_override)
        system_bar.add_view_badge(self._badge)
        coordinator.suggestion_ready.connect(self._on_suggestion)
        coordinator.decision_changed.connect(self._on_decision_changed)

    def _on_suggestion(self, suggestion: object) -> None:
        """Show the recognition badge; ask the user when not confident."""
        if not isinstance(suggestion, ViewSuggestion):
            return
        self._badge.set_suggestion(suggestion)
        if suggestion.is_confident:
            if suggestion.profile_id:
                self._show_status(
                    self._tr("view_recognition.detected_profile", view=suggestion.view, profile=suggestion.profile_id)
                )
        else:
            # Low confidence: the badge alone is not enough — ask immediately.
            self._open_override(suggestion)

    def _on_decision_changed(self, decision: object) -> None:
        if not isinstance(decision, ViewDecision):
            return
        self._badge.set_suggestion(
            ViewSuggestion(
                view=decision.view,
                confidence=decision.confidence,
                category=view_category(decision.view),
                profile_id=decision.profile_id,
                source=decision.source,
            )
        )

    def _open_override(self, suggestion: object = None) -> None:  # noqa: ANN001
        """Open the override dialog for the current suggestion."""
        if not isinstance(suggestion, ViewSuggestion):
            suggestion = ViewSuggestion(
                view=UNKNOWN_VIEW,
                confidence=0.0,
                category="unknown",
                profile_id=None,
                source=ViewDecisionSource.AUTO,
            )
        dialog = ViewOverrideDialog(suggestion, self._badge)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.chosen_view()
        if chosen:
            self._coordinator.choose_view(chosen)

    @staticmethod
    def _tr(key: str, **kwargs: object) -> str:
        from echo_personal_tool.application.localization import tr

        return tr(key, **kwargs)
