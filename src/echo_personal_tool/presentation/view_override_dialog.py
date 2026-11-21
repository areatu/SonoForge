"""Override dialog for a view-recognition suggestion (issue 639, step 4).

Shows the classifier suggestion (view + confidence + proposed profile) and
lets the user pick a view from the canonical list. The choice is returned to
the caller, which persists it through the workflow; cancelling yields
``None`` and leaves any persisted decision untouched.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS, UNKNOWN_VIEW
from echo_personal_tool.domain.services.view_recognition_workflow import ViewSuggestion


class ViewOverrideDialog(QDialog):
    """Choose / confirm the view of the loaded series."""

    def __init__(self, suggestion: ViewSuggestion, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("viewOverrideDialog")
        self.setWindowTitle(tr("view_recognition.override_title"))
        self._suggestion = suggestion

        layout = QVBoxLayout(self)
        if suggestion.is_confident:
            headline = tr("view_recognition.detected") + f": {suggestion.view}"
        else:
            headline = tr("view_recognition.needs_choice")
        layout.addWidget(QLabel(headline, self))

        detail = f"{tr('view_recognition.confidence')}: {suggestion.confidence:.0%}"
        if suggestion.profile_id:
            detail += f" · {tr('view_recognition.profile')}: {suggestion.profile_id}"
        layout.addWidget(QLabel(detail, self))

        self._view_combo = QComboBox(self)
        self._view_combo.addItems(list(KNOWN_VIEWS) + [UNKNOWN_VIEW])
        index = self._view_combo.findText(suggestion.view)
        if index >= 0:
            self._view_combo.setCurrentIndex(index)
        layout.addWidget(self._view_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen_view(self) -> str | None:
        """The view selected by the user, or ``None`` when cancelled."""
        if self.result() != 1:
            return None
        return str(self._view_combo.currentText())
