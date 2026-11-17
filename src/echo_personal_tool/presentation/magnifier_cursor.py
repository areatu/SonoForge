"""The «лупа» pointer used while the magnifier is armed.

A magnifier cursor is the whole point of item 4 of the 2026-10-23 acceptance
list — the tool has to *announce* itself before the click, not after it.  The
glyph is rendered by the same SVG loader the chrome uses and tinted with the
theme, so it stays visible on light themes too.

The helper lives here rather than in the viewer widget because it is also the
first thing the loupe warm-up touches: rendering an SVG through
``QSvgRenderer`` pulls in the Qt SVG module, and doing that inside the first
``Z`` press was part of the freeze the owner reported on Windows 10 (item 6 of
the 2026-11-17 list).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor

logger = logging.getLogger(__name__)

#: Hot spot of the loupe glyph inside its 32 px box — the centre of the lens.
ZOOM_CURSOR_HOTSPOT = (9, 9)


def magnifier_cursor() -> QCursor:
    """The bundled search glyph as a cursor, or a cross when it is missing."""
    try:
        from echo_personal_tool.presentation.window_chrome.title_bar import load_icon

        icon = load_icon("search")
        if not icon.isNull():
            pixmap = icon.pixmap(32, 32)
            if not pixmap.isNull():
                return QCursor(pixmap, *ZOOM_CURSOR_HOTSPOT)
    except Exception:  # pragma: no cover - a broken install still gets a cursor
        # No payload: the diagnostics ratchet (ER-08/ER-09) forbids logging the
        # exception object, and the fallback below is the whole recovery.
        logger.debug("magnifier cursor unavailable, falling back to a cross")
    return QCursor(Qt.CursorShape.CrossCursor)
