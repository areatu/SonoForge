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

from echo_personal_tool.presentation.theme.palettes import PALETTES, get_palette_tokens, is_dark_theme
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
def _build_stylesheet(font_size: int, theme: str, accent_palette: str = "theme") -> str:
    """Build the application stylesheet of a concrete theme (cached)."""
    tokens = get_palette_tokens(theme if theme in PALETTES else "dark", accent_palette=accent_palette)
    arrow_up, arrow_down, check = _icon_paths(theme)
    return "".join(
        (
            _stylesheet_00_global(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_01_line_edit(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_02_status_bar(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_03_tabs(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_04_buttons(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_05_groupbox(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_06_lists_trees(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_07_scrollbar(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_08_splitter(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_09_slider(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_10_progressbar(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_11_spinbox(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_12_checkbox(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_13_tree_view_checkbox_indicators(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_14_settings(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_15_systembar(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_16_window_controls(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_17_activity_bar(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_18_layout_menu(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_19_toolpanel(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_20_thumbnail_gallery(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_21_tool_buttons_row_and_rail_ui_2_pr_3(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_22_tool_panel_tabs_and_native_overflow_controls(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_23_focus_ring(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_24_tooltips(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_25_constructor_dialog(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_26_multiview_two_clips_side_by_side(font_size, tokens, arrow_up, arrow_down, check),
            _stylesheet_27_menu_bar_menus(font_size, tokens, arrow_up, arrow_down, check),
        )
    )


def _stylesheet_00_global(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Global stylesheet section."""
    return f"""
/* ── Global ──────────────────────────────────────────────────── */
QWidget {{
    background-color: {tokens["surface.1"]};
    color: {tokens["text.1"]};
    font-family: "{FONT_FAMILY_UI}", sans-serif;
    font-size: {font_size}px;
}}
/* Captions are transparent by default.  The ``QWidget`` rule above also
   matches every ``QLabel``, so each caption painted the window surface on top
   of its parent.  Inside a hovered row (``#toolRow:hover`` = surface.3) the
   glyph/value/badge labels then read as grey stripes over the highlight
   (2026-10-25).  A more specific rule (``#id`` or a widget-local sheet) still
   overrides this one where a label really needs a fill. */
QLabel {{
    background: transparent;
}}
QMainWindow {{
    background-color: {tokens["surface.0"]};
}}
QDialog {{
    border: 1px solid {tokens["line.dialog"]};
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

"""


def _stylesheet_01_line_edit(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Line Edit stylesheet section."""
    return f"""/* ── Line Edit ──────────────────────────────────────────────── */
QLineEdit {{
    placeholder-text-color: {tokens["text.3"]};
    selection-background-color: {tokens["accent.selected"]};
    selection-color: {tokens["text.selected"]};
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

"""


def _stylesheet_02_status_bar(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Status bar stylesheet section."""
    return f"""/* ── Status bar ─────────────────────────────────────────────── */
QStatusBar {{
    background-color: {tokens["surface.2"]};
    color: {tokens["text.2"]};
    border-top: 1px solid {tokens["line.1"]};
}}

"""


def _stylesheet_03_tabs(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Tabs stylesheet section."""
    return f"""/* ── Tabs ───────────────────────────────────────────────────── */
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

"""


def _stylesheet_04_buttons(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Buttons stylesheet section."""
    return f"""/* ── Buttons ────────────────────────────────────────────────── */
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
#patientMetricEditor {{
    min-height: 22px;
    padding: 2px 6px;
}}
#toolButtonRow QToolButton {{
    padding: 4px 8px;
    min-height: 0px;
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

"""


def _stylesheet_05_groupbox(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the GroupBox stylesheet section."""
    return f"""/* ── GroupBox ───────────────────────────────────────────────── */
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

"""


def _stylesheet_06_lists_trees(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Lists / Trees stylesheet section."""
    return f"""/* ── Lists / Trees ─────────────────────────────────────────── */
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

"""


def _stylesheet_07_scrollbar(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Scrollbar stylesheet section."""
    return f"""/* ── Scrollbar ──────────────────────────────────────────────── */
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

"""


def _stylesheet_08_splitter(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Splitter stylesheet section."""
    return f"""/* ── Splitter ───────────────────────────────────────────────── */
QSplitter::handle {{
    background: {tokens["line.1"]};
    width: 2px;
}}
QSplitter::handle:hover {{
    background: {tokens["accent.tab"]};
}}

"""


def _stylesheet_09_slider(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Slider stylesheet section."""
    return f"""/* ── Slider ─────────────────────────────────────────────────── */
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

"""


def _stylesheet_10_progressbar(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the ProgressBar stylesheet section."""
    return f"""/* ── ProgressBar ────────────────────────────────────────────── */
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

"""


def _stylesheet_11_spinbox(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the SpinBox stylesheet section."""
    return f"""/* ── SpinBox ────────────────────────────────────────────────── */
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

"""


def _stylesheet_12_checkbox(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the CheckBox stylesheet section."""
    return f"""/* ── CheckBox ───────────────────────────────────────────────── */
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

"""


def _stylesheet_13_tree_view_checkbox_indicators(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Tree/View CheckBox indicators stylesheet section."""
    return f"""/* ── Tree/View CheckBox indicators ──────────────────────────── */
/* Match ordinary checkboxes: a filled disc is not a checked state. Keep
   an explicit check image and a stable border in selected/disabled rows too. */
QTreeWidget::indicator, QTreeView::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {tokens["line.2"]};
    background: {tokens["surface.2"]};
    border-radius: 3px;
}}
QTreeWidget::indicator:checked, QTreeView::indicator:checked {{
    background: {tokens["surface.hover"]};
    border-color: {tokens["accent"]};
    image: url("{check}");
}}
QTreeWidget::indicator:unchecked, QTreeView::indicator:unchecked {{
    image: none;
}}
QTreeWidget::indicator:hover, QTreeView::indicator:hover {{
    border-color: {tokens["accent"]};
}}
QTreeWidget::item, QTreeView::item {{
    min-height: {max(22, font_size + 6)}px;
}}


"""


def _stylesheet_14_settings(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Settings stylesheet section."""
    return f"""/* ── Settings ───────────────────────────────────────────────── */
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
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
    color: {tokens["accent.text"]};
    font-weight: 600;
}}
QPushButton:default:hover {{
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
}}
QPushButton:default:disabled {{
    background: {tokens["surface.2"]};
    border-color: {tokens["line.1"]};
    color: {tokens["text.disabled"]};
}}

"""


def _stylesheet_15_systembar(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the SystemBar stylesheet section."""
    return f"""/* ── SystemBar ──────────────────────────────────────────────── */
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
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
    color: {tokens["accent.text"]};
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
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
    color: {tokens["accent.text"]};
    font-weight: 600;
}}

"""


def _stylesheet_16_window_controls(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Window Controls stylesheet section."""
    return f"""/* ── Window Controls ──────────────────────────────────────────── */
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

"""


def _stylesheet_17_activity_bar(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Activity Bar stylesheet section."""
    return f"""/* ── Activity Bar ──────────────────────────────────────────────── */
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
    background: {tokens["accent.tint"]};
    border-left: 2px solid {tokens["accent.line"]};
    color: {tokens["accent.text"]};
}}

"""


def _stylesheet_18_layout_menu(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Layout Menu stylesheet section."""
    return f"""/* ── Layout Menu ──────────────────────────────────────────────── */
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

"""


def _stylesheet_19_toolpanel(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the ToolPanel stylesheet section."""
    return f"""/* ── ToolPanel ──────────────────────────────────────────────── */
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

"""


def _stylesheet_20_thumbnail_gallery(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Thumbnail Gallery stylesheet section."""
    return f"""/* ── Thumbnail Gallery ──────────────────────────────────────── */
#thumbnailGallery {{
    background: {tokens["surface.0"]};
    border-right: 1px solid {tokens["line.1"]};
}}

"""


def _stylesheet_21_tool_buttons_row_and_rail_ui_2_pr_3(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Tool buttons (row and rail, UI-2 PR-3) stylesheet section."""
    return f"""/* ── Tool buttons (row and rail, UI-2 PR-3) ──────────────────── */
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

"""


def _stylesheet_22_tool_panel_tabs_and_native_overflow_controls(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Tool-panel tabs and native overflow controls stylesheet section."""
    return f"""/* ── Tool-panel tabs and native overflow controls ───────────── */
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

"""


def _stylesheet_23_focus_ring(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Focus ring stylesheet section."""
    return f"""/* ── Focus ring ─────────────────────────────────────────────── */
QTabBar::tab:focus {{
    border-color: {tokens["accent.tab"]};
}}
QSpinBox:focus, QCheckBox:focus {{
    border-color: {tokens["accent"]};
}}

"""


def _stylesheet_24_tooltips(font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str) -> str:
    """Build the Tooltips stylesheet section."""
    return f"""/* ── Tooltips ───────────────────────────────────────────────── */
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

"""


def _stylesheet_25_constructor_dialog(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Constructor Dialog stylesheet section."""
    return f"""/* ── Constructor Dialog ─────────────────────────────────────── */
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

"""


def _stylesheet_26_multiview_two_clips_side_by_side(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Multiview (two clips side by side) stylesheet section."""
    return f"""/* ── Multiview (two clips side by side) ─────────────────────── */
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
    color: {tokens["text.selected"]};
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
    background: {tokens["accent.tint"]};
    border-color: {tokens["accent.line"]};
    color: {tokens["accent.text"]};
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

"""


def _stylesheet_27_menu_bar_menus(
    font_size: int, tokens: dict[str, str], arrow_up: str, arrow_down: str, check: str
) -> str:
    """Build the Menu Bar & Menus stylesheet section."""
    return f"""/* ── Menu Bar & Menus ──────────────────────────────────────── */
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


def build_clinical_stylesheet(font_size: int = 13, theme: str = "dark", *, accent_palette: str = "theme") -> str:
    """Build the application stylesheet of a theme.

    *theme* is a theme id ("dark", "light", "vscode_dark", "vscode_light",
    "graphite") or "system", which is resolved to the current system colour
    scheme on every call — the system may change while the application runs.
    The sheet of a concrete theme is cached per (font size, theme).
    """
    resolved = system_theme_id() if theme == "system" else theme
    return _build_stylesheet(font_size, resolved, accent_palette)


def clear_stylesheet_cache() -> None:
    """Drop the cached stylesheets (after a change of the icon set)."""
    _build_stylesheet.cache_clear()
