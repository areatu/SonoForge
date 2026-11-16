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


def test_ui_and_mono_fonts_hint_vertically_only(qapp: QApplication) -> None:
    """Item 8 (2026-11-16): the UI must not condense glyphs at fractional DPI.

    Full hinting rounds advances to whole pixels and squeezes the glyphs into
    them — measured ~1.6× narrower than the same word on the printed sheet.
    Vertical-only hinting keeps baselines crisp and the proportions natural.
    """
    from PySide6.QtGui import QFont

    from echo_personal_tool.resources.bundled_fonts import mono_font, ui_font

    expected = QFont.HintingPreference.PreferVerticalHinting
    assert ui_font().hintingPreference() == expected
    assert mono_font().hintingPreference() == expected
    assert ui_font(bold=True).hintingPreference() == expected
