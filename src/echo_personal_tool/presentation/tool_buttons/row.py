"""The tool row above the snapshot (UI-2 PR-3, D-08).

Spec §4.1: a 42 px strip over the image, icons, and a caption only next to the
active tool; §4.2: the composition of the row and its right group («масштаб»).
The buttons come from :mod:`~echo_personal_tool.presentation.tool_buttons.buttons`,
so the row, the rail and the panel's tools block can never disagree about which
tools exist or in which order they sit.

§4.1 also promises that at 1024 px «часть кнопок ряда уходит в „Ещё“», so the row
measures itself on resize and folds what does not fit into a menu: the tools stay
reachable, nothing vanishes without a trace (D-08).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QToolButton, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.theme.controls import GAP_XS, SPACE_LG
from echo_personal_tool.presentation.tool_buttons.base import (
    BUTTON_EDGE_MIN,
    ROW_HEIGHT_MIN,
    ToolButtonsBase,
)
from echo_personal_tool.presentation.tool_buttons.buttons import GROUP_VIEW, caption, unavailable_reason
from echo_personal_tool.presentation.ui_metrics import control_height

#: Width the «Ещё» button costs and the gap between the buttons of the row.
#: Wide enough for its caption and the count of what it hides: a bare «…» does
#: not say that anything is behind it (2026-10-30 report, item 2).
MORE_WIDTH = 68
SPACING = GAP_XS
#: The hairline between two groups (§4.2) — one pixel of the stylesheet rule.
SEPARATOR_WIDTH = 1
#: ``#toolButtonRow QToolButton { padding: 4px 8px }`` — the cell's own insets.
CELL_PADDING_X = 8
#: Style gap between the glyph and the caption of a «text beside icon» button.
ICON_TEXT_GAP = 4
#: Captions are kept only while they cost less than the glyph cells do: a strip
#: where the labelled layout would bury even a couple of tools in «Ещё» while
#: the glyph layout shows all of them drops the captions (2026-10-30, item 2).
#: The earlier share-based rule («компактно, если подписи прячут больше
#: трети») switched at 830 px but kept captions at 858 px and there folded five
#: tools — widening the window hid buttons — and it left the English row folding
#: four tools at 1366 px while the glyph cells needed far less.


class ToolButtonRow(ToolButtonsBase):
    """The horizontal strip; one signal out, whatever the button is (D-09 TP)."""

    OBJECT_NAME = "toolButtonRow"
    VIEW = "row"

    def __init__(self, parent: QWidget | None = None) -> None:
        # The layout is built parentless: QWidget.__init__ has to run first, and
        # the base class assembles the buttons only when ``build()`` is called.
        self._layout = QHBoxLayout()
        self._widths: dict[str, int] = {}
        self._hidden: frozenset[str] = frozenset()
        #: ``True`` while the strip is too narrow for eleven captioned buttons:
        #: the cells then shrink to their glyph and only the armed tool keeps a
        #: caption (spec §4.1), which is what keeps the row inside 1366 px.
        self._compact = False
        self._measuring = False
        super().__init__(parent)
        self.setLayout(self._layout)
        self._layout.setContentsMargins(SPACE_LG, 2, SPACE_LG, 2)
        self._layout.setSpacing(SPACING)
        self._more = QToolButton(self)
        self._more.setObjectName("toolButtonMore")
        self._more.setText("…")
        self._more.setAutoRaise(True)
        self._more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more.setVisible(False)
        self._menu = QMenu(self._more)
        self._menu.aboutToShow.connect(self._fill_menu)
        self._more.setMenu(self._menu)
        self._more.setAccessibleName(tr("toolbtn.more"))
        self.build()

    def shows_captions(self, spec) -> bool:
        """Captions while they fit; in a narrow viewer only the armed tool's."""
        if self._compact:
            return spec.id == self._active
        return True

    def is_compact(self) -> bool:
        """Whether the row dropped to glyph-only cells (the width made it)."""
        return self._compact

    def update_font_metrics(self) -> None:
        """A font change must re-measure the cells, not only re-read captions."""
        super().update_font_metrics()
        self.update_geometry()

    # ── assembly ────────────────────────────────────────────────────

    def arrange(self) -> None:
        """The measurement groups in catalog order, the view group on the right."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for index, spec in enumerate(self.specs()):
            if spec.group == GROUP_VIEW:
                continue
            control = self.button(spec.id)
            if control is None:
                continue
            if index and spec.separated:
                self._layout.addWidget(self._separator())
            self._layout.addWidget(control)
        self._layout.addStretch(1)
        self._layout.addWidget(self._more)
        for spec in self.specs():
            if spec.group == GROUP_VIEW:
                control = self.button(spec.id)
                if control is not None:
                    self._layout.addWidget(control)

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setObjectName("toolButtonSeparator")
        return line

    # ── geometry ────────────────────────────────────────────────────

    def _caption_width(self, control, edge: int) -> int:
        """Cell width that shows the whole caption beside the glyph.

        What a ``ToolButtonTextBesideIcon`` button really paints: the glyph, the
        4 px style gap after it, the caption and the 2 × 8 px padding of the
        stylesheet.  The earlier formula added 28 px on top of the glyph *and*
        the caption and over-measured every cell by ~14 px — eleven cells asked
        for 1478 px where 1330 are enough, and the row folded buttons it could
        have shown.
        """
        control.ensurePolished()
        icon_width = self.ICON_EDGE + ICON_TEXT_GAP if not control.icon().isNull() else 0
        return max(edge, control.fontMetrics().horizontalAdvance(control.text()) + icon_width + CELL_PADDING_X * 2 + 4)

    def _row_width(self, widths: dict[str, int], edge: int) -> int:
        """What the row needs for *widths*: cells, separators, margins, «Ещё»."""
        margins = self._layout.contentsMargins()
        total = margins.left() + margins.right() + MORE_WIDTH + SPACING
        for spec in self.specs():
            total += widths.get(spec.id, edge) + SPACING
            if spec.separated:
                total += SEPARATOR_WIDTH + SPACING
        return total

    def update_geometry(self) -> None:
        """42 px for the strip; the cells are sized so that the row fits.

        §4.1 pins the strip at 42 px while UA-05 asks for a 44 px target: inside a
        42 px row that is not reachable, so the row takes the strip and leaves the
        remainder of the target to the key (L, C, V, K) and the panel, which stay
        44 px.  The height is a floor, never a ceiling: a 24 px font grows it.

        Width: captions are measured, not assumed.  While eleven captioned cells
        fit the strip they all keep their caption; when they do not — a 1366 px
        window gave the row 830 px and it needed 1478 — the row drops to glyph
        cells and captions the armed tool only, which is the composition of §4.1
        and fits a 1024 px viewer without folding anything into «Ещё».  The menu
        still exists for the widths where even the glyphs do not fit.
        """
        if self._measuring:
            return
        self._measuring = True
        try:
            height = max(ROW_HEIGHT_MIN, control_height(self, padding=8) + 4)
            self.setFixedHeight(height)
            edge = max(BUTTON_EDGE_MIN - 8, height - 4)
            for spec in self.specs():
                control = self.button(spec.id)
                if control is not None:
                    control.setIconSize(QSize(self.ICON_EDGE, self.ICON_EDGE))
            self._more.setIconSize(QSize(self.ICON_EDGE, self.ICON_EDGE))

            caption_widths = {
                spec.id: self._caption_width(control, edge)
                for spec in self.specs()
                if (control := self.button(spec.id)) is not None
            }
            margins = self._layout.contentsMargins()
            available = self.width() - margins.left() - margins.right()
            # A width of 0 means "still being assembled": keep the labelled
            # layout, the first real resize corrects it.  Otherwise the row picks
            # the composition that *folds fewer tools*: while the captions cost
            # no button they stay, and as soon as they do the glyph cells win
            # (spec §4.1: icons, and the caption only next to the armed tool).
            compact = False
            if available > 0:
                cells = [spec for spec in self.specs()]
                labelled = [self._cell_width(spec, caption_widths.get(spec.id, edge)) for spec in cells]
                glyphs = [self._cell_width(spec, edge) for spec in cells]
                folded_labelled = len(cells) - self._fitting_count(labelled, available)
                folded_glyphs = len(cells) - self._fitting_count(glyphs, available)
                compact = folded_glyphs < folded_labelled
            if compact != self._compact:
                self._compact = compact
                for spec in self.specs():
                    control = self.button(spec.id)
                    if control is not None:
                        control.setToolButtonStyle(self.button_style(spec))

            self._widths = {}
            for spec in self.specs():
                control = self.button(spec.id)
                if control is None:
                    continue
                # In the compact mode only the armed tool keeps its caption,
                # and it keeps the whole of it.
                width = caption_widths[spec.id] if self.shows_captions(spec) else edge
                control.setFixedSize(width, edge)
                self._widths[spec.id] = width + SPACING + (SEPARATOR_WIDTH + SPACING if spec.separated else 0)
            self._more.setFixedSize(MORE_WIDTH, edge)
            for index in range(self._layout.count()):
                item = self._layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if isinstance(widget, QFrame):
                    widget.setFixedHeight(edge - 4)
            self._fold()
        finally:
            self._measuring = False

    def _cell_width(self, spec, width: int) -> int:
        """What the cell costs in the strip: its width, the gap, the separator."""
        cell = width + SPACING
        if spec.separated:
            cell += SEPARATOR_WIDTH + SPACING
        return cell

    def _fitting_count(self, cells: list[int], available: int) -> int:
        """How many cells fit at *available* px, «Ещё» reserving its own width.

        Mirrors :meth:`_fold`, so the mode the row picks and the buttons it then
        hides are decided by the same arithmetic.
        """
        used = MORE_WIDTH
        keep = 0
        for cell in cells:
            used += cell
            if used > available:
                break
            keep += 1
        return keep

    def needed_width(self) -> int:
        """What the row would need to paint every button at once (§4.1)."""
        return sum(self._widths.values()) + MORE_WIDTH + SPACING

    def hidden_ids(self) -> frozenset[str]:
        """The buttons currently folded into «Ещё» (what the 1024 px test reads)."""
        return self._hidden

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # The width decides the cells, not only which of them fit: a row that
        # was first laid out at 830 px stayed in the glyph-only mode after the
        # window grew to 1920 (measured compact there while 9 of 10 captions
        # would have fitted).  Re-measuring on every resize closes that.
        self.update_geometry()

    def _fold(self) -> None:
        """Keep what fits on the strip; the rest goes into the menu."""
        controls = [self.button(spec.id) for spec in self.specs()]
        if any(control is None for control in controls) or not controls:
            return
        available = self.width()
        if available <= 0:
            # Not laid out yet (the widget is still being assembled): the row
            # keeps every button, and the first real resize folds what is left.
            for control in controls:
                control.setVisible(True)
            self._more.setVisible(False)
            self._hidden = frozenset()
            return
        used = MORE_WIDTH
        keep = 0
        for spec in self.specs():
            control = self.button(spec.id)
            assert control is not None
            used += self._widths.get(spec.id, BUTTON_EDGE_MIN)
            if used > available:
                break
            keep += 1
        folded = frozenset(spec.id for index, spec in enumerate(self.specs()) if index >= keep)
        for spec in self.specs():
            control = self.button(spec.id)
            if control is not None:
                control.setVisible(spec.id not in folded)
        self._more.setVisible(bool(folded))
        self._hidden = folded
        self._update_more_caption()

    def _update_more_caption(self) -> None:
        """Name what «Ещё» hides: caption, count, tooltip and accessible name.

        The button used to be a bare «…»: nothing on the strip said whether one
        tool or six were behind it, and the menu had to be opened to find out.
        """
        hidden = [spec for spec in self.specs() if spec.id in self._hidden]
        if not hidden:
            self._more.setText(tr("toolbtn.more"))
            self._more.setToolTip("")
            return
        names = ", ".join(caption(spec, self._language) for spec in hidden)
        self._more.setText(f"{tr('toolbtn.more')} {len(hidden)}")
        self._more.setToolTip(f"{tr('toolbtn.more')}: {names}")
        self._more.setAccessibleName(f"{tr('toolbtn.more')} ({len(hidden)}): {names}")

    def _fill_menu(self) -> None:
        """Menu entries for the folded buttons, in the row's own order (§4.1)."""
        self._menu.clear()
        for spec in self.specs():
            if spec.id not in self._hidden:
                continue
            action = self._menu.addAction(caption(spec, self._language))
            action.setEnabled(not unavailable_reason(spec, self.state(), self._language))
            action.triggered.connect(lambda _checked=False, button_id=spec.id: self.action_requested.emit(button_id))
