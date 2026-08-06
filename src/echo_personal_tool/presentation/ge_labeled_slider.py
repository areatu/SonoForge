"""Clinical-style wide labeled slider with fill indicator."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from echo_personal_tool.presentation.dark_theme import (
    SLIDER_FILL,
    SLIDER_TRACK,
    get_theme_palette,
)


class _SliderTrack(QWidget):
    """Paint track + fill behind a transparent-handle slider."""

    def __init__(self, slider: QSlider, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slider = slider
        self._label = label
        self.setMinimumHeight(28)
        self.setMaximumHeight(28)
        slider.valueChanged.connect(self.update)
        slider.rangeChanged.connect(self.update)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        p = get_theme_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(p["border"]), 1))
        painter.setBrush(QColor(p.get("slider_track", SLIDER_TRACK)))
        painter.drawRoundedRect(rect, 4, 4)

        minimum = self._slider.minimum()
        maximum = self._slider.maximum()
        span = max(1, maximum - minimum)
        ratio = (self._slider.value() - minimum) / span
        fill_width = max(0, int(rect.width() * ratio))
        if fill_width > 0:
            fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.get("slider_fill", SLIDER_FILL)))
            painter.drawRoundedRect(fill_rect, 4, 4)

        painter.setPen(QColor(p["text"]))
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(max(8, font.pointSize()))
        painter.setFont(font)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._label)
        painter.end()


class TopLabeledSlider(QWidget):
    """Standard horizontal slider with a text label above the track."""

    valueChanged = Signal(int)

    def __init__(
        self,
        label: str,
        *,
        minimum: int = 0,
        maximum: int = 100,
        value: int = 50,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = QLabel(label)
        self._title.setStyleSheet("font-weight: 600;")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setValue(value)
        self._slider.valueChanged.connect(self.valueChanged.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._slider)

    def slider(self) -> QSlider:
        return self._slider

    def value(self) -> int:
        return self._slider.value()

    def setValue(self, value: int) -> None:
        self._slider.setValue(value)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._slider.setRange(minimum, maximum)

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        self._title.setEnabled(enabled)
        self._slider.setEnabled(enabled)


class GeLabeledSlider(QWidget):
    """Wide slider with centered label and blue fill (Clinical controls style)."""

    valueChanged = Signal(int)

    def __init__(
        self,
        label: str,
        *,
        minimum: int = 0,
        maximum: int = 100,
        value: int = 50,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label

        self._decrement = QPushButton("<")
        self._decrement.setFixedSize(24, 28)
        self._decrement.clicked.connect(lambda: self.setValue(self.value() - 1))

        self._increment = QPushButton(">")
        self._increment.setFixedSize(24, 28)
        self._increment.clicked.connect(lambda: self.setValue(self.value() + 1))

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setValue(value)
        p = get_theme_palette()
        self._slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                height: 28px;
                background: transparent;
                border: none;
            }}
            QSlider::sub-page:horizontal {{
                background: transparent;
            }}
            QSlider::add-page:horizontal {{
                background: transparent;
            }}
            QSlider::handle:horizontal {{
                background: {p["accent_bright"]};
                width: 6px;
                margin: -2px 0;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {p["accent_tab"]};
            }}
            """
        )
        self._slider.valueChanged.connect(self.valueChanged.emit)

        track_container = QWidget()
        track_layout = QVBoxLayout(track_container)
        track_layout.setContentsMargins(0, 0, 0, 0)
        self._track = _SliderTrack(self._slider, label, track_container)
        track_layout.addWidget(self._track)
        self._slider.setParent(self._track)
        self._slider.setGeometry(0, 0, 200, 28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._decrement)
        layout.addWidget(track_container, stretch=1)
        layout.addWidget(self._increment)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        track = self._track
        if track is not None:
            self._slider.setGeometry(0, 0, track.width(), track.height())

    def slider(self) -> QSlider:
        return self._slider

    def value(self) -> int:
        return self._slider.value()

    def setValue(self, value: int) -> None:
        self._slider.setValue(value)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._slider.setRange(minimum, maximum)

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        self._slider.setEnabled(enabled)
        self._decrement.setEnabled(enabled)
        self._increment.setEnabled(enabled)
