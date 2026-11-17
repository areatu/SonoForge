"""Publication ownership for the current STE job (#552).

GUI-thread confined. This owner holds immutable identities, never pixels,
workers, calibration state or measurement documents. Worker lifetime remains
with AppController; invalidation revokes publication, not native execution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, TypeVar

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState

_Payload = TypeVar("_Payload")


@dataclass(frozen=True)
class AnalysisBasis:
    """Document/media epoch plus the exact clinical inputs used by a job."""

    document_id: str
    study_generation: int
    instance_uid: str
    source_path: str
    calibration: tuple[object, ...]
    frame_time_ms: float | None
    contours: tuple[object, ...]


@dataclass(frozen=True)
class AnalysisTicket:
    request_id: int
    basis: AnalysisBasis


class AnalysisJobs:
    """One publishable STE request; a newer request supersedes the old one.

    Request IDs never reset, so A→B→A and repeated jobs with identical inputs
    cannot revive an old callback. Both success and error consume a ticket.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._active: AnalysisTicket | None = None

    def begin(self, basis: AnalysisBasis) -> AnalysisTicket:
        self._sequence += 1
        self._active = AnalysisTicket(self._sequence, basis)
        return self._active

    def invalidate(self) -> None:
        self._active = None

    def observe(self, basis: AnalysisBasis) -> None:
        """Revoke immediately on an input change, even if later undone (ABA)."""
        if self._active is not None and self._active.basis != basis:
            self.invalidate()

    def observe_state(
        self, state: ViewerState, instance: InstanceMetadata | None, document_id: Callable[[], str], generation: int
    ) -> None:
        # Do not scan the document/contours on playback ticks without a pending job.
        if self._active is not None:
            self.observe(analysis_basis(state, instance, document_id=document_id(), generation=generation))

    def finish(self, ticket: AnalysisTicket, basis: AnalysisBasis) -> bool:
        """Consume exactly once, only for the still-current document and inputs."""
        if self._active != ticket:
            return False
        self._active = None
        return ticket.basis == basis

    def connect(
        self,
        signals: Any,
        current_basis: Callable[[], AnalysisBasis],
        receive: Callable[[Any], None],
        error: Callable[[str], None],
        connection: Any,
    ) -> None:
        """Bind both terminal signals to the same publication ticket.

        Signal objects and connection type are supplied by the Qt adapter;
        this module imports neither Qt nor the concrete worker.
        """
        deliver = partial(self.deliver, self.begin(current_basis()), current_basis)
        signals.finished.connect(partial(deliver, receive), connection)
        signals.error.connect(partial(deliver, error), connection)

    def deliver(
        self,
        ticket: AnalysisTicket,
        current_basis: Callable[[], AnalysisBasis],
        receive: Callable[[_Payload], None],
        payload: _Payload,
    ) -> None:
        """Admit a queued terminal callback without owning worker/UI lifetime."""
        basis = current_basis()
        if self.finish(ticket, basis) and basis.instance_uid:
            receive(payload)


def analysis_basis(
    state: ViewerState, instance: InstanceMetadata | None, *, document_id: str, generation: int
) -> AnalysisBasis:
    """Copy clinical inputs; do not keep mutable contour point lists alive."""
    calibration = state.effective_calibration
    return AnalysisBasis(
        document_id=document_id,
        study_generation=generation,
        instance_uid=instance.sop_instance_uid if instance else "",
        source_path=str(instance.path) if instance and instance.path else "",
        calibration=(state.effective_pixel_spacing, calibration.signature() if calibration else None),
        frame_time_ms=state.frame_time_ms,
        contours=tuple(
            (
                c.measurement_id,
                c.revision,
                c.sop_instance_uid,
                c.frame_index,
                c.phase,
                c.view,
                c.chamber,
                tuple(c.points),
                c.mitral_annulus,
                c.apex_landmark,
            )
            for c in state.contours
        ),
    )


def tracking_failure(emit: Callable[[str], None], _code: str) -> None:
    """Render only a stable localized message, never the worker error text."""
    emit(tr("app.speckle_error"))
