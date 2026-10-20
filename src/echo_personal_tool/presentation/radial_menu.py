"""Radial tool menu of the viewer (TP-6, spec §4.4, Q-09).

A marking menu: hold the right button on an idle frame and the wheel of
eight sectors appears after :data:`SHOW_DELAY_MS`; a jerk of at least
:data:`JERK_PX` towards a sector picks it without showing the wheel; a quick
click without a jerk falls back to the legacy context menu of the viewer.
The wheel itself is dumb geometry — :class:`RadialMenuController` owns the
gesture and the window owns the controller, so ``ViewerWidget`` keeps no
gesture state of its own (the QH-3 rule).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from echo_personal_tool.infrastructure.i18n import tr

#: Hold time after which the wheel appears.
SHOW_DELAY_MS = 250
#: Minimum travel of the right button that selects a sector without the wheel.
JERK_PX = 24.0
#: Sectors drawn on the wheel: seven tools plus the fixed «Ещё…».
TOTAL_SECTORS = 8
#: Radii of the wheel: the centre disc is the Esc target.
INNER_RADIUS = 34
OUTER_RADIUS = 112
#: Id of the fixed sector that opens the legacy context menu.
MORE_ID = "more"


def sector_at(dx: float, dy: float) -> int:
    """The sector index (0 = top, clockwise) a vector points at."""
    angle = math.degrees(math.atan2(dy, dx))
    return round(((angle + 90.0) % 360.0) / (360.0 / TOTAL_SECTORS)) % TOTAL_SECTORS


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
        side = 2 * (OUTER_RADIUS + 4)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(side, side)
        self.move(int(center.x() - side / 2), int(center.y() - side / 2))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

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
        self._hover = self._index_at(event.position())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton and event.button() != Qt.MouseButton.RightButton:
            event.ignore()
            return
        index = self._index_at(event.position())
        if index < 0:
            self.dismiss()
            return
        self.select_sector(index)

    def _index_at(self, pos: QPointF) -> int:
        """Sector index under a window-local point; the centre disc is −1."""
        delta = pos - self._center_in_window
        distance = math.hypot(delta.x(), delta.y())
        if distance < INNER_RADIUS:
            return -1
        if distance > OUTER_RADIUS:
            return -1
        return sector_at(delta.x(), delta.y())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self._center_in_window
        step = 360.0 / TOTAL_SECTORS
        more = tr("radial.more")
        labels = [more if tool_id == MORE_ID else caption for tool_id, caption in self._sectors]
        labels.append(more)
        for index in range(TOTAL_SECTORS):
            start = -90.0 - step / 2.0 + index * step
            path_fill = QColor(40, 44, 52, 230)
            if index == self._hover:
                path_fill = QColor(70, 90, 120, 240)
            painter.setBrush(path_fill)
            painter.setPen(QPen(QColor(120, 130, 145), 1))
            painter.drawPie(
                QRectF(center.x() - OUTER_RADIUS, center.y() - OUTER_RADIUS, 2 * OUTER_RADIUS, 2 * OUTER_RADIUS),
                int(start * 16),
                int(step * 16),
            )
            mid = math.radians(start + step / 2.0)
            text_pos = QPointF(
                center.x() + math.cos(mid) * (OUTER_RADIUS + INNER_RADIUS) / 2.0,
                center.y() + math.sin(mid) * (OUTER_RADIUS + INNER_RADIUS) / 2.0,
            )
            painter.drawText(text_pos, labels[index])
        painter.setBrush(QColor(28, 30, 36, 245))
        painter.setPen(QPen(QColor(120, 130, 145), 1))
        painter.drawEllipse(center, INNER_RADIUS - 2, INNER_RADIUS - 2)
        painter.drawText(QRectF(center.x() - INNER_RADIUS, center.y() - 12, 2 * INNER_RADIUS, 24), Qt.AlignmentFlag.AlignCenter, "Esc")


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
        """Track the jerk while the button is held and no wheel is shown."""
        if self._press is None or self._menu is not None:
            return self._menu is not None
        delta = global_pos - self._press
        if math.hypot(delta.x(), delta.y()) >= JERK_PX:
            self._jerk_sector = sector_at(delta.x(), delta.y())
        return True

    def on_right_release(self, global_pos: QPointF) -> bool:
        """Resolve the gesture: jerk sector, wheel (its own grab) or legacy menu."""
        if self._press is None:
            return False
        if self._menu is not None:
            return True  # the popup grabbed the release and resolves itself
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
