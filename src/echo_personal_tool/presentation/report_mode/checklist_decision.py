"""Explicit «not applicable / not obtained» decision of a checklist item.

The checklist is a completeness control, not a diagnosis: when a measurement is
not expected in this study (or could not be obtained), the physician says so
explicitly.  Both choices require a reason, because an unexplained exception
would make the printed sheet look complete without explaining the gap.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.services.report_sections import (
    CHECK_NOT_APPLICABLE,
    CHECK_NOT_OBTAINED,
    ChecklistDecision,
)


class ChecklistDecisionDialog(QDialog):
    """Pick «неприменимо» or «не получено» and record the mandatory reason."""

    def __init__(
        self,
        *,
        label: str,
        current: ChecklistDecision | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("checklistDecisionDialog")
        self.setWindowTitle(tr("report.checklist.decision_title"))
        self.setModal(True)
        self.resize(420, 180)

        title = QLabel(label)
        title.setObjectName("checklistDecisionLabel")
        title.setWordWrap(True)

        self._kind = QComboBox(self)
        self._kind.setObjectName("checklistDecisionKind")
        self._kind.addItem(tr("report.checklist.not_applicable"), CHECK_NOT_APPLICABLE)
        self._kind.addItem(tr("report.checklist.not_obtained"), CHECK_NOT_OBTAINED)
        if current is not None:
            index = self._kind.findData(current.kind)
            if index >= 0:
                self._kind.setCurrentIndex(index)

        self._reason = QLineEdit(self)
        self._reason.setObjectName("checklistDecisionReason")
        self._reason.setPlaceholderText(tr("report.checklist.reason_placeholder"))
        if current is not None:
            self._reason.setText(current.reason)
        self._reason.textChanged.connect(self._sync_ok)

        form = QFormLayout()
        form.addRow(tr("report.checklist.kind"), self._kind)
        form.addRow(tr("report.checklist.reason"), self._reason)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(self._buttons)
        self._sync_ok()

    def _sync_ok(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(bool(self._reason.text().strip()))

    def decision(self) -> ChecklistDecision:
        """The chosen kind and the trimmed reason."""
        kind = self._kind.currentData()
        return ChecklistDecision(
            kind=kind if isinstance(kind, str) else CHECK_NOT_OBTAINED,
            reason=self._reason.text().strip(),
        )

    @classmethod
    def ask(
        cls,
        parent: QWidget,
        label: str,
        *,
        current: ChecklistDecision | None = None,
    ) -> ChecklistDecision | None:
        """Run the dialog; ``None`` means the physician cancelled."""
        dialog = cls(label=label, current=current, parent=parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        decision = dialog.decision()
        return decision if decision.reason else None
