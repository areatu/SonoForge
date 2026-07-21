"""Tests for bundled DejaVu fonts."""


from __future__ import annotations

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
