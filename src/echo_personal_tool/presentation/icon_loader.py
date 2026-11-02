"""One loader for the bundled SVG glyphs (UI-0 §5.3, D-07, UA-14).

The glyphs of ``resources/icons`` are SVG files that paint with
``currentColor``.  Until now every widget loaded them on its own with
``QPixmap.loadFromData(svg_bytes)``, which only works while Qt's ``qsvg``
**image-format plugin** is on the plugin path.  A frozen Windows build that does
not ship that plugin therefore renders *no* glyph at all — the caption buttons
of the title bar, the system-bar actions and the tab close mark come out empty
or as a placeholder — while the same code looks correct on Linux, where the
plugin is always present.

``QSvgRenderer`` is part of ``PySide6.QtSvg`` (a Python module, not a plugin
file), so rasterising through it removes that dependency: one code path, the
same picture on Windows, Linux and macOS, at every DPR.

The pixmap is rendered once at :data:`ICON_RENDER_EDGE` logical pixels with an
alpha channel and then scaled by ``QIcon`` to the ``iconSize`` of the button, so
a 16 px caption glyph and a 20 px tool glyph come from the same crisp source.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

#: Edge the glyphs are rasterised at; ``QIcon`` scales it down to ``iconSize``.
ICON_RENDER_EDGE = 48

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def icon_dir() -> Path:
    """The icon directory, honouring the onefile bundle (UA-14)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    return _ICON_DIR


def svg_source(name: str, color: str | None = None) -> str | None:
    """Text of ``<name>.svg`` with ``currentColor`` replaced by *color*.

    ``None`` when the theme has no such glyph: a caption-only button is a design
    case of several views (§4.1), not an error.
    """
    if not name:
        return None
    path = icon_dir() / f"{name}.svg"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if color:
        text = text.replace("currentColor", color)
    return text


def load_svg_icon(
    name: str,
    *,
    color: str | None = None,
    gap_ratio: float = 0.0,
) -> QIcon:
    """A bundled glyph as a ``QIcon``, tinted with *color* (default ``text.1``).

    *gap_ratio* widens the returned box by that fraction of the glyph edge and
    leaves the extra room transparent on the right.  Qt draws the icon of a
    ``QPushButton`` a fixed 4 px from the caption and offers no knob for it, so a
    wider box is the only way to open the icon↔text gap the design asks for:
    the caller asks ``QIcon`` for ``glyph + gap`` and gets the glyph unchanged
    with the gap added (``ACTION_ICON_GAP`` of the system bar).

    Empty when there is no glyph or the renderer rejects the file — callers keep
    their caption fallback.
    """
    from PySide6.QtSvg import QSvgRenderer

    source = svg_source(name, color)
    if source is None:
        return QIcon()
    if color is None:
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        source = svg_source(name, get_theme_tokens()["text.1"])
        if source is None:  # pragma: no cover - file vanished between calls
            return QIcon()
    renderer = QSvgRenderer(source.encode("utf-8"))
    if not renderer.isValid():
        return QIcon()
    pad = int(round(ICON_RENDER_EDGE * max(gap_ratio, 0.0)))
    pixmap = QPixmap(ICON_RENDER_EDGE + pad, ICON_RENDER_EDGE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, ICON_RENDER_EDGE, ICON_RENDER_EDGE))
    painter.end()
    return QIcon(pixmap)


def load_svg_pixmap(name: str, *, color: str | None = None) -> QPixmap:
    """The same glyph as a ``QPixmap`` for callers that set a pixmap, not an icon."""
    icon = load_svg_icon(name, color=color)
    if icon.isNull():
        return QPixmap()
    return icon.pixmap(ICON_RENDER_EDGE, ICON_RENDER_EDGE)
