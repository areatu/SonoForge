"""AHA segment assignment and GLS aggregation for apical views."""

from __future__ import annotations

import math

import numpy as np

from echo_personal_tool.domain.models.speckle import TrackingKernel

# A4C visible segments (simplified 6 segments for apical 4-ch)
A4C_SEGMENT_NAMES = {
    1: "Basal septal",
    2: "Basal lateral",
    3: "Mid septal",
    4: "Mid lateral",
    5: "Apical septal",
    6: "Apical lateral",
}


def _angle_deg_from_center(center: tuple[float, float], point: tuple[float, float]) -> float:
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _a4c_angle_to_segment(angle_deg: float) -> int:
    """Map angle (degrees from LV center, image coords) to A4C segment 1-6."""
    if angle_deg >= 300.0 or angle_deg < 60.0:
        return 1
    if angle_deg < 120.0:
        return 2
    if angle_deg < 180.0:
        return 3
    if angle_deg < 240.0:
        return 4
    if angle_deg < 270.0:
        return 5
    return 6


def assign_aha_segments(
    kernels: list[TrackingKernel],
    lv_center: tuple[float, float],
    view: str = "A4C",
) -> list[TrackingKernel]:
    """Return new kernels with aha_segment and arc_length_param set based on angle from lv_center."""
    if view != "A4C":
        return list(kernels)

    assigned: list[TrackingKernel] = []
    for kernel in kernels:
        if kernel.layer != "endo":
            assigned.append(kernel)
            continue

        angle_deg = _angle_deg_from_center(lv_center, kernel.center)
        segment = _a4c_angle_to_segment(angle_deg)
        arc_length_param = angle_deg / 360.0
        assigned.append(
            TrackingKernel(
                center=kernel.center,
                radius=kernel.radius,
                node_index=kernel.node_index,
                layer=kernel.layer,
                aha_segment=segment,
                arc_length_param=arc_length_param,
            )
        )
    return assigned


def compute_aha_segment_strain(
    per_kernel_strain: np.ndarray,
    kernels: list[TrackingKernel],
    ncc_scores: np.ndarray,
) -> tuple[dict[int, float], dict[int, float]]:
    """Return (segment_strain, segment_quality).

    Per-segment strain is the **mean** of the strains of the endocardial
    kernels that belong to the segment (a single mis-tracked kernel must not
    dominate the segmental value). Per-segment quality is the mean NCC of those
    same kernels. Epicardial kernels (layer != "endo") are excluded.
    """
    segment_strains: dict[int, list[float]] = {}
    segment_ncc: dict[int, list[float]] = {}

    for idx, kernel in enumerate(kernels):
        if kernel.layer != "endo" or kernel.aha_segment <= 0:
            continue
        seg = kernel.aha_segment
        segment_strains.setdefault(seg, []).append(float(per_kernel_strain[idx]))
        segment_ncc.setdefault(seg, []).append(float(ncc_scores[idx]))

    segment_strain = {seg: float(np.mean(values)) for seg, values in segment_strains.items()}
    segment_quality = {seg: float(np.mean(values)) for seg, values in segment_ncc.items()}
    return segment_strain, segment_quality


def compute_gls_from_segments(
    segment_strain: dict[int, float],
    segment_quality: dict[int, float],
    min_quality: float = 0.4,
) -> float:
    """Clinical GLS as the mean of the segmental strains passing the quality gate.

    Segments whose quality is below ``min_quality`` are excluded; if none pass,
    the mean over all measured segments is used. Returns 0.0 when no segment
    strains are available.
    """
    if not segment_strain:
        return 0.0

    passing = [strain for seg, strain in segment_strain.items() if segment_quality.get(seg, 0.0) >= min_quality]
    if not passing:
        passing = list(segment_strain.values())
    return float(np.mean(passing))


def choose_clinical_gls(
    curve_gls: float,
    segment_strain: dict[int, float],
    segment_quality: dict[int, float],
    min_segment_quality: float = 0.4,
    min_segments: int = 3,
) -> tuple[float, str]:
    """Pick the GLS to report from the curve-based and segment-based estimates.

    The curve-based GLS (peak of the global strain curve between ED and ES) is
    used as the primary value unless at least ``min_segments`` segments have
    acceptable quality — then the clinical segment-mean GLS replaces it. This
    avoids reporting the single worst segment (old ``np.min`` behaviour) and
    also avoids trusting segments when coverage is too low.

    Returns ``(gls, source)`` where source is ``"curve"`` or ``"segments"``.
    """
    if not segment_strain or not segment_quality:
        return curve_gls, "curve"
    passing = [seg for seg, q in segment_quality.items() if q >= min_segment_quality]
    if len(passing) < min_segments:
        return curve_gls, "curve"
    values = [segment_strain[seg] for seg in passing if seg in segment_strain]
    if not values:
        return curve_gls, "curve"
    seg_gls = float(np.mean(values))
    if seg_gls == 0.0:
        return curve_gls, "curve"
    return seg_gls, "segments"
