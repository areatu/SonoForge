"""Top system bar: study context, global actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class _ElidingStatusLabel(QLabel):
    """Single-line status text: elide when space is tight; full text in tooltip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        base = super().minimumSizeHint()
        return QSize(0, base.height())

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._apply_elision()

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        if not self._full_text:
            super().setText("")
            self.setToolTip("")
            return
        available = max(self.contentsRect().width(), 0)
        if available <= 0:
            super().setText("")
            self.setToolTip(self._full_text)
            return
        elided = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available,
        )
        super().setText(elided)
        if elided != self._full_text:
            self.setToolTip(self._full_text)
        else:
            self.setToolTip("")


class SystemBar(QWidget):
    """EchoPac-style header above the main splitter."""

    open_folder_requested = Signal()
    load_from_server_requested = Signal()
    reset_session_requested = Signal()
    caliper_requested = Signal()
    calibration_requested = Signal()
    doppler_calibration_requested = Signal()
    settings_requested = Signal()
    references_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemBar")

        self._study_label = QLabel("No study loaded")
        self._study_label.setMinimumWidth(120)
        self._study_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )

        self._status_label = _ElidingStatusLabel()

        btn_open = QPushButton("Open folder…")
        btn_open.clicked.connect(self.open_folder_requested.emit)

        btn_load_server = QPushButton("Загрузить с сервера…")
        btn_load_server.clicked.connect(self.load_from_server_requested.emit)

        self._btn_settings = QPushButton("Настройки")
        self._btn_settings.setToolTip("Параметры измерений и отображения")
        self._btn_settings.clicked.connect(self.settings_requested.emit)

        btn_caliper = QPushButton("Caliper")
        btn_caliper.setToolTip("Linear distance (Dist1, Dist2, …)")
        btn_caliper.clicked.connect(self.caliper_requested.emit)

        btn_calibration = QPushButton("Calibration B-mode")
        btn_calibration.setToolTip("B-mode pixel spacing: depth scale line")
        btn_calibration.clicked.connect(self.calibration_requested.emit)

        btn_doppler_calibration = QPushButton("Calibration Doppler")
        btn_doppler_calibration.setToolTip(
            "Doppler spectrogram: ROI → baseline → velocity scale"
        )
        btn_doppler_calibration.clicked.connect(self.doppler_calibration_requested.emit)

        self._btn_references = QPushButton("Нормативы")
        self._btn_references.setToolTip("Справочник нормативных значений ASE")
        self._btn_references.clicked.connect(self.references_requested.emit)

        btn_reset = QPushButton("Reset")
        btn_reset.setObjectName("resetButton")
        btn_reset.clicked.connect(self.reset_session_requested.emit)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(btn_open, 0)
        left_layout.addWidget(btn_load_server, 0)
        left_layout.addWidget(self._study_label, 0)
        left_layout.addWidget(self._status_label, 1)

        self._actions_widget = QWidget()
        self._actions_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        for button in (
            self._btn_settings,
            btn_caliper,
            btn_calibration,
            btn_doppler_calibration,
            self._btn_references,
            btn_reset,
        ):
            actions_layout.addWidget(button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        layout.addWidget(left, 1)
        layout.addWidget(self._actions_widget, 0)
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)

        self._status_label.set_full_text("Ready")

    def set_study_context(self, label: str, modality: str = "") -> None:
        del modality
        self._study_label.setText(label)
        self._study_label.setToolTip(label)

    def clear_study_context(self) -> None:
        self._study_label.setText("No study loaded")
        self._study_label.setToolTip("")

    def set_status_message(self, message: str) -> None:
        self._status_label.set_full_text(message)
