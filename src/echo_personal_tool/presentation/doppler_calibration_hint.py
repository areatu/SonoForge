"""Click-through hint shown when a spectral Doppler strip has no velocity scale."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtWidgets import QLabel

from echo_personal_tool.infrastructure.i18n import tr

DOPPLER_MANUAL_CALIBRATION_HINT_KEY = "viewer.doppler_manual_calibration_hint"


def doppler_manual_calibration_hint_style() -> str:
    """Match the results overlay: translucent plate, readable text, no grab."""
    return (
        "background-color: rgba(0, 0, 0, 178);"
        " color: #e8eef4;"
        " padding: 11px 18px;"
        " border: 2px solid #3d7cb8;"
        " border-radius: 5px;"
        " font-size: 16px;"
    )


class DopplerManualCalibrationHint(QLabel):
    """Centered label that must never steal calibration clicks."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dopplerManualCalibrationHint")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(doppler_manual_calibration_hint_style())
        self.hide()
        self.reload_text()

    def reload_text(self) -> None:
        self.setText(tr(DOPPLER_MANUAL_CALIBRATION_HINT_KEY))
        self.adjustSize()

    def event(self, event) -> bool:  # type: ignore[override]
        # Belt and braces: even a direct delivery must not consume a click.
        if event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.Enter,
            QEvent.Type.Leave,
        }:
            event.ignore()
            return False
        return super().event(event)


def place_hint_in_rect(hint: QLabel, bounds: QRect, center: QPoint | None = None) -> None:
    """Center ``hint`` on ``center`` (or the rect center) and keep it inside ``bounds``."""
    if bounds.width() < 8 or bounds.height() < 8:
        return
    max_width = max(140, min(420, bounds.width() - 16))
    hint.setWordWrap(True)
    hint.setFixedWidth(max_width)
    hint.adjustSize()
    anchor = center if center is not None else bounds.center()
    x = anchor.x() - hint.width() // 2
    y = anchor.y() - hint.height() // 2
    x = max(bounds.left(), min(x, bounds.right() - hint.width() + 1))
    y = max(bounds.top(), min(y, bounds.bottom() - hint.height() + 1))
    hint.move(x, y)
    hint.raise_()
