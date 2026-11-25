"""Controller glue for the fusion and assist publication owners (#552).

Application-layer adapter in the ``segmentation_delivery`` style: the owner
ledgers stay Qt-free in :mod:`echo_personal_tool.application.fusion_jobs`, and
this module is the only place that reads controller attributes to build or
re-check a ticket. Keeps the AppController line/method ratchet (#474) from
growing while the ownership wiring stays one call per site.
"""

from __future__ import annotations

from typing import Any

from echo_personal_tool.application.composition import assist_jobs_of, fusion_jobs_of
from echo_personal_tool.application.fusion_jobs import (
    AssistTicket,
    FusionTicket,
    assist_basis,
    fusion_basis,
)


def _clinical_context(controller: Any) -> tuple[Any, Any]:
    """The controller's live state snapshot and current instance."""
    return controller._state_manager.snapshot, controller._current_instance


def begin_fusion_run(
    controller: Any,
    *,
    anchor_frame: int,
    window: tuple[int, ...],
    original_shape: tuple[int, int],
) -> FusionTicket:
    """Begin a fusion-run ticket from the controller's current clinical context."""
    state, instance = _clinical_context(controller)
    return fusion_jobs_of(controller).begin(
        fusion_basis(
            state,
            instance,
            document_id=controller._resolve_study_uid(),
            generation=controller._study_load_generation,
            anchor_frame=anchor_frame,
            window=window,
            original_shape=original_shape,
        )
    )


def finish_fusion_run(controller: Any, ticket: FusionTicket) -> bool | None:
    """Consume the run's publication ticket against the fresh context (tri-state)."""
    state, instance = _clinical_context(controller)
    return fusion_jobs_of(controller).finish(
        ticket,
        state,
        instance,
        controller._resolve_study_uid,
        controller._study_load_generation,
    )


def begin_assist_request(controller: Any, *, frame_index: int) -> AssistTicket:
    """Begin an LA-assist ticket from the controller's current clinical context."""
    state, instance = _clinical_context(controller)
    return assist_jobs_of(controller).begin(
        assist_basis(
            state,
            instance,
            document_id=controller._resolve_study_uid(),
            generation=controller._study_load_generation,
            frame_index=frame_index,
            loaded_frame_index=controller._loaded_frame_index,
        )
    )


def finish_assist_request(controller: Any, ticket: AssistTicket) -> bool | None:
    """Consume the assist ticket against the fresh context (tri-state)."""
    state, instance = _clinical_context(controller)
    return assist_jobs_of(controller).finish(
        ticket,
        state,
        instance,
        controller._resolve_study_uid,
        controller._study_load_generation,
        controller._loaded_frame_index,
    )


def observe_publication_owners(controller: Any, state: Any) -> None:
    """Re-check the fusion and assist owners against a fresh state snapshot.

    Called from ``_on_state_changed`` and ``on_contours_changed`` (the latter
    applies contours with ``emit=False`` and would otherwise bypass the state
    observation): any input change revokes publication immediately, even if it
    is later undone (ABA). Both owners are idle-cheap, so playback ticks cost
    two ``is not None`` checks.
    """
    fusion = fusion_jobs_of(controller)
    was_active = fusion.is_active()
    fusion.observe_state(
        state,
        controller._current_instance,
        controller._resolve_study_uid,
        controller._study_load_generation,
    )
    if was_active and not fusion.is_active():
        # The live run just lost its ticket (context change / ABA): release its
        # intermediate masks now instead of keeping them until the next run.
        controller._clear_fusion_state()
    assist_jobs_of(controller).observe_state(
        state,
        controller._current_instance,
        controller._resolve_study_uid,
        controller._study_load_generation,
        controller._loaded_frame_index,
    )
