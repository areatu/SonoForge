"""Offset magnifier loupe (variant B) for precise contour/caliper placement.

Floats left-above the cursor so the true point stays visible. Source pixels
must come from the already-displayed (post-PHI-mask, post-W/L) buffer — the
lens never touches raw DICOM.

Magnification is real: crop size = display diameter / zoom, upscaled with
INTER_NEAREST so ultrasound speckle stays honest.
"""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

_SHOW_MS = 150
_HIDE_MS = 140
_DEFAULT_DIAMETER = 220
_MIN_DIAMETER = 160
_MAX_DIAMETER = 420
_PAD = 22


def _to_pixmap(up_u8: np.ndarray) -> QPixmap:
    if up_u8.ndim == 2:
        h, w = up_u8.shape
        qimg = QImage(up_u8.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    else:
        rgb = np.ascontiguousarray(up_u8[..., :3])
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class MagnifierLens(QWidget):
    """Floating circular loupe positioned with an offset from the cursor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)

        self._op_effect = QGraphicsOpacityEffect(self)
        self._op_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._op_effect)

        self._pixmap: QPixmap | None = None
        self._zoom = 3.0
        self._diameter = _DEFAULT_DIAMETER
        self.setFixedSize(self._diameter + 2 * _PAD, self._diameter + 2 * _PAD)
        self.hide()

        self._anchor_delta = QPoint(0, 0)  # lens-center -> true cursor, for stem
        self._scale = 1.0
        self._anim: QParallelAnimationGroup | None = None
        self._reduce_motion = False

    # -- Qt property for pop animation -------------------------------------
    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, value: float) -> None:
        self._scale = float(value)
        self.update()

    lensScale = Property(float, _get_scale, _set_scale)

    # -- public API ---------------------------------------------------------
    def configure(self, zoom: float, reduce_motion: bool = False) -> None:
        self._zoom = float(max(2.0, min(6.0, zoom)))
        self._reduce_motion = reduce_motion

    def set_lens_diameter(self, diameter: int) -> None:
        diameter = int(max(_MIN_DIAMETER, min(_MAX_DIAMETER, diameter)))
        if diameter != self._diameter:
            self._diameter = diameter
            self.setFixedSize(diameter + 2 * _PAD, diameter + 2 * _PAD)

    def set_crop(self, display_u8: np.ndarray, cx: float, cy: float) -> None:
        """Crop display-image coords around (cx, cy); crop = diameter / zoom."""
        h, w = display_u8.shape[:2]
        half = max(8, int(round(self._diameter / self._zoom / 2)))
        x0, y0 = int(round(cx)) - half, int(round(cy)) - half
        pad_l, pad_t = max(0, -x0), max(0, -y0)
        pad_r = max(0, x0 + 2 * half - w)
        pad_b = max(0, y0 + 2 * half - h)
        crop = display_u8[max(0, y0) : max(0, y0) + 2 * half, max(0, x0) : max(0, x0) + 2 * half]
        if crop.size == 0:
            return
        if pad_l or pad_t or pad_r or pad_b:
            crop = cv2.copyMakeBorder(crop, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
        up = cv2.resize(crop, (self._diameter, self._diameter), interpolation=cv2.INTER_NEAREST)
        self._pixmap = _to_pixmap(np.ascontiguousarray(up))
        self.update()

    def show_animated(self) -> None:
        if self._reduce_motion:
            self._scale = 1.0
            self._op_effect.setOpacity(1.0)
            self.show()
            return
        self._run_anim(show=True)

    def hide_animated(self, instant: bool = False) -> None:
        if instant or self._reduce_motion or not self.isVisible():
            self._stop_anim()
            self.hide()
            return
        self._run_anim(show=False)

    # -- internals ----------------------------------------------------------
    def _stop_anim(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def _run_anim(self, show: bool) -> None:
        self._stop_anim()
        group = QParallelAnimationGroup(self)
        scale_anim = QPropertyAnimation(self, b"lensScale", group)
        scale_anim.setDuration(_SHOW_MS if show else _HIDE_MS)
        scale_anim.setStartValue(0.8 if show else self._scale)
        scale_anim.setEndValue(1.0 if show else 0.88)
        scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        op_anim = QPropertyAnimation(self._op_effect, b"opacity", group)
        op_anim.setDuration(_SHOW_MS if show else _HIDE_MS)
        op_anim.setStartValue(0.0 if show else self._op_effect.opacity())
        op_anim.setEndValue(1.0 if show else 0.0)
        op_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(scale_anim)
        group.addAnimation(op_anim)
        if show:
            self._scale = 0.8
            self._op_effect.setOpacity(0.0)
            self.show()
        else:
            group.finished.connect(self._on_hide_finished)
        self._anim = group
        group.start()

    def _on_hide_finished(self) -> None:
        self.hide()
        # Reset for the next show (invisible anyway, so no flicker).
        self._scale = 1.0
        self._op_effect.setOpacity(1.0)

    def set_anchor_delta(self, delta: QPoint) -> None:
        self._anchor_delta = delta

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        d = self._diameter
        cx = cy = _PAD + d / 2
        radius = d / 2 * self._scale
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Stem toward the true cursor point.
        if self._anchor_delta != QPoint(0, 0):
            p.setPen(QPen(QColor(255, 255, 255, 190), 1.5))
            p.drawLine(
                int(cx),
                int(cy),
                int(cx + self._anchor_delta.x() * 0.30),
                int(cy + self._anchor_delta.y() * 0.30),
            )

        # Circular image, or dark placeholder before the first crop.
        path = QPainterPath()
        path.addEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
        p.save()
        p.setClipPath(path)
        if self._pixmap is not None:
            side = d * self._scale
            p.drawPixmap(int(cx - side / 2), int(cy - side / 2), int(side), int(side), self._pixmap)
        else:
            p.fillRect(
                int(cx - radius),
                int(cy - radius),
                int(radius * 2),
                int(radius * 2),
                QColor(12, 14, 17),
            )
        p.restore()

        # Single white rim + crosshair + badge.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(240, 244, 248, 245), 2.0))
        p.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.0))
        p.drawLine(int(cx - 10), int(cy), int(cx + 10), int(cy))
        p.drawLine(int(cx), int(cy - 10), int(cx), int(cy + 10))
        p.fillRect(int(cx - 1), int(cy - 1), 3, 3, QColor(255, 255, 255, 230))
        p.setBrush(QBrush(QColor(20, 24, 28, 215)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(int(cx - 28), int(cy + radius - 14), 56, 20, 6, 6)
        p.setPen(QPen(QColor(255, 255, 255, 235)))
        p.drawText(
            int(cx - 28),
            int(cy + radius - 14),
            56,
            20,
            Qt.AlignmentFlag.AlignCenter,
            f"{self._zoom:.1f}x",
        )
        p.end()
