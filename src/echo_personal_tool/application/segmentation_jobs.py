"""Publication ownership for one pending auto-segmentation (#552).

GUI-thread confined. Revoking a ticket does not cancel native inference, and
worker lifetime stays with the controller. A revoked current worker remains
busy until terminal delivery unless the existing clip-switch path resets it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from echo_personal_tool.application.analysis_jobs import AnalysisBasis, analysis_basis
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState


@dataclass(frozen=True)
class SegmentationBasis(AnalysisBasis):
    frame_index: int
    loaded_frame_index: int | None
    is_playing: bool
    contour_flags: tuple[object, ...]


@dataclass(frozen=True)
class SegmentationTicket:
    request_id: int
    basis: SegmentationBasis


def segmentation_basis(
    state: ViewerState,
    instance: InstanceMetadata | None,
    *,
    document_id: str,
    generation: int,
    loaded_frame_index: int | None,
) -> SegmentationBasis:
    base = analysis_basis(state, instance, document_id=document_id, generation=generation)
    return SegmentationBasis(
        base.document_id,
        base.study_generation,
        base.instance_uid,
        base.source_path,
        base.calibration,
        base.frame_time_ms,
        base.contours,
        state.current_frame_index,
        loaded_frame_index,
        state.is_playing,
        tuple(
            (c.source, c.unassisted, c.measurement_label, c.refine_step, c.refine_locked_indices)
            for c in state.contours
        ),
    )


class SegmentationJobs:
    """Single current owner: latest request wins, success/error consume once."""

    def __init__(self) -> None:
        self._sequence = 0
        self._current: SegmentationTicket | None = None
        self._valid = False

    def begin(self, basis: SegmentationBasis) -> SegmentationTicket:
        self._sequence += 1
        self._current = SegmentationTicket(self._sequence, basis)
        self._valid = True
        return self._current

    def invalidate(self) -> None:
        self._valid = False

    def observe_state(
        self,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: Callable[[], str],
        generation: int,
        loaded_frame_index: int | None,
    ) -> None:
        if self._current is not None and self._valid:
            basis = segmentation_basis(
                state, instance, document_id=document_id(), generation=generation, loaded_frame_index=loaded_frame_index
            )
            if self._current.basis != basis:
                self.invalidate()

    def finish(self, ticket: SegmentationTicket, basis: SegmentationBasis) -> bool | None:
        """True: publish, False: current but stale, None: superseded/already consumed."""
        if self._current != ticket:
            return None
        allowed = self._valid and ticket.basis == basis and bool(basis.instance_uid)
        self._current = None
        self._valid = False
        return allowed
