"""Visible interface-palette picker for the Settings dialog.

Two different questions were hiding behind one control (2026-10-27 review,
item 1: «палитра меняет цвета всего окна, также как и тема»):

* the **theme** — the ground, the panels, the text: what the window *is*;
* the **accent palette** — the colour of the controls that act: the push
  button, the selected chip, the focus ring, the slider fill.

The picker is the second question, and only it.  Each card paints the surfaces
of the *current* theme (unchanged by the card) beside the accent it applies, so
the promise «меняются кнопки и поля, фон остаётся» is visible before the card
is pressed.  A card writes the accent preference — never the theme; the theme
combo above stays the single source of the window's ground.

Clinical overlays are deliberately not in the preview: they never follow an
accent palette.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QSizePolicy, QToolButton, QWidget

from echo_personal_tool.presentation.theme.palettes import get_palette_tokens


@dataclass(frozen=True)
class PalettePreset:
    """One named accent palette shown as a card.

    A preset has no theme: the ground is the user's theme, and the accent is
    the only thing the card changes.
    """

    preset_id: str
    accent: str
    label_key: str


#: Five accents: «Из темы» (the theme's own accent) and the four overrides.
#: The first one is the default of a fresh profile, so a new install opens with
#: a checked card.
PRESETS: tuple[PalettePreset, ...] = (
    PalettePreset("accent_theme", "theme", "preferences.accent_theme"),
    PalettePreset("accent_blue", "blue", "preferences.accent_blue"),
    PalettePreset("accent_teal", "teal", "preferences.accent_teal"),
    PalettePreset("accent_violet", "violet", "preferences.accent_violet"),
    PalettePreset("accent_amber", "amber", "preferences.accent_amber"),
)

#: The theme swatches every card starts with, then the accent it applies.
_SWATCH_ROLES = ("surface.1", "surface.2", "surface.3")
_SWATCH_EDGE = 15
_SWATCH_GAP = 3
_PREVIEW_W = 86
_PREVIEW_H = 24
_CARD_COLUMNS = 3
#: A card is a preview *and* a caption under it; without a floor the three
#: cards of the settings form collapsed to the width of the pixmap and the
#: captions disappeared.
_CARD_MIN_W = 104
_CARD_MIN_H = 56

#: English captions for a picker created without a translator (tests, previews).
#: The Settings dialog injects its own ``tr`` — this module deliberately has
#: no translation import edge of its own (architecture allowlist).
_FALLBACK_LABELS = {
    "preferences.accent_theme": "From theme",
    "preferences.accent_blue": "Blue",
    "preferences.accent_teal": "Teal",
    "preferences.accent_violet": "Violet",
    "preferences.accent_amber": "Amber",
}


def _fallback_tr(key: str) -> str:
    return _FALLBACK_LABELS.get(key, key)


def _preview_pixmap(theme: str, accent: str, line: str) -> QPixmap:
    """The ground of the active theme, then the accent the card applies."""
    tokens = get_palette_tokens(theme, accent_palette=accent)
    pixmap = QPixmap(_PREVIEW_W, _PREVIEW_H)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    x = 0
    painter.setPen(Qt.PenStyle.NoPen)
    for role in _SWATCH_ROLES:
        painter.setBrush(QColor(tokens[role]))
        painter.drawRoundedRect(QRectF(x, 4, _SWATCH_EDGE, _PREVIEW_H - 8), 3, 3)
        x += _SWATCH_EDGE + _SWATCH_GAP
    # A gap, then the accent as the one coloured mark: the card promises a
    # colour of the controls, not a repaint of the window.
    x += 3
    painter.setBrush(QColor(tokens["accent"]))
    painter.drawRoundedRect(QRectF(x, 4, _PREVIEW_W - x, _PREVIEW_H - 8), 3, 3)
    # A hairline of the frame colour keeps a light preset visible on a light
    # dialog background.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QColor(line))
    painter.drawRoundedRect(QRectF(0.5, 0.5, _PREVIEW_W - 1, _PREVIEW_H - 1), 4, 4)
    painter.end()
    return pixmap


class InterfacePalettePicker(QWidget):
    """A 3×2 grid of checkable accent cards over the surfaces of the theme."""

    #: Accent id of the card the user pressed.  The theme is never reported:
    #: the picker cannot change it.
    palette_selected = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        translate: Callable[[str], str] | None = None,
        theme: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("interfacePalettePicker")
        from echo_personal_tool.presentation.dark_theme import current_theme_id

        self._tr: Callable[[str], str] = translate or _fallback_tr
        self._theme = theme or current_theme_id()
        tokens = get_palette_tokens(self._theme)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._cards: dict[str, QToolButton] = {}
        self._preset_by_accent = {preset.accent: preset.preset_id for preset in PRESETS}
        for index, preset in enumerate(PRESETS):
            card = QToolButton(self)
            card.setObjectName(f"paletteCard_{preset.preset_id}")
            card.setCheckable(True)
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            self._paint_card(card, preset, tokens)
            card.setToolTip(f"{self._tr('preferences.interface_palette')}: {self._tr(preset.label_key)}")
            card.setAccessibleName(self._tr(preset.label_key))
            card.setMinimumWidth(_CARD_MIN_W)
            card.setMinimumHeight(_CARD_MIN_H)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.clicked.connect(lambda _checked=False, p=preset: self.palette_selected.emit(p.accent))
            self._group.addButton(card)
            self._cards[preset.preset_id] = card
            layout.addWidget(card, index // _CARD_COLUMNS, index % _CARD_COLUMNS)
        self._apply_card_style(tokens)

    def _paint_card(self, card: QToolButton, preset: PalettePreset, tokens: dict[str, str]) -> None:
        preview = _preview_pixmap(self._theme, preset.accent, tokens["line.1"])
        card.setIcon(QIcon(preview))
        card.setIconSize(preview.size())
        card.setText(self._tr(preset.label_key))

    def _apply_card_style(self, tokens: dict[str, str]) -> None:
        """Card chrome: a preview tile, not a toolbar button.

        The generic chip rule of the panel left the cards with the icon size
        and no padding, so the caption was clipped away and «Палитра
        интерфейса» read as five colour strips.  A card is a 104 × 56 tile:
        the surfaces of the theme on top, the accent mark beside them, the
        caption under, and the accent frame + accent caption when checked.
        """
        from echo_personal_tool.presentation.theme.controls import BUTTON_RADIUS, button_qss

        self.setStyleSheet(
            button_qss(
                "#interfacePalettePicker QToolButton",
                tokens,
                variant="chip",
                height=None,
                padding_x=8,
                padding_y=6,
                radius=BUTTON_RADIUS + 2,
                font_size=None,
            )
            + f"""
            #interfacePalettePicker QToolButton {{
                font-size: 11px;
                font-weight: 500;
                color: {tokens["text.2"]};
            }}
            #interfacePalettePicker QToolButton:hover {{
                color: {tokens["text.1"]};
            }}
            #interfacePalettePicker QToolButton:checked {{
                background: {tokens["accent.tint"]};
                border: 1px solid {tokens["accent.line"]};
                color: {tokens["accent.text"]};
                font-weight: 600;
            }}
            """
        )

    def set_theme(self, theme: str) -> None:
        """Repaint the surface swatches of every card for a new theme.

        The theme switch is the business of the theme combo; the picker only
        follows it so the preview keeps telling the truth about the ground.
        A ``system`` mode is resolved to the concrete palette first.
        """
        from echo_personal_tool.presentation.theme.system_theme import resolve_theme_id

        theme = resolve_theme_id(theme) if theme else ""
        if not theme or theme == self._theme:
            return
        self._theme = theme
        tokens = get_palette_tokens(theme)
        for preset in PRESETS:
            card = self._cards.get(preset.preset_id)
            if card is not None:
                self._paint_card(card, preset, tokens)
        self._apply_card_style(tokens)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_current(self, accent: str) -> None:
        """Check the card of *accent*; a hand-picked value checks none."""
        preset_id = self._preset_by_accent.get(accent)
        for card_id, card in self._cards.items():
            card.setChecked(card_id == preset_id)

    def current_preset(self) -> str | None:
        checked = self._group.checkedButton()
        for card_id, card in self._cards.items():
            if card is checked:
                return card_id
        return None

    def reload_text(self) -> None:
        for preset in PRESETS:
            card = self._cards[preset.preset_id]
            card.setText(self._tr(preset.label_key))
            card.setToolTip(f"{self._tr('preferences.interface_palette')}: {self._tr(preset.label_key)}")
            card.setAccessibleName(self._tr(preset.label_key))
