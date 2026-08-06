"""Unit tests for DICOM vs cine segment ROI selection."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.segment_roi import (
    ECHONET_CROP_CENTER_SQUARE,
    echonet_crop_mode_for_media,
    resolve_cine_segment_roi_xyxy,
    resolve_segment_roi_xyxy,
)


def test_echonet_crop_mode_uses_center_square_for_cine_and_dicom() -> None:
    assert echonet_crop_mode_for_media("dicom") == ECHONET_CROP_CENTER_SQUARE
    assert echonet_crop_mode_for_media("mp4") == ECHONET_CROP_CENTER_SQUARE


def test_resolve_cine_roi_uses_upper_panel_heuristic() -> None:
    height, width = 600, 800
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), :] = 140
    frame[int(height * 0.62) :, :] = 40

    roi = resolve_cine_segment_roi_xyxy(frame)

    assert roi is not None
    assert roi[1] == 0.0
    assert roi[3] - roi[1] < height * 0.72


def test_resolve_cine_roi_trims_right_ui_strip() -> None:
    height, width = 800, 1276
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), 350:910] = 130
    frame[: int(height * 0.62), 1220:1270] = 200
    frame[int(height * 0.62) :, :] = 40

    roi = resolve_cine_segment_roi_xyxy(frame)

    assert roi is not None
    assert roi[0] >= 300.0
    assert roi[2] <= 950.0
    assert roi[2] - roi[0] < width * 0.55


def test_resolve_segment_roi_mp4_uses_heuristic_not_dicom_tags(tmp_path) -> None:
    height, width = 600, 800
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), :] = 140
    frame[int(height * 0.62) :, :] = 40
    fake_path = tmp_path / "clip.mp4"

    roi = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        instance_path=fake_path,
    )

    assert roi is not None
    assert roi[1] == 0.0
    assert roi[3] - roi[1] < height * 0.72


def test_frozen_cine_roi_reused_across_frames() -> None:
    height, width = 600, 800
    frame_a = np.zeros((height, width, 3), dtype=np.uint8)
    frame_a[: int(height * 0.62), 100:700] = 140
    frame_a[int(height * 0.62) :, :] = 40

    frame_b = np.zeros((height, width, 3), dtype=np.uint8)
    frame_b[: int(height * 0.62), 200:750] = 140
    frame_b[int(height * 0.62) :, :] = 40

    roi_a = resolve_cine_segment_roi_xyxy(frame_a)
    roi_b_live = resolve_cine_segment_roi_xyxy(frame_b)
    roi_b_frozen = resolve_segment_roi_xyxy(
        frame_b,
        media_format="mp4",
        frozen_cine_roi=roi_a,
    )

    assert roi_a is not None
    assert roi_b_live is not None
    assert roi_b_frozen == roi_a
    assert abs(roi_b_live[0] - roi_a[0]) > 1.0
