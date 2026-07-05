"""GE EchoPac-inspired themes for the presentation layer."""

from __future__ import annotations

import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Dark palette (warm dark, JetBrains Darcula inspired) ──────────
_DARK = {
    "bg_dark": "#111827",
    "bg_panel": "#1a2332",
    "bg_control": "#243044",
    "bg_button": "#2e4054",
    "bg_button_hover": "#3a5068",
    "bg_button_pressed": "#1e2a38",
    "accent": "#9ca3b0",
    "accent_bright": "#b0b8c0",
    "accent_tab": "#3b82f6",
    "text": "#f1f5f9",
    "text_dim": "#94a3b8",
    "border": "#334155",
    "slider_track": "#1e2834",
    "slider_fill": "#3b82f6",
    "reset_bg1": "#991b1b",
    "reset_bg2": "#7f1d1d",
    "reset_hov1": "#dc2626",
    "reset_hov2": "#991b1b",
    "reset_pressed": "#7f1d1d",
    "reset_border": "#ef4444",
    "reset_border_hov": "#f87171",
    "reset_text": "#f1f5f9",
    "progress_text": "#f1f5f9",
    "hover_btn1": "#3a5068",
    "success": "#34d399",
    "warning": "#fb923c",
    "error": "#f87171",
}

# ── Light palette ──────────────────────────────────────────────────
_LIGHT = {
    "bg_dark": "#f8fafc",
    "bg_panel": "#ffffff",
    "bg_control": "#f1f5f9",
    "bg_button": "#e2e8f0",
    "bg_button_hover": "#cbd5e1",
    "bg_button_pressed": "#94a3b8",
    "accent": "#8896a4",
    "accent_bright": "#6b7a8c",
    "accent_tab": "#1d4ed8",
    "text": "#0f172a",
    "text_dim": "#64748b",
    "border": "#e2e8f0",
    "slider_track": "#e2e8f0",
    "slider_fill": "#3b82f6",
    "reset_bg1": "#dc2626",
    "reset_bg2": "#b91c1c",
    "reset_hov1": "#ef4444",
    "reset_hov2": "#dc2626",
    "reset_pressed": "#b91c1c",
    "reset_border": "#ef4444",
    "reset_border_hov": "#f87171",
    "reset_text": "#ffffff",
    "progress_text": "#ffffff",
    "hover_btn1": "#cbd5e1",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
}

# ── VS Code Dark 2026 (Default Dark+ inspired) ───────────────────
_VS_CODE_DARK = {
    "bg_dark": "#1e1e1e",
    "bg_panel": "#252526",
    "bg_control": "#333333",
    "bg_button": "#3c3c3c",
    "bg_button_hover": "#454545",
    "bg_button_pressed": "#2d2d2d",
    "accent": "#007acc",
    "accent_bright": "#1a8fe3",
    "accent_tab": "#007acc",
    "text": "#cccccc",
    "text_dim": "#858585",
    "border": "#3c3c3c",
    "slider_track": "#3c3c3c",
    "slider_fill": "#007acc",
    "reset_bg1": "#c42b1c",
    "reset_bg2": "#a01d10",
    "reset_hov1": "#e04030",
    "reset_hov2": "#c42b1c",
    "reset_pressed": "#8b1a10",
    "reset_border": "#e04030",
    "reset_border_hov": "#f05545",
    "reset_text": "#cccccc",
    "progress_text": "#cccccc",
    "hover_btn1": "#505050",
    "success": "#4ec9b0",
    "warning": "#cca700",
    "error": "#f14c4c",
}

# ── VS Code Light 2026 (Default Light+ inspired) ──────────────────
_VS_CODE_LIGHT = {
    "bg_dark": "#ffffff",
    "bg_panel": "#f3f3f3",
    "bg_control": "#ececec",
    "bg_button": "#ddd",
    "bg_button_hover": "#c8c8c8",
    "bg_button_pressed": "#b0b0b0",
    "accent": "#0066b8",
    "accent_bright": "#005a9e",
    "accent_tab": "#0066b8",
    "text": "#333333",
    "text_dim": "#6e6e6e",
    "border": "#d4d4d4",
    "slider_track": "#d4d4d4",
    "slider_fill": "#0066b8",
    "reset_bg1": "#c42b1c",
    "reset_bg2": "#a01d10",
    "reset_hov1": "#e04030",
    "reset_hov2": "#c42b1c",
    "reset_pressed": "#8b1a10",
    "reset_border": "#c42b1c",
    "reset_border_hov": "#e04030",
    "reset_text": "#ffffff",
    "progress_text": "#ffffff",
    "hover_btn1": "#c0c0c0",
    "success": "#16825d",
    "warning": "#bf8803",
    "error": "#c42b1c",
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
SLIDER_FILL = "#3b82f6"

_current_theme_mode = "dark"


def get_theme_palette() -> dict[str, str]:
    """Return the active theme palette dict."""
    return _resolve_theme(_current_theme_mode)


_THEME_MAP = {
    "dark": _DARK,
    "light": _LIGHT,
    "vscode_dark": _VS_CODE_DARK,
    "vscode_light": _VS_CODE_LIGHT,
}


def _resolve_theme(mode: str) -> dict[str, str]:
    direct = _THEME_MAP.get(mode)
    if direct is not None:
        return direct
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


def build_echopac_stylesheet(font_size: int = 13, *, theme: str = "dark") -> str:
    p = _resolve_theme(theme)
    return f"""
/* ── Global ──────────────────────────────────────────────────── */
QWidget {{
    background-color: {p["bg_panel"]};
    color: {p["text"]};
    font-family: "{FONT_FAMILY_UI}", sans-serif;
    font-size: {font_size}px;
}}
QMainWindow {{
    background-color: {p["bg_dark"]};
}}
QDialog {{
    background-color: {p["bg_panel"]};
    color: {p["text"]};
}}
QScrollArea {{
    background-color: {p["bg_panel"]};
    border: none;
}}
QScrollBar:vertical {{
    background: {p["bg_control"]};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p["accent_tab"]};
    min-height: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p["text_dim"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {p["bg_control"]};
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p["accent_tab"]};
    min-width: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p["text_dim"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Status bar ─────────────────────────────────────────────── */
QStatusBar {{
    background-color: {p["bg_control"]};
    color: {p["text_dim"]};
    border-top: 1px solid {p["border"]};
}}

/* ── Tabs ───────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {p["border"]};
    background: {p["bg_panel"]};
    top: -1px;
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {p["bg_control"]};
    color: {p["text_dim"]};
    border: 1px solid {p["border"]};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 2px;
    min-width: 72px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {p["bg_control"]};
    color: {p["text"]};
    font-weight: 600;
    border-radius: 8px 8px 0 0;
}}
QTabBar::tab:hover:!selected {{
    background: {p["bg_button_hover"]};
    color: {p["text"]};
}}

/* ── Buttons ────────────────────────────────────────────────── */
QPushButton, QToolButton {{
    background: {p["bg_button"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QPushButton:hover, QToolButton:hover {{
    background: {p["bg_button_hover"]};
    border-color: {p["accent"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {p["bg_button_pressed"]};
}}
QPushButton:checked, QToolButton:checked {{
    background: {p["bg_control"]};
    border-color: {p["accent"]};
    color: {p["text"]};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {p["text_dim"]};
    opacity: 0.45;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QCheckBox:disabled {{
    color: {p["text_dim"]};
    opacity: 0.45;
}}
QPushButton:focus, QToolButton:focus {{
    outline: none;
}}

/* ── GroupBox ───────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {p["accent_tab"]};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {p["text"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

/* ── Lists / Trees ─────────────────────────────────────────── */
QTreeWidget, QListWidget {{
    background: {p["bg_dark"]};
    border: 1px solid {p["border"]};
    border-radius: 4px;
    alternate-background-color: {p["bg_control"]};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {p["bg_control"]};
    color: {p["text"]};
}}

/* ── Scrollbar ──────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {p["bg_dark"]};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {p["accent_tab"]};
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {p["bg_dark"]};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {p["accent_tab"]};
    border-radius: 6px;
    min-width: 24px;
}}

/* ── Splitter ───────────────────────────────────────────────── */
QSplitter::handle {{
    background: {p["border"]};
    width: 2px;
}}
QSplitter::handle:hover {{
    background: {p["accent_tab"]};
}}

/* ── Slider ─────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background: {p["slider_track"]};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {p["text"]};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {p["accent_bright"]};
}}
QSlider::sub-page:horizontal {{
    background: {p["slider_fill"]};
    border-radius: 3px;
}}

/* ── ProgressBar ────────────────────────────────────────────── */
QProgressBar {{
    border: 1px solid {p["border"]};
    border-radius: 4px;
    background: {p["bg_control"]};
    text-align: center;
    color: {p["progress_text"]};
    height: 16px;
}}
QProgressBar::chunk {{
    background: {p["accent_tab"]};
    border-radius: 3px;
}}

/* ── SpinBox ────────────────────────────────────────────────── */
QSpinBox {{
    background: {p["bg_control"]};
    border: 1px solid {p["border"]};
    border-radius: 4px;
    padding: 2px 6px;
}}
QSpinBox:focus {{
    border-color: {p["accent_tab"]};
}}

/* ── CheckBox ───────────────────────────────────────────────── */
QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {p["border"]};
    background: {p["bg_control"]};
}}
QCheckBox::indicator:checked {{
    background: {p["text"]};
    border-color: {p["text"]};
}}

/* ── SystemBar ──────────────────────────────────────────────── */
#systemBar {{
    background: {p["bg_control"]};
    border-bottom: 1px solid {p["border"]};
    min-height: 34px;
}}
#systemBar QPushButton {{
    min-height: 23px;
    max-height: 23px;
    padding: 2px 10px;
    font-size: {max(font_size - 1, 11)}px;
    font-weight: 500;
}}
#systemBar QPushButton#resetButton {{
    background: {p["reset_bg1"]};
    border-color: {p["reset_border"]};
    color: {p["reset_text"]};
}}
#systemBar QPushButton#resetButton:hover {{
    background: {p["reset_hov1"]};
    border-color: {p["reset_border_hov"]};
}}
#systemBar QPushButton#resetButton:pressed {{
    background: {p["reset_pressed"]};
}}

/* ── Window Controls ──────────────────────────────────────────── */
#windowControls {{
    background: transparent;
}}
#windowControls QPushButton {{
    min-width: 28px;
    max-width: 28px;
    min-height: 23px;
    max-height: 23px;
    border: none;
    border-radius: 0;
    background: transparent;
    padding: 0;
}}
#windowControls QPushButton:hover {{
    background: {p["bg_button"]};
}}
#windowControls QPushButton#closeButton:hover {{
    background: #e81123;
    color: white;
}}

/* ── Activity Bar ──────────────────────────────────────────────── */
#activityBar {{
    background: {p["bg_panel"]};
    border-right: 1px solid {p["border"]};
}}
#activityBar QPushButton {{
    min-width: 92px;
    max-width: 92px;
    min-height: 52px;
    max-height: 52px;
    border: none;
    border-radius: 0;
    background: transparent;
    padding: 2px;
    font-size: 13px;
}}
#activityBar QPushButton:hover {{
    background: {p["bg_button"]};
}}
#activityBar QPushButton:checked {{
    background: {p["bg_control"]};
    border-left: 2px solid {p["accent_tab"]};
}}

/* ── Layout Menu ──────────────────────────────────────────────── */
#layoutMenu {{
    background: {p["bg_panel"]};
    border: 1px solid {p["border"]};
}}
#layoutMenu::item {{
    padding: 6px 24px;
}}
#layoutMenu::item:selected {{
    background: {p["bg_button"]};
}}

/* ── ToolPanel ──────────────────────────────────────────────── */
#toolPanel {{
    background: {p["bg_panel"]};
}}
#toolPanel QPushButton {{
    min-height: 20px;
    max-height: 20px;
    padding: 3px 10px;
    font-size: {max(font_size - 1, 11)}px;
    font-weight: 500;
}}
#toolPanel QPushButton#measuresSectionTitle {{
    color: {p["text"]};
    font-weight: 600;
    text-align: left;
    padding: 6px 8px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    min-height: 24px;
    max-height: none;
    font-size: {font_size}px;
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
    border-radius: 0 0 4px 0;
}}

/* ── Thumbnail Gallery ──────────────────────────────────────── */
#thumbnailGallery {{
    background: {p["bg_dark"]};
    border-right: 1px solid {p["border"]};
}}

/* ── Focus ring ─────────────────────────────────────────────── */
QTabBar::tab:focus {{
    border-color: {p["accent_tab"]};
}}
QSpinBox:focus, QCheckBox:focus {{
    border-color: {p["accent"]};
}}

/* ── Tooltips ───────────────────────────────────────────────── */
QToolTip {{
    background: {p["bg_control"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {max(font_size - 1, 11)}px;
}}

QHeaderView::section {{
    background: {p["bg_panel"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    padding: 6px 8px;
    font-weight: 600;
    font-size: {font_size}px;
}}
QHeaderView::section:hover {{
    background: {p["bg_button_hover"]};
}}
"""


def apply_echopac_theme(
    widget: QWidget | None = None,
    *,
    font_size: int = 13,
    theme: str = "dark",
    animate: bool = True,
) -> None:
    """Apply palette to the whole app. *theme* is 'dark', 'light', or 'system'."""
    global _current_theme_mode
    _current_theme_mode = theme
    app = QApplication.instance()
    if app is None:
        return
    if animate and widget is not None:
        _fade_theme_transition(widget, font_size, theme)
    else:
        _apply_theme_direct(app, widget, font_size, theme)


def _apply_theme_direct(
    app: QApplication,
    widget: QWidget | None,
    font_size: int,
    theme: str,
) -> None:
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


def _fade_theme_transition(widget: QWidget, font_size: int, theme: str) -> None:
    app = QApplication.instance()
    if app is None:
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(150)
    anim.setStartValue(0.6)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def _apply() -> None:
        _apply_theme_direct(app, widget, font_size, theme)
        effect.setOpacity(0.6)
        anim.start()

    QTimer.singleShot(0, _apply)
    widget._theme_anim = anim
    widget._theme_effect = effect
