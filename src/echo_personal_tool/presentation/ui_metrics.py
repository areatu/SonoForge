"""Font-metric sizes for UI chrome (Э4).

Fixed pixel sizes are reserved for *physical* objects: the viewer canvas, the
rulers, plot minimum heights.  Everything that surrounds text — buttons,
fields, toolbars, status bars, panel headers — derives its size from the font,
so a long RU label or the large-font setting cannot clip a caption, and the
global multiplier keeps working in logical pixels.

These helpers deliberately take the widget as the first argument: the answer
must be computed from the *effective* font (which already includes the
stylesheet and the application font) at the moment the widget is built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from PySide6.QtWidgets import QWidget

#: Minimum tap/click target for an icon-only control, in logical pixels.
MIN_CONTROL_HEIGHT = 22


def line_height(widget: QWidget) -> int:
    """Height of one text line in the widget's effective font."""
    return int(widget.fontMetrics().height())


def control_height(widget: QWidget, *, padding: int = 10, minimum: int = MIN_CONTROL_HEIGHT) -> int:
    """Height of a single-line control (button, field, label) for its font."""
    return max(minimum, line_height(widget) + padding)


def text_width(widget: QWidget, text: str, *, padding: int = 16, minimum: int = 0) -> int:
    """Width that fits ``text`` in the widget's font, plus padding."""
    return max(minimum, int(widget.fontMetrics().horizontalAdvance(text)) + padding)


def widest_text_width(
    widget: QWidget,
    texts: Iterable[str],
    *,
    padding: int = 16,
    minimum: int = 0,
) -> int:
    """Width that fits the longest of ``texts``."""
    widest = 0
    for text in texts:
        widest = max(widest, int(widget.fontMetrics().horizontalAdvance(text)))
    return max(minimum, widest + padding)


def two_line_height(widget: QWidget, *, padding: int = 12, minimum: int = 34) -> int:
    """Height of a two-line button (large caption + small caption)."""
    return max(minimum, 2 * line_height(widget) + padding)


def title_bar_height(widget: QWidget, *, padding: int = 14, minimum: int = 30) -> int:
    """Height of a custom window title bar."""
    return max(minimum, line_height(widget) + padding)


def icon_button_size(
    widget: QWidget,
    glyph: str = "\u25c0",
    *,
    padding_h: int = 12,
    padding_v: int = 8,
    minimum: int = MIN_CONTROL_HEIGHT,
) -> tuple[int, int]:
    """Square-ish size for a glyph-only button."""
    width = text_width(widget, glyph, padding=padding_h, minimum=minimum)
    height = control_height(widget, padding=padding_v, minimum=minimum)
    return width, height


def font_pixel_size(widget: QWidget, factor: float = 1.0, *, minimum: int = 8) -> int:
    """A font size derived from the widget's font (for inline HTML spans).

    ``QPushButton`` rich text does not follow the stylesheet font, so labels
    built as HTML must be told a size explicitly — this returns one relative to
    the effective font instead of a hard-coded constant.
    """
    base = widget.font().pixelSize()
    if base <= 0:  # a pt-based font (or an unset size): fall back to the metrics
        base = line_height(widget)
    return max(minimum, int(round(base * factor)))
