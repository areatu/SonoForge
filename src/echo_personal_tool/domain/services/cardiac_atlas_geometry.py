"""Metric, reversible geometry for the cardiac atlas. No image I/O or ML runtime.

Points are (x, y); DICOM spacing is (row_mm, column_mm). Without calibration
coordinates are explicitly dimensionless, in annulus-span units, never called mm.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def points_array(points: object) -> np.ndarray:
    """Validate finite N×2 coordinates at a domain boundary."""
    arr = np.asarray(points, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2 or not np.isfinite(arr).all():
        raise ValueError("expected finite (N, 2) coordinates")
    return arr


@dataclass(frozen=True)
class CanonicalFrame:
    """Orthogonal valve-centred frame, Y towards the supplied chamber apex.

    ``matrix`` maps image-pixel offsets to canonical coordinates. It accounts
    for anisotropic spacing *before* computing the orthogonal anatomical axes.
    The lateral anchor selects X handedness; no image/anatomical flip is used.
    """

    origin: tuple[float, float]
    matrix: tuple[tuple[float, float], tuple[float, float]]
    units: str

    @classmethod
    def from_landmarks(
        cls,
        septal: tuple[float, float],
        lateral: tuple[float, float],
        apex: tuple[float, float],
        *,
        pixel_spacing_mm: tuple[float, float] | None = None,
    ) -> CanonicalFrame:
        anchors = points_array([septal, lateral, apex])
        spacing = np.ones(2, dtype=np.float64)
        if pixel_spacing_mm is not None:
            spacing = np.asarray(pixel_spacing_mm[::-1], dtype=np.float64)
            if spacing.shape != (2,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
                raise ValueError("pixel spacing must contain positive finite row/column values")
        origin = (anchors[0] + anchors[1]) / 2
        chord = (anchors[1] - anchors[0]) * spacing
        axis = (anchors[2] - origin) * spacing
        span, length = float(np.linalg.norm(chord)), float(np.linalg.norm(axis))
        if min(span, length) < 1e-9:
            raise ValueError("degenerate annulus or long axis")
        y_axis = axis / length
        x_axis = np.array([y_axis[1], -y_axis[0]])
        cross_span = float(x_axis @ chord)
        if abs(cross_span) < span * 1e-6:
            raise ValueError("apex must be off the valve plane")
        x_axis *= 1 if cross_span > 0 else -1
        scale = 1.0 if pixel_spacing_mm is not None else span
        matrix = np.stack([x_axis, y_axis]) * spacing[None, :] / scale
        return cls(
            (float(origin[0]), float(origin[1])),
            ((float(matrix[0, 0]), float(matrix[0, 1])), (float(matrix[1, 0]), float(matrix[1, 1]))),
            "mm" if pixel_spacing_mm is not None else "annulus_span",
        )

    def image_to_atlas(self, points: object) -> np.ndarray:
        return np.asarray((points_array(points) - self.origin) @ np.asarray(self.matrix).T, dtype=np.float64)

    def atlas_to_image(self, points: object) -> np.ndarray:
        return np.asarray(
            points_array(points) @ np.linalg.inv(np.asarray(self.matrix)).T + self.origin, dtype=np.float64
        )

    def warp_image(
        self,
        image: np.ndarray,
        *,
        bounds: tuple[float, float, float, float],
        size: int = 128,
    ) -> np.ndarray:
        """Bilinearly sample an image onto an atlas grid; bounds=(xmin,ymin,xmax,ymax)."""
        from scipy.ndimage import map_coordinates

        if size < 2 or image.ndim not in (2, 3) or min(image.shape[:2]) < 2:
            raise ValueError("invalid image or atlas grid size")
        x0, y0, x1, y1 = bounds
        if not np.isfinite(bounds).all() or x1 <= x0 or y1 <= y0:
            raise ValueError("invalid atlas bounds")
        yy, xx = np.meshgrid(np.linspace(y0, y1, size), np.linspace(x0, x1, size), indexing="ij")
        pixels = self.atlas_to_image(np.column_stack([xx.ravel(), yy.ravel()]))
        coords = np.stack([pixels[:, 1], pixels[:, 0]])
        arr = np.asarray(image, dtype=np.float64)
        if arr.ndim == 2:
            return np.asarray(map_coordinates(arr, coords, order=1, mode="constant"), dtype=np.float64).reshape(
                size, size
            )
        return np.stack(
            [
                np.asarray(map_coordinates(arr[..., c], coords, order=1, mode="constant")).reshape(size, size)
                for c in range(arr.shape[2])
            ],
            axis=-1,
        )


def sector_polar(points: object, probe_apex: tuple[float, float]) -> np.ndarray:
    """Return (r, theta) with theta=0 along the +Y ultrasound beam."""
    delta = points_array(points) - points_array([probe_apex])[0]
    return np.column_stack([np.linalg.norm(delta, axis=1), np.arctan2(delta[:, 0], delta[:, 1])])


def sector_cartesian(polar: object, probe_apex: tuple[float, float]) -> np.ndarray:
    arr = points_array(polar)
    if np.any(arr[:, 0] < 0):
        raise ValueError("radius must be nonnegative")
    return np.column_stack([arr[:, 0] * np.sin(arr[:, 1]), arr[:, 0] * np.cos(arr[:, 1])]) + probe_apex


def resample_arc(points: object, count: int, *, closed: bool = False) -> np.ndarray:
    """Arclength correspondence. Open arcs keep the supplied endpoints/order."""
    arr = points_array(points)
    if count < 3 or len(arr) < 3:
        raise ValueError("an arc needs at least three nodes")
    if closed and np.linalg.norm(arr[0] - arr[-1]) > 1e-9:
        arr = np.vstack([arr, arr[:1]])
    distances = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(arr, axis=0), axis=1))]
    keep = np.r_[True, np.diff(distances) > 1e-9]
    arr, distances = arr[keep], distances[keep]
    if len(arr) < 3 or distances[-1] < 1e-9:
        raise ValueError("degenerate contour")
    samples = np.linspace(0, distances[-1], count, endpoint=not closed)
    return np.column_stack([np.interp(samples, distances, arr[:, c]) for c in range(2)])


def polygon_interior(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Strict polygon interior; boundary points shared by chambers are excluded."""
    p = points_array(points)
    a = points_array(polygon)
    b = np.roll(a, -1, axis=0)
    dx, dy = (b - a).T
    px, py = (p[:, None, :] - a[None, :, :]).transpose(2, 0, 1)
    cross = px * dy - py * dx
    dot = px * dx + py * dy
    boundary = (np.abs(cross) < 1e-7) & (dot >= -1e-7) & (dot <= dx * dx + dy * dy + 1e-7)
    crossings = ((a[:, 1] > p[:, None, 1]) != (b[:, 1] > p[:, None, 1])) & (
        p[:, None, 0] < a[:, 0] + (p[:, None, 1] - a[:, 1]) * dx / np.where(abs(dy) < 1e-12, 1e-12, dy)
    )
    return np.asarray((crossings.sum(axis=1) % 2 == 1) & ~boundary.any(axis=1), dtype=bool)


def edges_cross(first: np.ndarray, second: np.ndarray, *, same: bool = False) -> bool:
    """Proper segment crossings, excluding shared endpoints/edges."""
    a, b = first, np.roll(first, -1, axis=0)
    c, d = second, np.roll(second, -1, axis=0)

    def orient(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
        u, v = q - p, r - p
        return np.asarray(u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0], dtype=np.float64)

    o1 = orient(a[:, None], b[:, None], c[None])
    o2 = orient(a[:, None], b[:, None], d[None])
    o3 = orient(c[None], d[None], a[:, None])
    o4 = orient(c[None], d[None], b[:, None])
    crossed = (o1 * o2 < -1e-9) & (o3 * o4 < -1e-9)
    if same:
        np.fill_diagonal(crossed, False)
    return bool(crossed.any())
