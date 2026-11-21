"""View-recognition badge for the system bar (issue 639, step 4).

A compact clickable badge showing the recognised view and confidence of the
loaded series. Clicking it opens the override dialog (handled by the caller);
the badge itself is stateless beyond the suggestion it displays.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton

from echo_personal_tool.domain.models.view_recognition import UNKNOWN_VIEW
from echo_personal_tool.domain.services.view_recognition_workflow import ViewSuggestion


class ViewBadgeWidget(QToolButton):
    """Badge showing the recognised view + confidence; click → override."""

    override_requested = Signal()

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("viewBadge")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setEnabled(False)
        self.clicked.connect(lambda _checked: self.override_requested.emit())

    def set_suggestion(self, suggestion: ViewSuggestion) -> None:
        """Render a recognition suggestion on the badge."""
        if suggestion.view == UNKNOWN_VIEW:
            self.setText("?")
        else:
            self.setText(f"{suggestion.view} · {suggestion.confidence:.0%}")
        self.setToolTip(
            f"Вид: {suggestion.view} (уверенность {suggestion.confidence:.0%}) — нажмите, чтобы выбрать вид"
        )
        self.setEnabled(True)

    def reset(self) -> None:
        """Hide the badge (no series loaded / recognition not applicable)."""
        self.setText("")
        self.setToolTip("")
        self.setEnabled(False)
