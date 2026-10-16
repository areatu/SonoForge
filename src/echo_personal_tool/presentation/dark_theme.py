"""Dark clinical theme for the presentation layer."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.presentation.theme_tokens import (
    is_dark_theme,
    legacy_palette,
    tokens_for,
)
from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Palettes ───────────────────────────────────────────────────────
# Colours live in ``theme_tokens`` (UI-0). The dictionaries below are the
# historical 28-key palettes derived from the tokens; they stay importable for
# existing callers until UI-8 and are identical to the pre-token values.
_DARK = legacy_palette("dark")
_LIGHT = legacy_palette("light")
_VS_CODE_DARK = legacy_palette("vscode_dark")
_VS_CODE_LIGHT = legacy_palette("vscode_light")

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


def get_logo_path() -> Path:
    """Return the logo path matching the current theme (dark/inverted or light/original)."""
    from pathlib import Path

    _base = Path(__file__).resolve().parent.parent / "resources"
    mode = _current_theme_mode
    is_dark = mode in ("dark", "vscode_dark") or (mode == "system" and _is_system_dark())
    name = "logo_dark.png" if is_dark else "logo.png"
    path = _base / name
    return path if path.exists() else _base / "logo.png"


_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _windows_apps_use_dark() -> bool | None:
    """Windows "app mode": ``AppsUseLightTheme == 0`` means dark apps.

    ``None`` when the value cannot be read (old Windows, policy, no key).
    """
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY)
        try:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None
    return val == 0


def _macos_dark() -> bool | None:
    """macOS appearance; ``None`` when ``defaults`` cannot be run."""
    try:
        import subprocess

        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    return "Dark" in result.stdout


def _is_system_dark() -> bool:
    """Detect system dark mode on Windows/macOS/Linux."""
    import os

    if sys.platform == "win32":
        dark = _windows_apps_use_dark()
        return True if dark is None else dark  # default dark
    if sys.platform == "darwin":
        dark = _macos_dark()
        return False if dark is None else dark
    return os.environ.get("GTK_THEME", "").lower().endswith("dark")


_THEME_MAP = {
    "dark": _DARK,
    "light": _LIGHT,
    "vscode_dark": _VS_CODE_DARK,
    "vscode_light": _VS_CODE_LIGHT,
}


def _resolve_theme_id(mode: str) -> str:
    """Concrete palette id for a stored theme mode (``system`` asks the OS).

    Windows and macOS follow the OS appearance; when it cannot be read — and
    on Linux, where there is no reliable signal — the navy dark theme is used.
    """
    if mode in _THEME_MAP:
        return mode
    if mode == "system":
        if sys.platform == "win32":
            # UI-0: AppsUseLightTheme == 0 is *dark* mode (the old code had
            # this inverted and showed the light theme on a dark desktop).
            dark = _windows_apps_use_dark()
        elif sys.platform == "darwin":
            dark = _macos_dark()
        else:
            dark = None
        if dark is False:
            return "light"
    return "dark"


def _resolve_theme(mode: str) -> dict[str, str]:
    return _THEME_MAP[_resolve_theme_id(mode)]


def build_clinical_stylesheet(font_size: int = 13, *, theme: str = "dark") -> str:
    """Application stylesheet built from the design tokens of *theme*.

    ``system`` is resolved on every call (the OS appearance may change); the
    QSS itself is cached per concrete theme and font size.
    """
    return _build_stylesheet_cached(int(font_size), _resolve_theme_id(theme))


@lru_cache(maxsize=32)
def _build_stylesheet_cached(font_size: int, theme_id: str) -> str:
    t = tokens_for(theme_id)
    icon_theme = "dark" if is_dark_theme(theme_id) else "light"
    icons = Path(__file__).resolve().parent.parent / "resources" / "icons"
    arrow_up = (icons / f"chevron_up_{icon_theme}.svg").as_posix()
    arrow_down = (icons / f"chevron_down_{icon_theme}.svg").as_posix()
    check = (icons / f"check_{icon_theme}.svg").as_posix()
    return f"""
/* ── Global ──────────────────────────────────────────────────── */
QWidget {{
    background-color: {t["surface.1"]};
    color: {t["text.1"]};
    font-family: "{FONT_FAMILY_UI}", sans-serif;
    font-size: {font_size}px;
}}
QMainWindow {{
    background-color: {t["surface.0"]};
}}
QDialog {{
    background-color: {t["surface.1"]};
    color: {t["text.1"]};
}}
QScrollArea {{
    background-color: {t["surface.1"]};
    border: none;
}}
QScrollBar:vertical {{
    background: {t["surface.2"]};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t["line.1"]};
    min-height: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t["text.2"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {t["surface.2"]};
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {t["line.1"]};
    min-width: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t["text.2"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Line Edit ──────────────────────────────────────────────── */
QLineEdit {{
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 6px 10px;
    color: {t["text.1"]};
    background: {t["surface.2"]};
    font-size: {font_size}px;
}}
QLineEdit:focus {{
    border: 1px solid {t["accent"]};
}}

/* ── Status bar ─────────────────────────────────────────────── */
QStatusBar {{
    background-color: {t["surface.2"]};
    color: {t["text.2"]};
    border-top: 1px solid {t["line.1"]};
}}

/* ── Tabs ───────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t["line.1"]};
    background: {t["surface.1"]};
    top: -1px;
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {t["surface.2"]};
    color: {t["text.2"]};
    border: 1px solid {t["line.1"]};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 2px;
    min-width: 72px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {t["surface.2"]};
    color: {t["text.1"]};
    font-weight: 600;
    border-radius: 8px 8px 0 0;
}}
QTabBar::tab:hover:!selected {{
    background: {t["surface.hover"]};
    color: {t["text.1"]};
}}

/* ── Buttons ────────────────────────────────────────────────── */
QPushButton, QToolButton {{
    background: {t["surface.3"]};
    color: {t["text.1"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QPushButton:hover, QToolButton:hover {{
    background: {t["surface.hover"]};
    border-color: {t["accent"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {t["surface.pressed"]};
}}
QPushButton:checked, QToolButton:checked {{
    background: {t["surface.2"]};
    border-color: {t["accent"]};
    color: {t["text.1"]};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {t["text.2"]};
    background: {t["surface.2"]};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QCheckBox:disabled {{
    color: {t["text.2"]};
    background: {t["surface.2"]};
}}
QPushButton:focus, QToolButton:focus {{
    border-color: {t["accent"]};
}}

/* ── GroupBox ───────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {t["accent"]};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {t["text.1"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

/* ── Lists / Trees ─────────────────────────────────────────── */
QTreeWidget, QListWidget {{
    background: {t["surface.0"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    alternate-background-color: {t["surface.2"]};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {t["surface.2"]};
    color: {t["text.1"]};
}}

/* ── Scrollbar ──────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {t["surface.0"]};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {t["line.1"]};
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {t["surface.0"]};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {t["line.1"]};
    border-radius: 6px;
    min-width: 24px;
}}

/* ── Splitter ───────────────────────────────────────────────── */
QSplitter::handle {{
    background: {t["line.1"]};
    width: 2px;
}}
QSplitter::handle:hover {{
    background: {t["accent"]};
}}

/* ── Slider ─────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background: {t["control.track"]};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {t["text.1"]};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {t["accent.text"]};
}}
QSlider::sub-page:horizontal {{
    background: {t["accent"]};
    border-radius: 3px;
}}

/* ── ProgressBar ────────────────────────────────────────────── */
QProgressBar {{
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    background: {t["surface.2"]};
    text-align: center;
    color: {t["text.on_fill"]};
    height: 16px;
}}
QProgressBar::chunk {{
    background: {t["accent"]};
    border-radius: 3px;
}}

/* ── SpinBox ────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 3px 22px 3px 6px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {t["line.1"]};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid {t["line.1"]};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{arrow_up}");
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{arrow_down}");
    width: 10px;
    height: 10px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t["surface.hover"]};
}}
QComboBox {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 4px 24px 4px 8px;
}}
QComboBox:focus {{
    border-color: {t["accent"]};
}}
QComboBox::drop-down {{
    width: 24px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url("{arrow_down}");
    width: 12px;
    height: 12px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t["accent"]};
}}

/* ── CheckBox ───────────────────────────────────────────────── */
QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {t["line.1"]};
    background: {t["surface.2"]};
}}
QCheckBox::indicator:checked {{
    background: {t["surface.hover"]};
    border-color: {t["accent"]};
    image: url("{check}");
}}
QCheckBox::indicator:hover, QCheckBox:focus::indicator {{
    border-color: {t["accent"]};
}}

/* ── Tree/View CheckBox indicators ──────────────────────────── */
QTreeWidget::indicator, QTreeView::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {t["accent"]};
    background: transparent;
    border-radius: 50%;
}}
QTreeWidget::indicator:checked, QTreeView::indicator:checked {{
    background: {t["text.2"]};
    border: none;
}}
QTreeWidget::indicator:unchecked, QTreeView::indicator:unchecked {{
    background: transparent;
    border: 1px solid {t["accent"]};
}}

/* ── Settings ───────────────────────────────────────────────── */
#userPreferencesDialog {{
    border: 1px solid {t["line.1"]};
}}
#settingsNavigation {{
    background: {t["surface.0"]};
    border: none;
    border-right: 1px solid {t["line.1"]};
    border-radius: 0;
    padding: 8px 0;
}}
#settingsNavigation::item {{
    padding: 10px 12px;
    border-left: 3px solid transparent;
}}
#settingsNavigation::item:selected {{
    background: {t["surface.2"]};
    color: {t["text.1"]};
    border-left-color: {t["accent"]};
}}
#settingsNavigation::item:hover:!selected {{
    background: {t["surface.hover"]};
}}
#settingsFooter {{
    border-top: 1px solid {t["line.1"]};
}}
#preferencesTitleBar QPushButton {{
    min-height: 0;
    padding: 0;
    background: transparent;
    border: none;
}}
#preferencesTitleBar QPushButton:hover {{
    background: {t["danger.fill"]};
}}
#layoutPreview {{
    background: {t["surface.0"]};
    border: 1px solid {t["line.1"]};
    border-radius: 6px;
}}
#layoutPreviewPanel {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 3px;
    padding: 4px;
    font-size: {max(font_size - 1, 10)}px;
}}
#layoutPreviewViewer {{
    background: {t["surface.0"]};
    border: 1px solid {t["accent"]};
    border-radius: 3px;
    padding: 4px;
}}
QPushButton:default {{
    border-color: {t["accent"]};
}}

/* ── SystemBar ──────────────────────────────────────────────── */
#systemBar {{
    background: {t["surface.2"]};
    border-bottom: 1px solid {t["line.1"]};
    min-height: 34px;
}}
#preferencesTitleBar {{
    background: {t["surface.1"]};
    border-bottom: 1px solid {t["line.1"]};
    min-height: 34px;
}}
#systemBar QPushButton {{
    min-height: 23px;
    max-height: 23px;
    padding: 2px 10px;
    font-size: {max(font_size - 1, 11)}px;
    font-weight: 500;
}}
#systemBarContext, #systemBarActions {{
    background: transparent;
}}
#systemBar QPushButton#referencesButton {{
    border-color: {t["accent"]};
}}
#systemBar QPushButton#resetButton {{
    background: {t["danger.fill"]};
    border-color: {t["danger.line"]};
    color: {t["danger.text"]};
}}
#systemBar QPushButton#resetButton:hover {{
    background: {t["danger.hover"]};
    border-color: {t["danger.line.hover"]};
}}
#systemBar QPushButton#resetButton:pressed {{
    background: {t["danger.pressed"]};
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
#windowControls QPushButton:hover, #windowControls QPushButton:focus {{
    background: {t["surface.3"]};
}}
#windowControls QPushButton#closeButton:hover {{
    background: {t["window.close.hover"]};
    color: white;
}}

/* ── Activity Bar ──────────────────────────────────────────────── */
#activityBar {{
    background: {t["surface.1"]};
    border-right: 1px solid {t["line.1"]};
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
    background: {t["surface.3"]};
}}
#activityBar QPushButton:checked {{
    background: {t["surface.2"]};
    border-left: 2px solid {t["accent"]};
}}

/* ── Layout Menu ──────────────────────────────────────────────── */
#layoutMenu {{
    background: {t["surface.1"]};
    border: 1px solid {t["line.1"]};
}}
#layoutMenu::item {{
    padding: 6px 24px;
}}
#layoutMenu::item:selected {{
    background: {t["surface.3"]};
}}

/* ── ToolPanel ──────────────────────────────────────────────── */
#toolPanel {{
    background: {t["surface.1"]};
}}
#toolPanel QPushButton {{
    min-height: 20px;
    max-height: 20px;
    padding: 3px 10px;
    font-size: {max(font_size - 1, 11)}px;
    font-weight: 500;
}}
#toolPanel QPushButton#measuresSectionTitle {{
    color: {t["text.1"]};
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
    background: {t["surface.3"]};
    border-color: {t["line.1"]};
}}
#toolPanel QPushButton#measuresSectionTitle[expanded="true"] {{
    background: {t["surface.2"]};
    border-color: {t["accent"]};
}}
#toolPanel QWidget#measuresSectionBody {{
    background: {t["surface.0"]};
    border-left: 2px solid {t["accent"]};
    border-radius: 0 0 4px 0;
}}

/* ── Thumbnail Gallery ──────────────────────────────────────── */
#thumbnailGallery {{
    background: {t["surface.0"]};
    border-right: 1px solid {t["line.1"]};
}}

/* ── Tool-panel tabs and native overflow controls ───────────── */
#toolPanel QTabBar::tab {{
    min-width: 0;
    padding: 8px 10px;
    margin-right: 0;
}}
#toolPanel QTabBar QToolButton {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 3px;
    min-width: 20px;
    max-width: 20px;
    min-height: 24px;
    padding: 0;
}}
#toolPanel QTabBar QToolButton:hover {{
    background: {t["surface.hover"]};
}}

/* ── Focus ring ─────────────────────────────────────────────── */
QTabBar::tab:focus {{
    border-color: {t["accent"]};
}}
QSpinBox:focus, QCheckBox:focus {{
    border-color: {t["accent"]};
}}

/* ── Tooltips ───────────────────────────────────────────────── */
QToolTip {{
    background: {t["surface.2"]};
    color: {t["text.1"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {max(font_size - 1, 11)}px;
}}

QHeaderView::section {{
    background: {t["surface.1"]};
    color: {t["text.1"]};
    border: 1px solid {t["line.1"]};
    padding: 6px 8px;
    font-weight: 600;
    font-size: {font_size}px;
}}
QHeaderView::section:hover {{
    background: {t["surface.hover"]};
}}
QMessageBox {{
    background-color: {t["surface.1"]};
    color: {t["text.1"]};
}}
QMessageBox QLabel {{
    color: {t["text.1"]};
}}
QMessageBox QPushButton {{
    background-color: {t["surface.3"]};
    color: {t["text.1"]};
    border: 1px solid {t["line.1"]};
    padding: 6px 16px;
    min-width: 60px;
    border-radius: 4px;
}}
QMessageBox QPushButton:hover {{
    background-color: {t["surface.hover"]};
}}
QMessageBox QPushButton:pressed {{
    background-color: {t["surface.pressed"]};
}}
QMessageBox QLabel#qt_msgbox_label {{
    color: {t["text.1"]};
}}
QMessageBox QLabel#qt_msgbox_icon {{
    background: transparent;
}}

/* ── Constructor Dialog ─────────────────────────────────────── */
#constructorTitleBar {{
    background: {t["surface.1"]};
}}
#constructorTitleLabel {{
    color: {t["text.1"]};
    font-weight: bold;
    font-size: {font_size}px;
}}
#windowButton {{
    border: none;
    color: {t["text.1"]};
    font-size: 14px;
}}
#windowButton:hover {{
    background: {t["surface.hover"]};
}}
#constructorToolbar {{
    background: {t["surface.2"]};
    border-bottom: 1px solid {t["line.1"]};
}}
#constructorToolbar QPushButton {{
    border: 1px solid {t["line.1"]};
    border-radius: 3px;
    padding: 2px 8px;
    color: {t["text.1"]};
    background: {t["surface.1"]};
}}
#constructorToolbar QPushButton:hover {{
    background: {t["surface.hover"]};
}}
#constructorToolbar QPushButton:pressed {{
    background: {t["surface.pressed"]};
}}
#constructorDirtyLabel {{
    color: {t["accent"]};
    font-weight: bold;
    font-size: 14px;
}}

/* ── Multiview (two clips side by side) ─────────────────────── */
#multiviewPane_left, #multiviewPane_right {{
    background: {t["surface.0"]};
    border: 1px solid {t["line.1"]};
    border-radius: 6px;
}}
#multiviewPane_left[active="true"], #multiviewPane_right[active="true"] {{
    border: 2px solid {t["accent"]};
}}
#multiviewPaneHeader {{
    background: {t["surface.1"]};
    border-bottom: 1px solid {t["line.1"]};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
#multiviewPaneLetter, #multiviewPaneFile {{
    color: {t["text.1"]};
    font-weight: bold;
}}
#multiviewPaneView, #multiviewPaneFrame {{
    color: {t["text.2"]};
}}
#multiviewPaneActive {{
    color: {t["accent"]};
    font-weight: bold;
}}
#multiviewPaneReplace, #multiviewPaneMenu {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px 8px;
    color: {t["text.2"]};
}}
#multiviewPaneReplace:hover, #multiviewPaneMenu:hover {{
    background: {t["surface.hover"]};
    color: {t["text.1"]};
}}
#multiviewPlaceholder {{
    color: {t["text.2"]};
    background: {t["surface.0"]};
}}
#multiviewMarkerBar {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 2px;
}}
#multiviewMarkerButton {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 2px 8px;
    color: {t["text.2"]};
}}
#multiviewMarkerButton[placed="true"] {{
    background: {t["accent.selected"]};
    border-color: {t["accent"]};
    color: {t["text.1"]};
}}
#multiviewMarkerButton:disabled {{
    color: {t["text.2"]};
}}
#multiviewMarkerClear, #multiviewMarkerClearAll {{
    background: transparent;
    border: 1px solid transparent;
    color: {t["text.2"]};
    padding: 2px 6px;
}}
#multiviewMarkerClear:hover, #multiviewMarkerClearAll:hover {{
    background: {t["surface.hover"]};
    color: {t["text.1"]};
}}
#multiviewTransport {{
    background: {t["surface.1"]};
    border: 1px solid {t["line.1"]};
    border-radius: 6px;
}}
#multiviewMode_independent, #multiviewMode_common_window, #multiviewMode_event_cycle {{
    background: {t["surface.2"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 3px 10px;
    color: {t["text.2"]};
}}
#multiviewMode_independent:checked, #multiviewMode_common_window:checked,
#multiviewMode_event_cycle:checked {{
    background: {t["accent.selected"]};
    border-color: {t["accent"]};
    color: {t["text.1"]};
}}
#multiviewTransportStatus {{
    color: {t["text.2"]};
}}
#multiviewTransportRateLeft, #multiviewTransportRateRight {{
    color: {t["accent"]};
    font-weight: bold;
}}
#multiviewButton:checked {{
    background: {t["surface.hover"]};
    border: 1px solid {t["accent"]};
}}

/* ── Menu Bar & Menus ──────────────────────────────────────── */
QMenuBar {{
    background: {t["surface.1"]};
    color: {t["text.1"]};
    border-bottom: 1px solid {t["line.1"]};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
    border: none;
}}
QMenuBar::item:selected {{
    background: {t["surface.3"]};
    color: {t["text.1"]};
}}
QMenuBar::item:pressed {{
    background: {t["surface.pressed"]};
}}
QMenu {{
    background: {t["surface.1"]};
    color: {t["text.1"]};
    border: 1px solid {t["line.1"]};
    border-radius: 4px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 24px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {t["surface.hover"]};
    color: {t["text.1"]};
}}
QMenu::item:disabled {{
    color: {t["text.2"]};
}}
QMenu::separator {{
    height: 1px;
    background: {t["line.1"]};
    margin: 4px 8px;
}}
"""


def apply_clinical_theme(
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
    stylesheet = build_clinical_stylesheet(font_size, theme=theme)
    # Reapplying an identical app-wide sheet repolishes every open/hidden
    # dialog. Avoid that work when a window is opened without a theme change.
    if app.styleSheet() != stylesheet:
        app.setStyleSheet(stylesheet)
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
    from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QMainWindow

    from echo_personal_tool.presentation.ui_animations import _reduce_motion_enabled

    app = QApplication.instance()
    if app is None:
        return
    _apply_theme_direct(app, widget, font_size, theme)
    if _reduce_motion_enabled():
        return
    try:
        import shiboken6

        if not shiboken6.isValid(widget):
            return
    except ImportError:
        pass
    # PR1 stability: never attach a GraphicsEffect to a main window or any
    # window hosting a WebEngine view. With a live QWebEngineView/video
    # surface this is a known SIGSEGV path (theme switch then crashes, spawn
    # pool leaks semaphores). Plain widgets keep the fade (covered by
    # test_fade_theme_transition).
    if isinstance(widget, QMainWindow):
        return
    try:
        for child in widget.findChildren(QWidget):
            if "WebEngine" in type(child).__name__:
                return
    except RuntimeError:
        return
    try:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    except RuntimeError:
        return
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(150)
    anim.setStartValue(0.6)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def _cleanup() -> None:
        try:
            import shiboken6

            if shiboken6.isValid(widget):
                widget.setGraphicsEffect(None)
        except (ImportError, RuntimeError):
            pass

    anim.finished.connect(_cleanup)
    try:
        QTimer.singleShot(0, anim.start)
    except RuntimeError:
        _cleanup()
        return
    widget._theme_anim = anim
    widget._theme_effect = effect
