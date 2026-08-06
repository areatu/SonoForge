"""Unit tests for segmentation preprocessing and postprocessing."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.services.segmentation_service import (
    closed_polygon_to_open_arc,
    exclude_papillary_concavities,
    logits_to_mask,
    mask_to_contour,
    papillary_mask_cleanup,
    prepare_tensor,
    smooth_contour,
)


def _circle_mask(
    *,
    height: int,
    width: int,
    center_y: float,
    center_x: float,
    radius: float,
) -> np.ndarray:
    ys, xs = np.ogrid[:height, :width]
    distance = (ys - center_y) ** 2 + (xs - center_x) ** 2
    return (distance <= radius**2).astype(np.uint8)


def _polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def test_embed_echonet_mask_places_crop_in_frame() -> None:
    from echo_personal_tool.domain.services.segmentation_service import (
        EchoNetCropTransform,
        embed_echonet_mask,
    )

    mask = np.zeros((112, 112), dtype=np.uint8)
    mask[40:72, 40:72] = 1
    transform = EchoNetCropTransform(
        frame_height=480,
        frame_width=640,
        crop_y0=40,
        crop_x0=120,
        crop_height=224,
        crop_width=224,
    )

    embedded = embed_echonet_mask(mask, transform)

    assert embedded.shape == (480, 640)
    assert embedded[40:264, 120:344].any()
    assert not embedded[0:40, :].any()


def test_crop_frame_for_echonet_uses_b_mode_roi() -> None:
    from echo_personal_tool.domain.services.segmentation_service import crop_frame_for_echonet

    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    frame[50:550, 100:700] = 80
    roi = (100.0, 50.0, 700.0, 550.0)

    cropped, transform = crop_frame_for_echonet(frame, roi_xyxy=roi)

    assert cropped.shape[:2] == (transform.crop_height, transform.crop_width)
    assert transform.crop_height == 500
    assert transform.crop_width == 500
    assert transform.crop_y0 >= 50
    assert transform.crop_x0 >= 100


def test_crop_frame_for_echonet_full_roi_uses_entire_b_mode_rectangle() -> None:
    from echo_personal_tool.domain.services.segmentation_service import (
        EchoNetCropMode,
        crop_frame_for_echonet,
    )

    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    roi = (100.0, 50.0, 700.0, 550.0)

    cropped, transform = crop_frame_for_echonet(
        frame,
        roi_xyxy=roi,
        crop_mode=EchoNetCropMode.FULL_ROI,
    )

    assert transform.crop_height == 500
    assert transform.crop_width == 600
    assert cropped.shape[:2] == (500, 600)


def test_prepare_tensor_grayscale_shape_and_dtype() -> None:
    frame = np.full((64, 48), 128, dtype=np.uint8)

    tensor = prepare_tensor(frame, target_size=112)

    assert tensor.shape == (1, 3, 112, 112)
    assert tensor.dtype == np.float32


def test_prepare_tensor_rgb_shape_and_dtype() -> None:
    frame = np.zeros((80, 60, 3), dtype=np.uint8)
    frame[:, :, 0] = 200
    frame[:, :, 1] = 100
    frame[:, :, 2] = 50

    tensor = prepare_tensor(frame, target_size=112)

    assert tensor.shape == (1, 3, 112, 112)
    assert tensor.dtype == np.float32


def test_prepare_tensor_per_frame_normalization() -> None:
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    frame[:, :, 0] = 10
    frame[:, :, 1] = 20
    frame[:, :, 2] = 30

    tensor = prepare_tensor(frame, target_size=32)

    for channel in range(3):
        values = tensor[0, channel]
        assert values.mean() == pytest.approx(0.0, abs=1e-5)
        assert values.std() == pytest.approx(0.0, abs=1e-5)


def test_logits_to_mask_from_logits() -> None:
    logits = np.array([[[[-2.0, -0.1, 2.0]]]], dtype=np.float32)

    mask = logits_to_mask(logits, threshold=0.5)

    assert mask.shape == (1, 3)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)).issubset({0, 1})
    assert mask[0, 0] == 0
    assert mask[0, 1] == 0
    assert mask[0, 2] == 1


def test_logits_to_mask_from_probabilities() -> None:
    probabilities = np.array([[0.2, 0.8], [0.6, 0.4]], dtype=np.float32)

    mask = logits_to_mask(probabilities, threshold=0.5)

    assert mask.shape == (2, 2)
    assert mask.tolist() == [[0, 1], [1, 0]]


def test_open_arc_from_cavity_mask_uses_wider_end_as_annulus() -> None:
    from echo_personal_tool.domain.services.segmentation_service import open_arc_from_cavity_mask

    height, width = 400, 400
    mask = np.zeros((height, width), dtype=np.uint8)
    center_y, center_x, radius_y, radius_x = 220.0, 200.0, 150.0, 90.0
    ys, xs = np.ogrid[:height, :width]
    mask[((ys - center_y) ** 2 / radius_y**2 + (xs - center_x) ** 2 / radius_x**2) <= 1.0] = 1

    open_points, annulus, apex = open_arc_from_cavity_mask(mask, num_nodes=32)
    septal, lateral = annulus

    annulus_y = (septal[1] + lateral[1]) / 2.0
    assert annulus_y > apex[1]
    assert abs(lateral[0] - septal[0]) > 20.0
    assert open_points[0] == septal
    assert open_points[-1] == lateral


def test_open_arc_from_cavity_mask_flips_when_base_is_at_bottom() -> None:
    from echo_personal_tool.domain.services.segmentation_service import open_arc_from_cavity_mask

    height, width = 400, 400
    mask = np.zeros((height, width), dtype=np.uint8)
    for y in range(height):
        half_width = int(15 + (y / height) * 130)
        center_x = width // 2
        mask[y, center_x - half_width : center_x + half_width] = 1

    _, annulus, apex = open_arc_from_cavity_mask(mask, num_nodes=32, view_hint="A4C")
    annulus_y = (annulus[0][1] + annulus[1][1]) / 2.0
    assert annulus_y > apex[1]


def test_mitral_annulus_endpoints_allow_sloped_mv_line() -> None:
    from echo_personal_tool.domain.services.segmentation_service import _mitral_annulus_endpoints

    xs = np.array([10.0, 11.0, 12.0, 13.0, 87.0, 88.0, 89.0, 90.0])
    ys = np.array([100.0, 101.0, 100.0, 101.0, 118.0, 120.0, 119.0, 120.0])
    septal, lateral = _mitral_annulus_endpoints(xs, ys)
    assert septal[0] < lateral[0]
    assert lateral[1] - septal[1] > 8.0
    assert septal[1] != lateral[1]


def test_mask_to_contour_embedded_echonet_blob_has_full_span() -> None:
    from echo_personal_tool.domain.services.segmentation_service import (
        closed_polygon_to_open_arc,
        crop_frame_for_echonet,
        embed_echonet_mask,
        papillary_mask_cleanup,
        smooth_contour,
    )

    height, width = 600, 800
    _, transform = crop_frame_for_echonet(
        np.zeros((height, width), dtype=np.uint8),
        roi_xyxy=(100.0, 50.0, 700.0, 550.0),
    )
    onnx_mask = np.zeros((112, 112), dtype=np.uint8)
    onnx_mask[30:90, 25:85] = 1
    embedded = embed_echonet_mask(onnx_mask, transform)
    cleaned = papillary_mask_cleanup(embedded)
    closed = smooth_contour(mask_to_contour(cleaned, (height, width)), num_nodes=32)
    max_span = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in closed for b in closed)

    assert max_span > 100.0
    arc, annulus = closed_polygon_to_open_arc(closed)
    annulus_len = math.hypot(
        annulus[1][0] - annulus[0][0],
        annulus[1][1] - annulus[0][1],
    )
    assert annulus_len > 100.0
    assert len(arc) >= 3


def test_mask_to_contour_circle_area_scales_to_original_shape() -> None:
    mask_size = 64
    radius = 20.0
    mask = _circle_mask(
        height=mask_size,
        width=mask_size,
        center_y=mask_size / 2,
        center_x=mask_size / 2,
        radius=radius,
    )
    original_shape = (128, 128)
    scale = original_shape[0] / mask_size

    contour = mask_to_contour(mask, original_shape)

    assert len(contour) >= 3
    expected_area = math.pi * (radius * scale) ** 2
    assert _polygon_area(contour) == pytest.approx(expected_area, rel=0.05)


def test_smooth_contour_returns_requested_node_count() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

    resampled = smooth_contour(square, num_nodes=32)

    assert len(resampled) == 32
    assert all(len(point) == 2 for point in resampled)


def test_closed_polygon_to_open_arc_uses_longest_chord() -> None:
    polygon = [(0.0, 0.0), (100.0, 0.0), (70.0, 70.0), (30.0, 70.0)]
    arc, annulus = closed_polygon_to_open_arc(polygon)
    assert len(arc) >= 2
    assert arc[0] == annulus[0]
    assert arc[-1] == annulus[1]


def _mask_with_mid_notch(height: int = 64, width: int = 48) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[8:56, 12:36] = 1
    mask[28:40, 20:28] = 0  # papillary-like notch
    return mask


def test_papillary_mask_cleanup_fills_mid_notch() -> None:
    mask = _mask_with_mid_notch()
    cleaned = papillary_mask_cleanup(mask)
    assert cleaned[32, 24] == 1
    assert cleaned.sum() >= mask.sum()


def test_papillary_mask_cleanup_preserves_largest_component() -> None:
    mask = _mask_with_mid_notch()
    mask[2:6, 2:6] = 1  # speckle
    cleaned = papillary_mask_cleanup(mask)
    assert cleaned[2:6, 2:6].sum() == 0


def _arc_with_inward_bump() -> tuple[list[tuple[float, float]], tuple, tuple]:
    annulus = ((0.0, 0.0), (100.0, 0.0))
    apex = (50.0, 80.0)
    points = [
        annulus[0],
        (25.0, 40.0),
        (50.0, 55.0),  # inward bump (papillary)
        (75.0, 40.0),
        annulus[1],
    ]
    return points, annulus, apex


def test_exclude_papillary_concavities_raises_mid_cavity_bump() -> None:
    points, annulus, apex = _arc_with_inward_bump()
    result = exclude_papillary_concavities(points, annulus, apex)
    assert result[0] == annulus[0]
    assert result[-1] == annulus[1]
    mid_y = result[2][1]
    assert mid_y >= 55.0 - 2.0  # bumped outward toward chord


def test_exclude_papillary_concavities_leaves_smooth_arc_unchanged() -> None:
    annulus = ((0.0, 0.0), (100.0, 0.0))
    apex = (50.0, 80.0)
    points = [annulus[0], (50.0, 70.0), annulus[1]]
    result = exclude_papillary_concavities(points, annulus, apex)
    assert result[1][1] == pytest.approx(70.0, abs=2.0)


def test_logits_to_mask_adaptive_otsu_clamped() -> None:
    """Adaptive threshold must clamp to [0.35, 0.65]."""
    low = np.full((4, 4), 0.3, dtype=np.float32)
    high = np.full((4, 4), 0.7, dtype=np.float32)

    mask_low = logits_to_mask(low)
    mask_high = logits_to_mask(high)

    assert mask_low.min() == 0
    assert mask_high.max() == 1


def test_logits_to_mask_fixed_threshold_overrides_adaptive() -> None:
    probs = np.array([[0.4, 0.6], [0.55, 0.45]], dtype=np.float32)
    mask = logits_to_mask(probs, threshold=0.5)
    assert mask.tolist() == [[0, 1], [1, 0]]


def test_embed_echonet_mask_uses_linear_interpolation() -> None:
    """embed_echonet_mask with order=1 produces smooth upscaled mask."""
    from echo_personal_tool.domain.services.segmentation_service import (
        EchoNetCropTransform,
        embed_echonet_mask,
    )

    mask = np.zeros((112, 112), dtype=np.uint8)
    mask[40:72, 40:72] = 1
    transform = EchoNetCropTransform(
        frame_height=224,
        frame_width=224,
        crop_y0=0,
        crop_x0=0,
        crop_height=224,
        crop_width=224,
    )

    embedded = embed_echonet_mask(mask, transform)

    assert embedded.shape == (224, 224)
    assert embedded.dtype == np.uint8
    assert set(np.unique(embedded)).issubset({0, 1})


def test_papillary_mask_cleanup_es_stronger_closing() -> None:
    """ES phase uses larger SE than ED."""
    mask = _mask_with_mid_notch(height=100, width=80)
    cleaned_ed = papillary_mask_cleanup(mask, phase="ED")
    cleaned_es = papillary_mask_cleanup(mask, phase="ES")

    assert cleaned_ed.sum() <= cleaned_es.sum() + 10


def test_exclude_papillary_concavities_es_higher_depth_threshold() -> None:
    """ES phase uses higher depth_threshold_ratio (0.05 vs 0.04)."""
    points, annulus, apex = _arc_with_inward_bump()
    result_ed = exclude_papillary_concavities(points, annulus, apex, phase="ED")
    result_es = exclude_papillary_concavities(points, annulus, apex, phase="ES")

    assert result_ed[0] == annulus[0]
    assert result_es[0] == annulus[0]


def test_prepare_tensor_fixed_normalization() -> None:
    frame = np.full((32, 32, 3), 128, dtype=np.uint8)

    tensor = prepare_tensor(
        frame,
        target_size=32,
        fixed_mean=[0.124, 0.124, 0.124],
        fixed_std=[0.116, 0.116, 0.116],
    )

    assert tensor.shape == (1, 3, 32, 32)
    assert tensor.dtype == np.float32


def test_prepare_tensor_fixed_norm_falls_back_to_per_frame_when_none() -> None:
    frame = np.full((32, 32, 3), 128, dtype=np.uint8)

    tensor = prepare_tensor(frame, target_size=32, fixed_mean=None, fixed_std=None)

    assert tensor.shape == (1, 3, 32, 32)


# --- Phase 2: MV boundary snap tests ---


class TestMaskBoundaryPointsInBand:
    def test_extracts_boundary_points_within_band(self) -> None:
        from echo_personal_tool.domain.services.segmentation_service import (
            _mask_boundary_points_in_band,
        )

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[60:80, 20:80] = 1  # rectangle blob
        ys, xs = _mask_boundary_points_in_band(mask, y_low=60, y_high=80)
        assert len(ys) > 0
        assert len(xs) == len(ys)
        # All points should be on the boundary of the mask
        for y, x in zip(ys, xs):
            assert mask[y, x] == 1

    def test_empty_band_returns_empty(self) -> None:
        from echo_personal_tool.domain.services.segmentation_service import (
            _mask_boundary_points_in_band,
        )

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[10:20, 10:20] = 1
        ys, xs = _mask_boundary_points_in_band(mask, y_low=60, y_high=80)
        assert len(ys) == 0


class TestSnapAnnulusToMaskBoundary:
    def test_snap_moves_point_to_mask_edge(self) -> None:
        from echo_personal_tool.domain.services.segmentation_service import (
            _snap_annulus_to_mask_boundary,
        )

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[70:90, 20:80] = 1  # basal band blob
        septal, lateral = _snap_annulus_to_mask_boundary(
            (35.0, 80.0),
            (65.0, 80.0),
            mask,
            basal_y_range=(70, 90),
        )
        assert septal[0] < lateral[0]
        # Points should be on or very near the mask boundary
        sy, sx = int(round(septal[1])), int(round(septal[0]))
        ly, lx = int(round(lateral[1])), int(round(lateral[0]))
        assert 0 <= sy < 100 and 0 <= sx < 100
        assert 0 <= ly < 100 and 0 <= lx < 100

    def test_already_on_boundary_stays_close(self) -> None:
        from echo_personal_tool.domain.services.segmentation_service import (
            _snap_annulus_to_mask_boundary,
        )

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[70:90, 20:80] = 1
        # Points already on boundary (left edge = 20, right edge = 79)
        septal, lateral = _snap_annulus_to_mask_boundary(
            (20.0, 80.0),
            (79.0, 80.0),
            mask,
            basal_y_range=(70, 90),
        )
        assert abs(septal[0] - 20.0) < 2.0
        assert abs(lateral[0] - 79.0) < 2.0


class TestBlendAnnulusWithArcTips:
    def test_blends_when_close_to_arc_tip(self) -> None:
        from echo_personal_tool.domain.services.segmentation_service import (
            _blend_annulus_with_arc_tips,
        )

        annulus = ((20.0, 80.0), (80.0, 80.0))
        open_points = [(22.0, 82.0), (50.0, 40.0), (78.0, 82.0)]
        result = _blend_annulus_with_arc_tips(
            annulus,
            open_points,
            max_blend_dist_px=10.0,
            blend_weight=0.3,
        )
        septal, lateral = result
        # Should blend toward arc tips
        assert abs(septal[0] - 20.0) < 5.0
        assert abs(lateral[0] - 80.0) < 5.0

    def test_no_blend_when_far_from_arc_tip(self) -> None:
        from echo_personal_tool.domain.services.segmentation_service import (
            _blend_annulus_with_arc_tips,
        )

        annulus = ((20.0, 80.0), (80.0, 80.0))
        open_points = [(100.0, 10.0), (50.0, 40.0), (150.0, 10.0)]
        result = _blend_annulus_with_arc_tips(
            annulus,
            open_points,
            max_blend_dist_px=5.0,
            blend_weight=0.3,
        )
        septal, lateral = result
        # Far from tips → no blend, stays at original
        assert septal == annulus[0]
        assert lateral == annulus[1]


class TestSnapWiredIntoOpenArc:
    def test_open_arc_snap_does_not_break_existing(self) -> None:
        """Regression: existing sloped MV test still passes after snap wiring."""
        from echo_personal_tool.domain.services.segmentation_service import (
            open_arc_from_cavity_mask,
        )

        height, width = 400, 400
        mask = np.zeros((height, width), dtype=np.uint8)
        center_y, center_x, radius_y, radius_x = 220.0, 200.0, 150.0, 90.0
        ys, xs = np.ogrid[:height, :width]
        mask[((ys - center_y) ** 2 / radius_y**2 + (xs - center_x) ** 2 / radius_x**2) <= 1.0] = 1

        open_points, annulus, apex = open_arc_from_cavity_mask(mask, num_nodes=32)
        septal, lateral = annulus

        annulus_y = (septal[1] + lateral[1]) / 2.0
        assert annulus_y > apex[1]
        assert abs(lateral[0] - septal[0]) > 20.0
        assert open_points[0] == septal
        assert open_points[-1] == lateral
