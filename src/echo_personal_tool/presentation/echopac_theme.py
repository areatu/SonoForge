"""GE EchoPac-inspired dark theme for the presentation layer."""

from __future__ import annotations

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# Core palette (approximate GE EchoPAC dark blue-grey)
BG_DARK = "#0a1018"
BG_PANEL = "#121a24"
BG_CONTROL = "#1a2430"
BG_BUTTON = "#243040"
BG_BUTTON_HOVER = "#2e4054"
BG_BUTTON_PRESSED = "#1e2a38"
ACCENT = "#3d7cb8"
ACCENT_BRIGHT = "#4a9fd4"
ACCENT_TAB = "#2d6a9f"
TEXT = "#e8eef4"
TEXT_DIM = "#8fa3b8"
BORDER = "#2a3848"
SLIDER_TRACK = "#1e2834"
SLIDER_FILL = "#3a7cb5"

ECHOPAC_STYLESHEET = ""  # built by build_echopac_stylesheet()


def build_echopac_stylesheet(font_size: int = 12) -> str:
    return f"""
QWidget {{
    background-color: {BG_PANEL};
    color: {TEXT};
    font-family: "{FONT_FAMILY_UI}", sans-serif;
    font-size: {font_size}px;
}}
QMainWindow {{
    background-color: {BG_DARK};
}}
QStatusBar {{
    background-color: {BG_CONTROL};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG_PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: {BG_CONTROL};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 2px;
    min-width: 72px;
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {ACCENT_BRIGHT}, stop:1 {ACCENT_TAB});
    color: {TEXT};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {BG_BUTTON_HOVER};
    color: {TEXT};
}}
QPushButton, QToolButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {BG_BUTTON_HOVER}, stop:1 {BG_BUTTON});
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 24px;
}}
QPushButton:hover, QToolButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3a5068, stop:1 {BG_BUTTON_HOVER});
    border-color: {ACCENT};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {BG_BUTTON_PRESSED};
}}
QPushButton:checked, QToolButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {ACCENT_BRIGHT}, stop:1 {ACCENT});
    border-color: {ACCENT_BRIGHT};
}}
QGroupBox {{
    border: 1px solid {ACCENT_TAB};
    border-radius: 3px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {ACCENT_BRIGHT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QTreeWidget, QListWidget {{
    background: {BG_DARK};
    border: 1px solid {BORDER};
    alternate-background-color: {BG_CONTROL};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {ACCENT_TAB};
    color: {TEXT};
}}
QScrollBar:vertical {{
    background: {BG_DARK};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BG_BUTTON_HOVER};
    border-radius: 4px;
    min-height: 24px;
}}
QSplitter::handle {{
    background: {BORDER};
    width: 2px;
}}
#systemBar {{
    background: {BG_CONTROL};
    border-bottom: 1px solid {BORDER};
    min-height: 39px;
}}
#systemBar QPushButton {{
    min-height: 27px;
    max-height: 27px;
    padding: 3px 9px;
    font-size: 11px;
}}
#systemBar QPushButton#resetButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #8b3a3a, stop:1 #6b2a2a);
    border-color: #a04040;
    color: {TEXT};
}}
#systemBar QPushButton#resetButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a84848, stop:1 #7a3232);
    border-color: #c05050;
}}
#systemBar QPushButton#resetButton:pressed {{
    background: #5a2222;
}}
#toolPanel {{
    background: {BG_PANEL};
}}
#toolPanel QPushButton {{
    min-height: 18px;
    max-height: 18px;
    padding: 2px 9px;
    font-size: 11px;
}}
#toolPanel QPushButton#measuresSectionTitle {{
    color: {ACCENT_BRIGHT};
    font-weight: 600;
    text-align: left;
    padding: 6px 8px;
    border: 1px solid transparent;
    border-radius: 3px;
    background: transparent;
    min-height: 22px;
    max-height: none;
}}
#toolPanel QPushButton#measuresSectionTitle:hover {{
    background: {BG_BUTTON};
    border-color: {BORDER};
}}
#toolPanel QPushButton#measuresSectionTitle[expanded="true"] {{
    background: {BG_CONTROL};
    border-color: {ACCENT_TAB};
}}
#toolPanel QWidget#measuresSectionBody {{
    background: {BG_DARK};
    border-left: 2px solid {ACCENT_TAB};
}}
#thumbnailGallery {{
    background: {BG_DARK};
    border-right: 1px solid {BORDER};
}}
"""


def apply_echopac_theme(widget: QWidget | None = None, *, font_size: int = 12) -> None:
    """Apply EchoPac palette to the whole app or a subtree."""
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(build_echopac_stylesheet(font_size))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_PANEL))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_DARK))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_CONTROL))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_BUTTON))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_TAB))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    app.setPalette(palette)
    if widget is not None:
        widget.setPalette(palette)
