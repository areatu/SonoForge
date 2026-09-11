"""AHA segment assignment and GLS aggregation for apical views.

Segment assignment itself lives in :mod:`segment_map` (18-segment AHA model,
derived from the position along the material line and from the analysed view).
This module keeps the kernel-level API the worker and the UI already use, plus
the clinical GLS aggregation.
"""

from __future__ import annotations

import logging

import numpy as np

from echo_personal_tool.domain.models.speckle import TrackingKernel
from echo_personal_tool.domain.services.segment_map import (
    SEGMENT_NAMES,
    assign_segments_from_arc,
)

logger = logging.getLogger(__name__)

# Human-readable names for the six segments of a view (used by the UI panels).
A4C_SEGMENT_NAMES = {
    3: "Basal inferoseptal",
    9: "Mid inferoseptal",
    15: "Apical inferoseptal",
    6: "Basal anterolateral",
    12: "Mid anterolateral",
    18: "Apical anterolateral",
}


def _angle_deg_from_center(center: tuple[float, float], point: tuple[float, float]) -> float:
    """Legacy helper: angle of a point around the LV centroid (degrees)."""
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    return float(np.degrees(np.arctan2(dy, dx)) % 360.0)


def _a4c_angle_to_segment(angle_deg: float) -> int:
    """Legacy angular binning, kept only as a fallback for degenerate arcs.

    The angle from the *centroid* of an apical arc is not an anatomical
    coordinate — it is the defect behind issue #C2. It is used only when the
    arc cannot be built at all (e.g. fewer than three endocardial nodes), so
    that a result is still produced but flagged.
    """
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


def _arc_points_from_kernels(kernels: list[TrackingKernel]) -> tuple[np.ndarray, list[int]]:
    """Endocardial arc in node order: (points, kernel indices used)."""
    endo = [(i, k) for i, k in enumerate(kernels) if k.layer == "endo"]
    if len(endo) < 3:
        return np.empty((0, 2), dtype=np.float64), []
    endo.sort(key=lambda item: item[1].node_index)
    points = np.asarray([item[1].center for item in endo], dtype=np.float64)
    indices = [item[0] for item in endo]
    return points, indices


def assign_aha_segments(
    kernels: list[TrackingKernel],
    lv_center: tuple[float, float],
    view: str = "A4C",
    *,
    flip: bool = False,
) -> list[TrackingKernel]:
    """Return kernels with ``aha_segment``/``arc_length_param`` filled in.

    The segment of a kernel is derived from where its node sits **along the
    material line** (annulus → apex → annulus) and from the analysed ``view``
    (issue #C2). All layers of a node share the node's segment, so the
    epicardial and mid-wall kernels of one wall region report the same segment
    as the endocardium they belong to.

    ``flip`` declares a mirrored display (the view's first wall on the right of
    the screen instead of the left); the arc order itself does not matter,
    because :func:`assign_segments_from_arc` resolves the sides from the image.
    """
    points, endo_indices = _arc_points_from_kernels(kernels)
    if points.shape[0] < 3 or not np.all(np.isfinite(points)):
        logger.warning(
            "STE: cannot build the material line for segment assignment "
            "(endo nodes=%d) — falling back to the legacy angular binning",
            points.shape[0],
        )
        return _assign_aha_segments_angular(kernels, lv_center)

    try:
        assignment = assign_segments_from_arc(points, view, flip=flip)
    except ValueError as exc:
        logger.warning("STE: segment assignment failed (%s) — legacy fallback", exc)
        return _assign_aha_segments_angular(kernels, lv_center)

    segment_of_node = {kernels[idx].node_index: assignment.node_segments[pos] for pos, idx in enumerate(endo_indices)}
    param_of_node = {kernels[idx].node_index: assignment.arc_params[pos] for pos, idx in enumerate(endo_indices)}

    assigned: list[TrackingKernel] = []
    for kernel in kernels:
        node_segment = segment_of_node.get(kernel.node_index, 0)
        assigned.append(
            TrackingKernel(
                center=kernel.center,
                radius=kernel.radius,
                node_index=kernel.node_index,
                layer=kernel.layer,
                aha_segment=node_segment,
                arc_length_param=param_of_node.get(kernel.node_index, kernel.arc_length_param),
            )
        )
    logger.info(
        "STE segment map: view=%s flip=%s apex_node=%d segments=%s",
        view,
        flip,
        kernels[endo_indices[assignment.apex_index]].node_index if endo_indices else -1,
        sorted({k.aha_segment for k in assigned if k.aha_segment > 0}),
    )
    return assigned


def _assign_aha_segments_angular(
    kernels: list[TrackingKernel],
    lv_center: tuple[float, float],
) -> list[TrackingKernel]:
    """Deprecated angular assignment — fallback only (see :func:`assign_aha_segments`)."""
    assigned: list[TrackingKernel] = []
    for kernel in kernels:
        if kernel.layer != "endo":
            assigned.append(kernel)
            continue
        angle_deg = _angle_deg_from_center(lv_center, kernel.center)
        assigned.append(
            TrackingKernel(
                center=kernel.center,
                radius=kernel.radius,
                node_index=kernel.node_index,
                layer=kernel.layer,
                aha_segment=_a4c_angle_to_segment(angle_deg),
                arc_length_param=angle_deg / 360.0,
            )
        )
    return assigned


def segment_name(segment_id: int) -> str:
    """Canonical AHA name of a segment id (empty string for unknown ids)."""
    return SEGMENT_NAMES.get(int(segment_id), "")


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
