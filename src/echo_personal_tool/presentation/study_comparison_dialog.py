"""Choose the other study to put beside the current one (issue 562).

The dialog lists only studies already open in tabs.  It shows the study date,
the patient context available in the metadata, the study UID tail and the
source, so the physician names both sides of the comparison explicitly before
any pixels are loaded.  No automatic registration and no guessing: a missing
or conflicting name is shown as «идентичность не подтверждена».
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.study_comparison import ComparisonCandidate
from echo_personal_tool.domain.services.study_comparison import (
    ComparisonIdentity,
    PatientMatch,
    StudyIdentity,
    StudyOrder,
)

_PATIENT_KEYS = {
    PatientMatch.SAME: "comparison.patient.same",
    PatientMatch.DIFFERENT: "comparison.patient.different",
    PatientMatch.UNVERIFIED: "comparison.patient.unverified",
}

_ORDER_KEYS = {
    StudyOrder.PREVIOUS: "comparison.order.previous",
    StudyOrder.SAME_DAY: "comparison.order.same_day",
    StudyOrder.NEXT: "comparison.order.next",
    StudyOrder.UNKNOWN: "comparison.order.unknown",
}


def identity_text(identity: ComparisonIdentity) -> str:
    """One honest sentence about what the pair of studies proves."""
    patient = identity.patient_match
    return tr(
        _PATIENT_KEYS[patient],
        current=identity.current.patient_text,
        previous=identity.previous.patient_text,
        patient=identity.previous.patient_text,
    )


class StudyComparisonDialog(QDialog):
    """Pick one open study; the current one is named above the table."""

    def __init__(
        self,
        *,
        current: StudyIdentity,
        candidates: tuple[ComparisonCandidate, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("studyComparisonDialog")
        self.setWindowTitle(tr("comparison.title"))
        self.setModal(True)
        self.resize(720, 420)

        self._current = current
        self._candidates = candidates

        header = QLabel(
            tr(
                "comparison.current",
                date=current.date_text,
                patient=current.patient_text,
                ref=current.study_ref,
            )
        )
        header.setObjectName("comparisonCurrent")
        header.setWordWrap(True)

        self._table = QTableWidget(len(candidates), 4, self)
        self._table.setObjectName("comparisonCandidates")
        self._table.setHorizontalHeaderLabels(
            (
                tr("comparison.column.date"),
                tr("comparison.column.patient"),
                tr("comparison.column.study"),
                tr("comparison.column.source"),
            )
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for row, candidate in enumerate(candidates):
            for column, text in enumerate(
                (
                    candidate.identity.date_text,
                    candidate.identity.patient_text,
                    candidate.identity.study_ref,
                    candidate.identity.source or "—",
                )
            ):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, candidate.identity.study_uid)
                self._table.setItem(row, column, item)
        if candidates:
            self._table.selectRow(0)
        self._table.itemSelectionChanged.connect(self._refresh_hint)

        self._hint = QLabel("")
        self._hint.setObjectName("comparisonHint")
        self._hint.setWordWrap(True)

        note = QLabel(tr("comparison.hint"))
        note.setObjectName("comparisonRegistrationNote")
        note.setWordWrap(True)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText(tr("comparison.open"))
            ok.setEnabled(bool(candidates))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(header)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._hint)
        layout.addWidget(note)
        layout.addWidget(self._buttons)
        self._refresh_hint()

    def _selected_index(self) -> int | None:
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() is not None else []
        return rows[0].row() if rows else None

    def _refresh_hint(self) -> None:
        index = self._selected_index()
        if index is None or not (0 <= index < len(self._candidates)):
            self._hint.setText(tr("comparison.empty") if not self._candidates else "")
            return
        identity = ComparisonIdentity(self._current, self._candidates[index].identity)
        order = tr(_ORDER_KEYS[identity.order])
        self._hint.setText(f"{order} · {identity_text(identity)}")

    def selected_candidate(self) -> ComparisonCandidate | None:
        index = self._selected_index()
        return self._candidates[index] if index is not None and 0 <= index < len(self._candidates) else None

    def identity(self) -> ComparisonIdentity | None:
        candidate = self.selected_candidate()
        return ComparisonIdentity(self._current, candidate.identity) if candidate is not None else None


def ask_comparison_candidate(
    parent: QWidget,
    *,
    current: StudyIdentity,
    candidates: tuple[ComparisonCandidate, ...],
) -> ComparisonCandidate | None:
    """Run the picker; ``None`` means the physician cancelled or had no choice."""
    if not candidates:
        return None
    dialog = StudyComparisonDialog(current=current, candidates=candidates, parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_candidate()
