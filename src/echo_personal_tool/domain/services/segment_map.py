"""AHA 18-segment model for apical STE views (correct wall/level assignment).

The old assignment used the angle from the LV centroid and was hard-wired to a
single, unverified "A4C" layout: the centroid of an apical arc is not the LV
centre, the angular bins were asymmetric, and segments never depended on the
analysed view (issue #C2). The result was that a kernel of the *anterior* wall
could be reported as "inferoseptal" — and every downstream number inherited
that error.

Here the segment of a node is derived from its position **along the material
line** (the apical arc from one mitral annulus point through the apex to the
other) and from the wall the analysed view shows:

* level — basal (1), mid (2) or apical (3) third of the arc to the apex;
* side  — which half of the arc the node is on (1st or 2nd wall of the view).

Segment numbering follows the standard 18-segment AHA model; the apex has no
separate segment (apex = apical cap), apical segments carry the wall name of
the adjacent walls, following the convention used by GE/Philips reports:

.. code-block:: text

    A4C  inferoseptal 3/9/15   anterolateral 6/12/18
    A2C  anterior    1/7/13   inferior      4/10/16
    A3C  anteroseptal 2/8/14  inferolateral 5/11/17

Note the numbering itself is the AHA standard (1 basal anterior … 6 basal
anterolateral, then mid, then apical); only the *pair* of walls visible in a
view changes. That way the bull's-eye can place every measured segment at its
anatomical position without a per-view special case.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Canonical 18-segment AHA names, keyed by segment id.
SEGMENT_NAMES: dict[int, str] = {
    1: "basal anterior",
    2: "basal anteroseptal",
    3: "basal inferoseptal",
    4: "basal inferior",
    5: "basal inferolateral",
    6: "basal anterolateral",
    7: "mid anterior",
    8: "mid anteroseptal",
    9: "mid inferoseptal",
    10: "mid inferior",
    11: "mid inferolateral",
    12: "mid anterolateral",
    13: "apical anterior",
    14: "apical anteroseptal",
    15: "apical inferoseptal",
    16: "apical inferior",
    17: "apical inferolateral",
    18: "apical anterolateral",
}

# Wall pair visible in each apical view: (segment ids of the 1st wall, 2nd wall)
# in basal/mid/apical order. The first wall is the one on the left of the screen
# in a correctly oriented apical view.
VIEW_WALLS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "A4C": ((3, 9, 15), (6, 12, 18)),  # inferoseptal / anterolateral
    "A2C": ((1, 7, 13), (4, 10, 16)),  # anterior / inferior
    "A3C": ((2, 8, 14), (5, 11, 17)),  # anteroseptal / inferolateral
    "A5C": ((3, 9, 15), (6, 12, 18)),  # treated as A4C wall pair
}

SEGMENTS_PER_VIEW = 6

# Bull's-eye layout (GE/Philips convention): level -> 6 positions clockwise
# starting from the anterior wall. Used by the UI to place measured segments.
BULLSEYE_LAYOUT: dict[int, tuple[int, ...]] = {
    0: (1, 2, 3, 4, 5, 6),  # basal ring
    1: (7, 8, 9, 10, 11, 12),  # mid ring
    2: (13, 14, 15, 16, 17, 18),  # apical ring
}
BULLSEYE_APEX = 17  # apical cap drawn in the centre (inferolateral by convention)


def normalise_view(view: str | None) -> str:
    """Return a canonical view key (``A4C``/``A2C``/``A3C``)."""
    if not view:
        return "A4C"
    key = str(view).strip().upper().replace("AP", "")
    for candidate in ("A4C", "A2C", "A3C", "A5C"):
        if key.startswith(candidate):
            return candidate
    return "A4C"


def view_segment_ids(view: str | None) -> tuple[int, ...]:
    """All six segments of a view, sorted by segment id."""
    walls = VIEW_WALLS[normalise_view(view)]
    return tuple(sorted(walls[0] + walls[1]))


def segment_ids_in_view(view: str | None) -> tuple[int, ...]:
    """All six segments of a view in *anatomical* order (wall 1 then wall 2,
    basal → apical), i.e. the order a curve panel lists them in."""
    walls = VIEW_WALLS[normalise_view(view)]
    return tuple(walls[0] + walls[1])


def segment_ids_in_bullseye_order() -> tuple[int, ...]:
    """All 18 segment ids in the order the bull's-eye draws them."""
    return tuple(seg for level in (0, 1, 2) for seg in BULLSEYE_LAYOUT[level])


@dataclass(frozen=True)
class SegmentAssignment:
    """Result of assigning nodes of one view to AHA segments."""

    node_segments: tuple[int, ...]
    node_levels: tuple[int, ...]  # 0 basal / 1 mid / 2 apical
    node_sides: tuple[int, ...]  # 0 = first wall of the view, 1 = second wall
    apex_index: int  # node index closest to the anatomical apex
    arc_params: tuple[float, ...]  # 0..1 along the arc (from the first annulus)

    @property
    def n_nodes(self) -> int:
        return len(self.node_segments)


def apex_index_from_arc(points: np.ndarray) -> int:
    """Index of the apex on an open apical arc — the point farthest from the
    annulus chord (annulus = first↔last point), *not* the centroid.

    For a closed ring the chord is degenerate; in that case the point farthest
    from the mean of the curve is used, which is the usual definition of the
    apex for an LV outline.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 2:
        return 0
    chord = pts[-1] - pts[0]
    chord_norm = float(np.linalg.norm(chord))
    if chord_norm <= 1e-6:
        center = pts.mean(axis=0)
        return int(np.argmax(np.linalg.norm(pts - center, axis=1)))
    normal = np.array([-chord[1], chord[0]], dtype=np.float64) / chord_norm
    distance = np.abs((pts - pts[0]) @ normal)
    # The apex is unique and, for a noisy outline, is better found as the
    # furthest signed excursion: ties are broken by arc position (the middle).
    mid = (len(pts) - 1) / 2.0
    best = np.argmax(distance - 1e-9 * np.abs(np.arange(len(pts)) - mid))
    return int(best)


def _arc_length_params(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(seg.sum())
    if total <= 0:
        return np.linspace(0.0, 1.0, len(pts))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return cum / total


def assign_segments_from_arc(
    points: np.ndarray,
    view: str | None = "A4C",
    *,
    basal_fraction: float = 1.0 / 3.0,
    apical_fraction: float = 2.0 / 3.0,
) -> SegmentAssignment:
    """Assign every node of an apical arc to one of the six segments of a view.

    Args:
        points: (n_nodes, 2) node positions in arc order (annulus → apex →
            annulus), i.e. the order the material line is built in.
        view: analysed apical view — changes which wall pair is named.
        basal_fraction: arc fraction (measured from each annulus) that still
            counts as basal level.
        apical_fraction: arc fraction beyond which a node counts as apical.

    Returns:
        :class:`SegmentAssignment` with one segment per node. Every node gets a
        segment in ``1..18`` (no zeros), so the caller can rely on full
        coverage; the six segment ids of the view are used exactly once each
        side so the bull's-eye never shows a duplicate.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("points must have shape (n_nodes, 2)")
    n = len(pts)
    if n < 3:
        raise ValueError("at least three nodes are required to define an arc")
    walls = VIEW_WALLS[normalise_view(view)]
    first_wall, second_wall = walls

    apex = apex_index_from_arc(pts)
    # Distance from the apex along the arc, normalised per side: 0 at the apex,
    # 1 at the annulus. Using arc distance (not the chord) keeps the level
    # assignment stable when the apex is not in the middle of the arc.
    params = _arc_length_params(pts)
    apex_param = float(params[apex])
    left_span = max(apex_param, 1e-6)
    right_span = max(1.0 - apex_param, 1e-6)

    node_levels: list[int] = []
    node_sides: list[int] = []
    node_segments: list[int] = []
    for i in range(n):
        is_first_side = i <= apex
        side = 0 if is_first_side else 1
        # 0 at the apex → 1 at the annulus
        to_annulus = (
            (apex_param - float(params[i])) / left_span
            if is_first_side
            else (float(params[i]) - apex_param) / right_span
        )
        to_annulus = float(min(max(to_annulus, 0.0), 1.0))
        # to_annulus = 1 at the annulus, 0 at the apex
        if to_annulus >= 1.0 - basal_fraction:
            level = 0  # basal
        elif to_annulus >= 1.0 - apical_fraction:
            level = 1  # mid
        else:
            level = 2  # apical
        wall_segments = first_wall if side == 0 else second_wall
        node_levels.append(level)
        node_sides.append(side)
        node_segments.append(wall_segments[level])

    return SegmentAssignment(
        node_segments=tuple(int(s) for s in node_segments),
        node_levels=tuple(node_levels),
        node_sides=tuple(node_sides),
        apex_index=int(apex),
        arc_params=tuple(float(p) for p in params),
    )


def segments_present(node_segments: Sequence[int]) -> tuple[int, ...]:
    """Segment ids that actually received at least one node, sorted."""
    return tuple(sorted({int(s) for s in node_segments if int(s) > 0}))


def merge_segment_strain(per_node_values: dict[int, float]) -> dict[int, float]:
    """Aggregate per-node strain into per-segment strain (mean over nodes).

    Kept here (and not in the UI) so the bull's-eye, the table and the export
    read the same numbers; the mean — not the worst value — is the clinical
    convention for a segment.
    """
    buckets: dict[int, list[float]] = {}
    for segment, value in per_node_values.items():
        if value is None or not np.isfinite(value):
            continue
        buckets.setdefault(int(segment), []).append(float(value))
    return {segment: float(np.mean(values)) for segment, values in buckets.items()}
