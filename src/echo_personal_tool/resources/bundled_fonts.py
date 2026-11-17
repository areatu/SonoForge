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
#: Size of a caption painted over the image (strain segment labels, badges).
#: Was the ``8`` of ``QFont("sans-serif", 8)`` — 8 **points** ≈ 11 px at 96 dpi,
#: which is the same optical size, now in the UI's own unit.
OVERLAY_LABEL_PIXEL_SIZE = 11
#: Size of the overlay legend (``OVERLAY_VERIFICATION``).  Was the ``9`` of
#: ``QFont().setPointSize(9)`` ≈ 12 px at 96 dpi.
OVERLAY_LEGEND_PIXEL_SIZE = 12

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

    Hinting is **off** (``PreferNoHinting``); two earlier incidents decide this
    and both are measurable on any platform:

    * 2026-11-16, item 8 — at fractional DPI scaling (125 %/150 %) Qt rounds
      glyph advances to whole pixels, and full hinting narrows the glyphs to the
      rounded advance, so UI text came out horizontally condensed («Протокол»
      ~1.6× narrower than on the printed sheet).
    * 2026-11-17, item «шрифт» — full hinting also snaps *each stem* to the grid
      independently, so flat-top lowercase letters stop sharing a height.  At
      13 px the bundled Inter renders «м»/«т» one pixel shorter than «ь»/«и»/«п»/
      «я» (7 vs 8 px x-height, measured on the 2026-11-17 PACS screenshot), and
      ClearType adds blue/red fringes on the stems.  The same sweep at
      ``PreferNoHinting`` gives every flat letter the same 7 px height.
      ``PreferVerticalHinting`` is **not** a middle ground on Windows: Qt maps
      it to ``DWRITE_RENDERING_MODE_CLEARTYPE_NATURAL`` (hinted) and only
      ``PreferNoHinting`` to ``..._NATURAL_SYMMETRIC`` (outline, grid-fit off) —
      see ``qwindowsfontenginedirectwrite.cpp``
      ``hintingPreferenceToRenderingMode()``.  At 100 % DPR Qt's
      ``determineHinting()`` additionally turns the *default* preference into
      ``PreferFullHinting``, which is why the previous fix looked like a no-op
      on a 100 % Windows desktop.

    On FreeType (Linux/macOS) ``PreferNoHinting`` is byte-identical to
    ``PreferVerticalHinting`` at every size and DPR that was measured, so the
    change only affects the platform that had the artefact.
    """
    from PySide6.QtGui import QFont

    ensure_bundled_fonts_loaded()
    font = QFont(FONT_FAMILY_UI)
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def mono_font(*, pixel_size: int = DEFAULT_UI_PIXEL_SIZE, bold: bool = False) -> QFont:
    from PySide6.QtGui import QFont

    ensure_bundled_fonts_loaded()
    font = QFont(FONT_FAMILY_MONO)
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def overlay_label_font(*, pixel_size: int = OVERLAY_LABEL_PIXEL_SIZE) -> QFont:
    """Font for the text painted *inside* the image (segment labels, badges).

    These captions are Cyrillic (``strain.segment_name.*``: «БазПерг», «СрБок»),
    so they must come from the bundled UI family: ``QFont("sans-serif", 8)``
    resolved to the *system* sans, which is neither Inter nor guaranteed to have
    a Cyrillic set that matches the rest of the UI — the overlay text was
    visibly a different face from the panel text next to it.  A pixel size (not
    ``pt``) keeps the label the same size on every DPI, matching the rest of the
    interface, where ``pt`` is reserved for PDF/print.
    """
    return ui_font(pixel_size=pixel_size, bold=True)


def overlay_legend_font(*, pixel_size: int = OVERLAY_LEGEND_PIXEL_SIZE) -> QFont:
    """Font for the overlay *legend* (regular weight, one step larger).

    ``OVERLAY_VERIFICATION`` carries counts, so it is read at a glance and must
    line up with the segment labels — same family, no hinting, pixel units.
    """
    return ui_font(pixel_size=pixel_size, bold=False)


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
