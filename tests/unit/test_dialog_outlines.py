"""Dialog boundaries must survive full-bleed child backgrounds and live resize."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.presentation import dark_theme
from echo_personal_tool.presentation.theme.contrast import contrast_ratio

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _theme(qapp):
    previous = dark_theme._current_theme_mode, dark_theme._current_accent_palette
    yield
    dark_theme.apply_clinical_theme(theme=previous[0], accent_palette=previous[1], animate=False)


@pytest.mark.parametrize("theme", ["graphite", "light"])
def test_outline_is_visible_above_children_and_does_not_intercept_clicks(qtbot, theme):
    dark_theme.apply_clinical_theme(theme=theme, animate=False)
    tokens = dark_theme.get_theme_tokens()
    dialog = QDialog()
    dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    qtbot.addWidget(dialog)
    before_flags = dialog.windowFlags()
    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    fill = QWidget(dialog)
    fill.setStyleSheet(f"background: {tokens['surface.1']};")
    body = QVBoxLayout(fill)
    button = QPushButton("Test action")
    called = []
    button.clicked.connect(lambda: called.append(True))
    body.addWidget(button)
    root.addWidget(fill)
    dialog.resize(360, 200)
    dialog.show()
    QApplication.processEvents()
    outline = dialog.findChild(QWidget, "dialogOutline")
    assert outline is not None
    assert outline.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert dialog.windowFlags() == before_flags
    image = dialog.grab().toImage()
    assert image.pixelColor(0, 100) == QColor(tokens["line.dialog"])
    assert image.pixelColor(10, 10) == QColor(tokens["surface.1"])
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert called == [True]
    dialog.resize(420, 260)
    QApplication.processEvents()
    assert outline.geometry() == dialog.rect()
    assert dialog.grab().toImage().pixelColor(0, 130) == QColor(tokens["line.dialog"])
    # Reset/rebuild may add a new edge-to-edge child while the dialog stays
    # visible: re-ensuring must raise, not duplicate, the existing outline.
    from echo_personal_tool.presentation.theme.dialog_outline import ensure_dialog_outline

    cover = QWidget(dialog)
    cover.setGeometry(dialog.rect())
    cover.setStyleSheet(f"background: {tokens['surface.2']};")
    cover.show()
    ensure_dialog_outline(dialog)
    QApplication.processEvents()
    assert len(dialog.findChildren(QWidget, "dialogOutline")) == 1
    assert dialog.grab().toImage().pixelColor(0, 130) == QColor(tokens["line.dialog"])


@pytest.mark.parametrize("theme", ["graphite", "light"])
def test_native_selection_palette_is_readable_and_placeholder_has_explicit_role(qapp, theme):
    dark_theme.apply_clinical_theme(theme=theme, animate=False)
    palette = qapp.palette()
    fg = palette.color(QPalette.ColorRole.HighlightedText).name()
    bg = palette.color(QPalette.ColorRole.Highlight).name()
    assert contrast_ratio(fg, bg) >= 4.5
    tokens = dark_theme.get_theme_tokens()
    assert palette.color(QPalette.ColorRole.PlaceholderText) == QColor(tokens["text.3"])
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText) == QColor(tokens["text.disabled"])
