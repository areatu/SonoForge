"""Publication ownership for temporal-fusion runs and LA manual assist (#552).

GUI-thread confined, Qt-free. One monotonic ticket per fusion run and per
LA-assist request; a newer request supersedes the older one, so a late worker
callback from a superseded run can neither contaminate the current run's
intermediate masks/contours nor publish into a switched study. Revoking a
ticket does not cancel native inference, and worker lifetime stays with the
controller — exactly the segmentation-owner contract of #609 extended to the
two paths it explicitly left unprotected.

The basis snapshots the document and media epoch (document ID, study
generation, SOP/path, calibration signature/revision, frame time, contour
identities/geometry) plus the immutable parts of the run: fusion window,
anchor frame and original mask shape. Frame navigation does not revoke an
unchanged fusion run; a calibration, contour or document change does. The
LA-assist basis additionally pins the frame the user drew on, because the
delivered contour is a proposal for the shown frame.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.application.analysis_jobs import AnalysisBasis, analysis_basis
from echo_personal_tool.domain.models import Contour, TemporalFusionConfig, TemporalFusionResult
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.lv_temporal_fusion import temporal_fuse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FusionBasis(AnalysisBasis):
    """Document/media epoch plus the immutable geometry of one fusion run."""

    anchor_frame: int
    window: tuple[int, ...]
    original_shape: tuple[int, int]


@dataclass(frozen=True)
class FusionTicket:
    request_id: int
    basis: FusionBasis


def fusion_basis(
    state: ViewerState,
    instance: InstanceMetadata | None,
    *,
    document_id: str,
    generation: int,
    anchor_frame: int,
    window: tuple[int, ...],
    original_shape: tuple[int, int],
) -> FusionBasis:
    """Snapshot the clinical context of a fusion run; copies, never live state."""
    base = analysis_basis(state, instance, document_id=document_id, generation=generation)
    return FusionBasis(
        base.document_id,
        base.study_generation,
        base.instance_uid,
        base.source_path,
        base.calibration,
        base.frame_time_ms,
        base.contours,
        anchor_frame,
        window,
        original_shape,
    )


class FusionJobs:
    """Single current fusion run: latest request wins, publication consumes once.

    Ticket copies of the run geometry (``_rebuild``) let observers and delivery
    re-check the *fresh* document/calibration/contour state against the basis the
    run began with, while anchor/window/shape stay immutable.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._current: FusionTicket | None = None
        self._valid = False

    def begin(self, basis: FusionBasis) -> FusionTicket:
        self._sequence += 1
        self._current = FusionTicket(self._sequence, basis)
        self._valid = True
        return self._current

    def invalidate(self) -> None:
        self._valid = False

    def owns(self, ticket: FusionTicket) -> bool:
        """True while *ticket* is the current run and has not been revoked.

        Neighbor frame-load and ONNX callbacks consult this before starting the
        next stage, so a superseded run cannot queue work or store masks.
        """
        return self._current == ticket and self._valid

    def is_active(self) -> bool:
        """True while a run holds the ledger (used to detect revocation edges)."""
        return self._current is not None and self._valid

    def observe_state(
        self,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: Callable[[], str],
        generation: int,
    ) -> None:
        """Revoke on an input change even if later undone (ABA); cheap when idle."""
        if self._current is None or not self._valid:
            return
        if self._current.basis != self._rebuild(self._current, state, instance, document_id(), generation):
            self.invalidate()

    def _rebuild(
        self,
        ticket: FusionTicket,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: str,
        generation: int,
    ) -> FusionBasis:
        base = analysis_basis(state, instance, document_id=document_id, generation=generation)
        run = ticket.basis
        return FusionBasis(
            base.document_id,
            base.study_generation,
            base.instance_uid,
            base.source_path,
            base.calibration,
            base.frame_time_ms,
            base.contours,
            run.anchor_frame,
            run.window,
            run.original_shape,
        )

    def finish(
        self,
        ticket: FusionTicket,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: Callable[[], str],
        generation: int,
    ) -> bool | None:
        """True: publish; False: current run but inputs changed; None: superseded/consumed."""
        if self._current != ticket:
            return None
        basis = self._rebuild(ticket, state, instance, document_id(), generation)
        allowed = self._valid and ticket.basis == basis and bool(basis.instance_uid)
        self._current = None
        self._valid = False
        return allowed


@dataclass(frozen=True)
class AssistBasis(AnalysisBasis):
    """Document/media epoch plus the frame context of one LA-assist request."""

    frame_index: int
    current_frame_index: int
    loaded_frame_index: int | None


@dataclass(frozen=True)
class AssistTicket:
    request_id: int
    basis: AssistBasis


def assist_basis(
    state: ViewerState,
    instance: InstanceMetadata | None,
    *,
    document_id: str,
    generation: int,
    frame_index: int,
    loaded_frame_index: int | None,
) -> AssistBasis:
    """Snapshot the clinical context of an assist request (the shown frame included)."""
    base = analysis_basis(state, instance, document_id=document_id, generation=generation)
    return AssistBasis(
        base.document_id,
        base.study_generation,
        base.instance_uid,
        base.source_path,
        base.calibration,
        base.frame_time_ms,
        base.contours,
        frame_index,
        state.current_frame_index,
        loaded_frame_index,
    )


class AssistJobs:
    """Single current LA-assist request; latest request wins, delivery consumes once."""

    def __init__(self) -> None:
        self._sequence = 0
        self._current: AssistTicket | None = None
        self._valid = False

    def begin(self, basis: AssistBasis) -> AssistTicket:
        self._sequence += 1
        self._current = AssistTicket(self._sequence, basis)
        self._valid = True
        return self._current

    def invalidate(self) -> None:
        self._valid = False

    def is_active(self) -> bool:
        """True while a request holds the ledger (used to detect revocation edges)."""
        return self._current is not None and self._valid

    def observe_state(
        self,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: Callable[[], str],
        generation: int,
        loaded_frame_index: int | None,
    ) -> None:
        """Revoke on an input change even if later undone (ABA); cheap when idle."""
        if self._current is None or not self._valid:
            return
        if self._current.basis != self._rebuild(
            self._current, state, instance, document_id(), generation, loaded_frame_index
        ):
            self.invalidate()

    def _rebuild(
        self,
        ticket: AssistTicket,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: str,
        generation: int,
        loaded_frame_index: int | None,
    ) -> AssistBasis:
        base = analysis_basis(state, instance, document_id=document_id, generation=generation)
        request = ticket.basis
        return AssistBasis(
            base.document_id,
            base.study_generation,
            base.instance_uid,
            base.source_path,
            base.calibration,
            base.frame_time_ms,
            base.contours,
            request.frame_index,
            state.current_frame_index,
            loaded_frame_index,
        )

    def finish(
        self,
        ticket: AssistTicket,
        state: ViewerState,
        instance: InstanceMetadata | None,
        document_id: Callable[[], str],
        generation: int,
        loaded_frame_index: int | None,
    ) -> bool | None:
        """True: emit the proposal; False: current request but context changed; None: superseded."""
        if self._current != ticket:
            return None
        basis = self._rebuild(ticket, state, instance, document_id(), generation, loaded_frame_index)
        allowed = self._valid and ticket.basis == basis and bool(basis.instance_uid)
        self._current = None
        self._valid = False
        return allowed


def finalize_fused_contour(
    *,
    center_mask: np.ndarray,
    center_contour: Contour,
    neighbor_masks: dict[int, np.ndarray],
    neighbor_contours: dict[int, Contour],
    anchor_frame: int,
    phase: str,
    config: TemporalFusionConfig,
    original_shape: tuple[int, int],
    chamber: str,
    refine_pixels: np.ndarray | None,
    refine_is_cine: bool,
    instance_pixel_spacing: tuple[float, float] | None,
) -> tuple[TemporalFusionResult, Contour]:
    """Fuse, optionally refine on the anchor frame, and quality-gate the fused contour.

    The pure computational tail of a fusion run (#552): ``temporal_fuse``, the optional
    §5.2 step-6 refinement and the chamber-specific geometry gate. ``refine_pixels`` is
    the anchor frame's pixels when the anchor is still the displayed frame and auto
    refinement is enabled, ``None`` otherwise — refining against a frame the user has
    since scrolled to would move the contour. Returns ``(result, fused_contour)`` where
    the contour is the refined fused one, or the center-only contour when the fused one
    failed the gate; publication itself stays with the controller's ticket decision.
    """
    result = temporal_fuse(
        center_mask=center_mask,
        neighbor_masks=neighbor_masks,
        center_contour=center_contour,
        neighbor_contours=neighbor_contours,
        anchor_frame_index=anchor_frame,
        phase=phase,
        config=config,
        original_shape=original_shape,
    )

    fused_contour = result.fused_contour
    if refine_pixels is not None:
        from echo_personal_tool.domain.services.mbs_lite_service import refine_open_arc_contour

        refined, _ = refine_open_arc_contour(
            refine_pixels,
            fused_contour,
            cine=refine_is_cine,
        )
        fused_contour = refined
        # Keep the result in sync with the refined contour.
        result = dataclasses.replace(result, fused_contour=fused_contour)

    pixel_spacing = _instance_spacing(instance_pixel_spacing)
    if (chamber or "").upper() == "LA":
        from echo_personal_tool.domain.services.la_segmentation_service import explain_la_auto_reject_reason

        reject_reason = explain_la_auto_reject_reason(fused_contour, pixel_spacing)
    else:
        from echo_personal_tool.domain.calculations.lvef_simpson import explain_lv_auto_reject_reason

        reject_reason = explain_lv_auto_reject_reason(fused_contour, pixel_spacing)
    if reject_reason is not None:
        logger.info("[TF] fused contour rejected by quality gate: %s — using center-only", reject_reason)
        fused_contour = center_contour
    return result, fused_contour


def _instance_spacing(instance_pixel_spacing: tuple[float, float] | None) -> tuple[float, float] | None:
    """Normalize instance pixel spacing to a 2-tuple, else ``None``."""
    if instance_pixel_spacing is None:
        return None
    if len(instance_pixel_spacing) < 2:
        return None
    return (float(instance_pixel_spacing[0]), float(instance_pixel_spacing[1]))
