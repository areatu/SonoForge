"""Pure window-chrome hit-testing and cross-platform system move/resize helpers.

Implements the contract of ``docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md``
(§4.3, §8.3, UD-13):

- :func:`hit_test` is a pure function of ``(pos, window, *, border, caption,
  buttons, interactive, maximized)`` with no ``QWidget`` or OS dependency, so
  every zone, maximized state, and DPI scale (100 / 150 / 200 %) is unit-tested
  on every platform.
- :func:`zone_to_qt_edges` and :func:`zone_to_cursor_shape` translate the 8
  resize zones into ``Qt.Edge`` flags for ``QWindow.startSystemResize`` and
  resize cursors on non-Windows platforms.
- :func:`start_system_move` and :func:`start_system_resize` delegate window
  dragging and edge resizing to the window manager via ``QWindow``, with a
  deterministic geometry fallback for headless/offscreen QPA platforms.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QSize, Qt

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

Zone = Enum(
    "Zone",
    "CLIENT CAPTION MIN MAX CLOSE LEFT RIGHT TOP BOTTOM TOP_LEFT TOP_RIGHT BOTTOM_LEFT BOTTOM_RIGHT",
)

RESIZE_ZONES: frozenset[Zone] = frozenset(
    {
        Zone.LEFT,
        Zone.RIGHT,
        Zone.TOP,
        Zone.BOTTOM,
        Zone.TOP_LEFT,
        Zone.TOP_RIGHT,
        Zone.BOTTOM_LEFT,
        Zone.BOTTOM_RIGHT,
    }
)

BUTTON_ZONES: frozenset[Zone] = frozenset({Zone.MIN, Zone.MAX, Zone.CLOSE})

#: Default resize border thickness at 100 % scale (spec §4.3: 6 px).
DEFAULT_RESIZE_BORDER_PX: int = 6

_ZONE_EDGES: dict[Zone, Qt.Edge] = {
    Zone.LEFT: Qt.Edge.LeftEdge,
    Zone.RIGHT: Qt.Edge.RightEdge,
    Zone.TOP: Qt.Edge.TopEdge,
    Zone.BOTTOM: Qt.Edge.BottomEdge,
    Zone.TOP_LEFT: Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
    Zone.TOP_RIGHT: Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    Zone.BOTTOM_LEFT: Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    Zone.BOTTOM_RIGHT: Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
}

_ZONE_CURSORS: dict[Zone, Qt.CursorShape] = {
    Zone.LEFT: Qt.CursorShape.SizeHorCursor,
    Zone.RIGHT: Qt.CursorShape.SizeHorCursor,
    Zone.TOP: Qt.CursorShape.SizeVerCursor,
    Zone.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Zone.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    Zone.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    Zone.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    Zone.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
}


def _normalize_scale_ratio(scale: float | int) -> float:
    """Accept either a multiplier (1.0, 1.5, 2.0) or a percentage (100, 150, 200)."""
    value = float(scale)
    if value <= 0.0:
        return 1.0
    if value >= 10.0:
        return value / 100.0
    return value


def resize_border_for_scale(
    scale: float | int = 1.0,
    *,
    base: int = DEFAULT_RESIZE_BORDER_PX,
) -> int:
    """Return the resize border width in pixels for ``scale`` (ratio or percent)."""
    if base <= 0:
        return 0
    ratio = _normalize_scale_ratio(scale)
    return max(1, round(base * ratio))


def scale_point(point: QPoint, scale: float | int) -> QPoint:
    """Scale a ``QPoint`` by a DPI ratio or percentage."""
    ratio = _normalize_scale_ratio(scale)
    return QPoint(round(point.x() * ratio), round(point.y() * ratio))


def scale_size(size: QSize, scale: float | int) -> QSize:
    """Scale a ``QSize`` by a DPI ratio or percentage."""
    ratio = _normalize_scale_ratio(scale)
    return QSize(round(size.width() * ratio), round(size.height() * ratio))


def scale_rect(rect: QRect, scale: float | int) -> QRect:
    """Scale a ``QRect`` by a DPI ratio or percentage."""
    if not rect.isValid():
        return QRect()
    ratio = _normalize_scale_ratio(scale)
    return QRect(
        round(rect.x() * ratio),
        round(rect.y() * ratio),
        round(rect.width() * ratio),
        round(rect.height() * ratio),
    )


def hit_test(
    pos: QPoint,
    window: QSize,
    *,
    border: int = DEFAULT_RESIZE_BORDER_PX,
    caption: QRect = QRect(),
    buttons: Mapping[Zone, QRect] | None = None,
    interactive: Sequence[QRect] = (),
    maximized: bool = False,
) -> Zone:
    """Classify ``pos`` within ``window`` into a window-chrome :class:`Zone`.

    Priority order (spec §4.3, §8.3):
    1. Points outside ``0 <= x < width`` / ``0 <= y < height`` are ``CLIENT``.
    2. When ``not maximized`` and ``border > 0``, the outer ``border`` pixels
       resolve to the 8 resize edges/corners (``TOP_LEFT`` … ``BOTTOM_RIGHT``).
       In a maximized window, resize edges are inactive so top-edge drags and
       corner caption buttons work at the very edge of the screen.
    3. Window control buttons in ``buttons`` (``MIN``, ``MAX``, ``CLOSE``)
       resolve to their respective zone (enabling ``HTMAXBUTTON`` Snap Layouts
       on Windows 11).
    4. Interactive controls inside the caption (tabs, command field, action
       buttons) always resolve to ``CLIENT``.
    5. Remaining space inside ``caption`` resolves to ``CAPTION``.
    6. Everything else resolves to ``CLIENT``.
    """
    width = window.width()
    height = window.height()
    x = pos.x()
    y = pos.y()
    if width <= 0 or height <= 0 or x < 0 or y < 0 or x >= width or y >= height:
        return Zone.CLIENT

    if not maximized and border > 0:
        on_left = x < border
        on_right = x >= width - border
        on_top = y < border
        on_bottom = y >= height - border
        if on_top and on_left:
            return Zone.TOP_LEFT
        if on_top and on_right:
            return Zone.TOP_RIGHT
        if on_bottom and on_left:
            return Zone.BOTTOM_LEFT
        if on_bottom and on_right:
            return Zone.BOTTOM_RIGHT
        if on_left:
            return Zone.LEFT
        if on_right:
            return Zone.RIGHT
        if on_top:
            return Zone.TOP
        if on_bottom:
            return Zone.BOTTOM

    if buttons:
        for zone, rect in buttons.items():
            if rect.isValid() and rect.contains(pos):
                return zone

    for rect in interactive:
        if rect.isValid() and rect.contains(pos):
            return Zone.CLIENT

    if caption.isValid() and caption.contains(pos):
        return Zone.CAPTION

    return Zone.CLIENT


def zone_to_qt_edges(zone: Zone) -> Qt.Edge:
    """Return the ``Qt.Edge`` combination for ``zone`` (empty for non-resize zones)."""
    return _ZONE_EDGES.get(zone, Qt.Edge(0))


def zone_to_cursor_shape(zone: Zone) -> Qt.CursorShape | None:
    """Return the resize ``Qt.CursorShape`` for ``zone``, or ``None`` if not a resize edge."""
    return _ZONE_CURSORS.get(zone)


def restore_maximized_geometry_for_drag(
    maximized_geo: QRect,
    normal_size: QSize,
    cursor_global: QPoint,
    *,
    caption_height: int = 38,
) -> QRect:
    """Compute restored window geometry anchored proportionally under ``cursor_global``.

    Used when pulling a work-area-maximized window down from the title bar on
    platforms where ``startSystemMove`` does not unmaximize the window itself.
    """
    norm_w = max(normal_size.width(), 320)
    norm_h = max(normal_size.height(), 240)
    max_w = max(maximized_geo.width(), 1)
    rel_x = (cursor_global.x() - maximized_geo.x()) / max_w
    rel_x = min(max(rel_x, 0.1), 0.9)
    rel_y = min(max(cursor_global.y() - maximized_geo.y(), 0), max(caption_height - 1, 0))
    new_x = round(cursor_global.x() - rel_x * norm_w)
    new_y = cursor_global.y() - rel_y
    return QRect(new_x, new_y, norm_w, norm_h)


def collect_caption_geometry(
    window: QWidget,
    caption_widgets: Sequence[QWidget],
    *,
    button_widgets: Mapping[Zone, QWidget | None] | None = None,
    extra_interactive: Sequence[QWidget] = (),
) -> tuple[QRect, dict[Zone, QRect], list[QRect]]:
    """Gather ``(caption_rect, buttons, interactive)`` in ``window`` coordinates."""
    from PySide6.QtWidgets import (
        QAbstractButton,
        QAbstractSlider,
        QComboBox,
        QLineEdit,
        QTabBar,
    )
    from PySide6.QtWidgets import (
        QWidget as _QWidget,
    )

    caption_rect = QRect()
    buttons: dict[Zone, QRect] = {}
    excluded_widgets: set[QWidget] = set()

    if button_widgets:
        for zone, btn in button_widgets.items():
            if btn is None:
                continue
            excluded_widgets.add(btn)
            if not btn.isHidden() and btn.width() > 0 and btn.height() > 0:
                buttons[zone] = QRect(btn.mapTo(window, QPoint(0, 0)), btn.size())

    interactive: list[QRect] = []
    interactive_types = (QAbstractButton, QLineEdit, QComboBox, QAbstractSlider, QTabBar)

    for bar in caption_widgets:
        if bar is None or bar.isHidden() or bar.width() <= 0 or bar.height() <= 0:
            continue
        bar_rect = QRect(bar.mapTo(window, QPoint(0, 0)), bar.size())
        caption_rect = bar_rect if not caption_rect.isValid() else caption_rect.united(bar_rect)
        for child in bar.findChildren(_QWidget):
            if not isinstance(child, interactive_types):
                continue
            if child in excluded_widgets or child.isHidden() or not child.isVisibleTo(bar):
                continue
            if child.width() <= 0 or child.height() <= 0:
                continue
            interactive.append(QRect(child.mapTo(window, QPoint(0, 0)), child.size()))

    for widget in extra_interactive:
        if widget is None or widget in excluded_widgets or widget.isHidden():
            continue
        if widget.width() <= 0 or widget.height() <= 0:
            continue
        interactive.append(QRect(widget.mapTo(window, QPoint(0, 0)), widget.size()))

    return caption_rect, buttons, interactive


def start_system_move(
    window: QWidget,
    *,
    global_pos: QPoint | None = None,
    drag_offset: QPoint | None = None,
) -> bool:
    """Start an OS-managed window move, falling back to manual move when unsupported.

    Returns ``True`` when ``QWindow.startSystemMove()`` took over the drag, and
    ``False`` when the caller should continue feeding manual ``move()`` updates.
    """
    handle = window.windowHandle()
    user_maximized = bool(getattr(window, "_user_maximized", False))
    if handle is not None and not (user_maximized and not window.isMaximized()):
        if handle.startSystemMove():
            return True

    if global_pos is None:
        return False

    if window.isMaximized() or user_maximized:
        normal_geo = getattr(window, "_normal_geometry", None)
        normal_size = (
            normal_geo.size()
            if isinstance(normal_geo, QRect) and normal_geo.isValid()
            else QSize(max(window.minimumWidth(), 1024), max(window.minimumHeight(), 720))
        )
        restored = restore_maximized_geometry_for_drag(window.geometry(), normal_size, global_pos)
        if window.isMaximized():
            window.showNormal()
        window._user_maximized = False  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
        window.setGeometry(restored)
        updater = getattr(window, "_sync_maximize_button_state", None)
        if callable(updater):
            updater()
        if handle is not None and handle.startSystemMove():
            return True
        window.move(restored.topLeft())
        return False

    if drag_offset is not None:
        window.move(global_pos - drag_offset)
    return False


def start_system_resize(window: QWidget, edges: Qt.Edge) -> bool:
    """Start an OS-managed edge/corner resize via ``QWindow.startSystemResize``."""
    if not edges or window.isMaximized() or bool(getattr(window, "_user_maximized", False)):
        return False
    handle = window.windowHandle()
    if handle is None:
        return False
    return bool(handle.startSystemResize(edges))
