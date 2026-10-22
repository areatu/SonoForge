"""ContourEditingController — QH-3 slice for contour handles/selection.

Spec §7.1: owns handles/selection/draft edit; commands accepted change/delete.
It does NOT keep a separate inconsistent copy of study measurements — edits
are applied to the Store via explicit commands and the viewer re-renders from
`ViewerState.contours`.

For the pilot this is a thin adapter around the existing viewer contour
methods so the QH-0 harness stays green; subsequent slices move the full
RBF/magnetic-snap/freehand logic here in separate PRs (§7.2 steps 3–4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.presentation.viewer.commands import CommandResult, accepted, rejected
from echo_personal_tool.presentation.viewer.context import ViewerContext


class ContourEditingController(QObject):
    """Selection and draft editing for contours on the current frame."""

    contour_committed = Signal(object)  # Contour
    contour_deleted = Signal(object)  # contour_id / index
    selection_changed = Signal(object)  # index or None

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        # Narrow dependencies (not ViewerWidget):
        contour_provider: Callable[[], list[Any]] | None = None,
        selection_writer: Callable[[int | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._contours: list[Any] = []
        self._selected_index: int | None = None
        self._draft_points: list[tuple[float, float]] = []
        self._draft_active = False
        self._context: ViewerContext | None = None
        self._contour_provider = contour_provider
        self._selection_writer = selection_writer

    # -- context -------------------------------------------------------------

    @property
    def context(self) -> ViewerContext | None:
        return self._context

    def set_context(self, ctx: ViewerContext) -> None:
        if self._context is not None and self._context.generation != ctx.generation:
            self.cancel_draft(reason="generation_bump")
            self._selected_index = None
        self._context = ctx

    def set_contours(self, contours: list[Any]) -> None:
        self._contours = list(contours)
        if self._selected_index is not None and self._selected_index >= len(self._contours):
            self._selected_index = None

    # -- selection -----------------------------------------------------------

    def select(self, index: int | None) -> CommandResult:
        if index is not None and (index < 0 or index >= len(self._contours)):
            return rejected(f"contour_index_out_of_range:{index}")
        self._selected_index = index
        if self._selection_writer is not None:
            self._selection_writer(index)
        self.selection_changed.emit(index)
        return accepted(payload=index)

    @property
    def selected_index(self) -> int | None:
        return self._selected_index

    # -- draft ---------------------------------------------------------------

    def begin_draft(self, *, chamber: str, view: str = "A4C", phase: str = "ED") -> CommandResult:
        if self._draft_active:
            return rejected("draft_already_active")
        self._draft_active = True
        self._draft_points.clear()
        return accepted(payload={"chamber": chamber, "view": view, "phase": phase})

    def add_draft_point(self, pt: tuple[float, float]) -> CommandResult:
        if not self._draft_active:
            return rejected("no_draft")
        self._draft_points.append(pt)
        return accepted(payload=pt)

    def commit_draft(self) -> CommandResult:
        if not self._draft_active:
            return rejected("no_draft")
        if len(self._draft_points) < 3:
            return rejected("not_enough_points")
        points = list(self._draft_points)
        self._draft_active = False
        self._draft_points.clear()
        # Actual Contour construction stays in domain; controller emits result
        self.contour_committed.emit(points)
        return accepted(payload=points)

    def cancel_draft(self, *, reason: str = "user_cancel") -> CommandResult:
        was = self._draft_active or bool(self._draft_points)
        self._draft_active = False
        self._draft_points.clear()
        if was:
            self.selection_changed.emit(None)
        return accepted(reason=reason)

    # -- delete --------------------------------------------------------------

    def delete_selected(self) -> CommandResult:
        if self._selected_index is None:
            return rejected("no_selection")
        idx = self._selected_index
        if idx >= len(self._contours):
            return rejected("index_out_of_range")
        self._selected_index = None
        self.contour_deleted.emit(idx)
        return accepted(payload=idx)

    # -- lifecycle -----------------------------------------------------------

    def dispose(self) -> None:
        import warnings

        self._contours.clear()
        self._draft_points.clear()
        self._draft_active = False
        self._selected_index = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for sig in (self.contour_committed, self.contour_deleted, self.selection_changed):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass

    # -- facade for legacy ViewerWidget forwarding ---------------------------

    @property
    def drag_active(self) -> bool:
        # Kept for ViewerWidget compatibility check (_contour_editing_blocked)
        return self._draft_active
