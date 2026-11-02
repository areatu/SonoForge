"""Shared helpers for the STE strain UI: segment names, contour smoothing, palettes."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline

from echo_personal_tool.domain.services.segment_map import (
    SEGMENT_NAMES,
    view_segment_ids,
)
from echo_personal_tool.infrastructure.i18n import tr


def segment_name(segment_id: int) -> str:
    """Standard AHA name of a segment id (empty for unknown ids)."""
    return SEGMENT_NAMES.get(int(segment_id), f"Segment {segment_id}")


# Localised names of the six segments of the analysed view. The dict is keyed
# by the standard 18-segment AHA ids (issue #C2/#C11); ``strain.seg_<id>``
# covers all 18 so any view can be labelled.
AHA_SEGMENT_NAMES_RU: dict[int, str] = {seg: tr(f"strain.seg_{seg}") for seg in view_segment_ids("A4C")}


# ---------------------------------------------------------------------------
# Bull's-eye colour ramps (extracted here so ControlPanel and BullseyeWidget
# can both import them without a circular dependency).
# ---------------------------------------------------------------------------

STRAIN_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-16.0, (214, 24, 24)),  # normal — bright red
    (-11.0, (238, 106, 106)),  # light red
    (-6.0, (247, 176, 186)),  # light pink
    (0.0, (252, 224, 228)),  # pale pink — borderline/zero
    (float("inf"), (66, 133, 244)),  # any positive strain — blue
)

# "Deformation+" — the same clinical thresholds on a single-hue ramp, for
# readers who need luminance to carry the magnitude (colour-blind safe).
DEFORMATION_PLUS_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-16.0, (140, 0, 0)),
    (-11.0, (190, 40, 40)),
    (-6.0, (225, 110, 90)),
    (0.0, (245, 200, 180)),
    (float("inf"), (66, 133, 244)),
)

# Rainbow — the classic CFD/segmental look (blue = normal shortening).
RAINBOW_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-16.0, (28, 60, 160)),
    (-11.0, (40, 140, 200)),
    (-6.0, (90, 200, 160)),
    (0.0, (250, 220, 90)),
    (float("inf"), (210, 60, 60)),
)

# Monochrome with a threshold: everything at or below −16 % is black-white
# "normal", everything above is progressively lighter — a binary read-out.
MONOCHROME_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-16.0, (250, 250, 250)),
    (-11.0, (200, 200, 200)),
    (-6.0, (150, 150, 150)),
    (0.0, (95, 95, 95)),
    (float("inf"), (40, 40, 40)),
)

# ``C`` cycles through these in order; the first one is the default.
PALETTES: tuple[tuple[str, tuple[tuple[float, tuple[int, int, int]], ...]], ...] = (
    ("palette.ge", STRAIN_RAMP),
    ("palette.deformation_plus", DEFORMATION_PLUS_RAMP),
    ("palette.rainbow", RAINBOW_RAMP),
    ("palette.monochrome", MONOCHROME_RAMP),
)


def _smooth_contour(points: np.ndarray, n_output: int = 64) -> np.ndarray:
    """Resample a contour to *n_output* equidistant points using cubic splines.

    Returns the original ``points`` unchanged when the contour is too short
    for a meaningful parameterisation.
    """
    if len(points) < 4:
        return points

    # Close the contour
    closed = np.vstack([points, points[:1]])

    # Parameterize by cumulative arc length
    diffs = np.diff(closed, axis=0)
    dists = np.linalg.norm(diffs, axis=1)
    t = np.zeros(len(closed))
    t[1:] = np.cumsum(dists)
    total_len = t[-1]

    if total_len < 1e-6:
        return points

    t_norm = t / total_len

    # Fit cubic spline
    try:
        cs_x = CubicSpline(t_norm, closed[:, 0], bc_type="periodic")
        cs_y = CubicSpline(t_norm, closed[:, 1], bc_type="periodic")
    except Exception:
        return points

    # Interpolate
    t_new = np.linspace(0, 1, n_output, endpoint=False)
    x_new = cs_x(t_new)
    y_new = cs_y(t_new)

    return np.column_stack([x_new, y_new])
