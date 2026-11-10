"""Loop region strip for the cine playback bar (issue 7).

A thin strip painted directly above the frame slider. It shows the manually
placed A→B bounds of the loop the cine playback repeats, and lets the user
drag either bound with the mouse. ``visible`` is False until both bounds are
set (or set externally), so clips without a loop pay no visual cost.

The pixel↔frame mapping reuses :func:`~cine_phase_geometry.x_for_frame` /
:func:`frame_at_x` with the same inset as the slider groove.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from echo_personal_tool.presentation.cine_phase_geometry import SLIDER_INSET, frame_at_x, x_for_frame
from echo_personal_tool.presentation.dark_theme import get_theme_tokens


def _with_alpha(color: str, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(alpha)
    return result


class LoopRegionStrip(QWidget):
    """Paint and edit the A→B loop region of the frame slider below."""

    #: (which, frame) — which is "a" or "b"; emitted live while dragging.
    loop_bound_changed = Signal(str, int)
    #: Click-to-seek on the groove (never fires while dragging a bound).
    frame_selected = Signal(int)

    HEIGHT = 14
    _HANDLE_W = 12.0
    _HANDLE_H = 12.0
    _GRAB_PX = 7.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("loopRegionStrip")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._total = 0
        self._current_frame = 0
        self._loop_in: int | None = None
        self._loop_out: int | None = None
        self._armed = False
        self._drag: str | None = None

    # ── state ────────────────────────────────────────────────────────
    def set_region(self, loop_in: int | None, loop_out: int | None, armed: bool) -> None:
        """Set (or clear, with ``None``) the painted A→B region."""
        total = self._total
        if loop_in is None or loop_out is None or total < 1:
            self._loop_in = None
            self._loop_out = None
            self._armed = False
        else:
            a = max(0, min(int(loop_in), total - 1))
            b = max(0, min(int(loop_out), total - 1))
            self._loop_in, self._loop_out = (a, b) if a <= b else (b, a)
            self._armed = bool(armed)
        self.setVisible(self._loop_in is not None)
        self.update()

    def set_total_frames(self, total_frames: int) -> None:
        total = max(0, int(total_frames))
        if total != self._total:
            self._total = total
            if self._loop_in is not None:
                # Re-clamp to the new clip length; keep the armed flag only
                # when the region still has room.
                assert self._loop_out is not None
                a = min(self._loop_in, max(0, total - 1))
                b = min(self._loop_out, max(0, total - 1))
                self._loop_in, self._loop_out = (a, b) if a <= b else (b, a)
                self._armed = self._armed and a < b
                if total < 2:
                    self._loop_in = self._loop_out = None
                    self._armed = False
                self.setVisible(self._loop_in is not None)
            self.update()

    def set_current_frame(self, frame_index: int) -> None:
        value = max(0, int(frame_index))
        if value != self._current_frame:
            self._current_frame = value
            self.update()

    def region(self) -> tuple[int, int] | None:
        if self._loop_in is None or self._loop_out is None:
            return None
        return (self._loop_in, self._loop_out)

    def is_armed(self) -> bool:
        return self._armed

    # ── geometry ─────────────────────────────────────────────────────
    def _x(self, frame: int) -> float:
        return x_for_frame(frame, self._total, 0.0, float(self.width()), SLIDER_INSET)

    def _frame(self, x: float) -> int:
        return frame_at_x(x, self._total, 0.0, float(self.width()), SLIDER_INSET)

    def _handle_rects(self) -> tuple[QRectF, QRectF] | None:
        if self._loop_in is None or self._loop_out is None:
            return None
        top = (self.HEIGHT - self._HANDLE_H) / 2.0
        rect_a = QRectF(self._x(self._loop_in) - self._HANDLE_W / 2.0, top, self._HANDLE_W, self._HANDLE_H)
        rect_b = QRectF(self._x(self._loop_out) - self._HANDLE_W / 2.0, top, self._HANDLE_W, self._HANDLE_H)
        return rect_a, rect_b

    def _hit_handle(self, x: float) -> str | None:
        rects = self._handle_rects()
        if rects is None:
            return None
        rect_a, rect_b = rects
        center_a = rect_a.center().x()
        center_b = rect_b.center().x()
        dist_a = abs(x - center_a)
        dist_b = abs(x - center_b)
        best_name: str | None = None
        best = self._GRAB_PX
        for name, dist in (("a", dist_a), ("b", dist_b)):
            if dist <= best:
                best_name = name
                best = dist
        return best_name

    # ── painting ─────────────────────────────────────────────────────
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        tokens = get_theme_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())

        # Hairline groove the region sits on.
        painter.setPen(QPen(QColor(tokens["line.1"]), 1.0))
        painter.drawLine(0, int(self.HEIGHT - 1), int(width), int(self.HEIGHT - 1))

        if self._loop_in is None or self._loop_out is None:
            painter.end()
            return

        x0 = self._x(self._loop_in)
        x1 = self._x(self._loop_out)
        accent = tokens["accent.tab"]
        # The armed region is solid; a merely configured one is muted so the
        # user can tell «bounds set» from «loop on» at a glance.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_with_alpha(accent, 110 if self._armed else 45))
        painter.drawRoundedRect(QRectF(x0, 2.0, max(2.0, x1 - x0), self.HEIGHT - 6.0), 2.0, 2.0)

        # Playhead hairline, same convention as the phase strip.
        if self._total > 1:
            head_x = self._x(min(self._current_frame, self._total - 1))
            painter.setPen(QPen(QColor(tokens["text.1"]), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(int(head_x), 0, int(head_x), self.HEIGHT - 1)

        # Handles with letters.
        font = QFont(painter.font())
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        for letter, x in (("A", x0), ("B", x1)):
            rect = QRectF(
                x - self._HANDLE_W / 2.0, (self.HEIGHT - self._HANDLE_H) / 2.0, self._HANDLE_W, self._HANDLE_H
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(accent if self._armed else tokens["surface.3"]))
            painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.setPen(QColor(tokens["accent.on"] if self._armed else tokens["text.2"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()

    # ── interaction ──────────────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._total <= 0:
            super().mousePressEvent(event)
            return
        x = event.position().x()
        handle = self._hit_handle(x)
        if handle is not None:
            self._drag = handle
            event.accept()
            return
        self.frame_selected.emit(self._frame(x))
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None and self._total > 0:
            frame = self._frame(event.position().x())
            # The owner (state manager) clamps/orders the pair and pushes it
            # back through set_loop_region; the strip itself stays dumb.
            self.loop_bound_changed.emit(self._drag, frame)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def is_dragging(self) -> bool:
        return self._drag is not None
