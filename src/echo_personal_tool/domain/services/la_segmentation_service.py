"""LA mask → open-arc contour + quality gate (A4C ES only)."""

from __future__ import annotations

import logging
import math

import numpy as np
from scipy import ndimage

logger = logging.getLogger(__name__)

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.bench_metrics import mask_iou
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    resample_open_arc_landmarks,
    smooth_open_arc,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    _ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
    _warp_superellipse_open_arc,
)
from echo_personal_tool.infrastructure.i18n import tr

# ---------------------------------------------------------------------------
# Quality-gate thresholds
# ---------------------------------------------------------------------------
_MIN_LA_MASK_AREA_PX = 200
_MIN_LA_MV_SPAN_MM = 3.0
_MIN_LA_LONG_AXIS_PX = 10.0
_MAX_LA_ELLIPSE_RESIDUAL = 0.35


# ---------------------------------------------------------------------------
# Landmark extraction from binary mask
# ---------------------------------------------------------------------------


def _largest_component(binary: np.ndarray) -> np.ndarray:
    labeled, count = ndimage.label(binary)
    if count == 0:
        return binary
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    return labeled == int(np.argmax(counts))


def _la_landmarks_from_mask(
    mask: np.ndarray,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Extract MV septal/lateral + roof apex from LA binary mask.

    LA on A4C: MV annulus is at the **inferior** (bottom) of the cavity bbox,
    roof apex is at the **superior** (top).
    """
    binary = np.asarray(mask) > 0
    ys, xs = np.where(binary)
    if ys.size == 0:
        msg = "empty LA mask"
        raise ValueError(msg)

    y_min = int(ys.min())
    y_max = int(ys.max())
    height = y_max - y_min + 1

    # --- MV annulus: inferior 15-20% of mask bbox (widest horizontal span) ---
    band_depth = max(3, int(round(0.18 * height)))
    inferior_band = (y_max - band_depth, y_max)
    band_xs = xs[(ys >= inferior_band[0]) & (ys <= inferior_band[1])]
    band_ys = ys[(ys >= inferior_band[0]) & (ys <= inferior_band[1])]
    if band_xs.size < 2:
        # fallback: wider band (25%)
        band_depth = max(3, int(round(0.25 * height)))
        inferior_band = (y_max - band_depth, y_max)
        band_xs = xs[(ys >= inferior_band[0]) & (ys <= inferior_band[1])]
        band_ys = ys[(ys >= inferior_band[0]) & (ys <= inferior_band[1])]
    if band_xs.size < 2:
        msg = "cannot locate MV annulus on LA mask"
        raise ValueError(msg)

    # Septal = leftmost X in band, Lateral = rightmost X in band
    trim_pct = 10.0
    x_cut_low = float(np.percentile(band_xs, trim_pct))
    x_cut_high = float(np.percentile(band_xs, 100.0 - trim_pct))
    septal_mask = band_xs <= x_cut_low
    lateral_mask = band_xs >= x_cut_high
    if np.any(septal_mask):
        septal = (
            float(np.mean(band_xs[septal_mask])),
            float(np.mean(band_ys[septal_mask])),
        )
    else:
        idx = int(np.argmin(band_xs))
        septal = (float(band_xs[idx]), float(band_ys[idx]))
    if np.any(lateral_mask):
        lateral = (
            float(np.mean(band_xs[lateral_mask])),
            float(np.mean(band_ys[lateral_mask])),
        )
    else:
        idx = int(np.argmax(band_xs))
        lateral = (float(band_xs[idx]), float(band_ys[idx]))
    if septal[0] > lateral[0]:
        septal, lateral = lateral, septal

    # --- Roof apex: superior margin median ---
    apex_band_depth = max(3, int(round(0.10 * height)))
    superior_band = (y_min, y_min + apex_band_depth)
    apex_ys = ys[(ys >= superior_band[0]) & (ys <= superior_band[1])]
    apex_xs = xs[(ys >= superior_band[0]) & (ys <= superior_band[1])]
    if apex_xs.size > 0:
        apex = (float(np.median(apex_xs)), float(np.median(apex_ys)))
    else:
        # Fallback: median of all mask points above midpoint
        mid_y = (y_min + y_max) / 2.0
        above = ys < mid_y
        if np.any(above):
            apex = (float(np.median(xs[above])), float(np.median(ys[above])))
        else:
            apex = (float(np.median(xs)), float(y_min + 5))

    return septal, lateral, apex


# ---------------------------------------------------------------------------
# Landmark blending: AI mask + user clicks
# ---------------------------------------------------------------------------


def la_landmarks_from_mask_or_user(
    mask: np.ndarray,
    *,
    user_septal: tuple[float, float] | None = None,
    user_lateral: tuple[float, float] | None = None,
    user_apex: tuple[float, float] | None = None,
    blend_factor: float = 0.7,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Extract LA landmarks from AI mask, optionally blending with user clicks.

    Returns (septal, lateral, apex). If user landmarks are None,
    uses pure AI landmarks. Otherwise blends: result = AI * blend_factor + user * (1 - blend_factor).
    """
    component = _largest_component(np.asarray(mask) > 0)
    ai_septal, ai_lateral, ai_apex = _la_landmarks_from_mask(component)

    if user_septal is None or user_lateral is None or user_apex is None:
        return ai_septal, ai_lateral, ai_apex

    def _blend(
        ai: tuple[float, float],
        user: tuple[float, float],
        w: float,
    ) -> tuple[float, float]:
        return (
            ai[0] * w + user[0] * (1 - w),
            ai[1] * w + user[1] * (1 - w),
        )

    return (
        _blend(ai_septal, user_septal, blend_factor),
        _blend(ai_lateral, user_lateral, blend_factor),
        _blend(ai_apex, user_apex, blend_factor),
    )


# ---------------------------------------------------------------------------
# Mask boundary → open-arc contour
# ---------------------------------------------------------------------------


def la_mask_boundary_to_open_arc(
    mask: np.ndarray,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]] | None:
    """Extract open-arc contour from LA mask boundary.

    Uses the natural contour order from cv2.findContours (walks the perimeter).
    Splits the closed contour at the two points nearest septal/lateral,
    picks the arc whose midpoint is closest to apex (superior arc).
    Returns None if boundary extraction fails.
    """
    import cv2

    binary = np.asarray(mask, dtype=np.uint8)
    if binary.max() == 0:
        logger.warning("[LA-boundary] mask is empty (all zeros)")
        return None

    component = _largest_component(binary > 0).astype(np.uint8)
    pixel_count = int(component.sum())
    if pixel_count < _MIN_LA_MASK_AREA_PX:
        logger.warning("[LA-boundary] mask too small: %d < %d", pixel_count, _MIN_LA_MASK_AREA_PX)
        return None

    contours_cv, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours_cv:
        logger.warning("[LA-boundary] cv2.findContours returned empty")
        return None

    boundary = max(contours_cv, key=cv2.contourArea)
    pts = [(float(p[0][0]), float(p[0][1])) for p in boundary]
    if len(pts) < 4:
        logger.warning("[LA-boundary] boundary too short: %d pts", len(pts))
        return None

    # Find the two indices on the perimeter closest to septal and lateral
    def _nearest_idx(target: tuple[float, float]) -> int:
        best, best_d = 0, float("inf")
        for i, p in enumerate(pts):
            d = (p[0] - target[0]) ** 2 + (p[1] - target[1]) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    s_idx = _nearest_idx(septal)
    l_idx = _nearest_idx(lateral)
    if s_idx == l_idx:
        logger.warning("[LA-boundary] s_idx == l_idx (%d)", s_idx)
        return None

    n = len(pts)

    # The perimeter walk goes s_idx → s_idx+1 → ... → l_idx (forward arc)
    # and l_idx → l_idx+1 → ... → s_idx (backward arc).
    # Pick the arc whose midpoint is nearest to the apex (superior).
    def _arc_mid(a: int, b: int) -> tuple[float, float]:
        """Midpoint of the arc walking from a to b along the perimeter."""
        if a < b:
            arc = pts[a : b + 1]
        else:
            arc = pts[a:] + pts[: b + 1]
        mx = sum(p[0] for p in arc) / len(arc)
        my = sum(p[1] for p in arc) / len(arc)
        return mx, my

    fwd_mid = _arc_mid(s_idx, l_idx)
    fwd_dist = (fwd_mid[0] - apex[0]) ** 2 + (fwd_mid[1] - apex[1]) ** 2
    bwd_mid = _arc_mid(l_idx, s_idx)
    bwd_dist = (bwd_mid[0] - apex[0]) ** 2 + (bwd_mid[1] - apex[1]) ** 2

    if fwd_dist <= bwd_dist:
        arc_pts = pts[s_idx : l_idx + 1] if s_idx < l_idx else pts[s_idx:] + pts[: l_idx + 1]
    else:
        arc_pts = pts[l_idx : s_idx + 1] if l_idx < s_idx else pts[l_idx:] + pts[: s_idx + 1]

    if len(arc_pts) < 3:
        logger.warning("[LA-boundary] arc too short: %d pts", len(arc_pts))
        return None

    logger.warning(
        "[LA-boundary] OK: boundary=%d pts, arc=%d pts, s_idx=%d, l_idx=%d, "
        "septal=%s, lateral=%s, apex=%s",
        n, len(arc_pts), s_idx, l_idx, septal, lateral, apex,
    )

    resampled = resample_open_arc_landmarks(
        arc_pts,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=num_nodes,
    )
    resampled[0] = septal
    resampled[-1] = lateral

    smoothed = smooth_open_arc(
        resampled,
        (septal, lateral),
        apex=apex,
        iterations=3,
        blend=0.45,
        taubin=True,
    )
    smoothed[0] = septal
    smoothed[-1] = lateral
    return smoothed


# ---------------------------------------------------------------------------
# la_mask_to_contour — main public API
# ---------------------------------------------------------------------------


def la_mask_to_contour(
    mask: np.ndarray,
    *,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> tuple[
    list[tuple[float, float]],
    tuple[tuple[float, float], tuple[float, float]],
    tuple[float, float],
]:
    """Convert binary LA mask to open-arc contour via elliptical template.

    Returns (open_points, (septal, lateral), apex).

    Raises ValueError if mask is empty or landmarks cannot be extracted.
    """
    binary = np.asarray(mask) > 0
    if not binary.any():
        msg = "empty LA mask"
        raise ValueError(msg)

    component = _largest_component(binary)
    septal, lateral, apex = _la_landmarks_from_mask(component)

    # Try mask boundary extraction first (follows actual LA shape)
    logger.warning("[LA-mask2contour] calling boundary extraction, mask dtype=%s, shape=%s, pixels=%d",
                   component.dtype, component.shape, int(component.sum()))
    print(f"[LA-DEBUG] la_mask_to_contour called: mask_pixels={int(component.sum())}, "
          f"septal={septal}, lateral={lateral}, apex={apex}", flush=True)
    # Write to /tmp for debugging even if stdout is hidden
    try:
        with open("/tmp/la_boundary_debug.log", "a") as _dbg:
            _dbg.write(f"la_mask_to_contour called: pixels={int(component.sum())}, "
                       f"septal={septal}, lateral={lateral}, apex={apex}\n")
    except Exception:
        pass
    boundary_result = la_mask_boundary_to_open_arc(
        component,
        septal,
        lateral,
        apex,
        num_nodes=num_nodes,
    )
    if boundary_result is not None:
        logger.warning("[LA-mask2contour] boundary extraction SUCCEEDED, %d pts", len(boundary_result))
        print(f"[LA-DEBUG] boundary extraction SUCCEEDED: {len(boundary_result)} pts", flush=True)
        try:
            with open("/tmp/la_boundary_debug.log", "a") as _dbg:
                _dbg.write(f"boundary extraction SUCCEEDED: {len(boundary_result)} pts\n")
        except Exception:
            pass
        return boundary_result, (septal, lateral), apex
    logger.warning("[LA-mask2contour] boundary extraction FAILED → superellipse fallback")
    print("[LA-DEBUG] boundary extraction FAILED → superellipse fallback", flush=True)
    try:
        with open("/tmp/la_boundary_debug.log", "a") as _dbg:
            _dbg.write("boundary extraction FAILED → superellipse fallback\n")
    except Exception:
        pass

    # Fallback: superellipse template (geometric approximation)
    template = _warp_superellipse_open_arc(
        septal,
        lateral,
        apex,
        num_points=81,
        short_axis_ratio=_ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
    )
    resampled = resample_open_arc_landmarks(
        template,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=num_nodes,
    )
    # Force endpoints to MV landmarks
    resampled[0] = septal
    resampled[-1] = lateral
    return resampled, (septal, lateral), apex


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def _mask_ellipse_fit_residual(mask: np.ndarray, contour: Contour) -> float:
    """1 − IoU(mask, filled contour polygon), normalized ellipse-fit error."""
    binary = np.asarray(mask) > 0
    if not binary.any() or len(contour.points) < 3:
        return 0.0
    import cv2

    filled = np.zeros(binary.shape[:2], dtype=np.uint8)
    pts = np.array(contour.closed_polygon_points(), dtype=np.int32)
    if len(pts) < 3:
        return 0.0
    cv2.fillPoly(filled, [pts], 1)
    return 1.0 - mask_iou(binary.astype(np.uint8), filled)


def explain_la_auto_reject_reason(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    mask_pixels: int | None = None,
    mask: np.ndarray | None = None,
    roi_xyxy: tuple[float, float, float, float] | None = None,
) -> str | None:
    """Return a short Russian reason when LA auto contour should not enter review."""
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return tr("domain.la_seg.no_contour")

    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark

    # MV span (pixel distance)
    mv_span_px = math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])
    if mv_span_px < 5.0:
        return tr("domain.la_seg.no_annulus")

    # Spacing-aware MV span check
    if pixel_spacing is not None:
        row_spacing, col_spacing = pixel_spacing
        if row_spacing > 0 and col_spacing > 0:
            mv_span_mm = mv_span_px * ((row_spacing + col_spacing) / 2.0)
            if mv_span_mm < _MIN_LA_MV_SPAN_MM:
                return tr("domain.la_seg.annulus_too_small", mv_span_mm=mv_span_mm, min_mm=_MIN_LA_MV_SPAN_MM)

    # Apex must be above MV chord (image Y: smaller Y = superior)
    ma_mid_y = (septal[1] + lateral[1]) / 2.0
    if apex is not None and apex[1] >= ma_mid_y + 10.0:
        return tr("domain.la_seg.inverted")

    # Long axis: MA midpoint → apex
    if apex is not None:
        ma_mid_x = (septal[0] + lateral[0]) / 2.0
        long_axis_px = math.hypot(apex[0] - ma_mid_x, apex[1] - ma_mid_y)
        if long_axis_px < _MIN_LA_LONG_AXIS_PX:
            return tr("domain.la_seg.axis_too_short")

    # Mask area gate
    if mask_pixels is not None and mask_pixels < _MIN_LA_MASK_AREA_PX:
        return tr("domain.la_seg.cavity_too_small", pixels=str(mask_pixels), min_px=str(_MIN_LA_MASK_AREA_PX))

    if mask is not None:
        residual = _mask_ellipse_fit_residual(mask, contour)
        if residual > _MAX_LA_ELLIPSE_RESIDUAL:
            return tr("domain.la_seg.mask_irregular", residual=residual, max_residual=_MAX_LA_ELLIPSE_RESIDUAL)

    # Centroid outside ROI
    if roi_xyxy is not None and len(contour.points) >= 3:
        xs = [p[0] for p in contour.points]
        ys = [p[1] for p in contour.points]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        rx0, ry0, rx1, ry1 = roi_xyxy
        if not (rx0 <= cx <= rx1 and ry0 <= cy <= ry1):
            return tr("domain.la_seg.center_outside_roi")

    return None
