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
in (А.1, #639): the physician traces the free wall — tricuspid-annulus corner
toward the apex — with the freehand line tool, and the trace is stored as its
own contour kind (``RV_FREE_WALL_CHAMBER``, ``"RV_FW"``) so an area/volume
trace of the RV cavity (the FAC tool) can never be mistaken for the wall.

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

    Only traces of this chamber kind (:data:`RV_FREE_WALL_CHAMBER`) on this
    clip and view are usable — a cavity area trace of the FAC tool has the
    same chamber family but a different ``chamber`` id and is never selected.
    An accepted ED trace wins over ES (the strain reference is ED); a trace
    without a frame index cannot anchor the tracker and is skipped.
    """
    best: tuple[np.ndarray, int] | None = None
    best_rank: tuple[int, int] | None = None
    wanted_view = str(view or "A4C").upper()
    for contour in contours:
        if contour.chamber.upper() != RV_FREE_WALL_CHAMBER or contour.review_pending:
            continue
        if contour.view.upper() != wanted_view:
            continue
        if sop_instance_uid and (contour.sop_instance_uid or "") != sop_instance_uid:
            continue
        if contour.frame_index is None or len(contour.points) < MIN_ARC_POINTS:
            continue
        phase_rank = 0 if contour.phase.casefold() == "ed" else (1 if contour.phase.casefold() == "es" else 2)
        rank = (phase_rank, -contour.frame_index)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = (np.asarray(contour.points, dtype=np.float64), int(contour.frame_index))
    return best
