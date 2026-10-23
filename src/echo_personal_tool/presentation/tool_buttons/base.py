"""What the tool row and the tool rail share (UI-2 PR-3).

Both views are the same list of buttons (:data:`buttons.TOOL_BUTTONS`) in the
same order with the same availability, and both answer with one signal —
``action_requested(button_id)``.  Only the geometry differs, so that part lives
in :mod:`~echo_personal_tool.presentation.tool_buttons.row` and
:mod:`~echo_personal_tool.presentation.tool_buttons.rail`.

The rules this file enforces (spec ``docs/superpowers/specs/2026-10-16-ui-
redesign-spec-plan-ru.md``):

* §4.1 — the row is a 42 px strip of icons and shows a caption only next to the
  active button; the rail is 70 px wide and shows icon + caption + the key
  letter;
* D-08 — a tool unavailable in the current context is dimmed and its tooltip
  says why; the button is neither removed nor silently ignored;
* §5.3 — the stylesheet is assembled from theme tokens, so a theme switch only
  needs :meth:`ToolButtonsBase.reload_icons` + :meth:`apply_theme`, and the
  ratchet keeps no colour literal here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton, QWidget

from echo_personal_tool.infrastructure.i18n import get_language
from echo_personal_tool.presentation.tool_buttons import buttons
from echo_personal_tool.presentation.tool_buttons.buttons import ToolButtonSpec, ToolButtonState

# The nominal sizes live in the Qt-free :mod:`…tool_buttons.metrics`; they are
# re-exported here because the row, the rail and their tests have always read
# them from this module.
from echo_personal_tool.presentation.tool_buttons.metrics import (  # noqa: F401
    BUTTON_EDGE_MIN,
    ICON_EDGE_RAIL,
    ICON_EDGE_ROW,
    RAIL_WIDTH_MIN,
    ROW_HEIGHT_MIN,
    initial_for_caption,
)


def load_tool_icon(name: str) -> QIcon:
    """A bundled glyph tinted with ``text.1`` of the active theme (D-07).

    One loader for the whole shell (:mod:`presentation.icon_loader`): the row,
    the rail, the system bar and the caption buttons cannot drift apart in icon
    size, tint or dependency on Qt's ``qsvg`` plugin.  Empty when there is no
    glyph — a caption-only button is a design case of these views, not a defect.
    """
    from echo_personal_tool.presentation.icon_loader import load_svg_icon

    return load_svg_icon(name)


class ToolButton(QToolButton):
    """One button of the row or the rail."""

    def __init__(self, spec: ToolButtonSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.setObjectName("toolButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCheckable(spec.checkable)

    @property
    def spec(self) -> ToolButtonSpec:
        return self._spec


class ToolButtonsBase(QWidget):
    """Shared assembly of the row and the rail; subclasses only place buttons."""

    #: The one signal of both views: the id of the pressed button (D-09 TP).
    action_requested = Signal(str)

    #: QSS selector of the widget; also its name in the layout.
    OBJECT_NAME: ClassVar[str] = "toolButtons"

    #: Captions of the rail sit under the icon, in the row beside it (§4.1).
    VERTICAL_CAPTIONS: ClassVar[bool] = False

    #: ``QToolButton[view=…]`` property the stylesheet selects on.
    VIEW: ClassVar[str] = "row"

    #: Logical edge of the glyph in this view (see :data:`ICON_EDGE_ROW`).
    ICON_EDGE: ClassVar[int] = ICON_EDGE_ROW

    #: Which side of the strip the hairline closes (the rail: right, row: below).
    BORDER_PROPERTY: ClassVar[str] = "border-bottom"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self._specs: tuple[ToolButtonSpec, ...] = buttons.TOOL_BUTTONS
        self._controls: dict[str, ToolButton] = {}
        self._state = ToolButtonState()
        self._language = get_language()
        self._labels_mode = "icons_labels"
        self._active: str | None = None
        self._show_key_hints = False

    def build(self) -> None:
        """Assemble the buttons; the subclass calls it once its own parts exist."""
        self._rebuild()
        self.apply_theme()

    # ── assembly ────────────────────────────────────────────────────

    def set_specs(self, specs: Sequence[ToolButtonSpec]) -> None:
        """Replace the buttons (the views never reorder them on their own)."""
        self._specs = tuple(specs)
        self._rebuild()

    def specs(self) -> tuple[ToolButtonSpec, ...]:
        return self._specs

    def button(self, button_id: str) -> ToolButton | None:
        """The control of one button id (tests, the screenshot gate)."""
        return self._controls.get(button_id)

    def make_button(self, spec: ToolButtonSpec) -> ToolButton:
        """Build one control; subclasses add the properties they style on."""
        control = ToolButton(spec, self)
        control.setProperty("view", self.VIEW)
        control.clicked.connect(lambda _checked=False, button_id=spec.id: self.action_requested.emit(button_id))
        return control

    def _rebuild(self) -> None:
        for control in self._controls.values():
            control.deleteLater()
        self._controls = {spec.id: self.make_button(spec) for spec in self._specs}
        self.arrange()
        self.refresh()

    def arrange(self) -> None:
        """Place the controls; overridden by both views."""
        raise NotImplementedError

    # ── state ───────────────────────────────────────────────────────

    def set_state(self, state: ToolButtonState) -> None:
        """Clip / Multiview / context facts, then a repaint (D-08)."""
        self._state = state
        self.refresh()

    def state(self) -> ToolButtonState:
        return self._state

    def set_language(self, language: str) -> None:
        self._language = (language or "ru").strip().lower()[:2]
        self.refresh()

    def set_labels_mode(self, mode: str) -> None:
        """``icons_labels`` / ``icons`` of the layout document (§4.2)."""
        self._labels_mode = mode if mode in ("icons_labels", "icons") else "icons_labels"
        self.refresh()

    def set_key_hints_visible(self, visible: bool) -> None:
        """Temporarily expose the real activation keys while Alt/Option is held."""
        visible = bool(visible)
        if visible != self._show_key_hints:
            self._show_key_hints = visible
            self.refresh()

    def set_active(self, button_id: str | None) -> None:
        """Highlight the armed tool; only it keeps a caption in the row.

        Until ``ToolInteractionController`` (QH-3) owns the tool modes the window
        has nothing to report here, so the value stays ``None`` and every button
        behaves as a momentary one — which is exactly how the panel's buttons
        have always worked.
        """
        self._active = button_id
        self.refresh()

    def refresh(self) -> None:
        """Re-read captions, availability and the active tool, then repaint."""
        for spec in self._specs:
            control = self._controls.get(spec.id)
            if control is None:
                continue
            reason = buttons.unavailable_reason(spec, self._state, self._language)
            text = buttons.caption(spec, self._language)
            hint = buttons.key_hint(spec) if self._show_key_hints else ""
            control.setText(f"{text} · {hint}" if hint else text)
            control.setToolTip(_join(buttons.tooltip(spec, self._language), reason))
            icon = load_tool_icon(spec.icon)
            control.setIcon(icon)
            control.setEnabled(not reason)
            control.setChecked(spec.id == self._active)
            # UA-12: an icon-only control still has to name itself.
            control.setAccessibleName(buttons.caption(spec, self._language))
            # An icon-only button without a glyph used to fall back to its
            # caption, which the fixed 38 px cell then elided to «…»: the row
            # showed four identical «…» tiles (N-07).  The first letter of the
            # caption is a legible fallback; the tooltip keeps the whole name.
            if icon.isNull() and not self.shows_captions(spec):
                control.setText(self._initial(text))
                control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            else:
                control.setToolButtonStyle(self.button_style(spec))
        self.update_geometry()

    def button_style(self, spec: ToolButtonSpec) -> Qt.ToolButtonStyle:
        """Which of the three QToolButton styles this button draws right now."""
        if self._show_key_hints:
            return Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        if not self.shows_captions(spec):
            return Qt.ToolButtonStyle.ToolButtonIconOnly
        return (
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            if self.VERTICAL_CAPTIONS
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

    @staticmethod
    def _initial(text: str) -> str:
        """First visible character of a caption, for an icon-less button."""
        return initial_for_caption(text)

    def shows_captions(self, spec: ToolButtonSpec) -> bool:
        """The row captions the active button only; the rail captions all (§4.1)."""
        if self._labels_mode == "icons":
            return False
        return self.VERTICAL_CAPTIONS or spec.id == self._active

    # ── geometry and painting ───────────────────────────────────────

    def captions_for_metrics(self) -> tuple[str, ...]:
        """Every string the widget paints — what its size is measured from."""
        texts = [buttons.caption(spec, self._language) for spec in self._specs]
        texts += [buttons.key_hint(spec) for spec in self._specs]
        return tuple(text for text in texts if text)

    def update_geometry(self) -> None:
        """The subclass fixes its own dimension from what it paints."""
        raise NotImplementedError

    def update_font_metrics(self) -> None:
        """Re-measure after the UI font changed (Э4: sizes come from painting)."""
        self.refresh()

    def reload_text(self) -> None:
        """Re-read the locale (UI-1 PR-2 hands this to every chrome widget)."""
        self.refresh()

    def reload_icons(self) -> None:
        """Re-tint the glyphs after a theme switch (UA-14: reload ≠ restart)."""
        for spec in self._specs:
            control = self._controls.get(spec.id)
            if control is not None:
                control.setIcon(load_tool_icon(spec.icon))
        self.apply_theme()

    def apply_theme(self) -> None:
        """Tint the strip from the active theme (UI-0, D-07).

        A palette, not a local stylesheet: the shell audit of §5.3 forbids a widget
        of the chrome from carrying interpolated colours of its own, while the
        background, the text and the disabled glyph are exactly what a palette role
        is for.  Hover and the pressed look come from the style.
        """
        from PySide6.QtGui import QColor, QPalette

        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        palette = self.palette()
        for role, colour in (
            (QPalette.ColorRole.Window, tokens["surface.1"]),
            (QPalette.ColorRole.Base, tokens["surface.1"]),
            (QPalette.ColorRole.Button, tokens["surface.1"]),
            (QPalette.ColorRole.WindowText, tokens["text.1"]),
            (QPalette.ColorRole.Text, tokens["text.1"]),
            (QPalette.ColorRole.ButtonText, tokens["text.1"]),
        ):
            palette.setColor(role, QColor(colour))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["accent.selected"]))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(tokens["text.disabled"]))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        for control in self._controls.values():
            control.setPalette(palette)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        """A language change re-reads the captions (UA-16, UI-1 PR-2)."""
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.LanguageChange:
            self.refresh()
            self.apply_theme()
        super().changeEvent(event)


def _join(text: str, reason: str) -> str:
    """Tooltip + the reason the button is dimmed (D-08: the reason is shown)."""
    return f"{text} — {reason}" if reason else text
