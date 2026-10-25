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
    border-radius: 6px;
    padding: 6px 10px;
    color: {tokens["text.1"]};
    background: {tokens["surface.2"]};
    font-size: {font_size}px;
}}
QLineEdit:focus {{
    border: 1px solid {tokens["accent.tab"]};
}}
/* The clear button of a QLineEdit is a QToolButton Qt creates itself, and it
   used to inherit the button chrome further down (6 px of padding, a border,
   a 24 px minimum height): inside a 28 px field it then measured 22 × 38, so
   the «×» was drawn half below the field and cut by its bottom edge — the
   «смещённая кнопка удалить текст справа поля» of the 2026-10-23 list.  Two
   type selectors out-specify one, so this keeps the field's own button quiet
   wherever the field lives (the panel search, the PACS dialog, the picker). */
QLineEdit QToolButton {{
    background: transparent;
    border: none;
    border-radius: 3px;
    padding: 0px;
    margin: 0px;
    min-height: 0px;
    min-width: 0px;
    font-weight: 400;
}}
QLineEdit QToolButton:hover {{
    background: {tokens["surface.hover"]};
    border: none;
}}
QLineEdit QToolButton:pressed {{
    background: {tokens["surface.pressed"]};
    border: none;
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
/* Document tabs are quiet chips, not outlined cards (design A1, «визуал
   кнопок»): the active study is told apart by a filled pill and brighter text,
   and the outline that framed every tab — the selected one included — is gone.
   The 8 px corners that met the content edge went with it: a free-standing pill
   needs all four corners rounded. */
QTabBar::tab {{
    background: transparent;
    color: {tokens["text.2"]};
    border: 1px solid transparent;
    padding: 7px 14px;
    margin-right: 4px;
    min-width: 72px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
    font-weight: 600;
    border-radius: 6px;
}}
QTabBar::tab:hover:!selected {{
    background: {tokens["surface.hover"]};
    color: {tokens["text.1"]};
}}

/* ── Buttons ────────────────────────────────────────────────── */
/* The ui-redesign button contract (mockup `button()`): radius 6, a quiet
   resting surface, and a checked/active control that reads as tinted accent —
   16 % fill, 50 % border, accent caption — instead of the old outlined chip. */
QPushButton, QToolButton {{
    background: {tokens["surface.3"]};
    color: {tokens["text.1"]};
    border: 1px solid {tokens["line.2"]};
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: {font_size}px;
    font-weight: 500;
}}
QPushButton:hover, QToolButton:hover {{
    background: {tokens["surface.hover"]};
    border-color: {tokens["accent.line"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {tokens["surface.pressed"]};
}}
QPushButton:checked, QToolButton:checked {{
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
    color: {tokens["accent.text"]};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {tokens["text.disabled"]};
    background: {tokens["surface.2"]};
    border-color: {tokens["line.1"]};
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
    border-radius: 6px;
    background: {tokens["surface.2"]};
    text-align: center;
    color: {tokens["progress.text"]};
    height: 16px;
}}
QProgressBar::chunk {{
    background: {tokens["accent.tab"]};
    border-radius: 5px;
}}

/* ── SpinBox ────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {tokens["surface.2"]};
    border: 1px solid {tokens["line.1"]};
    border-radius: 6px;
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
    border-radius: 6px;
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
    /* Primary action of a dialog: the mockup's filled accent, dark ink on it. */
    background: {tokens["accent"]};
    border-color: {tokens["accent"]};
    color: {tokens["accent.on"]};
    font-weight: 600;
}}
QPushButton:default:hover {{
    background: {tokens["accent.text"]};
    border-color: {tokens["accent.text"]};
}}
QPushButton:default:disabled {{
    background: {tokens["surface.2"]};
    border-color: {tokens["line.1"]};
    color: {tokens["text.disabled"]};
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
#systemBar QPushButton, #systemBar QToolButton {{
    min-height: 23px;
    max-height: 23px;
    padding: 2px 8px;
    font-size: {max(font_size - 1, 11)}px;
    font-weight: 500;
    /* The action row is text + glyph on the bar itself (§4.1, A1), not a line of
       boxed chips: a filled, bordered rectangle behind every caption made the
       row loud and moved it away from the design. */
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
}}
#systemBar QPushButton:hover, #systemBar QToolButton:hover {{
    background: {tokens["surface.hover"]};
    border-color: transparent;
}}
#systemBar QPushButton:pressed, #systemBar QToolButton:pressed {{
    background: {tokens["surface.pressed"]};
}}
#systemBar QPushButton:checked, #systemBar QToolButton:checked {{
    background: {tokens["surface.2"]};
    border-color: {tokens["accent.tab"]};
}}
#systemBar QPushButton:disabled, #systemBar QToolButton:disabled {{
    color: {tokens["text.disabled"]};
    background: transparent;
}}
#systemBarSeparator {{
    background: {tokens["line.2"]};
    border: none;
    max-width: 1px;
    min-width: 1px;
}}
/* «PACS ▾» is a QToolButton with InstantPopup: the menu-indicator glyph of the
   style was drawn as a stray dash under the right edge and pushed the caption
   down relative to the neighbouring QPushButtons. The button opens the menu on
   the first click, so no arrow is needed; hide it and keep the metrics of the
   buttons it sits between. */
#systemBar QToolButton::menu-indicator {{
    image: none;
    width: 0;
    height: 0;
}}
#systemBarContext, #systemBarActions {{
    background: transparent;
}}
/* «Справочник» is an ordinary action of the row: the accent outline it used to
   carry made one of five equal buttons look selected. */
#systemBar QPushButton#referencesButton {{
    border-color: transparent;
}}
/* «Сброс» is destructive, not primary. Filled with the bright danger fill it was
   the loudest control of the row, so the modes «Изображения | Отчёт» read as
   disabled next to it. The muted shade (danger.bg2) keeps the button obviously
   destructive while the accent fill of the active segment becomes the loudest
   thing — which is what the segmented control is for. Text on it stays above
   4.5:1 in every theme (tests/unit/test_theme_graphite.py). */
#systemBar QPushButton#resetButton {{
    background: {tokens["state.danger.bg2"]};
    border-color: {tokens["state.danger.border"]};
    color: {tokens["state.danger.text"]};
}}
#systemBar QPushButton#resetButton:hover {{
    background: {tokens["state.danger.bg"]};
    border-color: {tokens["state.danger.border.hover"]};
}}
#systemBar QPushButton#resetButton:pressed {{
    background: {tokens["state.danger.bg.pressed"]};
}}

/* «Изображения | Отчёт» — one segmented control (spec §4.1, UD-08). The checked
   segment carries the accent fill; the unchecked one stays a quiet surface, so
   the pair reads as «this is the active mode», not as «these are two buttons,
   the outlined one is off». */
#systemBar QPushButton#modeImagesButton, #systemBar QPushButton#modeReportButton {{
    border: 1px solid {tokens["line.2"]};
    border-radius: 0;
    background: {tokens["surface.2"]};
    color: {tokens["text.1"]};
    padding: 2px 12px;
}}
#systemBar QPushButton#modeImagesButton {{
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
    border-right: none;
}}
#systemBar QPushButton#modeReportButton {{
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}}
#systemBar QPushButton#modeImagesButton:hover, #systemBar QPushButton#modeReportButton:hover {{
    background: {tokens["surface.hover"]};
    color: {tokens["text.1"]};
}}
#systemBar QPushButton#modeImagesButton:checked, #systemBar QPushButton#modeReportButton:checked {{
    background: {tokens["accent.tab"]};
    border-color: {tokens["accent.tab"]};
    color: {tokens["accent.on"]};
    font-weight: 600;
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

/* ── Tool buttons (row and rail, UI-2 PR-3) ──────────────────── */
/* The global QToolButton rule reserves 12 px of padding per side. In the fixed
   38 px cell of the row that left a 10 px glyph box, so the pictogram sat small
   and off-centre; the icon box is now the button box and the glyph is sized by
   ToolButtonsBase.ICON_EDGE. */
QToolButton[view="row"], QToolButton[view="rail"] {{
    padding: 0;
    min-height: 0;
    min-width: 0;
}}
QToolButton[view="row"]:checked, QToolButton[view="rail"]:checked {{
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
    color: {tokens["accent.text"]};
}}
QToolButton[view="row"]:disabled, QToolButton[view="rail"]:disabled {{
    color: {tokens["text.disabled"]};
}}
#toolButtonSeparator {{
    background: {tokens["line.2"]};
    max-width: 1px;
    min-width: 1px;
    border: none;
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
