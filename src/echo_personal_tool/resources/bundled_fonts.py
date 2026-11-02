"""Register bundled TTF fonts (DejaVu, Inter, JetBrains Mono)."""

from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QFont

from echo_personal_tool.infrastructure.paths import fonts_cache_dir

FONT_FAMILY_UI = "Inter"
FONT_FAMILY_MONO = "JetBrains Mono"
DEFAULT_UI_PIXEL_SIZE = 13

_FONT_FILES = (
    "Inter-Regular.ttf",
    "Inter-Bold.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Medium.ttf",
    "InterDisplay-Regular.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Bold.ttf",
)

_FONT_CACHE_DIR = fonts_cache_dir()
_loaded = False


def ensure_bundled_fonts_loaded() -> None:
    """Load bundled TTFs into Qt (idempotent)."""
    from PySide6.QtGui import QFontDatabase

    global _loaded
    if _loaded:
        return
    for file_name in _FONT_FILES:
        path = _resolved_font_path(file_name)
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            size = path.stat().st_size if path.is_file() else -1
            raise RuntimeError(f"Failed to load bundled font: {file_name} ({size} bytes at {path})")
    _loaded = True


def ui_font(*, pixel_size: int = DEFAULT_UI_PIXEL_SIZE, bold: bool = False) -> QFont:
    """Application font in logical pixels.

    One unit for the whole UI: the same pixel size goes into the QSS
    stylesheet and into the application font (Э4).  ``pt`` remains only in
    PDF/print output.
    """
    from PySide6.QtGui import QFont

    ensure_bundled_fonts_loaded()
    font = QFont(FONT_FAMILY_UI)
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    return font


def mono_font(*, pixel_size: int = DEFAULT_UI_PIXEL_SIZE, bold: bool = False) -> QFont:
    from PySide6.QtGui import QFont

    ensure_bundled_fonts_loaded()
    font = QFont(FONT_FAMILY_MONO)
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    return font


def report_cyrillic_font_path() -> Path:
    """Stable on-disk path for ReportLab PDF export."""
    return _resolved_font_path("Inter-Regular.ttf")


@lru_cache(maxsize=len(_FONT_FILES))
def _resolved_font_path(file_name: str) -> Path:
    dest = _FONT_CACHE_DIR / file_name
    if dest.is_file():
        return dest
    _FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ref = resources.files("echo_personal_tool.resources.fonts").joinpath(file_name)
    # Atomic publish: pytest-xdist workers share this cache, and a sibling
    # must never observe a half-written file (addApplicationFont then fails
    # with -1 on a valid font).
    tmp = dest.with_name(f"{file_name}.{os.getpid()}.tmp")
    tmp.write_bytes(ref.read_bytes())
    os.replace(tmp, dest)
    return dest
