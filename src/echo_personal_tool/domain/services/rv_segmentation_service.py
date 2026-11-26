"""Review-only RV cavity proposals, bounded refinement and fail-closed QC (ML.3).

The atlas describes the cavity envelope: do not carve holes for trabeculae or
moderator band. This is not proof of clinical ASE agreement. No Qt/ML runtime.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.cardiac_atlas_geometry import edges_cross, polygon_interior


def _area(points: np.ndarray) -> float:
    return float(abs(np.sum(points[:, 0] * np.roll(points[:, 1], -1) - points[:, 1] * np.roll(points[:, 0], -1))) / 2)


def _inside_sector(points: np.ndarray, mask: np.ndarray) -> bool:
    # Sample entire segments, not only vertices: a free wall can cross a cutout.
    samples = []
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        count = max(2, int(np.ceil(np.linalg.norm(b - a) * 2)) + 1)
        samples.append(np.linspace(a, b, min(count, 4096)))
    dense = np.vstack(samples)
    h, w = mask.shape
    if np.any(dense < 0) or np.any(dense[:, 0] > w - 1) or np.any(dense[:, 1] > h - 1):
        return False
    safe = ndimage.binary_erosion(mask, iterations=1, border_value=0)
    x, y = np.rint(dense).astype(int).T
    return bool(safe[y, x].all())


def explain_rv_auto_reject_reason(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    frame_shape: tuple[int, int],
    sector_mask: np.ndarray | None,
    lv_contour: Contour | None,
    confidence: float = 1.0,
) -> str | None:
    """Stable reason codes, deliberately broad safety limits, NOT normal ranges."""
    if contour.chamber != "RV" or contour.phase not in {"ED", "ES"} or contour.view not in {"A4C", "RV_A4C"}:
        return "unsupported_context"
    points = np.asarray(contour.points, dtype=float)
    if points.ndim != 2 or points.shape[1:] != (2,) or not 5 <= len(points) <= 1024 or not np.isfinite(points).all():
        return "invalid_contour"
    if not np.isfinite(confidence) or confidence < 0.5:
        return "low_confidence"
    if contour.mitral_annulus is None or contour.apex_landmark is None:
        return "missing_landmarks"
    anchors = np.asarray([*contour.mitral_annulus, contour.apex_landmark], dtype=float)
    if anchors.shape != (3, 2) or not np.isfinite(anchors).all():
        return "missing_landmarks"
    if not np.allclose(points[[0, -1]], anchors[:2], atol=1e-4):
        return "annulus_mismatch"
    if np.min(np.linalg.norm(points - anchors[2], axis=1)) > 1e-4:
        return "apex_mismatch"
    if pixel_spacing is None:
        return "missing_calibration"
    spacing = np.asarray(pixel_spacing, dtype=float)
    if spacing.shape != (2,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
        return "invalid_calibration"
    # DICOM is (row, column); physical norm is not mean-spacing × pixel norm.
    chord = (anchors[1] - anchors[0]) * spacing[::-1]
    span_mm = float(np.linalg.norm(chord))
    if not 3 <= span_mm <= 90:
        return "annulus_span"
    axis = anchors[2] - anchors[:2].mean(axis=0)
    if np.linalg.norm(axis) < 3:
        return "short_axis"
    area = _area(points)
    if not 24 <= area <= frame_shape[0] * frame_shape[1] * 0.65:
        return "cavity_area"
    if edges_cross(points, points):
        return "self_intersection"
    if sector_mask is None:
        return "missing_sector"
    if sector_mask.shape != frame_shape or not np.isfinite(sector_mask).all():
        return "invalid_sector"
    if not _inside_sector(points, np.asarray(sector_mask, dtype=bool)):
        return "sector_clipped"
    if lv_contour is None:
        return "missing_lv_context"
    if (
        lv_contour.chamber != "LV"
        or lv_contour.view != contour.view
        or lv_contour.phase != contour.phase
        or lv_contour.frame_index != contour.frame_index
        or lv_contour.sop_instance_uid != contour.sop_instance_uid
    ):
        return "invalid_lv_context"
    lv = np.asarray(lv_contour.points, dtype=float)
    if lv.ndim != 2 or lv.shape[1:] != (2,) or len(lv) < 3 or not np.isfinite(lv).all():
        return "invalid_lv_context"
    if (
        edges_cross(points, lv)
        or polygon_interior(points, lv).any()
        or polygon_interior(lv, points).any()
        or polygon_interior(np.array([points.mean(axis=0)]), lv).any()
        or polygon_interior(np.array([lv.mean(axis=0)]), points).any()
    ):
        return "lv_overlap"
    septal_direction = anchors[2] - anchors[0]
    rv_delta, lv_delta = anchors[1] - anchors[0], lv.mean(axis=0) - anchors[0]
    rv_side = septal_direction[0] * rv_delta[1] - septal_direction[1] * rv_delta[0]
    lv_side = septal_direction[0] * lv_delta[1] - septal_direction[1] * lv_delta[0]
    if rv_side * lv_side >= 0:
        return "septal_orientation"
    return None


def build_rv_auto_contour(
    frame: np.ndarray,
    points: np.ndarray,
    *,
    annulus: tuple[tuple[float, float], tuple[float, float]],
    apex: tuple[float, float],
    phase: str,
    view: str,
    frame_index: int,
    pixel_spacing: tuple[float, float] | None,
    sector_mask: np.ndarray | None,
    lv_contour: Contour | None,
    confidence: float = 1.0,
    refine: bool = True,
) -> tuple[Contour | None, str | None]:
    """Preserve septum/anchors and dropout prior; never publish invalid clipped seeds."""
    initial = Contour(
        phase=phase,
        view=view,
        chamber="RV",
        points=[(float(p[0]), float(p[1])) for p in points],
        mitral_annulus=annulus,
        apex_landmark=apex,
        num_nodes=len(points),
        frame_index=frame_index,
        source="ai",
        review_pending=True,
    )

    def quality(contour: Contour) -> str | None:
        return explain_rv_auto_reject_reason(
            contour,
            pixel_spacing,
            frame_shape=(frame.shape[0], frame.shape[1]),
            sector_mask=sector_mask,
            lv_contour=lv_contour,
            confidence=confidence,
        )

    reason = quality(initial)
    if reason is not None:
        return None, reason
    if not refine:
        return initial, None
    gray = np.mean(frame[..., :3], axis=2) if frame.ndim == 3 else np.asarray(frame, dtype=float)
    gray = np.nan_to_num(gray)
    gray = (gray - gray.min()) / max(float(np.ptp(gray)), 1e-6)
    # Signed dark-blood -> bright-wall derivative, not gradient magnitude:
    # an inner bright trabecula's reverse edge must not attract the cavity wall.
    split = int(np.argmin(np.linalg.norm(points - np.asarray(apex), axis=1)))
    refined = points.copy()
    center = points.mean(axis=0)
    for index in range(split + 1, len(points) - 1):
        tangent = points[index + 1] - points[index - 1]
        normal = np.array([-tangent[1], tangent[0]])
        normal /= max(float(np.linalg.norm(normal)), 1e-8)
        if np.dot(normal, points[index] - center) < 0:
            normal = -normal
        offsets = np.linspace(-2, 2, 17)
        candidates = points[index] + offsets[:, None] * normal
        outside, inside = candidates + normal, candidates - normal
        contrast = ndimage.map_coordinates(
            gray, [outside[:, 1], outside[:, 0]], order=1, mode="nearest"
        ) - ndimage.map_coordinates(gray, [inside[:, 1], inside[:, 0]], order=1, mode="nearest")
        score = contrast - 0.04 * np.abs(offsets)  # explicit local shape prior
        best = int(np.argmax(score))
        if contrast[best] >= 0.15 and score[best] > 0.1:
            refined[index] = candidates[best]
    proposal = replace(initial, points=[(float(p[0]), float(p[1])) for p in refined])
    # A refinement cannot destroy valid geometry; rollback to the prior, not a clipped snake.
    if quality(proposal) is not None:
        return initial, None
    return proposal, None
