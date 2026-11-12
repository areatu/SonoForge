"""Contour drawing/storage owner extracted from :class:`ViewerWidget` (A5).

``ViewerContours`` owns the *state* of contours:

* the stored list and the list currently rendered for the frame;
* the active drawing mode/stage, phase/view/chamber and landmark steps;
* freehand points and the click-tracking used by the finish gesture.

It deliberately does **not** create :class:`Contour` objects, calculate areas or
volumes, emit signals, render pyqtgraph items or persist anything.  Those stay
with the viewer, which is the clinical owner.  The class is Qt-free.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from echo_personal_tool.domain.calculations.planimeter import GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER
from echo_personal_tool.domain.models.contour import Contour

ContourModeKind = Literal["manual", "model", "closed"]
ContourStage = Literal["ma_septal", "ma_lateral", "arc", "apex", "polygon", "trace"]


class ViewerContours:
    """One owner for contour drawing and storage state."""

    def __init__(self) -> None:
        self.stored: list[Contour] = []
        self.visible: list[Contour] = []

        self.active_arc_points: list[tuple[float, float]] = []
        self.freehand_recording = False
        self.freehand_points: list[tuple[float, float]] = []
        self.freehand_open_arc = False

        self.mode_active = False
        self.mode_kind: ContourModeKind | None = None
        self.stage: ContourStage | None = None
        self.active_phase: str | None = None
        self.active_view = "A4C"
        self.active_chamber = "LV"
        self.active_mitral_septal: tuple[float, float] | None = None
        self.active_mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = None
        self.active_apex_landmark: tuple[float, float] | None = None

        self.last_click_ms: float | None = None
        self.last_click_screen: tuple[float, float] | None = None
        self.last_point_screen: tuple[float, float] | None = None
        self.first_point_screen: tuple[float, float] | None = None

        self.area_tool_mode = "click"
        self.lv_input = "landmarks"
        self.atrial_input = "landmarks"

    # ── storage ─────────────────────────────────────────────────────

    def set_stored(self, contours: list[Contour]) -> None:
        self.stored = list(contours)

    def find_index(self, contour: Contour) -> int | None:
        """Index of the stored contour this one replaces, if any."""
        instance_uid = contour.sop_instance_uid
        is_planimeter = contour.chamber.upper() in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}
        for index, existing in enumerate(self.stored):
            if (
                existing.phase.casefold() == contour.phase.casefold()
                and existing.view.casefold() == contour.view.casefold()
                and existing.chamber.casefold() == contour.chamber.casefold()
                and existing.frame_index == contour.frame_index
                and existing.sop_instance_uid == instance_uid
            ):
                if is_planimeter and existing.measurement_label != contour.measurement_label:
                    continue
                return index
        return None

    def upsert(self, contour: Contour) -> None:
        index = self.find_index(contour)
        if index is None:
            self.stored.append(contour)
        else:
            self.stored[index] = contour

    # ── active drawing ──────────────────────────────────────────────

    def clear_active(self) -> None:
        """Drop every piece of the running contour without touching storage."""
        self.active_mitral_septal = None
        self.active_mitral_annulus = None
        self.active_apex_landmark = None
        self.active_arc_points = []
        self.freehand_recording = False
        self.freehand_open_arc = False
        self.freehand_points = []
        self.active_phase = None
        self.stage = None
        self.mode_kind = None
        self.mode_active = False
        self.reset_clicks()

    # ── click tracking ──────────────────────────────────────────────

    def reset_clicks(self) -> None:
        self.last_click_ms = None
        self.last_click_screen = None
        self.last_point_screen = None
        self.first_point_screen = None

    def remember_click(self, screen_point: tuple[float, float] | None) -> None:
        self.last_click_ms = time.monotonic() * 1000.0
        self.last_click_screen = screen_point

    def forget_point_screens(self) -> None:
        self.first_point_screen = None
        self.last_point_screen = None


class ContourStateAttribute:
    """Compatibility descriptor for the reviewed ``ViewerContract``/tests.

    The state lives on :class:`ViewerContours`; the viewer no longer stores a
    second copy.  The descriptor keeps the frozen private names
    (``viewer._stored_contours`` …) readable and writable for the declared test
    seam without adding per-field property methods to the widget.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __get__(self, instance: object, owner: type[object] | None = None) -> Any:
        if instance is None:
            return self
        state = getattr(instance, "contour_state")
        return getattr(state, self._name)

    def __set__(self, instance: object, value: Any) -> None:
        state = getattr(instance, "contour_state")
        setattr(state, self._name, value)
