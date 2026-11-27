"""Non-modal, default-yes training-only review on the image surface."""

from __future__ import annotations

from collections import deque
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.training_archive import MeasurementArchiveCapture
from echo_personal_tool.domain.models.training_archive import ArchiveDecision
from echo_personal_tool.presentation.dark_theme import get_theme_tokens


class TrainingArchivePrompt(QFrame):
    """The sample is already saved. No excludes that exact material only.

    Receipts contain no pixels or patient identity. An unanswered prompt expires
    as Yes; bounded queues cannot retain frames or block clinical tools.
    """

    def __init__(self, parent: QWidget, capture: MeasurementArchiveCapture) -> None:
        super().__init__(parent)
        self.setObjectName("trainingArchivePrompt")
        self.capture = capture
        self.pending: deque[ArchiveDecision] = deque(maxlen=32)
        self.current: ArchiveDecision | None = None
        layout = QVBoxLayout(self)
        self.caption = QLabel()
        self.context = QLabel()
        layout.addWidget(self.caption)
        layout.addWidget(self.context)
        buttons = QHBoxLayout()
        self.yes = QPushButton()
        self.no = QPushButton()
        self.yes.clicked.connect(self.accept)
        self.no.clicked.connect(self.reject)
        buttons.addWidget(self.yes)
        buttons.addWidget(self.no)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(8000)
        self.timer.timeout.connect(self.accept)
        parent.installEventFilter(self)
        capture.saved = self.offer
        self.destroyed.connect(lambda: setattr(capture, "saved", None))
        self.hide()

    def offer(self, decision: ArchiveDecision) -> None:
        if self.capture.paused:
            return
        # A newer version of this slot supersedes its old prompt.
        self.pending = deque((d for d in self.pending if d.sample_id != decision.sample_id), maxlen=32)
        if self.current is not None and self.current.sample_id == decision.sample_id:
            self.current = None
        self.pending.append(decision)
        if self.current is None:
            self.advance()

    def advance(self) -> None:
        self.timer.stop()
        self.current = self.pending.popleft() if self.pending else None
        if self.current is None or self.capture.paused:
            self.hide()
            return
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"QFrame#trainingArchivePrompt {{ background: {tokens['surface.2']}; "
            f"color: {tokens['text.1']}; border: 1px solid {tokens['line.1']}; border-radius: 6px; }}"
        )
        self.caption.setText(tr("ml.contour_prompt"))
        self.context.setText(
            tr(
                "ml.contour_prompt_context",
                chamber=self.current.chamber,
                phase=self.current.phase,
                frame=self.current.frame_index + 1,
            )
        )
        self.yes.setText(tr("ml.contour_yes"))
        self.no.setText(tr("ml.contour_no"))
        self.no.setToolTip(tr("ml.contour_no_tip"))
        self.setToolTip(tr("ml.contour_default_yes"))
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start()

    def accept(self) -> None:
        self.advance()

    def reject(self) -> None:
        if self.current is None:
            return
        if not self.capture.reject(self.current):
            self.context.setText(tr("ml.contour_reject_failed"))
            self.timer.stop()  # allow retry; do not claim exclusion on failed I/O
            return
        self.advance()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(8, (parent.width() - self.width()) // 2), 12)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.reposition()
        return False


def install_training_archive_prompt(window: Any) -> None:
    from echo_personal_tool.application.composition import services_of

    services = services_of(window._controller)
    capture = services.training_archive if services is not None else None
    if capture is not None and window._viewer.findChild(TrainingArchivePrompt) is None:
        TrainingArchivePrompt(window._viewer, capture)
