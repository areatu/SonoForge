"""RV strain — free-wall GLS (plan А.7, issue #645).

The right ventricle is measured the way the left one is (:mod:`strain_computation`)
and the way the LA roof already is (:mod:`la_strain`): kernels ride the drawn
free-wall line (:mod:`arc_strain`), the strain is the Lagrangian length change
of that line against its end-diastole length, and the clinical number is the
**RV GLS** — the peak negative strain of the free wall between ventricular ED
(MVc/TRc reference frame, ED from the А.3/А.4 phase route) and end-systole.
Healthy free walls read roughly −20…−30 %; the value is reported with its
sign, consistent with the LV GLS convention of this application.

The contour is *manual* while view recognition for the RV-focused view is not
in (А.1, #639): the physician either traces the free wall — tricuspid-annulus
corner toward the apex — with the freehand line tool (its own contour kind,
``RV_FREE_WALL_CHAMBER``, ``"RV_FW"``), or reuses the **closed RV cavity
contour of the FAC tool** (chamber ``RV``): the free-wall side of that border
is then derived geometrically from the LV cavity of the same clip (the septum
faces the LV). The dedicated trace always wins when both exist — it was drawn
for strain.

Honest limits, the same as the LA arc: the endpoints (annulus corner, apex)
track like any other node — a drifting endpoint bends the whole curve, so the
tracking quality travels with the number; the burned-ECG strip (А.5) is not
applied to the arc kernels (no mask hook in the bidirectional tracker) — a
clip whose strip covers the free wall must not run RV strain, and the caller
decides. When ES was not resolved the metric is not produced at all — a
systolic peak searched over a window that has no end-systole is not a
measurement.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from echo_personal_tool.domain.models.contour import RV_FREE_WALL_CHAMBER, Contour
from echo_personal_tool.domain.models.speckle import RvStrainMetrics, SpeckleConfig
from echo_personal_tool.domain.services.arc_strain import MIN_ARC_POINTS, track_arc

#: Below this peak the wall did not measurably shorten in systole: still a
#: measurement (akinesia, a phantom, a failed track), but the report must say
#: so instead of presenting ≈0 as a strain value.
NO_SHORTENING_PEAK_PCT = -1.0


def compute_rv_gls(
    strain: np.ndarray,
    *,
    ed_index: int,
    es_index: int,
) -> RvStrainMetrics | None:
    """Peak negative free-wall strain between ventricular ED and ES.

    Only finite samples of the window compete — a lost frame never wins the
    peak. Returns ``None`` when the window is too short to be systole or has
    no finite sample at all; no number is invented from an empty curve. A peak
    above :data:`NO_SHORTENING_PEAK_PCT` comes back with the
    ``rv_strain.no_systolic_shortening`` warning (the value stays — it is
    measured, just ≈0).
    """
    curve = np.asarray(strain, dtype=np.float64)
    n = curve.size
    start = int(np.clip(int(ed_index), 0, n - 1))
    end = int(np.clip(int(es_index), 0, n - 1))
    if end - start < MIN_ARC_POINTS:
        return None
    window = curve[start : end + 1]
    finite = np.flatnonzero(np.isfinite(window))
    if finite.size == 0:
        return None
    offset = int(finite[np.argmin(window[finite])])
    gls_pct = float(window[offset])
    gls_index = start + offset
    warnings: list[str] = []
    if gls_pct > NO_SHORTENING_PEAK_PCT:
        warnings.append("rv_strain.no_systolic_shortening")
    return RvStrainMetrics(gls_pct=gls_pct, gls_index=gls_index, warnings=tuple(warnings))


def track_rv_free_wall(
    frames: np.ndarray,
    wall_points: np.ndarray,
    anchor_index: int,
    config: SpeckleConfig,
    *,
    kernel_radius: int,
) -> tuple[np.ndarray, float, float] | None:
    """Track the drawn free wall through the window from the contour's frame.

    Thin chamber-named alias of :func:`arc_strain.track_arc` so the worker
    reads chamber-first; returns ``(positions, ncc_mean, valid_fraction)`` or
    ``None`` when the trace is too short to track.
    """
    return track_arc(frames, wall_points, anchor_index, config, kernel_radius=kernel_radius)


def select_rv_free_wall_contour(
    contours: Iterable[Contour],
    *,
    sop_instance_uid: str | None,
    view: str,
) -> tuple[np.ndarray, int] | None:
    """The RV free-wall trace to track on one clip, or ``None``.

    Priority (user feedback, А.7 follow-up):

    1. an explicit free-wall trace (``RV_FW``) — the strain-dedicated tool;
    2. **the FAC-style closed RV cavity contour** (chamber ``RV``), whose
       free-wall side is *derived* geometrically — the arc of the cavity
       border facing away from the LV cavity of the same clip (the septum is
       the LV-facing side). Without an accepted LV contour on the same clip
       the septal side cannot be told from the free wall, so the fallback
       does nothing instead of guessing.

    Only contours of this clip and view are usable — a cavity trace drawn on
    another clip sits on different pixel motion. An accepted ED contour wins
    over ES (the strain reference is ED); a contour without a frame index
    cannot anchor the tracker and is skipped.
    """
    best: tuple[np.ndarray, int] | None = None
    best_rank: tuple[int, int] | None = None
    wanted_view = str(view or "A4C").upper()
    usable = _usable_contours(contours, wanted_view=wanted_view, sop_instance_uid=sop_instance_uid)
    for contour, frame in usable:
        if contour.chamber.upper() != RV_FREE_WALL_CHAMBER:
            continue
        if len(contour.points) < MIN_ARC_POINTS:
            continue
        phase_rank = 0 if contour.phase.casefold() == "ed" else (1 if contour.phase.casefold() == "es" else 2)
        rank = (phase_rank, -frame)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = (np.asarray(contour.points, dtype=np.float64), int(frame))
    if best is not None:
        return best
    # Fallback: the FAC-style closed cavity contour + the same clip's LV
    # cavity → the free wall is the arc facing away from the LV.
    cavity = _best_cavity_contour(usable, chamber="RV", min_points=MIN_CAVITY_POINTS)
    if cavity is None:
        return None
    (cavity_points, cavity_frame), _ = cavity
    lv = _best_cavity_contour(usable, chamber="LV", min_points=MIN_ARC_POINTS)
    if lv is None:
        return None
    lv_centroid = lv[0][0].mean(axis=0)
    arc = free_wall_arc_from_cavity(cavity_points, lv_centroid)
    if arc is None:
        return None
    return (arc, cavity_frame)


def _usable_contours(
    contours: Iterable[Contour],
    *,
    wanted_view: str,
    sop_instance_uid: str | None,
) -> list[tuple[Contour, int]]:
    """Contours of this clip and view with a resolvable frame index."""
    usable: list[tuple[Contour, int]] = []
    for contour in contours:
        if contour.review_pending:
            continue
        if contour.view.upper() != wanted_view:
            continue
        if sop_instance_uid and (contour.sop_instance_uid or "") != sop_instance_uid:
            continue
        if contour.frame_index is None:
            continue
        usable.append((contour, int(contour.frame_index)))
    return usable


def _best_cavity_contour(
    usable: Iterable[tuple[Contour, int]],
    *,
    chamber: str,
    min_points: int,
) -> tuple[tuple[np.ndarray, int], tuple[Contour, int]] | None:
    """The best (ED first) accepted cavity contour of one chamber kind."""
    best: tuple[tuple[Contour, int], tuple[int, int]] | None = None
    for contour, frame in usable:
        if contour.chamber.upper() != chamber or len(contour.points) < min_points:
            continue
        phase_rank = 0 if contour.phase.casefold() == "ed" else (1 if contour.phase.casefold() == "es" else 2)
        rank = (phase_rank, -frame)
        if best is None or rank < best[1]:
            best = ((contour, frame), rank)
    if best is None:
        return None
    contour, frame = best[0]
    return ((np.asarray(contour.points, dtype=np.float64), frame), (contour, frame))


#: A cavity outline with fewer points cannot yield a meaningful free-wall arc.
MIN_CAVITY_POINTS = 8

#: The derived free-wall arc must be a real arc, not two stray points: below
#: this the extraction found no coherent wall (a degenerate contour) and
#: strain from it would be a fabrication.
MIN_FREE_WALL_ARC_POINTS = 6


def free_wall_arc_from_cavity(cavity: np.ndarray, lv_centroid: np.ndarray) -> np.ndarray | None:
    """The free-wall arc of a closed RV cavity contour, or ``None``.

    The septum is the cavity side that faces the LV: with the centroids of
    both cavities the septal direction is the unit vector from the RV
    centroid toward the LV centroid.  The free wall is the longest contiguous
    run of border points on the *far* side of that axis, kept in contour
    order — the same endocardial border a dedicated free-wall trace would
    follow, derived instead of re-drawn.  A degenerate input (no usable LV
    separation, no coherent arc) returns ``None``: a guessed wall would
    fabricate a strain value.
    """
    points = np.asarray(cavity, dtype=np.float64)
    if points.ndim != 2 or points.shape[0] < MIN_CAVITY_POINTS or points.shape[1] != 2:
        return None
    lv = np.asarray(lv_centroid, dtype=np.float64).reshape(2)
    rv_centroid = points.mean(axis=0)
    axis = lv - rv_centroid
    norm = float(np.hypot(*axis))
    if not np.isfinite(norm) or norm < 1e-6:
        return None
    axis /= norm
    projection = (points - rv_centroid) @ axis
    far = projection < 0.0
    if not far.any() or far.all():
        return None
    # Longest circular run of "far" points, in contour order (the contour is
    # a closed loop, so the run may wrap around the end).
    n = points.shape[0]
    doubled = np.concatenate([far, far])
    best_start, best_len, run = 0, 0, 0
    for index in range(2 * n):
        if doubled[index]:
            run += 1
            if run > best_len:
                best_len, best_start = run, index - run + 1
        else:
            run = 0
    best_len = min(best_len, n)
    if best_len < MIN_FREE_WALL_ARC_POINTS:
        return None
    return np.asarray(points[np.arange(best_start, best_start + best_len) % n], dtype=np.float64)
