"""Re-interpolate a widget's own stylesheet when the theme changes.

A widget that builds its stylesheet from
:func:`~echo_personal_tool.presentation.dark_theme.get_theme_tokens` bakes the
colours of the theme that was active at build time into a plain string.  The
application sheet follows a theme switch on its own — Qt re-parses it for every
widget — but a private sheet does not: after «Светлая» → «Графит» the widget
kept the light colours while everything around it went dark, which is how the
protocol card of the measurement panel ended up a white block inside a dark
panel (item 4 of the 2026-10-23 acceptance list).

Qt does tell the widget: setting a stylesheet on ``QApplication`` delivers
``QEvent::StyleChange`` (and ``PaletteChange``) to every widget.  Reacting to
that event is what the mixin below does, so a token-built sheet cannot drift
from the theme whichever path changed it — the preferences dialog, the welcome
page, or a palette flip of the desktop.

The widget has to implement ``_apply_style()``; the mixin calls it back.  Calls
are guarded because ``setStyleSheet`` itself provokes another ``StyleChange``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: The events a theme switch reaches the widgets with.
THEME_EVENTS: frozenset[QEvent.Type] = frozenset(
    {
        QEvent.Type.StyleChange,
        QEvent.Type.PaletteChange,
        QEvent.Type.ApplicationPaletteChange,
    }
)

#: Attribute the re-entrancy guard lives on.
_GUARD = "_token_restyle_busy"

#: Attribute holding the tokens the sheet was last interpolated from.
_APPLIED = "_token_restyle_applied"


class TokenRestyleMixin:
    """Re-runs ``_apply_style`` of a widget whenever the theme changes.

    Mix in *before* the widget class::

        class ProtocolCard(TokenRestyleMixin, QFrame):
            def _apply_style(self) -> None: ...
    """

    def changeEvent(self, event: Any) -> None:  # noqa: ANN401 - Qt event
        super().changeEvent(event)  # type: ignore[misc]
        if event is not None and event.type() in THEME_EVENTS:
            self.restyle_tokens()

    def restyle_tokens(self) -> None:
        """Re-interpolate the sheet from the tokens of the *current* theme.

        Idempotent and re-entrant: ``setStyleSheet`` sends another
        ``StyleChange`` (to this widget and to everything under it), so the
        call is guarded, and a widget whose sheet already carries the current
        tokens does nothing at all — a panel of fifty rows then costs one
        re-interpolation per row instead of one per event of the burst.
        """
        if getattr(self, _GUARD, False):
            return
        apply_style = getattr(self, "_apply_style", None)
        if apply_style is None:  # pragma: no cover - a mixin without its half
            return
        tokens = get_theme_tokens()
        if getattr(self, _APPLIED, None) == tokens:
            return
        setattr(self, _GUARD, True)
        try:
            apply_style()
        finally:
            setattr(self, _GUARD, False)
            setattr(self, _APPLIED, tokens)
