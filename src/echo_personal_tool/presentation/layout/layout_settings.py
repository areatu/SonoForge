"""Layout controls of the «Appearance & layout» settings section (UI-2 PR-2).

Spec: ``docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md`` §4.2
(presets), §4.9 (the settings section), §8.1 (``LayoutConfig`` v2).

:class:`LayoutSettingsWidget` edits a :class:`LayoutConfigV2` document: the
three preset tiles with mini-schemes, the «Tool buttons» row, the tool-label
mode, the status-bar toggle and the single-file focus toggle. The dialog
reads :meth:`document` on accept and applies it without a restart; nothing
is stored or rebuilt from here.

The schemes are painted from the semantic tokens of the active theme, so the
widget adds no colour literals (G-3). ``row`` and ``panel`` tool buttons are
stored but assemble as ``auto`` until UI-2 PR-3 builds the row and the panel
block; the combo tooltip says so.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.layout.presets import (
    PRESET_CLASSIC,
    PRESET_FILMSTRIP,
    PRESETS,
    LayoutConfigV2,
)


def _tokens() -> dict[str, str]:
    from echo_personal_tool.presentation.dark_theme import get_theme_tokens

    return get_theme_tokens()


class _PresetScheme(QWidget):
    """A mini-scheme of one preset: gallery / viewer / panel blocks (spec §4.9).

    The blocks are proportional to the widget size, so the tiles survive a
    narrow dialog. A click selects the preset of the tile.
    """

    clicked = Signal()

    def __init__(self, preset: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preset = preset
        self._selected = False
        self.setMinimumSize(120, 76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def preset(self) -> str:
        return self._preset

    def set_selected(self, selected: bool) -> None:
        if self._selected != selected:
            self._selected = selected
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:  # type: ignore[override]
        tokens = _tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(tokens["accent" if self._selected else "line.1"]), 2 if self._selected else 1))
        painter.setBrush(QColor(tokens["surface.1"]))
        painter.drawRoundedRect(rect, 6, 6)

        margin, gap = 8, 5
        inner = rect.adjusted(margin, margin, -margin, -margin)
        if self._preset == PRESET_FILMSTRIP:
            strip_height = round(inner.height() * 0.30)
            top = inner.adjusted(0, 0, 0, -(strip_height + gap))
            viewer_width = round(top.width() * 0.66)
            self._paint_block(painter, tokens, top.adjusted(0, 0, -(top.width() - viewer_width + gap), 0), "viewer")
            self._paint_block(painter, tokens, top.adjusted(viewer_width + gap, 0, 0, 0), "panel")
            self._paint_block(painter, tokens, inner.adjusted(0, inner.height() - strip_height, 0, 0), "gallery")
        else:
            widths = (0.30, 0.44, 0.26)
            kinds = ("gallery", "viewer", "panel") if self._preset == PRESET_CLASSIC else ("panel", "viewer", "gallery")
            x = inner.left()
            for index, (fraction, kind) in enumerate(zip(widths, kinds)):
                width = round(inner.width() * fraction) if index < 2 else inner.right() - x + 1
                self._paint_block(painter, tokens, _sliced(inner, x, width), kind)
                x += width + gap

    def _paint_block(self, painter: QPainter, tokens: dict[str, str], rect: QRect, kind: str) -> None:
        painter.setPen(QPen(QColor(tokens["line.1"]), 1))
        painter.setBrush(QColor(tokens["surface.0"] if kind == "viewer" else "surface.3"))
        painter.drawRoundedRect(rect, 3, 3)
        if kind == "viewer":
            return
        line = QColor(tokens["text.3"])
        line.setAlpha(110)
        painter.setPen(QPen(line, 2))
        rows = 3 if kind == "gallery" else 4
        for row in range(rows):
            y = rect.top() + round(rect.height() * (row + 1) / (rows + 1))
            painter.drawLine(rect.left() + 4, y, rect.right() - 4, y)


def _sliced(inner: QRect, x: int, width: int) -> QRect:
    """A vertical slice of ``inner`` starting at ``x`` (the painter helper above)."""
    return QRect(x, inner.top(), width, inner.height())


class _PresetTile(QWidget):
    """One preset tile: the scheme, the radio button and the caption (mock 07)."""

    def __init__(self, preset: str, group: QButtonGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preset = preset
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.scheme = _PresetScheme(preset, self)
        self.scheme.setObjectName(f"layoutPresetScheme_{preset}")
        self.radio = QRadioButton(tr(f"layout.preset_{preset}"), self)
        self.radio.setObjectName(f"layoutPreset_{preset}")
        group.addButton(self.radio)
        caption = QLabel(tr(f"layout.preset_{preset}_hint"), self)
        caption.setObjectName("layoutPresetCaption")
        caption.setWordWrap(True)
        layout.addWidget(self.scheme, stretch=1)
        layout.addWidget(self.radio)
        layout.addWidget(caption)
        self.scheme.clicked.connect(lambda: self.radio.setChecked(True))
        self.radio.toggled.connect(self.scheme.set_selected)

    @property
    def preset(self) -> str:
        return self._preset


class LayoutSettingsWidget(QWidget):
    """The layout group of the settings: presets, tool buttons and the v2 flags."""

    TOOL_BUTTON_MODES: tuple[str, ...] = ("auto", "row", "rail", "panel")
    TOOL_LABEL_MODES: tuple[str, ...] = ("icons_labels", "icons")

    def __init__(self, document: LayoutConfigV2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("layoutSettingsSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        description = QLabel(tr("layout.group_hint"), self)
        description.setWordWrap(True)
        description.setObjectName("layoutGroupHint")
        layout.addWidget(description)

        self._preset_group = QButtonGroup(self)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self._tiles: dict[str, _PresetTile] = {}
        for preset in PRESETS:
            tile = _PresetTile(preset, self._preset_group, self)
            self._tiles[preset] = tile
            tiles.addWidget(tile, stretch=1)
        layout.addLayout(tiles)

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        self._tool_buttons = QComboBox(self)
        self._tool_buttons.setObjectName("layoutToolButtonsCombo")
        for mode in self.TOOL_BUTTON_MODES:
            self._tool_buttons.addItem(tr(f"layout.tool_buttons_{mode}"), mode)
        self._tool_buttons.setToolTip(tr("layout.tool_buttons_hint"))
        form.addRow(tr("layout.tool_buttons"), self._tool_buttons)

        self._tool_labels = QComboBox(self)
        self._tool_labels.setObjectName("layoutToolLabelsCombo")
        for mode in self.TOOL_LABEL_MODES:
            self._tool_labels.addItem(tr(f"layout.tool_labels_{mode}"), mode)
        form.addRow(tr("layout.tool_labels"), self._tool_labels)

        self._status_bar = QCheckBox(tr("layout.status_bar_mode"), self)
        self._status_bar.setObjectName("layoutStatusBarCheck")
        form.addRow(self._status_bar)

        self._single_file_focus = QCheckBox(tr("layout.single_file_focus"), self)
        self._single_file_focus.setObjectName("layoutSingleFileFocusCheck")
        self._single_file_focus.setToolTip(tr("layout.single_file_focus_hint"))
        form.addRow(self._single_file_focus)
        layout.addLayout(form)

        tokens = _tokens()
        self.setStyleSheet(
            "#layoutPresetCaption, #layoutGroupHint {\n"
            f"    color: {tokens['text.2']};\n"
            "}\n"
        )
        self.set_document(document)

    def document(self) -> LayoutConfigV2:
        """The document the controls currently describe."""
        preset = next((name for name, tile in self._tiles.items() if tile.radio.isChecked()), PRESET_CLASSIC)
        tool_buttons = self._tool_buttons.currentData()
        tool_labels = self._tool_labels.currentData()
        return LayoutConfigV2(
            preset=preset if preset in PRESETS else PRESET_CLASSIC,
            tool_buttons=tool_buttons if tool_buttons in self.TOOL_BUTTON_MODES else "auto",
            tool_labels=tool_labels if tool_labels in self.TOOL_LABEL_MODES else "icons_labels",
            status_bar_visible=self._status_bar.isChecked(),
            single_file_focus=self._single_file_focus.isChecked(),
        )

    def set_document(self, document: LayoutConfigV2) -> None:
        """Show ``document`` in every control (used on open and on reset)."""
        self._preset_group.blockSignals(True)
        tile = self._tiles.get(document.preset, self._tiles[PRESET_CLASSIC])
        tile.radio.setChecked(True)
        for name, other in self._tiles.items():
            other.scheme.set_selected(other is tile)
        self._preset_group.blockSignals(False)
        self._tool_buttons.setCurrentIndex(max(self._tool_buttons.findData(document.tool_buttons), 0))
        self._tool_labels.setCurrentIndex(max(self._tool_labels.findData(document.tool_labels), 0))
        self._status_bar.setChecked(document.status_bar_visible)
        self._single_file_focus.setChecked(document.single_file_focus)
