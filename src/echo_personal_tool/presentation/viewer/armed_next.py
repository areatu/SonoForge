"""The armed «next click starts the paired tool» chain (extracted state machine).

Paired tools (diastole/systole calipers, ED→ES contours, ТЗ п. 2) arm the
second half after the first one: the operator scrolls to the next frame and
the first click there already starts the paired step — no button press in
between.  Item 13 of the 2026-10-23 list added the frame gate: a click on
the *arming* frame belongs to the contour that was just drawn, so the chain
must not start until the operator is on another frame (a still image, where
there is no other frame, never blocks; another clip releases the gate).

This module owns that state and its transitions.  It is Qt-free and
viewer-free on purpose: the viewer calls :meth:`ArmedNextChain.arm` /
:meth:`clear` with the current ``(frame, instance uid)`` and consults
:meth:`waits_for_another_frame` before dispatching a click to the tool
start.  The pending step is stored in the historical tuple shape
(``("caliper", label)`` / ``("contour", chamber, view, phase, model)``) so
existing tests and the status line keep reading it unchanged.
"""

from __future__ import annotations

from typing import Final

CONTOUR_CHAIN_KIND: Final = "contour"
CALIPER_CHAIN_KIND: Final = "caliper"
NO_ORIGIN: Final = (None, None)


class ArmedNextChain:
    """The armed second half of a paired tool and where it was armed.

    Invariants (pinned by ``tests/unit/test_paired_tools.py``):

    * an empty chain never gates anything (``waits_for_another_frame`` is
      ``False`` and ``start`` reports "nothing armed");
    * the gate applies only while the operator stands on the arming frame of
      the same clip; scrolling the cine keeps the chain armed;
    * a missing arming frame (a still image) never gates;
    * another clip (different SOP instance UID) releases the gate and also
      drops the chain in the viewer (the viewer does that via :meth:`clear`).
    """

    __slots__ = ("_origin", "_pending")

    def __init__(self) -> None:
        self._pending: tuple | None = None
        self._origin: tuple[int | None, str | None] = NO_ORIGIN

    def arm(self, pending: tuple, *, current_frame: int | None, current_uid: str | None) -> None:
        """Arm *pending* (the historical tuple shape) at the current position."""
        self._pending = pending
        self._origin = (current_frame, current_uid)

    def clear(self) -> None:
        """Forget the chained step (Esc, tool switch, another clip)."""
        self._pending = None
        self._origin = NO_ORIGIN

    def pending(self) -> tuple | None:
        """What the next click would start, for tests and the status line."""
        return self._pending

    def kind(self) -> str | None:
        """The chain kind (``"caliper"`` / ``"contour"``), ``None`` when idle."""
        return self._pending[0] if self._pending is not None else None

    def waits_for_another_frame(self, *, current_frame: int | None, current_uid: str | None) -> bool:
        """Whether the chain is armed but the operator is still on that frame.

        ``True`` while the armed step must not start: the click belongs to
        the contour that was just drawn.  A missing frame index (a still
        image, so no systole to scroll to) never blocks: there is no other
        frame to wait for, and the click keeps its old meaning.
        """
        if self._pending is None:
            return False
        armed_frame, armed_uid = self._origin
        if armed_frame is None or (armed_uid is not None and current_uid != armed_uid):
            return False
        return current_frame == armed_frame

    def hint_phase(self) -> str:
        """The phase name for the «scroll away» hint (``"ES"`` for contours)."""
        if self._pending is None:
            return ""
        return "ES" if self._pending[0] == CONTOUR_CHAIN_KIND else ""
