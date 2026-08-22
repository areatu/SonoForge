"""Floating overlay for real-time STE smoothing control."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class SteSensitivityOverlay(QWidget):
    """Compact floating panel with a smoothing slider that triggers re-computation."""

    smoothness_changed = Signal(float)

    _DEBOUNCE_MS = 150

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("steSensitivityOverlay")
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        header = QLabel("Сглаживание")
        header.setObjectName("steOverlayHeader")
        layout.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(6)

        self._value_label = QLabel("1.0")
        self._value_label.setObjectName("steOverlayValue")
        self._value_label.setFixedWidth(30)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 200)
        self._slider.setValue(100)
        self._slider.setTickPosition(QSlider.TickPosition.NoTicks)
        self._slider.setMinimumWidth(140)
        self._slider.valueChanged.connect(self._on_slider_moved)

        self._reset_btn = QLabel("↺")
        self._reset_btn.setObjectName("steOverlayReset")
        self._reset_btn.setFixedSize(20, 20)
        self._reset_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from PySide6.QtGui import QFont

        font = QFont()
        font.setPointSize(11)
        self._reset_btn.setFont(font)

        row.addWidget(self._slider)
        row.addWidget(self._value_label)
        row.addWidget(self._reset_btn)
        layout.addLayout(row)

        self.setStyleSheet(self._build_style())
        self.hide()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_change)

    def set_smoothness(self, value: float) -> None:
        self._updating = True
        self._slider.setValue(int(value * 100))
        self._value_label.setText(f"{value:.1f}")
        self._updating = False

    def _on_slider_moved(self, raw: int) -> None:
        if self._updating:
            return
        val = raw / 100.0
        self._value_label.setText(f"{val:.1f}")
        self._debounce.start()

    def _emit_change(self) -> None:
        val = self._slider.value() / 100.0
        self.smoothness_changed.emit(val)

    def _build_style(self) -> str:
        return (
            "#steSensitivityOverlay { background: #1e293b; border: 1px solid #334155; border-radius: 6px; }"
            "#steOverlayHeader { color: #94a3b8; font-size: 11px; font-weight: 600; }"
            "#steOverlayValue { color: #e2e8f0; font-size: 12px; font-weight: bold; }"
            "#steOverlayReset { color: #94a3b8; }"
            "QSlider::groove:horizontal { height: 4px; background: #334155; border-radius: 2px; }"
            "QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; "
            "background: #3b82f6; border-radius: 7px; }"
            "QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 2px; }"
        )
