"""Physician adjudication of discordant conclusion criteria."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import get_language, tr
from echo_personal_tool.domain.services.report_conclusion import ConclusionFinding
from echo_personal_tool.domain.translation import tr_for_language


class ConclusionDecisionDialog(QDialog):
    """Leave the review item or explicitly choose an evidence-supported band."""

    def __init__(self, finding: ConclusionFinding, *, current: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("conclusionDecisionDialog")
        self.setWindowTitle(tr("report.conclusion.choice.title"))
        self.setModal(True)
        self.resize(540, 200)
        layout = QVBoxLayout(self)
        label = QLabel(tr_for_language(finding.text_key, get_language()), self)
        label.setWordWrap(True)
        layout.addWidget(label)
        labels: tuple[str, ...]
        if finding.id == "mv.stenosis":
            labels = ("MVA PHT (cm²)", "MVA PISA (cm²)", tr("report.conclusion.choice.mean_gradient"))
        elif finding.id == "tv.regurgitation":
            labels = ("TR VC (mm)",)
        else:
            labels = ("EROA (cm²)", "RVol (mL)", "RF (%)")
        evidence = "; ".join(
            f"{name}: {value:g}" for name, value in zip(labels, finding.candidate_evidence, strict=True) if value >= 0
        )
        if evidence:
            data_label = QLabel(evidence, self)
            data_label.setObjectName("conclusionDecisionEvidence")
            data_label.setWordWrap(True)
            layout.addWidget(data_label)
        hint = QLabel(tr("report.conclusion.choice.hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._choice = QComboBox(self)
        self._choice.setObjectName("conclusionDecisionChoice")
        self._choice.addItem(tr("report.conclusion.choice.review"), "")
        for key in finding.candidates:
            self._choice.addItem(tr_for_language(key, get_language()), key)
        if current:
            index = self._choice.findData(current)
            if index >= 0:
                self._choice.setCurrentIndex(index)
        layout.addWidget(self._choice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @classmethod
    def ask(cls, parent: QWidget, finding: ConclusionFinding, *, current: str | None = None) -> str | None:
        dialog = cls(finding, current=current, parent=parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        value = dialog._choice.currentData()
        return value if isinstance(value, str) and value in finding.candidates else None
