"""QSS builder: the application stylesheet assembled from semantic tokens (UI-0, PR-1).

The stylesheet is a pure function of the theme tokens and the font size, so it
can be cached: ``build_clinical_stylesheet()`` is called on every theme switch
and on every font-size change, and the result is reused for equal arguments.

The rules are the rules of the former ``dark_theme.build_clinical_stylesheet()``
— the colours are read from tokens instead of the legacy palette keys, the
layout of the sheet is unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from echo_personal_tool.presentation.theme.palettes import PALETTES, is_dark_theme
from echo_personal_tool.presentation.theme.system_theme import system_theme_id
from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI


def _icon_paths(theme: str) -> tuple[str, str, str]:
    """Return the (arrow up, arrow down, check) icon paths of a theme."""
    icon_theme = "dark" if is_dark_theme(theme) else "light"
    icons = Path(__file__).resolve().parent.parent.parent / "resources" / "icons"
    return (
        (icons / f"chevron_up_{icon_theme}.svg").as_posix(),
        (icons / f"chevron_down_{icon_theme}.svg").as_posix(),
        (icons / f"check_{icon_theme}.svg").as_posix(),
    )


@lru_cache(maxsize=32)
def _build_stylesheet(font_size: int, theme: str) -> str:
    """Build the application stylesheet of a concrete theme (cached)."""
    tokens = PALETTES.get(theme, PALETTES["dark"])
    arrow_up, arrow_down, check = _icon_paths(theme)
    return f"""
/* ── Global ──────────────────────────────────────────────────── */
QWidget {{
    background-color: {tokens["surface.1"]};
    color: {tokens["text.1"]};
    font-family: "{FONT_FAMILY_UI}", sans-serif;
    font-size: {font_size}px;
}}
QMainWindow {{
    background-color: {tokens["surface.0"]};
}}
QDialog {{
    background-color: {tokens["surface.1"]};
    color: {tokens["text.1"]};
}}
QScrollArea {{
    background-color: {tokens["surface.1"]};
    border: none;
}}
QScrollBar:vertical {{
    background: {tokens["surface.2"]};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {tokens["line.2"]};
    min-height: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {tokens["text.2"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {tokens["surface.2"]};
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {tokens["line.2"]};
    min-width: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {tokens["text.2"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Line Edit ──────────────────────────────────────────────── */
QLineEdit {{
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    padding: 6px 10px;
    color: {tokens["text.1"]};
    background: {tokens["surface.2"]};
    font-size: {font_size}px;
}}
QLineEdit:focus {{
    border: 1px solid {tokens["accent.tab"]};
}}

/* ── Status bar ─────────────────────────────────────────────── */
QStatusBar {{
    background-color: {tokens["surface.2"]};
    color: {tokens["text.2"]};
    border-top: 1px solid {tokens["line.1"]};
}}

/* ── Tabs ───────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {tokens["line.1"]};
    background: {tokens["surface.1"]};
    top: -1px;
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {tokens["surface.2"]};
    color: {tokens["text.2"]};
    border: 1px solid {tokens["line.1"]};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 2px;
    min-width: 72px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
    font-weight: 600;
    border-radius: 8px 8px 0 0;
}}
QTabBar::tab:hover:!selected {{
    background: {tokens["surface.hover"]};
    color: {tokens["text.1"]};
}}

/* ── Buttons ────────────────────────────────────────────────── */
QPushButton, QToolButton {{
    background: {tokens["surface.3"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QPushButton:hover, QToolButton:hover {{
    background: {tokens["surface.hover"]};
    border-color: {tokens["accent"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {tokens["surface.pressed"]};
}}
QPushButton:checked, QToolButton:checked {{
    background: {tokens["surface.2"]};
    border-color: {tokens["accent"]};
    color: {tokens["text.1"]};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {tokens["text.disabled"]};
    background: {tokens["surface.2"]};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QCheckBox:disabled {{
    color: {tokens["text.disabled"]};
    background: {tokens["surface.2"]};
}}
QPushButton:focus, QToolButton:focus {{
    border-color: {tokens["accent"]};
}}

/* ── GroupBox ───────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {tokens["accent.tab"]};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {tokens["text.1"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

/* ── Lists / Trees ─────────────────────────────────────────── */
QTreeWidget, QListWidget {{
    background: {tokens["surface.0"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    alternate-background-color: {tokens["surface.2"]};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
}}

/* ── Scrollbar ──────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {tokens["surface.0"]};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {tokens["line.2"]};
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {tokens["surface.0"]};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {tokens["line.2"]};
    border-radius: 6px;
    min-width: 24px;
}}

/* ── Splitter ───────────────────────────────────────────────── */
QSplitter::handle {{
    background: {tokens["line.1"]};
    width: 2px;
}}
QSplitter::handle:hover {{
    background: {tokens["accent.tab"]};
}}

/* ── Slider ─────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background: {tokens["slider.track"]};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {tokens["text.1"]};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {tokens["accent.text"]};
}}
QSlider::sub-page:horizontal {{
    background: {tokens["slider.fill"]};
    border-radius: 3px;
}}

/* ── ProgressBar ────────────────────────────────────────────── */
QProgressBar {{
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    background: {tokens["surface.2"]};
    text-align: center;
    color: {tokens["progress.text"]};
    height: 16px;
}}
QProgressBar::chunk {{
    background: {tokens["accent.tab"]};
    border-radius: 3px;
}}

/* ── SpinBox ────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 4px;
    padding: 3px 22px 3px 6px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {tokens["line.2"]};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid {tokens["line.2"]};
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
    background: {tokens["surface.hover"]};
}}
QComboBox {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    padding: 4px 24px 4px 8px;
}}
QComboBox:focus {{
    border-color: {tokens["accent"]};
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
    border-color: {tokens["accent.tab"]};
}}

/* ── CheckBox ───────────────────────────────────────────────── */
QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {tokens["line.2"]};
    background: {tokens["surface.2"]};
}}
QCheckBox::indicator:checked {{
    background: {tokens["surface.hover"]};
    border-color: {tokens["accent"]};
    image: url("{check}");
}}
QCheckBox::indicator:hover, QCheckBox:focus::indicator {{
    border-color: {tokens["accent"]};
}}

/* ── Tree/View CheckBox indicators ──────────────────────────── */
QTreeWidget::indicator, QTreeView::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {tokens["accent.tab"]};
    background: transparent;
    border-radius: 50%;
}}
QTreeWidget::indicator:checked, QTreeView::indicator:checked {{
    background: {tokens["text.2"]};
    border: none;
}}
QTreeWidget::indicator:unchecked, QTreeView::indicator:unchecked {{
    background: transparent;
    border: 1px solid {tokens["accent.tab"]};
}}

/* ── Settings ───────────────────────────────────────────────── */
#userPreferencesDialog {{
    border: 1px solid {tokens["line.2"]};
}}
#settingsNavigation {{
    background: {tokens["surface.0"]};
    border: none;
    border-right: 1px solid {tokens["line.1"]};
    border-radius: 0;
    padding: 8px 0;
}}
#settingsNavigation::item {{
    padding: 10px 12px;
    border-left: 3px solid transparent;
}}
#settingsNavigation::item:selected {{
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
    border-left-color: {tokens["accent"]};
}}
#settingsNavigation::item:hover:!selected {{
    background: {tokens["surface.hover"]};
}}
#settingsFooter {{
    border-top: 1px solid {tokens["line.1"]};
}}
#preferencesTitleBar QPushButton {{
    min-height: 0;
    padding: 0;
    background: transparent;
    border: none;
}}
#preferencesTitleBar QPushButton:hover {{
    background: {tokens["state.danger.bg"]};
}}
#layoutPreview {{
    background: {tokens["surface.0"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 6px;
}}
#layoutPreviewPanel {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 3px;
    padding: 4px;
    font-size: {max(font_size - 1, 10)}px;
}}
#layoutPreviewViewer {{
    background: {tokens["surface.0"]};
    border: 1px solid {tokens["accent"]};
    border-radius: 3px;
    padding: 4px;
}}
QPushButton:default {{
    border-color: {tokens["accent"]};
}}

/* ── SystemBar ──────────────────────────────────────────────── */
#systemBar {{
    background: {tokens["surface.2"]};
    border-bottom: 1px solid {tokens["line.1"]};
    min-height: 34px;
}}
#preferencesTitleBar {{
    background: {tokens["surface.1"]};
    border-bottom: 1px solid {tokens["line.1"]};
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
    border-color: {tokens["accent"]};
}}
#systemBar QPushButton#resetButton {{
    background: {tokens["state.danger.bg"]};
    border-color: {tokens["state.danger.border"]};
    color: {tokens["state.danger.text"]};
}}
#systemBar QPushButton#resetButton:hover {{
    background: {tokens["state.danger.bg.hover"]};
    border-color: {tokens["state.danger.border.hover"]};
}}
#systemBar QPushButton#resetButton:pressed {{
    background: {tokens["state.danger.bg.pressed"]};
}}
/* «Изображения | Отчёт» segmented pair (UI-4 PR-1, UD-08). */
#modeSwitch QPushButton#modeImagesButton {{
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
    padding: 2px 12px;
}}
#modeSwitch QPushButton#modeReportButton {{
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-left: none;
    padding: 2px 12px;
}}
#modeSwitch QPushButton#modeImagesButton:checked,
#modeSwitch QPushButton#modeReportButton:checked {{
    background: {tokens["accent"]};
    border-color: {tokens["accent"]};
    color: {tokens["accent.on"]};
}}
#modeSwitch QPushButton#modeImagesButton:checked {{
    border-right: 1px solid {tokens["accent"]};
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
    background: {tokens["surface.3"]};
}}
#windowControls QPushButton#closeButton:hover {{
    background: {tokens["state.danger.solid"]};
    color: {tokens["state.danger.on"]};
}}

/* ── Activity Bar ──────────────────────────────────────────────── */
#activityBar {{
    background: {tokens["surface.1"]};
    border-right: 1px solid {tokens["line.1"]};
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
    background: {tokens["surface.3"]};
}}
#activityBar QPushButton:checked {{
    background: {tokens["surface.2"]};
    border-left: 2px solid {tokens["accent.tab"]};
}}

/* ── Layout Menu ──────────────────────────────────────────────── */
#layoutMenu {{
    background: {tokens["surface.1"]};
    border: 1px solid {tokens["line.2"]};
}}
#layoutMenu::item {{
    padding: 6px 24px;
}}
#layoutMenu::item:selected {{
    background: {tokens["surface.3"]};
}}

/* ── ToolPanel ──────────────────────────────────────────────── */
#toolPanel {{
    background: {tokens["surface.1"]};
}}
#toolPanel QPushButton {{
    min-height: 20px;
    max-height: 20px;
    padding: 3px 10px;
    font-size: {max(font_size - 1, 11)}px;
    font-weight: 500;
}}
#toolPanel QPushButton#measuresSectionTitle {{
    color: {tokens["text.1"]};
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
    background: {tokens["surface.3"]};
    border-color: {tokens["line.1"]};
}}
#toolPanel QPushButton#measuresSectionTitle[expanded="true"] {{
    background: {tokens["surface.2"]};
    border-color: {tokens["accent.tab"]};
}}
#toolPanel QWidget#measuresSectionBody {{
    background: {tokens["surface.0"]};
    border-left: 2px solid {tokens["accent.tab"]};
    border-radius: 0 0 4px 0;
}}

/* ── Thumbnail Gallery ──────────────────────────────────────── */
#thumbnailGallery {{
    background: {tokens["surface.0"]};
    border-right: 1px solid {tokens["line.1"]};
}}

/* ── Tool-panel tabs and native overflow controls ───────────── */
#toolPanel QTabBar::tab {{
    min-width: 0;
    padding: 8px 10px;
    margin-right: 0;
}}
#toolPanel QTabBar QToolButton {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 3px;
    min-width: 20px;
    max-width: 20px;
    min-height: 24px;
    padding: 0;
}}
#toolPanel QTabBar QToolButton:hover {{
    background: {tokens["surface.hover"]};
}}

/* ── Focus ring ─────────────────────────────────────────────── */
QTabBar::tab:focus {{
    border-color: {tokens["accent.tab"]};
}}
QSpinBox:focus, QCheckBox:focus {{
    border-color: {tokens["accent"]};
}}

/* ── Tooltips ───────────────────────────────────────────────── */
QToolTip {{
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {max(font_size - 1, 11)}px;
}}

QHeaderView::section {{
    background: {tokens["surface.1"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.2"]};
    padding: 6px 8px;
    font-weight: 600;
    font-size: {font_size}px;
}}
QHeaderView::section:hover {{
    background: {tokens["surface.hover"]};
}}
QMessageBox {{
    background-color: {tokens["surface.1"]};
    color: {tokens["text.1"]};
}}
QMessageBox QLabel {{
    color: {tokens["text.1"]};
}}
QMessageBox QPushButton {{
    background-color: {tokens["surface.3"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.1"]};
    padding: 6px 16px;
    min-width: 60px;
    border-radius: 4px;
}}
QMessageBox QPushButton:hover {{
    background-color: {tokens["surface.hover"]};
}}
QMessageBox QPushButton:pressed {{
    background-color: {tokens["surface.pressed"]};
}}
QMessageBox QLabel#qt_msgbox_label {{
    color: {tokens["text.1"]};
}}
QMessageBox QLabel#qt_msgbox_icon {{
    background: transparent;
}}

/* ── Constructor Dialog ─────────────────────────────────────── */
#constructorTitleBar {{
    background: {tokens["surface.1"]};
}}
#constructorTitleLabel {{
    color: {tokens["text.1"]};
    font-weight: bold;
    font-size: {font_size}px;
}}
#windowButton {{
    border: none;
    color: {tokens["text.1"]};
    font-size: 14px;
}}
#windowButton:hover {{
    background: {tokens["surface.hover"]};
}}
#constructorToolbar {{
    background: {tokens["surface.2"]};
    border-bottom: 1px solid {tokens["line.1"]};
}}
#constructorToolbar QPushButton {{
    border: 1px solid {tokens["line.1"]};
    border-radius: 3px;
    padding: 2px 8px;
    color: {tokens["text.1"]};
    background: {tokens["surface.1"]};
}}
#constructorToolbar QPushButton:hover {{
    background: {tokens["surface.hover"]};
}}
#constructorToolbar QPushButton:pressed {{
    background: {tokens["surface.pressed"]};
}}
#constructorDirtyLabel {{
    color: {tokens["accent"]};
    font-weight: bold;
    font-size: 14px;
}}

/* ── Multiview (two clips side by side) ─────────────────────── */
#multiviewPane_left, #multiviewPane_right {{
    background: {tokens["surface.0"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 6px;
}}
#multiviewPane_left[active="true"], #multiviewPane_right[active="true"] {{
    border: 2px solid {tokens["accent"]};
}}
#multiviewPaneHeader {{
    background: {tokens["surface.1"]};
    border-bottom: 1px solid {tokens["line.1"]};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
#multiviewPaneLetter, #multiviewPaneFile {{
    color: {tokens["text.1"]};
    font-weight: bold;
}}
#multiviewPaneView, #multiviewPaneFrame {{
    color: {tokens["text.2"]};
}}
#multiviewPaneActive {{
    color: {tokens["accent"]};
    font-weight: bold;
}}
#multiviewPaneReplace, #multiviewPaneMenu {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px 8px;
    color: {tokens["text.2"]};
}}
#multiviewPaneReplace:hover, #multiviewPaneMenu:hover {{
    background: {tokens["surface.hover"]};
    color: {tokens["text.1"]};
}}
#multiviewPlaceholder {{
    color: {tokens["text.2"]};
    background: {tokens["surface.0"]};
}}
#multiviewMarkerBar {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 2px;
}}
#multiviewMarkerButton {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 4px;
    padding: 2px 8px;
    color: {tokens["text.2"]};
}}
#multiviewMarkerButton[placed="true"] {{
    background: {tokens["accent.selected"]};
    border-color: {tokens["accent"]};
    color: {tokens["text.1"]};
}}
#multiviewMarkerButton:disabled {{
    color: {tokens["text.disabled"]};
}}
#multiviewMarkerClear, #multiviewMarkerClearAll {{
    background: transparent;
    border: 1px solid transparent;
    color: {tokens["text.2"]};
    padding: 2px 6px;
}}
#multiviewMarkerClear:hover, #multiviewMarkerClearAll:hover {{
    background: {tokens["surface.hover"]};
    color: {tokens["text.1"]};
}}
#multiviewTransport {{
    background: {tokens["surface.1"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 6px;
}}
#multiviewMode_independent, #multiviewMode_common_window, #multiviewMode_event_cycle {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 4px;
    padding: 3px 10px;
    color: {tokens["text.2"]};
}}
#multiviewMode_independent:checked, #multiviewMode_common_window:checked,
#multiviewMode_event_cycle:checked {{
    background: {tokens["accent.selected"]};
    border-color: {tokens["accent"]};
    color: {tokens["text.1"]};
}}
#multiviewTransportStatus {{
    color: {tokens["text.2"]};
}}
#multiviewTransportRateLeft, #multiviewTransportRateRight {{
    color: {tokens["accent"]};
    font-weight: bold;
}}
#multiviewButton:checked {{
    background: {tokens["surface.hover"]};
    border: 1px solid {tokens["accent"]};
}}

/* ── Menu Bar & Menus ──────────────────────────────────────── */
QMenuBar {{
    background: {tokens["surface.1"]};
    color: {tokens["text.1"]};
    border-bottom: 1px solid {tokens["line.1"]};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
    border: none;
}}
QMenuBar::item:selected {{
    background: {tokens["surface.3"]};
    color: {tokens["text.1"]};
}}
QMenuBar::item:pressed {{
    background: {tokens["surface.pressed"]};
}}
QMenu {{
    background: {tokens["surface.1"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 4px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 24px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {tokens["surface.hover"]};
    color: {tokens["text.1"]};
}}
QMenu::item:disabled {{
    color: {tokens["text.disabled"]};
}}
QMenu::separator {{
    height: 1px;
    background: {tokens["line.1"]};
    margin: 4px 8px;
}}
"""


def build_clinical_stylesheet(font_size: int = 13, theme: str = "dark") -> str:
    """Build the application stylesheet of a theme.

    *theme* is a theme id ("dark", "light", "vscode_dark", "vscode_light",
    "graphite") or "system", which is resolved to the current system colour
    scheme on every call — the system may change while the application runs.
    The sheet of a concrete theme is cached per (font size, theme).
    """
    resolved = system_theme_id() if theme == "system" else theme
    return _build_stylesheet(font_size, resolved)


def clear_stylesheet_cache() -> None:
    """Drop the cached stylesheets (after a change of the icon set)."""
    _build_stylesheet.cache_clear()
