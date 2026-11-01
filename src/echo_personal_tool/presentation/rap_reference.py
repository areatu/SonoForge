"""The RAP hover card — the same S2 window the measurement rows show.

The protocol step «ДПП / RAP» is a physician input, not an automatic estimate.
Asking the user to remember the IVC categories while choosing 3 / 8 / 15 is
exactly the case the S2 reference card was built for: a 400 ms hover opens a
frameless card beside the anchor, with the norm, the gradations, the ASE 2025
source and «Открыть в справочнике».  This module hosts that gesture for any
widget (the RAP step tile of the right panel and the chips of the step bar).

The card itself is :class:`~presentation.reference_card.ReferenceCard`; only
the hover timing, the travel grace and the model binding live here.  One host
owns at most one card, parented to its own widget, so the panel's row cards and
the RAP card cannot reuse (and fight over) the same window.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.presentation.reference_card import (
    HOVER_DELAY_MS,
    RAP_PARAM_KEY,
    ReferenceCard,
    rap_card_model,
)

#: Grace while the pointer travels from the anchor into the card.
_HIDE_GRACE_MS = 250

# The model factory lives with ``card_for_row`` in ``reference_card`` (already
# reviewed for the i18n edge); re-export it here so RAP hosts keep one import.
__all__ = ["RAP_PARAM_KEY", "RapReferenceHover", "rap_card_model"]


class RapReferenceHover(QObject):
    """400 ms hover → RAP S2 card; leaving hides it after the travel grace.

    ``attach(widget)`` installs an event filter on one or more widgets (the
    step tile, every RAP chip).  The card is placed beside the widget's global
    rectangle, never over it, by ``ReferenceCard.popup_at``.
    """

    #: «Открыть в справочнике» of the card: the host opens S1 on ``ra.rap``.
    reference_requested = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._host = parent
        self._card: ReferenceCard | None = None
        self._anchors: list[QWidget] = []
        self._pending: QWidget | None = None
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(HOVER_DELAY_MS)
        self._show_timer.timeout.connect(self._show_pending)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_HIDE_GRACE_MS)
        self._hide_timer.timeout.connect(self._hide_if_idle)

    def attach(self, widget: QWidget) -> None:
        if widget is not None and widget not in self._anchors:
            self._anchors.append(widget)
            widget.installEventFilter(self)

    @property
    def card(self) -> ReferenceCard | None:
        return self._card

    # ── gestures ───────────────────────────────────────────────────

    # Qt's C++ virtuals are camelCase; renaming them drops the override.
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.Enter and obj in self._anchors:
            self._hide_timer.stop()
            self._pending = obj if isinstance(obj, QWidget) else None
            self._show_timer.start()
        elif kind == QEvent.Type.Leave and obj in self._anchors:
            self._show_timer.stop()
            self._pending = None
            self._hide_timer.start()
        elif kind == QEvent.Type.FocusIn and obj in self._anchors:
            self._hide_timer.stop()
            self._pending = obj if isinstance(obj, QWidget) else None
            self._show_pending()
        return super().eventFilter(obj, event)

    def _show_pending(self) -> None:
        anchor_widget = self._pending
        self._pending = None
        if anchor_widget is None:
            return
        model = rap_card_model()
        if not model.has_norm:
            # Honest answer: never show an empty «no norms» popup.
            return
        card = self._card
        if card is None:
            card = ReferenceCard(self._host)
            card.setObjectName("rapReferenceCard")
            card.reference_requested.connect(self.reference_requested.emit)
            self._card = card
        # A second RAP chip (or a measurement row) must never leave the card of
        # the previous anchor floating over the new one.
        for top in QApplication.topLevelWidgets():
            if isinstance(top, ReferenceCard) and top is not card and top.isVisible():
                top.hide()
        card.set_model(model)
        anchor = QRect(anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()), anchor_widget.size())
        card.popup_at(anchor.topLeft(), anchor)
        card.show()
        self._hide_timer.stop()

    def _hide_if_idle(self) -> None:
        card = self._card
        if card is None or not card.isVisible():
            return
        if card.underMouse() or any(anchor.underMouse() for anchor in self._anchors):
            self._hide_timer.start()
            return
        card.hide()

    def hide_now(self) -> None:
        self._show_timer.stop()
        self._hide_timer.stop()
        self._pending = None
        if self._card is not None:
            self._card.hide()
