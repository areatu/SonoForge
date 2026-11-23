"""LA strain — reservoir / conduit / booster (plan А.6, issue #644).

The left atrium is tracked with the same speckle machinery as the LV wall
(:mod:`speckle_tracking`): kernels are sampled along the LA open-arc roof
contour (the one the LA-volume tool draws, ``la_segmentation_service``
contract), the tracker propagates them from an anchor frame to every frame of
the analysis window, and the strain is the Lagrangian arc-length change of the
tracked arc — the same definition A the LV GLS uses
(:func:`strain_computation.lagrangian_strain_pct`).

Phase convention (Badano/ASE): the curve is zeroed at *ventricular*
end-diastole (MVc — the LA is smallest right after its own contraction, and
reservoir filling starts there). The curve rises to its positive peak at
mitral-valve opening (reservoir), falls through early filling (conduit) and
goes negative during atrial contraction (booster), reaching its minimum at the
next MVC. The three clinical numbers:

* **LASr** (reservoir) — the peak positive strain of the beat;
* **LAScd** (conduit) — LASr minus the strain at the onset of atrial
  contraction (the end of the diastasis plateau);
* **LASct** (booster) — the strain at that onset minus the peak negative
  strain of the beat.

All three are reported as positive magnitudes. The A-onset is *measured* from
the curve (the last local maximum after the reservoir peak, after the
early-filling minimum); when the curve is too flat or noisy to show one, the
window fraction fallback states itself in ``warnings`` — nothing is silently
guessed. An MVO frame (from the А.9 valve events, when the LV strain supports
them) narrows the reservoir search window; without it the peak is searched
over the whole beat, which is where it physically sits anyway.

Honest limits: the arc endpoints are the mitral-annulus corners of the drawn
contour and they track like any other node — a drifting annulus corner bends
the whole curve, so the tracking quality travels with the numbers; the
burned-ECG strip (А.5) is not applied to LA kernels in the bidirectional
tracker (no mask hook there) — a clip whose strip covers the LA roof must not
run LA strain, and the caller decides (the controller passes the contour only
for clips without a strip overlap).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.speckle import LaStrainMetrics, SpeckleConfig, TrackingKernel
from echo_personal_tool.domain.services.arc_strain import (
    MIN_ARC_POINTS,
    arc_strain_curve,
    build_arc_kernels,
    track_arc,
)

#: A-onset fallback as a fraction of the reservoir-end → MVC window, used only
#: when the curve morphology cannot resolve the onset (stated in warnings).
A_ONSET_FALLBACK_FRACTION = 0.6
#: Minimum reservoir→end span (frames) for conduit/booster to be measurable.
MIN_DIASTOLE_FRAMES = 4


def build_la_arc_kernels(arc_points: np.ndarray, *, kernel_radius: int) -> list[TrackingKernel]:
    """One tracking kernel per LA-arc node, ordered along the open arc."""
    return build_arc_kernels(arc_points, kernel_radius=kernel_radius)


def track_la_arc(
    frames: np.ndarray,
    arc_points: np.ndarray,
    anchor_index: int,
    config: SpeckleConfig,
    *,
    kernel_radius: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[np.ndarray, float, float] | None:
    """Track the LA arc through the window, anchored at ``anchor_index``."""
    return track_arc(
        frames,
        arc_points,
        anchor_index,
        config,
        kernel_radius=kernel_radius,
        progress_callback=progress_callback,
    )


def compute_la_strain_curve(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
) -> np.ndarray:
    """Lagrangian arc-length strain of the tracked LA arc, zeroed at ``ed_index``.

    The LA strain zero sits at *ventricular* end-diastole (MVc) regardless of
    which frame anchored the kernels — the reference length is measured on
    the tracked positions at the ED frame.
    """
    return arc_strain_curve(positions, ed_index, pixel_spacing)


def _smooth_small(curve: np.ndarray, window: int = 3) -> np.ndarray:
    if curve.size < window:
        return curve
    kernel = np.ones(int(window), dtype=np.float64) / float(window)
    padded = np.pad(curve, (window // 2, window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: curve.size]


def detect_a_onset(
    strain: np.ndarray,
    *,
    reservoir_index: int,
    end_index: int,
) -> tuple[int | None, str]:
    """The last local maximum of the curve between the reservoir peak and MVC.

    The onset of atrial contraction ends the diastasis plateau; on the strain
    curve it is a local maximum after the early-filling minimum. Returns
    ``(index, source)`` with ``source`` ``"curve"`` or ``"none"`` — the caller
    decides whether the window-fraction fallback is acceptable and records it
    in the warnings.
    """
    strain = np.asarray(strain, dtype=np.float64)
    end = int(np.clip(int(end_index), 0, strain.size - 1))
    peak = int(np.clip(int(reservoir_index), 0, strain.size - 1))
    if end - peak < MIN_DIASTOLE_FRAMES:
        return None, "none"
    smoothed = _smooth_small(np.nan_to_num(strain, nan=0.0))
    segment = smoothed[peak : end + 1]
    if segment.size < 3:
        return None, "none"
    # Interior local maxima of the segment; the reservoir peak itself is
    # excluded by starting at +1 inside the segment.  The left comparison
    # accepts equality, so a flat diastasis plateau that simply *stops*
    # (falls to the right) still ends at its last plateau frame.
    interior = segment[1:-1]
    if interior.size == 0:
        return None, "none"
    maxima = np.flatnonzero((interior >= segment[:-2]) & (interior > segment[2:])) + 1
    if maxima.size == 0:
        return None, "none"
    return int(maxima[-1]) + peak, "curve"


def compute_la_phase_metrics(
    strain: np.ndarray,
    *,
    ed_index: int,
    end_index: int,
    mvo_index: int | None = None,
) -> LaStrainMetrics | None:
    """Reservoir / conduit / booster from the LA strain curve of one beat.

    ``mvo_index`` (А.9 valve events, when the LV strain supports them) narrows
    the reservoir window; ``None`` searches the peak over the whole beat.
    Returns ``None`` when the curve has no usable finite span — no numbers are
    invented from an empty curve.
    """
    curve = np.asarray(strain, dtype=np.float64)
    n = curve.size
    start = int(np.clip(int(ed_index), 0, n - 1))
    end = int(np.clip(int(end_index), 0, n - 1))
    if end - start < MIN_ARC_POINTS or not np.isfinite(curve[start : end + 1]).any():
        return None

    warnings: list[str] = []
    reservoir_end = end
    if mvo_index is not None:
        mvo = int(np.clip(int(mvo_index), start + 1, end))
        if mvo < end:
            reservoir_end = mvo
    window = curve[start : reservoir_end + 1]
    finite = np.flatnonzero(np.isfinite(window))
    if finite.size == 0:
        return None
    reservoir_offset = int(finite[np.argmax(window[finite])])
    reservoir_index = start + reservoir_offset
    reservoir_pct = float(window[reservoir_offset])

    a_onset: int | None
    a_onset, onset_source = detect_a_onset(curve, reservoir_index=reservoir_index, end_index=end)
    if a_onset is None and end - reservoir_index >= MIN_DIASTOLE_FRAMES:
        a_onset = int(round(reservoir_index + A_ONSET_FALLBACK_FRACTION * (end - reservoir_index)))
        a_onset = int(np.clip(a_onset, reservoir_index + 1, end))
        onset_source = "window_fraction"
        warnings.append("la_strain.a_onset_estimated")
    conduit_pct: float | None = None
    booster_pct: float | None = None
    booster_min_index: int | None = None
    if a_onset is not None:
        onset_value = curve[a_onset]
        if np.isfinite(onset_value):
            conduit_pct = reservoir_pct - float(onset_value)
            tail = curve[a_onset : end + 1]
            finite_tail = np.flatnonzero(np.isfinite(tail))
            if finite_tail.size:
                min_offset = int(finite_tail[np.argmin(tail[finite_tail])])
                booster_min_index = a_onset + min_offset
                booster_pct = float(onset_value) - float(tail[min_offset])

    return LaStrainMetrics(
        reservoir_pct=reservoir_pct,
        conduit_pct=conduit_pct,
        booster_pct=booster_pct,
        reservoir_index=reservoir_index,
        a_onset_index=a_onset,
        a_onset_source=onset_source,
        booster_min_index=booster_min_index,
        warnings=tuple(warnings),
    )


def select_la_strain_contour(
    contours: Iterable[Contour],
    *,
    sop_instance_uid: str | None,
    view: str,
) -> tuple[np.ndarray, int | None] | None:
    """The LA contour to track on one clip, or ``None``.

    Only contours of this very clip (same ``sop_instance_uid``) and view are
    usable — an LA contour drawn on another clip sits on different pixel
    motion. An accepted ED contour wins over ES; a contour without a frame
    index cannot anchor the tracker and is skipped.
    """
    best: tuple[np.ndarray, int | None] | None = None
    best_rank: tuple[int, int] | None = None
    wanted_view = str(view or "A4C").upper()
    for contour in contours:
        if contour.chamber.upper() != "LA" or contour.review_pending:
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
