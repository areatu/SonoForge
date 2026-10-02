"""Timeline marker strip for one Multiview pane.

The strip is aligned with the pane's frame slider (not with the pane itself) so
a marker sits exactly above the frame it belongs to.  Clicking a marker moves
that pane; in a synchronised mode the controller turns the click into a move of
the shared playhead.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from echo_personal_tool.domain.models.multiview import EventMarker

#: Marker colours cycle in this order; the number keeps them distinguishable.
_MARKER_COLORS = ("#ff5252", "#ffb300", "#40c4ff", "#69f0ae", "#e040fb", "#ffd740")

_STRIP_HEIGHT = 18


def marker_color(ordinal: int) -> str:
    return _MARKER_COLORS[ordinal % len(_MARKER_COLORS)]


class MarkerStrip(QWidget):
    """Draws the ordered event markers of a single pane above its slider."""

    marker_clicked = Signal(int)  # frame index
    marker_remove_requested = Signal(int)  # marker ordinal
    marker_renamed = Signal(int, str)  # marker ordinal, new label

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_STRIP_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("")
        self._markers: tuple[EventMarker, ...] = ()
        self._total_frames = 0
        self._current_frame = 0
        self._window: tuple[int, int] | None = None
        self._track = QRectF()

    # ── data ────────────────────────────────────────────────────────

    def set_markers(self, markers: tuple[EventMarker, ...], total_frames: int) -> None:
        self._markers = tuple(markers)
        self._total_frames = max(0, int(total_frames))
        self.update()

    def set_current_frame(self, frame_index: int) -> None:
        self._current_frame = max(0, int(frame_index))
        self.update()

    def set_window(self, start_frame: int | None, end_frame: int | None) -> None:
        """Extent of the shared common window drawn on this pane's timeline.

        Spec 8.2: each pane shows its own start and the common endpoint, so the
        part of the longer clip that is *not* played stays visible as such.
        """
        if start_frame is None or end_frame is None or end_frame <= start_frame:
            self._window = None
        else:
            self._window = (int(start_frame), int(end_frame))
        self.update()

    def set_track(self, left: float, width: float) -> None:
        """Horizontal extent of the pane slider this strip is aligned with."""
        self._track = QRectF(left, 0.0, max(1.0, width), float(_STRIP_HEIGHT))
        self.update()

    # ── geometry helpers ────────────────────────────────────────────

    def _ratio(self, frame_index: int) -> float:
        if self._total_frames <= 1:
            return 0.0
        return min(1.0, max(0.0, frame_index / float(self._total_frames - 1)))

    def marker_rects(self) -> list[tuple[QRectF, EventMarker]]:
        rects: list[tuple[QRectF, EventMarker]] = []
        for ordinal, marker in enumerate(self._markers):
            ratio = self._ratio(marker.frame_index)
            centre = self._track.left() + ratio * self._track.width()
            rects.append((QRectF(centre - 7.0, 1.0, 14.0, _STRIP_HEIGHT - 2.0), marker))
        return rects

    # ── painting ────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # baseline
        baseline_y = float(_STRIP_HEIGHT) - 5.0
        painter.setPen(QPen(QColor("#3a3f45"), 1.0))
        painter.drawLine(
            QPoint(int(self._track.left()), int(baseline_y)),
            QPoint(int(self._track.left() + self._track.width()), int(baseline_y)),
        )
        # shared common window (spec 8.2)
        if self._window is not None:
            start_x = self._track.left() + self._ratio(self._window[0]) * self._track.width()
            end_x = self._track.left() + self._ratio(self._window[1]) * self._track.width()
            band = QRectF(start_x, 0.0, max(1.0, end_x - start_x), float(_STRIP_HEIGHT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(64, 226, 222, 38))
            painter.drawRoundedRect(band, 3.0, 3.0)
            painter.setPen(QPen(QColor("#40e2de"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPoint(int(start_x), 0), QPoint(int(start_x), int(baseline_y)))
            painter.drawLine(QPoint(int(end_x), 0), QPoint(int(end_x), int(baseline_y)))
        # playhead
        if self._total_frames > 0:
            playhead = self._track.left() + self._ratio(self._current_frame) * self._track.width()
            painter.setPen(QPen(QColor("#8ab4f8"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPoint(int(playhead), 0), QPoint(int(playhead), int(baseline_y)))
        font = QFont(painter.font())
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        for ordinal, (rect, marker) in enumerate(self.marker_rects()):
            color = QColor(marker_color(ordinal))
            painter.setPen(QPen(color, 1.4))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.setPen(QPen(QColor("#0b0d10"), 1.0))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(ordinal + 1))
            label = f"{marker.label} · {tr_frame(marker.frame_index)}"
            text_width = painter.fontMetrics().horizontalAdvance(label) + 6
            text_rect = QRectF(rect.center().x() - text_width / 2.0, baseline_y + 1.0, text_width, 11.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(11, 13, 16, 220))
            painter.drawRoundedRect(text_rect, 2.0, 2.0)
            painter.setPen(QPen(QColor("#d7dde3"), 1.0))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()

    # ── interaction ─────────────────────────────────────────────────

    def _hit(self, pos) -> tuple[int, EventMarker] | None:
        for ordinal, (rect, marker) in enumerate(self.marker_rects()):
            if rect.contains(QPointF(pos)):
                return ordinal, marker
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit(event.position())
            if hit is not None:
                self.marker_clicked.emit(hit[1].frame_index)
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        hit = self._hit(event.pos())
        if hit is None:
            super().contextMenuEvent(event)
            return
        from PySide6.QtWidgets import QMenu

        ordinal, marker = hit
        menu = QMenu(self)
        menu.addAction(tr_remove_marker(ordinal + 1), lambda: self.marker_remove_requested.emit(ordinal))
        menu.addAction(
            tr_rename_marker(ordinal + 1),
            lambda: self._rename_marker(ordinal, marker),
        )
        menu.exec(event.globalPos())

    def _rename_marker(self, ordinal: int, marker: EventMarker) -> None:
        """Let the user label the event differently from the default МК."""
        from PySide6.QtWidgets import QInputDialog

        label, ok = QInputDialog.getText(
            self,
            tr_rename_title(),
            tr_rename_label(),
            text=marker.label,
        )
        if not ok:
            return
        self.marker_renamed.emit(ordinal, label.strip())

    def refresh_tooltip(self) -> None:
        if not self._markers:
            self.setToolTip("")
            return
        lines = [f"{index + 1}. {marker.describe()}" for index, marker in enumerate(self._markers)]
        self.setToolTip("\n".join(lines))


def tr_frame(frame_index: int) -> str:
    """``frame_index`` (0-based) rendered as the 1-based label used in the UI."""
    return f"#{frame_index + 1}"


def tr_remove_marker(ordinal: int) -> str:
    from echo_personal_tool.infrastructure.i18n import tr

    return tr("multiview.marker.remove", number=str(ordinal))


def tr_rename_marker(ordinal: int) -> str:
    from echo_personal_tool.infrastructure.i18n import tr

    return tr("multiview.marker.rename", number=str(ordinal))


def tr_rename_title() -> str:
    from echo_personal_tool.infrastructure.i18n import tr

    return tr("multiview.marker.rename_title")


def tr_rename_label() -> str:
    from echo_personal_tool.infrastructure.i18n import tr

    return tr("multiview.marker.rename_label")
