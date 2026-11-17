"""Tests for bundled DejaVu fonts."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from echo_personal_tool.resources.bundled_fonts import (
    FONT_FAMILY_MONO,
    FONT_FAMILY_UI,
    ensure_bundled_fonts_loaded,
    report_cyrillic_font_path,
)

pytestmark = pytest.mark.gui


def test_bundled_fonts_register_in_qt(qapp: QApplication) -> None:
    ensure_bundled_fonts_loaded()
    families = set(QFontDatabase.families())
    assert FONT_FAMILY_UI in families
    assert FONT_FAMILY_MONO in families


def test_report_font_path_exists() -> None:
    path = report_cyrillic_font_path()
    assert path.is_file()
    assert path.suffix.lower() == ".ttf"


def test_ui_and_mono_fonts_are_not_grid_fitted(qapp: QApplication) -> None:
    """Item 8 (2026-11-16) + item «шрифт» (2026-11-17): no glyph-grid fitting.

    Two artefacts share one cause — Qt snapping glyph *outlines* to the pixel
    grid:

    * at fractional DPI the advances round and full hinting squeezes the glyphs
      into them (~1.6× narrower than the same word on the printed sheet);
    * full hinting also snaps each stem on its own, so at 13 px «м»/«т» end up
      one pixel shorter than «ь»/«и»/«п»/«я» (measured on the 2026-11-17 PACS
      screenshot: 7 px vs 8 px x-height), and ClearType adds colour fringes.

    Only ``PreferNoHinting`` maps to DirectWrite's *symmetric natural* mode with
    grid-fitting off; ``PreferVerticalHinting`` still grid-fits on Windows, and
    at 100 % DPR the *default* preference becomes full hinting.
    """
    from PySide6.QtGui import QFont

    from echo_personal_tool.resources.bundled_fonts import mono_font, ui_font

    expected = QFont.HintingPreference.PreferNoHinting
    assert ui_font().hintingPreference() == expected
    assert mono_font().hintingPreference() == expected
    assert ui_font(bold=True).hintingPreference() == expected


def test_flat_cyrillic_letters_share_one_height(qapp: QApplication) -> None:
    """The visible symptom: flat-top lowercase letters must not differ in height.

    «н м ь т и п г к ч ш ъ ы» all sit on the same outline height (Inter: 1118
    units, no overshoot), so any difference the rasteriser introduces is a
    rendering artefact.  Measured as ink boxes on a real paint device — the same
    path the UI uses — at the shipping size and at a fractional DPR.
    """
    import numpy as np
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

    from echo_personal_tool.resources.bundled_fonts import ui_font

    flat = "нмьтипгкчшъы"

    def ink_height(font: QFont, char: str, dpr: float) -> int:
        width, height = int(40 * dpr), int(60 * dpr)
        image = QImage(width, height, QImage.Format.Format_Grayscale8)
        image.setDevicePixelRatio(dpr)
        image.fill(0)
        painter = QPainter(image)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(int(8 * dpr), int(40 * dpr), char)
        painter.end()
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, image.bytesPerLine())[:, :width]
        rows = np.where((pixels > 60).any(axis=1))[0]
        return int(rows.max() - rows.min() + 1) if rows.size else 0

    for dpr in (1.0, 1.15, 1.25):
        font = ui_font(pixel_size=13)
        heights = {char: ink_height(font, char, dpr) for char in flat}
        assert len(set(heights.values())) == 1, f"DPR {dpr}: uneven letter heights {heights}"
        # Sanity: the measurement is live, not a set of zeros.
        assert min(heights.values()) > 0
        assert QFontMetricsF(font).xHeight() > 0


def test_overlay_captions_use_the_bundled_ui_family(qapp: QApplication) -> None:
    """Overlay text is Cyrillic, so it must not fall back to the system face.

    ``QFont("sans-serif", 8)`` resolved to the *system* sans in **points**: a
    different typeface from the panel text next to it and a size that ignored
    the UI's pixel unit and hinting policy.
    """
    from echo_personal_tool.resources.bundled_fonts import (
        FONT_FAMILY_UI,
        OVERLAY_LABEL_PIXEL_SIZE,
        OVERLAY_LEGEND_PIXEL_SIZE,
        overlay_label_font,
        overlay_legend_font,
    )

    label = overlay_label_font()
    legend = overlay_legend_font()
    for font, size in ((label, OVERLAY_LABEL_PIXEL_SIZE), (legend, OVERLAY_LEGEND_PIXEL_SIZE)):
        assert font.family() == FONT_FAMILY_UI
        assert font.pixelSize() == size
        assert font.pointSize() == -1
    assert label.bold()
    assert not legend.bold()
