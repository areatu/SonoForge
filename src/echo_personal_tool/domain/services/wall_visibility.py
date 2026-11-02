"""Is the tissue under a tracked node actually visible in the image?

A tracked position is a measurement only where there is tissue to measure. When
part of the wall leaves the sector (the apex in A2C, the anterior wall at the
lateral edge, a probe shift), the block matcher still returns a position: it
locks onto the boundary of the data region or onto a featureless area, where
``cv2.matchTemplate`` can even read NCC = 1.0 for a blank patch. The strain
curve then silently mixes measured and unmeasured tissue. Measured on the
kinematic phantom: with 1.7 % of the node-frames outside the field of view GLS
read −11.5 % against a true −19.5 % while the report still said ``valid``
(clinical review Q4). Neither the NCC nor the coverage fraction sees it,
because both look at the *match*, not at the *image*.

This module measures, per node and frame, whether the tissue under the node is
visible at all:

* the kernel must be fully inside the frame (the field of view ends there);
* the kernel must lie on image data: most of it must be above a floor derived
  from the clip itself, so the blank region outside the sector (and its blurred
  edge) is recognised as having no tissue;
* the kernel must still carry speckle — its standard deviation compared with the
  value it had at end-diastole, where the operator drew the contour.

``measure_wall_visibility`` returns the per-node loss fraction. The worker
excludes the nodes that fail over a meaningful share of the cycle from the
strain measurement, so the reported number describes the tissue that was
actually seen, and the QC report says how much was excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# A node invisible for more than this share of the analysed frames is not a
# measurement of the myocardium but of the edge of the data region. The
# phantom showed a measurable GLS bias well below this limit, so the report is
# downgraded as soon as anything had to be excluded — this constant only decides
# which nodes are dropped from the measurement.
MAX_NODE_LOSS = 0.10
# A kernel counts as empty when most of it (the median pixel) sits on the data
# floor: then there is no tissue under the node any more. The median, not the
# mean, because a kernel that merely touches the sector edge and a very bright
# specular pixel must not move the statistic; the share of floor pixels alone
# would also flag dark speckle minima in a low-SNR clip (measured at 10 dB).
MIN_TEXTURE_RATIO = 0.35
# Pixel value above which a frame carries data, as a fraction of the brightest
# pixel of the clip. Outside the sector the value sits at the floor.
DATA_FLOOR_FRACTION = 0.02


@dataclass(frozen=True)
class WallVisibility:
    """Per-node visibility of the tracked tissue along the cardiac cycle."""

    loss_fraction: float
    node_loss: np.ndarray

    def visible_nodes(self, max_loss: float = MAX_NODE_LOSS) -> np.ndarray:
        """Nodes whose kernel is visible in all but ``max_loss`` of the frames."""
        return self.node_loss <= float(max_loss)


def measure_wall_visibility(
    frames: np.ndarray,
    positions: np.ndarray,
    *,
    reference_index: int = 0,
    kernel_radius: int = 6,
) -> WallVisibility:
    """Fraction of node-frames whose tissue is not visible in ``frames``.

    ``frames`` is the (T, H, W) stack the tracker worked on, ``positions`` the
    (T, K, 2) tracked positions as ``(x=column, y=row)`` in the same pixel
    grid, ``reference_index`` the frame the contour was drawn on (end diastole).

    Never raises on degenerate input: an empty or non-finite track yields a zero
    loss, so callers that have no image data keep their previous behaviour.
    """
    images = np.asarray(frames, dtype=np.float64)
    track = np.asarray(positions, dtype=np.float64)
    if images.ndim != 3 or track.ndim != 3 or track.shape[2] != 2:
        raise ValueError("frames must be (T, H, W) and positions must be (T, K, 2)")
    n_nodes = int(track.shape[1])
    n_frames = int(min(images.shape[0], track.shape[0]))
    if n_nodes == 0 or n_frames == 0:
        return WallVisibility(loss_fraction=0.0, node_loss=np.zeros(n_nodes, dtype=np.float64))

    images = images[:n_frames]
    track = track[:n_frames]
    radius = max(1, int(kernel_radius))
    data_floor = DATA_FLOOR_FRACTION * float(np.max(images))
    reference_index = int(np.clip(reference_index, 0, n_frames - 1))

    lost = np.zeros((n_frames, n_nodes), dtype=bool)
    for index in range(n_nodes):
        stds = np.full(n_frames, np.nan, dtype=np.float64)
        empty = np.ones(n_frames, dtype=bool)
        outside = np.zeros(n_frames, dtype=bool)
        for frame in range(n_frames):
            x, y = track[frame, index]
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            patch = _patch(images[frame], float(x), float(y), radius)
            if patch is None:
                outside[frame] = True
                continue
            stds[frame] = float(np.std(patch))
            empty[frame] = float(np.median(patch)) <= data_floor
        ref_std = float(stds[reference_index])
        if not np.isfinite(ref_std):
            finite = stds[np.isfinite(stds)]
            ref_std = float(np.median(finite)) if finite.size else 0.0
        lost[:, index] = (
            outside | ~np.isfinite(stds) | empty | ((ref_std > 1e-6) & (stds < MIN_TEXTURE_RATIO * ref_std))
        )

    node_loss = lost.mean(axis=0)
    return WallVisibility(loss_fraction=float(lost.mean()), node_loss=node_loss)


def _patch(image: np.ndarray, x: float, y: float, radius: int) -> np.ndarray | None:
    """Kernel patch around a position, or ``None`` when it leaves the frame."""
    height, width = image.shape
    cx, cy = int(round(x)), int(round(y))
    if cx - radius < 0 or cy - radius < 0 or cx + radius > width - 1 or cy + radius > height - 1:
        return None
    return image[cy - radius : cy + radius + 1, cx - radius : cx + radius + 1]


__all__ = ["MAX_NODE_LOSS", "WallVisibility", "measure_wall_visibility"]
