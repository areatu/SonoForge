"""Top system bar: study context, view mode, global actions."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)


class SystemBar(QWidget):
    """EchoPac-style header above the main splitter."""

    open_folder_requested = Signal()
    reset_session_requested = Signal()
    caliper_requested = Signal()
    auto_segment_requested = Signal()
    view_mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemBar")

        self._study_label = QLabel("No study loaded")
        self._study_label.setMinimumWidth(200)

        self._modality_label = QLabel("")
        self._modality_label.setMinimumWidth(80)

        self._status_label = QLabel("Ready")
        self._status_label.setMinimumWidth(160)

        self._btn_2d = QToolButton()
        self._btn_2d.setText("2D")
        self._btn_2d.setCheckable(True)
        self._btn_2d.setChecked(True)
        self._btn_2d.clicked.connect(lambda: self._select_mode("2d"))

        self._btn_doppler = QToolButton()
        self._btn_doppler.setText("Doppler")
        self._btn_doppler.setCheckable(True)
        self._btn_doppler.clicked.connect(lambda: self._select_mode("doppler"))

        btn_open = QPushButton("Open folder…")
        btn_open.clicked.connect(self.open_folder_requested.emit)

        btn_caliper = QPushButton("Caliper")
        btn_caliper.setToolTip("Linear caliper (L)")
        btn_caliper.clicked.connect(self.caliper_requested.emit)

        self._btn_auto = QPushButton("Auto Segment")
        self._btn_auto.setToolTip("ONNX auto-segment (I)")
        self._btn_auto.setEnabled(False)
        self._btn_auto.clicked.connect(self.auto_segment_requested.emit)

        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(self.reset_session_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._study_label)
        layout.addWidget(self._modality_label)
        layout.addStretch(1)
        layout.addWidget(self._btn_2d)
        layout.addWidget(self._btn_doppler)
        layout.addWidget(btn_open)
        layout.addWidget(btn_caliper)
        layout.addWidget(self._btn_auto)
        layout.addWidget(btn_reset)
        layout.addWidget(self._status_label)

    def set_study_context(self, label: str, modality: str = "") -> None:
        self._study_label.setText(label)
        self._modality_label.setText(modality)

    def set_status_message(self, message: str) -> None:
        self._status_label.setText(message[:120])

    def set_view_mode(self, mode: str) -> None:
        is_2d = mode.strip().lower() == "2d"
        self._btn_2d.setChecked(is_2d)
        self._btn_doppler.setChecked(not is_2d)

    def set_auto_segment_enabled(self, enabled: bool) -> None:
        self._btn_auto.setEnabled(enabled)

    def _select_mode(self, mode: str) -> None:
        self.set_view_mode(mode)
        self.view_mode_changed.emit(mode)
