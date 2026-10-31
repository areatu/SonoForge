"""Radial tool menu of the viewer (TP-6, spec §4.4, Q-09).

A marking menu: hold the right button on an idle frame and the wheel of
eight sectors appears after :data:`SHOW_DELAY_MS`; a jerk of at least
:data:`JERK_PX` towards a sector picks it without showing the wheel; a quick
click without a jerk falls back to the legacy context menu of the viewer.

Geometry is one contract for the wheel and the gesture: sector *i* covers the
direction ``-90° + i·45°`` measured on the screen (0° is «right», angles grow
clockwise), so sector 0 is straight up, 2 right, 4 down and 6 left.  The wheel
paint iterates the same table — the previous version painted the sectors with
Qt's counter-clockwise angles, so the highlighted sector was mirrored against
the pointer and the whole menu read as «selection goes the other way»
(item 5 of the 2026-10-23 acceptance list).
The wheel itself is dumb geometry — :class:`RadialMenuController` owns the
gesture and the window owns the controller, so ``ViewerWidget`` keeps no
gesture state of its own (the QH-3 rule).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.localization import tr

#: Hold time after which the wheel appears.
SHOW_DELAY_MS = 250
#: Minimum travel of the right button that selects a sector without the wheel.
JERK_PX = 24.0
#: Sectors drawn on the wheel: seven tools plus the fixed «Ещё…».
TOTAL_SECTORS = 8
#: Radii of the wheel: the centre disc is the Esc target.
INNER_RADIUS = 38
#: Outer radius: large enough that a full short label («LVEDV A4C», «КСО ·
#: 4-кам.») fits its chord without eliding to «LVESV…» (2026-10-25).
OUTER_RADIUS = 130
#: Transparent frame kept around the ring so the popup never clips its edge.
WHEEL_MARGIN = 6
#: Id of the fixed sector that opens the legacy context menu.
MORE_ID = "more"


def sector_at(dx: float, dy: float) -> int:
    """The sector index (0 = top, clockwise) a vector points at."""
    angle = math.degrees(math.atan2(dy, dx))
    return round(((angle + 90.0) % 360.0) / (360.0 / TOTAL_SECTORS)) % TOTAL_SECTORS


def sector_center_angle(index: int) -> float:
    """Direction of sector *index* in screen degrees (0 = right, clockwise).

    The single source of both the paint and the hit test: sector 0 is up
    (−90°), every next one is one step clockwise.
    """
    return -90.0 + index * (360.0 / TOTAL_SECTORS)


def sector_span_angle() -> float:
    """Angular width of one sector, in degrees."""
    return 360.0 / TOTAL_SECTORS


class RadialMenu(QWidget):
    """The wheel: seven tool sectors, «Ещё…» and the centre «Esc»."""

    sector_chosen = Signal(str)  # tool id or MORE_ID
    dismissed = Signal()

    def __init__(self, center: QPointF, sectors: Sequence[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._center_in_window = QPointF(OUTER_RADIUS + 4, OUTER_RADIUS + 4)
        configured = [(tool_id, caption) for tool_id, caption in sectors if tool_id][: TOTAL_SECTORS - 1]
        # Short contexts (M-mode has three tools) pad the wheel with «Ещё…».
        empty = (TOTAL_SECTORS - 1) - len(configured)
        self._sectors = tuple(configured) + ((MORE_ID, "…"),) * empty
        self._hover = -1
        self._resolved = False
        # A translucent popup: the wheel is a ring, the four corners of its
        # window must stay see-through.  Without this attribute the window was
        # an opaque square around the circular sectors — exactly the «квадрат с
        # круговыми секциями внутри» of the acceptance list (item 5).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        side = 2 * (OUTER_RADIUS + WHEEL_MARGIN)
        self._center_in_window = QPointF(side / 2.0, side / 2.0)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(side, side)
        # The pressed point is the hub: the wheel is centred where the button
        # went down, so a stroke towards a sector means what it looks like.
        self.move(
            int(round(center.x() - self._center_in_window.x())), int(round(center.y() - self._center_in_window.y()))
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # The button went down in the *viewer*, so this popup never receives the
        # pointer moves of a held right button: without polling, the highlight
        # either froze or — with a release that never arrived — the wheel stayed
        # up and picked a sector on its own (item 5 of the 2026-10-23 list).
        # The poll reads the real cursor, the one thing both sides agree on.
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(16)
        self._cursor_timer.timeout.connect(self.follow_cursor)

    def sector_ids(self) -> tuple[str, ...]:
        """The tool ids in wheel order, ending with the fixed «Ещё…»."""
        return tuple(tool_id for tool_id, _ in self._sectors) + (MORE_ID,)

    def select_sector(self, index: int) -> None:
        """Resolve the wheel on a sector (used by the mouse handler and tests)."""
        if self._resolved:
            return
        self._resolved = True
        if 0 <= index < len(self._sectors):
            self.sector_chosen.emit(self._sectors[index][0])
        elif index == len(self._sectors):
            self.sector_chosen.emit(MORE_ID)
        else:
            self.dismissed.emit()
        self.close()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # The poll starts on the event loop, not inside showEvent: the popup is
        # not mapped yet here, and mapping a global point onto an unmapped popup
        # is exactly the sort of half-built state that crashes a platform plugin.
        QTimer.singleShot(0, self._start_following)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._cursor_timer.stop()
        super().hideEvent(event)

    def _start_following(self) -> None:
        if self.isVisible():
            self._cursor_timer.start()
            self.follow_cursor()

    def follow_cursor(self) -> None:
        """Highlight the sector the *real* cursor points at (see the poll note)."""
        self.set_pointer(self.to_local(QCursor.pos()))

    def to_local(self, global_pos: QPointF) -> QPointF:
        """A global point in this popup's coordinates (``mapFromGlobal`` yields ``QPoint``)."""
        local = self.mapFromGlobal(QPointF(global_pos).toPoint())
        return QPointF(float(local.x()), float(local.y()))

    def set_pointer(self, local_pos: QPointF) -> None:
        """Highlight one window-local point; the tests and ``follow_cursor`` use it."""
        index = self._index_at(local_pos)
        if index != self._hover:
            self._hover = index
            self.update()

    def cursor_index(self) -> int:
        """The sector under the real cursor (−1 for the hub or outside)."""
        return self._index_at(self.to_local(QCursor.pos()))

    def dismiss(self) -> None:
        if not self._resolved:
            self._resolved = True
            self.dismissed.emit()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self._resolved:
            self._resolved = True
            self.dismissed.emit()
        super().closeEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.set_pointer(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.release_at(event.position(), button=event.button())

    def release_at(self, local_pos: QPointF, *, button: Qt.MouseButton | None = None) -> None:
        """Resolve the wheel on a release at *local_pos* (mouse handler and controller)."""
        if button is not None and button not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return
        index = self._index_at(local_pos)
        if index < 0:
            self.set_pointer(local_pos)
            self.dismiss()
            return
        self.set_pointer(local_pos)
        self.select_sector(index)

    def _index_at(self, pos: QPointF) -> int:
        """Sector index under a window-local point; the centre disc is −1.

        Only the *direction* matters outside the hub: a marking menu keeps the
        sector highlighted however far the pointer travelled, so a gesture that
        overshoots the ring still picks what the user aimed at.
        """
        delta = pos - self._center_in_window
        if math.hypot(delta.x(), delta.y()) < INNER_RADIUS:
            return -1
        return sector_at(delta.x(), delta.y())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        center = self._center_in_window
        span = sector_span_angle()
        more = tr("radial.more")
        # The padding sectors of a short context are a bare ellipsis: five
        # identical «Ещё…» captions only made the wheel noisy.
        labels = ["…" if tool_id == MORE_ID else caption for tool_id, caption in self._sectors]
        labels.append(more)

        ring_face = _with_alpha(tokens["surface.2"], 235)
        hover_face = _with_alpha(tokens["accent"], 210)
        hover_text = QColor(tokens["accent.on"])
        text_colour = QColor(tokens["text.1"])
        # A thin contrasting outline so the sectors read as separate slices
        # (2026-10-25: previously fill==pen and the wheel looked like one disc).
        outline = _with_alpha(tokens.get("line.2", tokens["text.3"]), 200)
        ring_rect = QRectF(
            center.x() - OUTER_RADIUS,
            center.y() - OUTER_RADIUS,
            2 * OUTER_RADIUS,
            2 * OUTER_RADIUS,
        )
        # A label has to fit the chord of its own sector, otherwise it spills over
        # its neighbours and over the outer edge of the ring.
        label_radius = (INNER_RADIUS + OUTER_RADIUS) / 2.0
        chord = 2.0 * label_radius * math.sin(math.radians(span) / 2.0)
        label_width = max(36.0, chord - 4.0)
        font = QFont(painter.font())
        font.setPixelSize(max(10, int(min(13.0, label_width / 4.2))))
        painter.setFont(font)

        for index in range(TOTAL_SECTORS):
            # One geometry for the paint and the hit test: sector 0 is up and the
            # sectors run clockwise on screen.  Qt measures counter-clockwise, so
            # a sector centred on screen angle c is a pie from −c − span/2.
            qt_center = -sector_center_angle(index)
            hovered = index == self._hover
            fill = hover_face if hovered else ring_face
            painter.setBrush(fill)
            # Fill first without a pen (no seam), then a thin outline on top.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(ring_rect, int(round((qt_center - span / 2.0) * 16)), int(round(span * 16)))
            painter.setPen(QPen(hover_text if hovered else outline, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPie(ring_rect, int(round((qt_center - span / 2.0) * 16)), int(round(span * 16)))

            screen_angle = math.radians(sector_center_angle(index))
            # Two-line slot: the short label can wrap («КСО · 4-кам.») instead
            # of eliding to «LVESV…» (2026-10-25).
            slot = QRectF(
                center.x() + math.cos(screen_angle) * label_radius - label_width / 2.0,
                center.y() + math.sin(screen_angle) * label_radius - 16,
                label_width,
                32,
            )
            text = labels[index]
            # Prefer a compact form without the context suffix for the wheel.
            if " · " in text:
                text = text.split(" · ", 1)[0]
            painter.setPen(hover_text if hovered else text_colour)
            painter.drawText(slot, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

        hub = QRectF(
            center.x() - INNER_RADIUS + 2,
            center.y() - INNER_RADIUS + 2,
            2 * INNER_RADIUS - 4,
            2 * INNER_RADIUS - 4,
        )
        painter.setBrush(_with_alpha(tokens["surface.0"], 250))
        painter.setPen(QPen(_with_alpha(tokens["line.2"], 220), 1))
        painter.drawEllipse(hub)
        painter.setPen(QColor(tokens["text.2"]))
        painter.drawText(hub, Qt.AlignmentFlag.AlignCenter, "Esc")
        painter.end()


def _with_alpha(colour: str, alpha: int) -> QColor:
    """A palette token as a translucent brush."""
    value = QColor(colour)
    value.setAlpha(alpha)
    return value


class RadialMenuController:
    """The three viewer entry points of the wheel (press, move, release)."""

    def __init__(
        self,
        *,
        sectors: Callable[[], Sequence[tuple[str, str]]],
        on_tool: Callable[[str], None],
        on_more: Callable[[], None],
        parent=None,
    ) -> None:
        self._sectors_source = sectors
        self._on_tool = on_tool
        self._on_more = on_more
        self._press: QPointF | None = None
        self._jerk_sector: int | None = None
        self._menu: RadialMenu | None = None
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SHOW_DELAY_MS)
        self._timer.timeout.connect(self._show_menu)

    @property
    def gesture_active(self) -> bool:
        return self._press is not None

    @property
    def menu(self) -> RadialMenu | None:
        return self._menu

    def on_right_press(self, global_pos: QPointF) -> bool:
        """Start the hold; the wheel (or the jerk) resolves it later."""
        self.cancel()
        self._press = QPointF(global_pos)
        self._jerk_sector = None
        self._timer.start()
        return True

    def on_pointer_move(self, global_pos: QPointF) -> bool:
        """Track the jerk while the button is held; drive the wheel once it is up."""
        if self._press is None:
            return False
        if self._menu is not None:
            # The popup owns the gesture from now on: one highlight rule, the
            # cursor, so the viewer's moves and the wheel's poll cannot disagree.
            self._menu.set_pointer(self._menu.to_local(global_pos))
            return True
        delta = global_pos - self._press
        if math.hypot(delta.x(), delta.y()) >= JERK_PX:
            self._jerk_sector = sector_at(delta.x(), delta.y())
        return True

    def on_right_release(self, global_pos: QPointF) -> bool:
        """Resolve the gesture: jerk sector, wheel (its own grab) or legacy menu."""
        if self._press is None:
            return False
        if self._menu is not None:
            # A release over the wheel resolves it; a release elsewhere (the
            # button went down in the viewer, the wheel is a separate popup)
            # dismisses it rather than leaving a dead wheel on screen.
            menu, self._menu = self._menu, None
            self._press = None
            menu.release_at(menu.to_local(global_pos))
            self._timer.stop()
            return True
        self._timer.stop()
        press, self._press = self._press, None
        delta = global_pos - press
        if self._jerk_sector is None and math.hypot(delta.x(), delta.y()) >= JERK_PX:
            self._jerk_sector = sector_at(delta.x(), delta.y())
        jerk, self._jerk_sector = self._jerk_sector, None
        if jerk is not None:
            self._resolve(jerk)
        else:
            self._on_more()
        return True

    def cancel(self) -> None:
        self._timer.stop()
        self._press = None
        self._jerk_sector = None
        if self._menu is not None:
            menu, self._menu = self._menu, None
            menu.close()

    def _show_menu(self) -> None:
        if self._press is None or self._jerk_sector is not None:
            return  # released early, or the jerk already picked a sector
        sectors = tuple(self._sectors_source())
        if not sectors:
            self._on_more()
            self._press = None
            return
        menu = RadialMenu(self._press, sectors)
        menu.sector_chosen.connect(self._on_sector_chosen)
        menu.dismissed.connect(self._on_menu_dismissed)
        self._menu = menu
        menu.show()

    def _on_sector_chosen(self, tool_id: str) -> None:
        self._menu = None
        self._press = None
        if tool_id == MORE_ID:
            self._on_more()
        else:
            self._on_tool(tool_id)

    def _on_menu_dismissed(self) -> None:
        self._menu = None
        self._press = None

    def _resolve(self, index: int) -> None:
        sectors = tuple(self._sectors_source())
        if 0 <= index < len(sectors):
            self._on_tool(sectors[index][0])
        else:
            self._on_more()
