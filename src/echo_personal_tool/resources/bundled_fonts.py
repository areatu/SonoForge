"""Register bundled TTF fonts (Golos Text, JetBrains Mono)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

FONT_FAMILY_UI = "Golos Text"
FONT_FAMILY_MONO = "JetBrains Mono"
DEFAULT_UI_POINT_SIZE = 13

_FONT_FILES = (
    "GolosText-Regular.ttf",
    "GolosText-Medium.ttf",
    "GolosText-SemiBold.ttf",
    "GolosText-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Bold.ttf",
)

_FONT_CACHE_DIR = Path.home() / ".sonoforge" / "fonts"
_loaded = False


def ensure_bundled_fonts_loaded() -> None:
    """Load bundled TTFs into Qt (idempotent)."""
    global _loaded
    if _loaded:
        return
    for file_name in _FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(str(_resolved_font_path(file_name)))
        if font_id < 0:
            raise RuntimeError(f"Failed to load bundled font: {file_name}")
    _loaded = True


def ui_font(*, point_size: int = DEFAULT_UI_POINT_SIZE, bold: bool = False) -> QFont:
    ensure_bundled_fonts_loaded()
    font = QFont(FONT_FAMILY_UI, point_size)
    font.setBold(bold)
    return font


def mono_font(*, point_size: int = DEFAULT_UI_POINT_SIZE, bold: bool = False) -> QFont:
    ensure_bundled_fonts_loaded()
    font = QFont(FONT_FAMILY_MONO, point_size)
    font.setBold(bold)
    return font


def report_cyrillic_font_path() -> Path:
    """Stable on-disk path for ReportLab PDF export."""
    return _resolved_font_path("GolosText-Regular.ttf")


@lru_cache(maxsize=len(_FONT_FILES))
def _resolved_font_path(file_name: str) -> Path:
    dest = _FONT_CACHE_DIR / file_name
    if dest.is_file():
        return dest
    _FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ref = resources.files("echo_personal_tool.resources.fonts").joinpath(file_name)
    dest.write_bytes(ref.read_bytes())
    return dest
