"""GE EchoPac-inspired themes for the presentation layer."""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Dark palette (EchoPAC blue-grey) ──────────────────────────────
_DARK = {
    "bg_dark": "#0a1018",
    "bg_panel": "#121a24",
    "bg_control": "#1a2430",
    "bg_button": "#243040",
    "bg_button_hover": "#2e4054",
    "bg_button_pressed": "#1e2a38",
    "accent": "#3d7cb8",
    "accent_bright": "#4a9fd4",
    "accent_tab": "#2d6a9f",
    "text": "#e8eef4",
    "text_dim": "#8fa3b8",
    "border": "#2a3848",
    "slider_track": "#1e2834",
    "slider_fill": "#3a7cb5",
    "reset_bg1": "#8b3a3a",
    "reset_bg2": "#6b2a2a",
    "reset_hov1": "#a84848",
    "reset_hov2": "#7a3232",
    "reset_pressed": "#5a2222",
    "reset_border": "#a04040",
    "reset_border_hov": "#c05050",
    "hover_btn1": "#3a5068",
}

# ── Light palette ──────────────────────────────────────────────────
_LIGHT = {
    "bg_dark": "#f0f0f0",
    "bg_panel": "#ffffff",
    "bg_control": "#e8e8e8",
    "bg_button": "#d4d4d4",
    "bg_button_hover": "#c0c0c0",
    "bg_button_pressed": "#b0b0b0",
    "accent": "#2563a8",
    "accent_bright": "#1d5fa0",
    "accent_tab": "#2060a0",
    "text": "#1a1a1a",
    "text_dim": "#555555",
    "border": "#c0c0c0",
    "slider_track": "#d0d0d0",
    "slider_fill": "#2563a8",
    "reset_bg1": "#c04040",
    "reset_bg2": "#a03030",
    "reset_hov1": "#d05050",
    "reset_hov2": "#b03838",
    "reset_pressed": "#802020",
    "reset_border": "#c04040",
    "reset_border_hov": "#d05050",
    "hover_btn1": "#a0b8c8",
}

# Backward-compatible module-level constants (dark theme defaults)
BG_DARK = _DARK["bg_dark"]
BG_PANEL = _DARK["bg_panel"]
BG_CONTROL = _DARK["bg_control"]
BG_BUTTON = _DARK["bg_button"]
BG_BUTTON_HOVER = _DARK["bg_button_hover"]
BG_BUTTON_PRESSED = _DARK["bg_button_pressed"]
ACCENT = _DARK["accent"]
ACCENT_BRIGHT = _DARK["accent_bright"]
ACCENT_TAB = _DARK["accent_tab"]
TEXT = _DARK["text"]
TEXT_DIM = _DARK["text_dim"]
BORDER = _DARK["border"]
SLIDER_TRACK = "#1e2834"
SLIDER_FILL = "#3a7cb5"

_current_theme_mode = "dark"


def get_theme_palette() -> dict[str, str]:
    """Return the active theme palette dict."""
    return _resolve_theme(_current_theme_mode)


def _resolve_theme(mode: str) -> dict[str, str]:
    if mode == "light":
        return _LIGHT
    if mode == "system":
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return _LIGHT if val == 0 else _DARK
            except Exception:
                return _DARK
        if sys.platform == "darwin":
            import subprocess
            try:
                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True, text=True, timeout=2,
                )
                return _DARK if "Dark" in result.stdout else _LIGHT
            except Exception:
                return _DARK
        return _DARK
    return _DARK


def build_echopac_stylesheet(font_size: int = 12, *, theme: str = "dark") -> str:
    p = _resolve_theme(theme)
    return f"""
QWidget {{
    background-color: {p["bg_panel"]};
    color: {p["text"]};
    font-family: "{FONT_FAMILY_UI}", sans-serif;
    font-size: {font_size}px;
}}
QMainWindow {{
    background-color: {p["bg_dark"]};
}}
QStatusBar {{
    background-color: {p["bg_control"]};
    color: {p["text_dim"]};
    border-top: 1px solid {p["border"]};
}}
QTabWidget::pane {{
    border: 1px solid {p["border"]};
    background: {p["bg_panel"]};
    top: -1px;
}}
QTabBar::tab {{
    background: {p["bg_control"]};
    color: {p["text_dim"]};
    border: 1px solid {p["border"]};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 2px;
    min-width: 72px;
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["accent_bright"]}, stop:1 {p["accent_tab"]});
    color: {p["text"]};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {p["bg_button_hover"]};
    color: {p["text"]};
}}
QPushButton, QToolButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["bg_button_hover"]}, stop:1 {p["bg_button"]});
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 24px;
}}
QPushButton:hover, QToolButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["hover_btn1"]}, stop:1 {p["bg_button_hover"]});
    border-color: {p["accent"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {p["bg_button_pressed"]};
}}
QPushButton:checked, QToolButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["accent_bright"]}, stop:1 {p["accent"]});
    border-color: {p["accent_bright"]};
}}
QGroupBox {{
    border: 1px solid {p["accent_tab"]};
    border-radius: 3px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {p["accent_bright"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QTreeWidget, QListWidget {{
    background: {p["bg_dark"]};
    border: 1px solid {p["border"]};
    alternate-background-color: {p["bg_control"]};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {p["accent_tab"]};
    color: {p["text"]};
}}
QScrollBar:vertical {{
    background: {p["bg_dark"]};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {p["bg_button_hover"]};
    border-radius: 4px;
    min-height: 24px;
}}
QSplitter::handle {{
    background: {p["border"]};
    width: 2px;
}}
#systemBar {{
    background: {p["bg_control"]};
    border-bottom: 1px solid {p["border"]};
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
        stop:0 {p["reset_bg1"]}, stop:1 {p["reset_bg2"]});
    border-color: {p["reset_border"]};
    color: {p["text"]};
}}
#systemBar QPushButton#resetButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["reset_hov1"]}, stop:1 {p["reset_hov2"]});
    border-color: {p["reset_border_hov"]};
}}
#systemBar QPushButton#resetButton:pressed {{
    background: {p["reset_pressed"]};
}}
#toolPanel {{
    background: {p["bg_panel"]};
}}
#toolPanel QPushButton {{
    min-height: 18px;
    max-height: 18px;
    padding: 2px 9px;
    font-size: 11px;
}}
#toolPanel QPushButton#measuresSectionTitle {{
    color: {p["accent_bright"]};
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
    background: {p["bg_button"]};
    border-color: {p["border"]};
}}
#toolPanel QPushButton#measuresSectionTitle[expanded="true"] {{
    background: {p["bg_control"]};
    border-color: {p["accent_tab"]};
}}
#toolPanel QWidget#measuresSectionBody {{
    background: {p["bg_dark"]};
    border-left: 2px solid {p["accent_tab"]};
}}
#thumbnailGallery {{
    background: {p["bg_dark"]};
    border-right: 1px solid {p["border"]};
}}
"""


def apply_echopac_theme(
    widget: QWidget | None = None,
    *,
    font_size: int = 12,
    theme: str = "dark",
) -> None:
    """Apply palette to the whole app. *theme* is 'dark', 'light', or 'system'."""
    global _current_theme_mode
    _current_theme_mode = theme
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(build_echopac_stylesheet(font_size, theme=theme))
    p = _resolve_theme(theme)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(p["bg_panel"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(p["bg_dark"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(p["bg_button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(p["text"]))
    app.setPalette(palette)
    if widget is not None:
        widget.setPalette(palette)
