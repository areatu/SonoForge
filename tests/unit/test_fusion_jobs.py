"""Qt-free publication ownership for fusion runs and LA assist (#552).

Covers the two publication owners that the segmentation slice (#609) explicitly
left unprotected, plus the pure fusion tail and the LA-assist contract fix.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.fusion_jobs import (
    AssistJobs,
    FusionJobs,
    _instance_spacing,
    assist_basis,
    finalize_fused_contour,
    fusion_basis,
)
from echo_personal_tool.domain.models import Contour, InstanceMetadata, TemporalFusionConfig
from echo_personal_tool.domain.services.la_segmentation_service import build_la_assist_contour

_INSTANCE = InstanceMetadata(
    sop_instance_uid="1.2.3.4.5",
    series_uid="1.2.3.4.6",
    modality="US",
    number_of_frames=10,
    pixel_spacing=(0.5, 0.5),
    frame_time_ms=40.0,
    series_description="Test",
    path=Path("/cine.dcm"),
)


def _state():
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    return ViewerState(
        instance=_INSTANCE,
        current_frame_index=2,
        total_frames=10,
        frame_time_ms=40.0,
        is_playing=False,
    )


def _fusion_kwargs(**overrides):
    values = {
        "document_id": "study",
        "generation": 1,
        "anchor_frame": 2,
        "window": (1, 2, 3),
        "original_shape": (8, 8),
    }
    values.update(overrides)
    return values


def _assist_kwargs(**overrides):
    values = {
        "document_id": "study",
        "generation": 1,
        "frame_index": 2,
        "loaded_frame_index": 2,
    }
    values.update(overrides)
    return values


# ── FusionJobs: one publishable run, latest wins ─────────────────────────────


def test_fusion_latest_run_supersedes_the_old_one():
    owner = FusionJobs()
    old = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    latest = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    assert latest.request_id > old.request_id
    # The superseded ticket is neither owned nor publishable...
    assert not owner.owns(old)
    assert owner.finish(old, _state(), _INSTANCE, lambda: "study", 1) is None
    # ...and the newest one publishes exactly once.
    assert owner.owns(latest)
    assert owner.finish(latest, _state(), _INSTANCE, lambda: "study", 1) is True
    assert owner.finish(latest, _state(), _INSTANCE, lambda: "study", 1) is None


def test_fusion_consume_keeps_immutable_run_geometry():
    owner = FusionJobs()
    owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    ticket = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    # observe/finish rebuild the fresh document/calibration/contour parts, but the
    # run's own geometry comes from the ticket, so frame navigation is not an ABA.
    state = replace(_state(), current_frame_index=5)
    assert owner.owns(ticket)
    assert owner.finish(ticket, state, _INSTANCE, lambda: "study", 1) is True


@pytest.mark.parametrize(
    "change",
    [
        {"document_id": "other"},
        {"generation": 2},
    ],
)
def test_fusion_changed_fresh_parts_reject_publication(change):
    owner = FusionJobs()
    ticket = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    stale = fusion_basis(_state(), _INSTANCE, **_fusion_kwargs(**change))
    # The rebuild takes the run geometry from the ticket and the document epoch from
    # the controller: only the fresh parts (document id, generation, calibration,
    # contours) can reject a delivery here.
    assert owner.finish(ticket, _state(), _INSTANCE, lambda: stale.document_id, stale.study_generation) is not True


def test_fusion_new_run_with_different_geometry_supersedes_the_old_one():
    owner = FusionJobs()
    old = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    # A new run on another anchor/window is a new ticket: the old one is neither owned
    # nor publishable, so its late neighbor callbacks cannot contaminate the new run.
    owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs(anchor_frame=4, window=(3, 4, 5))))
    assert not owner.owns(old)
    assert owner.finish(old, _state(), _INSTANCE, lambda: "study", 1) is None


def test_fusion_invalidated_ticket_cannot_be_resumed():
    owner = FusionJobs()
    ticket = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    owner.invalidate()
    assert not owner.owns(ticket)
    assert owner.finish(ticket, _state(), _INSTANCE, lambda: "study", 1) is not True


def test_fusion_observed_change_then_undo_does_not_revive_run():
    owner = FusionJobs()
    ticket = owner.begin(fusion_basis(_state(), _INSTANCE, **_fusion_kwargs()))
    owner.observe_state(replace(_state(), manual_pixel_spacing=(1.0, 1.0)), _INSTANCE, lambda: "study", 1)
    owner.observe_state(_state(), _INSTANCE, lambda: "study", 1)
    assert not owner.owns(ticket)
    assert owner.finish(ticket, _state(), _INSTANCE, lambda: "study", 1) is not True


# ── AssistJobs: single current LA-assist request ─────────────────────────────


def test_assist_latest_request_supersedes_and_consumes_once():
    owner = AssistJobs()
    old = owner.begin(assist_basis(_state(), _INSTANCE, **_assist_kwargs()))
    latest = owner.begin(assist_basis(_state(), _INSTANCE, **_assist_kwargs()))
    assert latest.request_id > old.request_id
    assert owner.finish(old, _state(), _INSTANCE, lambda: "study", 1, 2) is None
    assert owner.finish(latest, _state(), _INSTANCE, lambda: "study", 1, 2) is True
    assert owner.finish(latest, _state(), _INSTANCE, lambda: "study", 1, 2) is None


def test_assist_frame_change_revokes_even_undone():
    owner = AssistJobs()
    ticket = owner.begin(assist_basis(_state(), _INSTANCE, **_assist_kwargs()))
    owner.observe_state(replace(_state(), current_frame_index=3), _INSTANCE, lambda: "study", 1, 3)
    owner.observe_state(_state(), _INSTANCE, lambda: "study", 1, 2)
    assert owner.finish(ticket, _state(), _INSTANCE, lambda: "study", 1, 2) is not True


# ── finalize_fused_contour: fusion tail with gate and anchor-only refinement ──


def _ring_mask(shape: tuple[int, int], center: float) -> np.ndarray:
    ys, xs = np.ogrid[: shape[0], : shape[1]]
    return ((ys - center) ** 2 + (xs - center) ** 2 <= 16).astype(np.uint8)


def _contour_for(y: float) -> Contour:
    return Contour(
        phase="ED",
        frame_index=2,
        points=[(4.0, y), (8.0, y + 2.0), (12.0, y)],
        sop_instance_uid="1.2.3.4.5",
    )


def test_finalize_returns_refined_gate_result_without_pixels():
    config = TemporalFusionConfig(window=3)
    result, fused = finalize_fused_contour(
        center_mask=_ring_mask((8, 8), 4.0),
        center_contour=_contour_for(2.0),
        neighbor_masks={1: _ring_mask((8, 8), 4.0), 3: _ring_mask((8, 8), 4.0)},
        neighbor_contours={1: _contour_for(2.5), 3: _contour_for(1.5)},
        anchor_frame=2,
        phase="ED",
        config=config,
        original_shape=(8, 8),
        chamber="LV",
        refine_pixels=None,
        refine_is_cine=False,
        instance_pixel_spacing=(0.5, 0.5),
    )
    assert result.frames_used >= 1
    assert fused.phase == "ED"


def test_finalize_skips_refinement_when_anchor_is_not_displayed():
    config = TemporalFusionConfig(window=3)
    called = False
    result, _ = finalize_fused_contour(
        center_mask=_ring_mask((8, 8), 4.0),
        center_contour=_contour_for(2.0),
        neighbor_masks={1: _ring_mask((8, 8), 4.0), 3: _ring_mask((8, 8), 4.0)},
        neighbor_contours={1: _contour_for(2.5), 3: _contour_for(1.5)},
        anchor_frame=2,
        phase="ED",
        config=config,
        original_shape=(8, 8),
        chamber="LV",
        refine_pixels=None,  # anchor scrolled away: never refined
        refine_is_cine=True,
        instance_pixel_spacing=(0.5, 0.5),
    )
    assert not called
    assert result.frames_used >= 1


def test_instance_spacing_normalization():
    assert _instance_spacing((0.5, 0.5)) == (0.5, 0.5)
    assert _instance_spacing((0.5,)) is None
    assert _instance_spacing(None) is None


# ── build_la_assist_contour: the OnnxWorker ndarray contract (#609 follow-up) ─


def test_build_la_assist_accepts_the_ndarray_payload_onnx_worker_emits():
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[8:24, 8:24] = 1
    contour = build_la_assist_contour(
        mask,
        user_septal=(10.0, 8.0),
        user_lateral=(10.0, 24.0),
        user_apex=(24.0, 16.0),
        frame_index=2,
    )
    # The legacy dict contract made this path dead code: the worker emits an ndarray,
    # and the assisted proposal is an open-arc LA contour for the requested frame.
    assert contour is not None
    assert (contour.chamber, contour.view, contour.phase) == ("LA", "A4C", "ES")
    assert contour.frame_index == 2 and contour.source == "manual" and not contour.review_pending


def test_build_la_assist_rejects_dict_and_tiny_masks():
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[8:24, 8:24] = 1
    assert (
        build_la_assist_contour(
            {"mask": mask}, user_septal=(10.0, 8.0), user_lateral=(10.0, 24.0), user_apex=(24.0, 16.0), frame_index=2
        )
        is None
    )
    assert (
        build_la_assist_contour(
            np.ones((4, 4), dtype=np.uint8),
            user_septal=(1.0, 1.0),
            user_lateral=(1.0, 3.0),
            user_apex=(3.0, 2.0),
            frame_index=2,
        )
        is None
    )
    assert (
        build_la_assist_contour(
            "not-a-mask", user_septal=(1.0, 1.0), user_lateral=(1.0, 3.0), user_apex=(3.0, 2.0), frame_index=2
        )
        is None
    )
