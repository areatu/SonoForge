"""ML.3 preview adapter over the existing #552 segmentation publication owner.

The worker is injected or explicitly requested; this module creates no session
and publishes pending contours only. ML.6 owns the UI bundle selector.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_VIEWS, TemplatePrediction


def template_review_contours(
    prediction: TemplatePrediction, *, frame_index: int, sop_instance_uid: str
) -> tuple[Contour, ...]:
    """No auto-accept, cross-frame delivery, or laundering manual contours as AI."""
    if prediction.reject_reason is not None or prediction.view == "UNKNOWN":
        return ()
    if not sop_instance_uid:
        raise ValueError("missing instance identity")
    if (
        prediction.view not in TEMPLATE_VIEWS
        or not np.isfinite(prediction.confidence)
        or not 0 <= prediction.confidence <= 1
        or len({c.chamber for c in prediction.contours}) != len(prediction.contours)
    ):
        raise ValueError("invalid template prediction context")
    if any(
        c.source != "ai"
        or not c.review_pending
        or c.frame_index != frame_index
        or c.view != prediction.view
        or c.phase not in {"ED", "ES"}
        or c.chamber not in {"LV", "LA", "RV"}
        or c.sop_instance_uid not in {None, "", sop_instance_uid}
        for c in prediction.contours
    ):
        raise ValueError("invalid review-only template payload")
    return tuple(replace(c, sop_instance_uid=sop_instance_uid) for c in prediction.contours)


def connect_template_segmentation(
    controller: Any,
    worker: Any,
    receive_review: Callable[[tuple[Contour, ...]], None],
    failed: Callable[[str], None],
    timed_out: Callable[[], None],
) -> None:
    """Use the SAME ticket, cancellation/ABA checks and worker retention as LV/LA."""
    from echo_personal_tool.application.segmentation_delivery import connect_segmentation

    frame_index = controller._state_manager.snapshot.current_frame_index
    instance = controller._current_instance
    sop = instance.sop_instance_uid if instance is not None else ""

    def receive(payload: object) -> None:
        if not isinstance(payload, TemplatePrediction):
            failed("invalid_template_payload")
            return
        try:
            contours = template_review_contours(payload, frame_index=frame_index, sop_instance_uid=sop)
        except ValueError:
            failed("invalid_template_payload")
            return
        if contours:
            receive_review(contours)
        else:
            failed("template_rejected")

    connect_segmentation(controller, worker, receive, failed, timed_out)


def request_template_segmentation(
    controller: Any,
    *,
    models_dir: Path,
    phase: str,
    view: str,
    sector_mask: np.ndarray | None,
    allow_unvalidated: bool = False,
) -> bool:
    """Explicit local-bundle entry point. No default model discovery/activation.

    Refuse to replace any confirmed input: publishing an AI draft must not remove
    a measured contour and thereby change FAC/GLS/report values indirectly.
    """
    from echo_personal_tool.application.composition import services_of
    from echo_personal_tool.application.workers.echo_template_worker import EchoTemplateWorker
    from echo_personal_tool.infrastructure.i18n import tr

    state = controller._state_manager.snapshot
    instance = controller._current_instance
    bound = services_of(controller)
    if (
        controller._segment_in_progress
        or state.is_playing
        or instance is None
        or (bound is not None and not bound.capabilities.ai_segmentation)
        or phase not in {"ED", "ES"}
        or view not in TEMPLATE_VIEWS
        or controller._current_frame_pixels is None
        or controller._loaded_frame_index != state.current_frame_index
    ):
        return False
    frame_index = state.current_frame_index
    sop = instance.sop_instance_uid

    def conflicts(existing: Contour) -> bool:
        return (
            existing.phase == phase
            and existing.view == view
            and not existing.review_pending
            and existing.sop_instance_uid in {None, "", sop}
        )

    if any(conflicts(c) for c in state.contours):
        return False
    pixel_spacing, _ = controller._resolve_pixel_spacing(state)
    worker = EchoTemplateWorker(
        np.asarray(controller._current_frame_pixels),
        models_dir=models_dir,
        phase=phase,
        frame_index=frame_index,
        pixel_spacing=pixel_spacing,
        sector_mask=sector_mask,
        requested_view=view,
        allow_unvalidated=allow_unvalidated,
    )

    def publish(contours: tuple[Contour, ...]) -> None:
        current = controller._state_manager.snapshot.contours
        if any(conflicts(c) for c in current) or any(c.phase != phase or c.view != view for c in contours):
            return
        keys = {(c.phase, c.view, c.chamber) for c in contours}
        retained = [c for c in current if not (c.review_pending and (c.phase, c.view, c.chamber) in keys)]
        controller.on_contours_changed([*retained, *contours])
        controller.status_message.emit(
            tr("app.ai_review_prompt", view=view, phase=phase, refine_key="", accept_key="Enter")
        )

    def failed(_code: str) -> None:
        controller.status_message.emit(tr("app.segmentation_unavailable"))

    controller._segment_in_progress = True
    connect_template_segmentation(controller, worker, publish, failed, lambda: failed("template_timeout"))
    return True
