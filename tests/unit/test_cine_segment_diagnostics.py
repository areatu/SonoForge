"""Unit tests for cine_segment_diagnostics (report, helpers, format)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from echo_personal_tool.domain.services.cine_segment_diagnostics import (
    CineSegmentDiagnosticReport,
    _arc_depth_px,
    _arc_span_px,
    _collect_issues,
    _mask_bbox,
    _mask_centroid,
    format_diagnostic_report,
    render_diagnostic_overlay,
)


# ── CineSegmentDiagnosticReport ────────────────────────────────────


class TestCineSegmentDiagnosticReport:
    def test_creation(self) -> None:
        report = CineSegmentDiagnosticReport(
            source_path="/video.mp4",
            frame_index=5,
            frame_shape=(480, 640),
            media_format="mp4",
            roi_xyxy=(100.0, 50.0, 500.0, 400.0),
            crop_mode="echonet",
            crop_y0=50,
            crop_x0=100,
            crop_height=350,
            crop_width=400,
            mask_pixels=1200,
            mask_bbox=(150, 80, 450, 350),
            mask_centroid_xy=(300.0, 200.0),
            annulus_mid_y=100.0,
            apex_y=350.0,
            arc_point_count=32,
            arc_span_px=300.0,
            arc_depth_px=80.0,
            reject_reason=None,
            onnx_available=True,
        )
        assert report.source_path == "/video.mp4"
        assert report.frame_index == 5
        assert report.onnx_available is True
        assert report.issues == ()

    def test_frozen(self) -> None:
        report = CineSegmentDiagnosticReport(
            source_path=None, frame_index=0, frame_shape=(100, 100),
            media_format="mp4", roi_xyxy=None, crop_mode="none",
            crop_y0=0, crop_x0=0, crop_height=100, crop_width=100,
            mask_pixels=0, mask_bbox=None, mask_centroid_xy=None,
            annulus_mid_y=None, apex_y=None, arc_point_count=0,
            arc_span_px=None, arc_depth_px=None, reject_reason=None,
            onnx_available=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.mask_pixels = 500  # type: ignore[misc]


# ── _mask_bbox ─────────────────────────────────────────────────────


class TestMaskBbox:
    def test_empty_mask(self) -> None:
        mask = np.zeros((50, 50), dtype=np.uint8)
        assert _mask_bbox(mask) is None

    def test_single_pixel(self) -> None:
        mask = np.zeros((50, 50), dtype=np.uint8)
        mask[10, 20] = 1
        assert _mask_bbox(mask) == (20, 10, 20, 10)

    def test_rectangle(self) -> None:
        mask = np.zeros((50, 50), dtype=np.uint8)
        mask[5:15, 10:30] = 1
        assert _mask_bbox(mask) == (10, 5, 29, 14)


# ── _mask_centroid ─────────────────────────────────────────────────


class TestMaskCentroid:
    def test_empty_mask(self) -> None:
        mask = np.zeros((50, 50), dtype=np.uint8)
        assert _mask_centroid(mask) is None

    def test_center_of_mass(self) -> None:
        mask = np.zeros((50, 50), dtype=np.uint8)
        mask[20:30, 20:30] = 1
        cx, cy = _mask_centroid(mask)
        assert abs(cx - 24.5) < 0.1
        assert abs(cy - 24.5) < 0.1


# ── _arc_depth_px ──────────────────────────────────────────────────


class TestArcDepthPx:
    def test_too_few_points(self) -> None:
        assert _arc_depth_px([(0.0, 0.0), (10.0, 0.0)], ((0.0, 0.0), (10.0, 0.0))) == 0.0

    def test_zero_denominator(self) -> None:
        points = [(5.0, 10.0), (5.0, 20.0), (5.0, 30.0)]
        annulus = ((5.0, 0.0), (5.0, 0.0))
        assert _arc_depth_px(points, annulus) == 0.0

    def test_perpendicular_depth(self) -> None:
        # Annulus at y=0, points at y=10
        points = [(0.0, 0.0), (5.0, 10.0), (10.0, 0.0)]
        annulus = ((0.0, 0.0), (10.0, 0.0))
        depth = _arc_depth_px(points, annulus)
        assert abs(depth - 10.0) < 0.1


# ── _arc_span_px ───────────────────────────────────────────────────


class TestArcSpanPx:
    def test_too_few_points(self) -> None:
        assert _arc_span_px([(0.0, 0.0)]) == 0.0

    def test_single_point(self) -> None:
        assert _arc_span_px([(5.0, 5.0)]) == 0.0

    def test_two_points(self) -> None:
        span = _arc_span_px([(0.0, 0.0), (3.0, 4.0)])
        assert abs(span - 5.0) < 1e-6

    def test_max_span(self) -> None:
        points = [(0.0, 0.0), (5.0, 0.0), (0.0, 3.0)]
        span = _arc_span_px(points)
        # max is (5,0)→(0,3) = sqrt(25+9) ≈ 5.83
        assert abs(span - 5.830951894845301) < 1e-6


# ── _collect_issues ────────────────────────────────────────────────


class TestCollectIssues:
    def _make_report(self, **kwargs) -> CineSegmentDiagnosticReport:
        defaults = dict(
            source_path=None, frame_index=0, frame_shape=(100, 100),
            media_format="mp4", roi_xyxy=None, crop_mode="none",
            crop_y0=0, crop_x0=0, crop_height=100, crop_width=100,
            mask_pixels=200, mask_bbox=None, mask_centroid_xy=None,
            annulus_mid_y=None, apex_y=None, arc_point_count=0,
            arc_span_px=None, arc_depth_px=None, reject_reason=None,
            onnx_available=False,
        )
        defaults.update(kwargs)
        return CineSegmentDiagnosticReport(**defaults)

    def test_no_issues(self) -> None:
        report = self._make_report(
            roi_xyxy=(10.0, 10.0, 90.0, 90.0),
            mask_pixels=200,
            mask_centroid_xy=(50.0, 50.0),
            annulus_mid_y=80.0,  # annulus below apex in image coords → correct
            apex_y=30.0,
            arc_depth_px=20.0,
        )
        assert _collect_issues(report) == ()

    def test_no_roi(self) -> None:
        report = self._make_report(roi_xyxy=None)
        issues = _collect_issues(report)
        assert any("ROI" in i for i in issues)

    def test_small_mask(self) -> None:
        report = self._make_report(mask_pixels=10)
        issues = _collect_issues(report)
        assert any("мала" in i for i in issues)

    def test_inverted_annulus_apex(self) -> None:
        report = self._make_report(
            roi_xyxy=(10.0, 10.0, 90.0, 90.0),
            mask_pixels=200,
            annulus_mid_y=30.0,  # annulus above apex → inverted
            apex_y=80.0,
        )
        issues = _collect_issues(report)
        assert any("инвертирован" in i for i in issues)

    def test_collapsed_arc(self) -> None:
        report = self._make_report(
            roi_xyxy=(10.0, 10.0, 90.0, 90.0),
            mask_pixels=200,
            annulus_mid_y=80.0,
            apex_y=30.0,
            arc_depth_px=2.0,
        )
        issues = _collect_issues(report)
        assert any("схлопнут" in i for i in issues)

    def test_narrow_mask(self) -> None:
        report = self._make_report(
            roi_xyxy=(10.0, 10.0, 110.0, 90.0),
            mask_pixels=200,
            mask_bbox=(50, 20, 55, 80),  # width=5, ROI width=100
        )
        issues = _collect_issues(report)
        assert any("узкая" in i for i in issues)

    def test_reject_reason(self) -> None:
        report = self._make_report(reject_reason="too_few_nodes")
        issues = _collect_issues(report)
        assert any("quality gate" in i for i in issues)

    def test_centroid_outside_roi(self) -> None:
        report = self._make_report(
            roi_xyxy=(10.0, 10.0, 90.0, 90.0),
            mask_pixels=200,
            mask_centroid_xy=(95.0, 50.0),  # outside ROI
        )
        issues = _collect_issues(report)
        assert any("вне B-mode" in i for i in issues)


# ── format_diagnostic_report ───────────────────────────────────────


class TestFormatDiagnosticReport:
    def test_basic(self) -> None:
        report = CineSegmentDiagnosticReport(
            source_path="/video.mp4", frame_index=0, frame_shape=(480, 640),
            media_format="mp4", roi_xyxy=(10.0, 20.0, 300.0, 400.0),
            crop_mode="echonet", crop_y0=20, crop_x0=10, crop_height=380,
            crop_width=290, mask_pixels=500, mask_bbox=(50, 30, 250, 350),
            mask_centroid_xy=(150.0, 200.0), annulus_mid_y=80.0,
            apex_y=350.0, arc_point_count=32, arc_span_px=200.0,
            arc_depth_px=60.0, reject_reason=None, onnx_available=True,
        )
        text = format_diagnostic_report(report)
        assert "/video.mp4" in text
        assert "ONNX available: True" in text
        assert "640x480" in text

    def test_with_issues(self) -> None:
        report = CineSegmentDiagnosticReport(
            source_path=None, frame_index=0, frame_shape=(100, 100),
            media_format="mp4", roi_xyxy=None, crop_mode="none",
            crop_y0=0, crop_x0=0, crop_height=100, crop_width=100,
            mask_pixels=0, mask_bbox=None, mask_centroid_xy=None,
            annulus_mid_y=None, apex_y=None, arc_point_count=0,
            arc_span_px=None, arc_depth_px=None, reject_reason=None,
            onnx_available=False, issues=("issue one", "issue two"),
        )
        text = format_diagnostic_report(report)
        assert "issues:" in text
        assert "issue one" in text


# ── render_diagnostic_overlay ──────────────────────────────────────


class TestRenderDiagnosticOverlay:
    def test_grayscale_to_bgr(self) -> None:
        frame = np.zeros((50, 80), dtype=np.uint8)
        result = render_diagnostic_overlay(frame, roi_xyxy=None)
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_with_roi(self) -> None:
        frame = np.zeros((50, 80), dtype=np.uint8)
        result = render_diagnostic_overlay(frame, roi_xyxy=(10.0, 10.0, 60.0, 40.0))
        assert result.shape == (50, 80, 3)

    def test_with_mask(self) -> None:
        frame = np.zeros((50, 80), dtype=np.uint8)
        mask = np.zeros((50, 80), dtype=np.uint8)
        mask[10:30, 20:50] = 1
        result = render_diagnostic_overlay(frame, roi_xyxy=None, mask=mask)
        assert result.shape == (50, 80, 3)

    def test_rgb_input(self) -> None:
        frame = np.zeros((50, 80, 3), dtype=np.uint8)
        result = render_diagnostic_overlay(frame, roi_xyxy=None)
        assert result.shape == (50, 80, 3)
