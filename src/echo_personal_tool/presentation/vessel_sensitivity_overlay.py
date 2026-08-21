"""Floating overlay for vessel auto-trace sensitivity (preset) control."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class VesselSensitivityOverlay(QWidget):
    """Compact vertical strip with three preset buttons for vessel auto-trace."""

    preset_changed = Signal(str)

    _PRESETS = (
        ("high", "High"),
        ("normal", "Normal"),
        ("low", "Low"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("vesselSensitivityOverlay")
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        for key, label in self._PRESETS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(52)
            btn.setObjectName("vesselOverlayBtn")
            btn.setProperty("preset", key)
            btn.clicked.connect(lambda checked, k=key: self._on_preset_clicked(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        self.setStyleSheet(self._build_style())
        self.hide()

    def set_preset(self, preset: str) -> None:
        """Update the active button without emitting a signal."""
        for key, btn in self._buttons.items():
            btn.setChecked(key == preset)

    def _on_preset_clicked(self, preset: str) -> None:
        for key, btn in self._buttons.items():
            btn.setChecked(key == preset)
        self.preset_changed.emit(preset)

    def _build_style(self) -> str:
        return (
            "#vesselSensitivityOverlay { background: transparent; }"
            "#vesselOverlayBtn {"
            "  color: #94a3b8; font-size: 10px; font-weight: 600;"
            "  background: rgba(15, 23, 42, 180); border: 1px solid #334155;"
            "  border-radius: 10px; padding: 4px 0;"
            "}"
            "#vesselOverlayBtn:hover { color: #e2e8f0; border-color: #64748b; }"
            "#vesselOverlayBtn:checked {"
            "  color: #ffffff; background: rgba(37, 99, 235, 220); border-color: #3b82f6;"
            "}"
        )
