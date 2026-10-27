"""Visible interface-palette picker for the Settings dialog.

The two comboboxes (theme + accent) are precise but abstract: the physician
cannot see what «Graphite + violet» does to a button or a field until the whole
application is repainted.  This widget is the missing *choice of a palette* —
six named combinations, each drawn with the four colours it actually applies:
panel surface, field surface, button surface and accent.  Clinical overlays
are deliberately not in the preview: they never follow an accent palette.

The picker is an editor, not a second preference: choosing a card writes the
two existing comboboxes.  A combination the user assembles by hand simply
leaves no card checked, and «Готово» still saves it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QToolButton, QWidget

from echo_personal_tool.presentation.theme.palettes import get_palette_tokens


@dataclass(frozen=True)
class PalettePreset:
    """One named (theme, accent) pair shown as a card."""

    preset_id: str
    theme: str
    accent: str
    label_key: str


#: Six presets: dark/light bases and the four accent colours.  The first one is
#: the default of a fresh profile, so a new install opens with a checked card.
PRESETS: tuple[PalettePreset, ...] = (
    PalettePreset("graphite", "graphite", "theme", "preferences.palette_graphite"),
    PalettePreset("ocean", "dark", "blue", "preferences.palette_ocean"),
    PalettePreset("amethyst", "graphite", "violet", "preferences.palette_amethyst"),
    PalettePreset("slate", "vscode_dark", "teal", "preferences.palette_slate"),
    PalettePreset("paper", "light", "amber", "preferences.palette_paper"),
    PalettePreset("frost", "vscode_light", "blue", "preferences.palette_frost"),
)

_SWATCH_ROLES = ("surface.1", "surface.2", "surface.3", "accent")
_SWATCH_EDGE = 18
_PREVIEW_W = 96
_PREVIEW_H = 26
_CARD_COLUMNS = 3


def _preview_pixmap(theme: str, accent: str, line: str) -> QPixmap:
    """Four rounded swatches: panel, field, button, active accent."""
    tokens = get_palette_tokens(theme, accent_palette=accent)
    pixmap = QPixmap(_PREVIEW_W, _PREVIEW_H)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gap = 4
    x = 0
    painter.setPen(Qt.PenStyle.NoPen)
    for role in _SWATCH_ROLES:
        rect = QRectF(x, 3, _SWATCH_EDGE, _PREVIEW_H - 6)
        painter.setBrush(QColor(tokens[role]))
        painter.drawRoundedRect(rect, 3, 3)
        x += _SWATCH_EDGE + gap
    # A hairline of the frame colour keeps a light preset visible on a light
    # dialog background.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QColor(line))
    painter.drawRoundedRect(QRectF(0.5, 3.5, x - gap - 1, _PREVIEW_H - 7), 3, 3)
    painter.end()
    return pixmap


class InterfacePalettePicker(QWidget):
    """A 3×2 grid of checkable palette cards."""

    #: (theme_id, accent_id) of the card the user pressed.
    palette_selected = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("interfacePalettePicker")
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._cards: dict[str, QToolButton] = {}
        self._preset_by_values = {(preset.theme, preset.accent): preset.preset_id for preset in PRESETS}
        for index, preset in enumerate(PRESETS):
            card = QToolButton(self)
            card.setObjectName(f"paletteCard_{preset.preset_id}")
            card.setCheckable(True)
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            preview = _preview_pixmap(preset.theme, preset.accent, tokens["line.2"])
            card.setIcon(QIcon(preview))
            card.setIconSize(preview.size())
            card.setText(tr(preset.label_key))
            card.setToolTip(f"{tr('preferences.color_theme')}: {tr(preset.label_key)}")
            card.setAccessibleName(tr(preset.label_key))
            card.setMinimumWidth(96)
            card.clicked.connect(lambda _checked=False, p=preset: self.palette_selected.emit(p.theme, p.accent))
            self._group.addButton(card)
            self._cards[preset.preset_id] = card
            layout.addWidget(card, index // _CARD_COLUMNS, index % _CARD_COLUMNS)
        self._apply_card_style(tokens)

    def _apply_card_style(self, tokens: dict[str, str]) -> None:
        from echo_personal_tool.presentation.theme.controls import button_qss

        self.setStyleSheet(
            button_qss(
                "QToolButton",
                tokens,
                variant="chip",
                height=None,
                padding_x=4,
                padding_y=4,
                radius=6,
                font_size=None,
            )
        )

    def set_current(self, theme: str, accent: str) -> None:
        """Check the card of *theme*/*accent*, or none for a custom pair."""
        preset_id = self._preset_by_values.get((theme, accent))
        for card_id, card in self._cards.items():
            card.setChecked(card_id == preset_id)

    def current_preset(self) -> str | None:
        checked = self._group.checkedButton()
        for card_id, card in self._cards.items():
            if card is checked:
                return card_id
        return None

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        for preset in PRESETS:
            card = self._cards[preset.preset_id]
            card.setText(tr(preset.label_key))
            card.setAccessibleName(tr(preset.label_key))
