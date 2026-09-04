"""Diagnostics for untagged cine (MP4) LV auto-segmentation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from echo_personal_tool.domain.calculations.lvef_simpson import explain_lv_auto_reject_reason
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.segment_roi import (
    echonet_crop_mode_for_media,
    resolve_segment_roi_xyxy,
)
from echo_personal_tool.domain.services.segmentation_service import (
    crop_frame_for_echonet,
    lv_cavity_mask_to_open_arc,
    mask_to_contour,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine
from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader


@dataclass(frozen=True)
class CineSegmentDiagnosticReport:
    source_path: str | None
    frame_index: int
    frame_shape: tuple[int, int]
    media_format: str
    roi_xyxy: tuple[float, float, float, float] | None
    crop_mode: str
    crop_y0: int
    crop_x0: int
    crop_height: int
    crop_width: int
    mask_pixels: int
    mask_bbox: tuple[int, int, int, int] | None
    mask_centroid_xy: tuple[float, float] | None
    annulus_mid_y: float | None
    apex_y: float | None
    arc_point_count: int
    arc_span_px: float | None
    arc_depth_px: float | None
    reject_reason: str | None
    onnx_available: bool
    issues: tuple[str, ...] = field(default_factory=tuple)


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(np.asarray(mask) > 0)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _mask_centroid(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.where(np.asarray(mask) > 0)
    if xs.size == 0:
        return None
    return float(np.mean(xs)), float(np.mean(ys))


def _arc_depth_px(
    points: list[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    if len(points) < 3:
        return 0.0
    septal, lateral = annulus
    dx = lateral[0] - septal[0]
    dy = lateral[1] - septal[1]
    denom = math.hypot(dx, dy)
    if denom == 0.0:
        return 0.0
    max_depth = 0.0
    for point in points[1:-1]:
        numer = abs(dy * point[0] - dx * point[1] + lateral[0] * septal[1] - lateral[1] * septal[0])
        max_depth = max(max_depth, numer / denom)
    return max_depth


def _arc_span_px(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    max_span = 0.0
    for index, first in enumerate(points):
        for second in points[index + 1 :]:
            span = math.hypot(second[0] - first[0], second[1] - first[1])
            max_span = max(max_span, span)
    return max_span


def _collect_issues(report: CineSegmentDiagnosticReport) -> tuple[str, ...]:
    issues: list[str] = []
    if report.roi_xyxy is None:
        issues.append(tr("domain.cine_diag.no_roi"))
    if report.mask_pixels < 80:
        issues.append(tr("domain.cine_diag.mask_too_small", pixels=str(report.mask_pixels)))
    if report.mask_centroid_xy is not None and report.roi_xyxy is not None:
        centroid_x, centroid_y = report.mask_centroid_xy
        x0, y0, x1, y1 = report.roi_xyxy
        roi_width = max(1.0, x1 - x0)
        if centroid_x > x0 + 0.82 * roi_width:
            issues.append(tr("domain.cine_diag.mask_shifted"))
        if not (x0 <= centroid_x <= x1 and y0 <= centroid_y <= y1):
            issues.append(tr("domain.cine_diag.centroid_outside"))
    if report.annulus_mid_y is not None and report.apex_y is not None:
        if report.annulus_mid_y < report.apex_y:
            issues.append(tr("domain.cine_diag.annulus_inverted", annulus=report.annulus_mid_y, apex=report.apex_y))
        if report.arc_depth_px is not None and report.arc_depth_px < 5.0:
            issues.append(tr("domain.cine_diag.contour_collapsed", depth=report.arc_depth_px))
    if report.roi_xyxy is not None and report.mask_bbox is not None:
        roi_width = max(1.0, report.roi_xyxy[2] - report.roi_xyxy[0])
        mask_width = float(report.mask_bbox[2] - report.mask_bbox[0])
        if mask_width < 0.12 * roi_width:
            issues.append(tr("domain.cine_diag.mask_narrow", width=mask_width, roi=roi_width))
    if report.reject_reason:
        issues.append(f"quality gate: {report.reject_reason}")
    return tuple(issues)


def diagnose_cine_frame(
    frame: np.ndarray,
    *,
    media_format: str = "mp4",
    source_path: str | None = None,
    frame_index: int = 0,
    run_onnx: bool = True,
    frozen_roi_xyxy: tuple[float, float, float, float] | None = None,
) -> CineSegmentDiagnosticReport:
    """Build a diagnostic report for one untagged cine frame."""
    original_shape = (int(frame.shape[0]), int(frame.shape[1]))
    roi_xyxy = frozen_roi_xyxy or resolve_segment_roi_xyxy(frame, media_format=media_format)
    crop_mode = echonet_crop_mode_for_media(media_format)
    _cropped, transform = crop_frame_for_echonet(frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode)

    engine = OnnxInferenceEngine()
    onnx_available = engine.is_available()
    mask_pixels = 0
    mask_bbox = None
    centroid = None
    annulus_mid_y = None
    apex_y = None
    arc_count = 0
    arc_span = None
    arc_depth = None
    reject_reason = None

    if run_onnx and onnx_available:
        mask = engine.segment(frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode)
        try:
            open_points, annulus, apex, cleaned = lv_cavity_mask_to_open_arc(
                mask,
                original_shape=original_shape,
                phase="ED",
                view_hint="A4C",
            )
            mask_pixels = int(np.count_nonzero(cleaned))
            mask_bbox = _mask_bbox(cleaned)
            centroid = _mask_centroid(cleaned)
            annulus_mid_y = (annulus[0][1] + annulus[1][1]) / 2.0
            apex_y = float(apex[1])
            arc_count = len(open_points)
            arc_span = _arc_span_px(open_points)
            arc_depth = _arc_depth_px(open_points, annulus)
            contour = Contour(
                phase="ED",
                view="A4C",
                chamber="LV",
                mitral_annulus=annulus,
                apex_landmark=apex,
                points=open_points,
                source="ai",
            )
            reject_reason = explain_lv_auto_reject_reason(
                contour,
                None,
                roi_xyxy=roi_xyxy,
            )
        except ValueError:
            cleaned = mask
            mask_pixels = int(np.count_nonzero(cleaned))
            mask_bbox = _mask_bbox(cleaned)
            centroid = _mask_centroid(cleaned)
            boundary = mask_to_contour(cleaned, original_shape)
            arc_count = len(boundary)

    base = CineSegmentDiagnosticReport(
        source_path=source_path,
        frame_index=frame_index,
        frame_shape=original_shape,
        media_format=media_format,
        roi_xyxy=roi_xyxy,
        crop_mode=crop_mode,
        crop_y0=transform.crop_y0,
        crop_x0=transform.crop_x0,
        crop_height=transform.crop_height,
        crop_width=transform.crop_width,
        mask_pixels=mask_pixels,
        mask_bbox=mask_bbox,
        mask_centroid_xy=centroid,
        annulus_mid_y=annulus_mid_y,
        apex_y=apex_y,
        arc_point_count=arc_count,
        arc_span_px=arc_span,
        arc_depth_px=arc_depth,
        reject_reason=reject_reason,
        onnx_available=onnx_available,
        issues=(),
    )
    return replace(base, issues=_collect_issues(base))


def format_diagnostic_report(report: CineSegmentDiagnosticReport) -> str:
    lines = [
        f"source: {report.source_path or '(array)'} frame={report.frame_index}",
        f"shape: {report.frame_shape[1]}x{report.frame_shape[0]} media={report.media_format}",
        f"ROI xyxy: {report.roi_xyxy}",
        f"crop: mode={report.crop_mode} y0={report.crop_y0} x0={report.crop_x0} "
        f"h={report.crop_height} w={report.crop_width}",
        f"ONNX available: {report.onnx_available}",
        f"mask: {report.mask_pixels} px bbox={report.mask_bbox} centroid={report.mask_centroid_xy}",
        f"annulus_y={report.annulus_mid_y} apex_y={report.apex_y} "
        f"arc_pts={report.arc_point_count} span={report.arc_span_px} depth={report.arc_depth_px}",
        f"reject: {report.reject_reason}",
    ]
    if report.issues:
        lines.append("issues:")
        lines.extend(f"  - {issue}" for issue in report.issues)
    return "\n".join(lines)


def load_video_frame(path: Path, frame_index: int) -> np.ndarray:
    reader = get_thread_video_reader()
    reader.open(path)
    try:
        return reader.read_frame(frame_index)
    finally:
        reader.release()


def render_diagnostic_overlay(
    frame: np.ndarray,
    *,
    roi_xyxy: tuple[float, float, float, float] | None,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """BGR overlay: green ROI, red mask contour."""
    if frame.ndim == 2:
        canvas = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        canvas = np.asarray(frame).copy()
        if canvas.shape[2] == 3:
            canvas = cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)
    if roi_xyxy is not None:
        x0, y0, x1, y1 = [int(round(v)) for v in roi_xyxy]
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 255, 0), 2)
    if mask is not None and np.any(mask):
        contours, _ = cv2.findContours(
            (mask > 0).astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_NONE,
        )
        cv2.drawContours(canvas, contours, -1, (0, 0, 255), 1)
    return canvas


def diagnose_video_file(
    path: Path,
    *,
    frame_index: int = 0,
    run_onnx: bool = True,
    freeze_roi_from_frame: int | None = None,
) -> CineSegmentDiagnosticReport:
    frozen_roi = None
    if freeze_roi_from_frame is not None:
        anchor = load_video_frame(path, freeze_roi_from_frame)
        frozen_roi = resolve_segment_roi_xyxy(anchor, media_format="mp4")
    frame = load_video_frame(path, frame_index)
    return diagnose_cine_frame(
        frame,
        media_format="mp4",
        source_path=str(path),
        frame_index=frame_index,
        run_onnx=run_onnx,
        frozen_roi_xyxy=frozen_roi,
    )
