"""Myocardial zone generation: dual-contour (endo + epi) and kernel sampling."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    TrackingKernel,
)


def _compute_normals(points: np.ndarray) -> np.ndarray:
    """Compute outward normals for an open arc contour.

    For interior points: tangent = next - prev.
    For endpoints: use the single adjacent segment.

    Args:
        points: (M, 2) ordered open-arc contour points (septal → apex → lateral).

    Returns:
        (M, 2) unit normal vectors pointing outward.
    """
    n = len(points)
    normals = np.zeros_like(points)
    for i in range(n):
        if n < 2:
            normals[i] = np.array([0.0, -1.0])
            continue
        if i == 0:
            tangent = points[1] - points[0]
        elif i == n - 1:
            tangent = points[-1] - points[-2]
        else:
            tangent = points[i + 1] - points[i - 1]
        normals[i] = np.array([-tangent[1], tangent[0]])
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    return normals / norms


def expand_contour_to_zone(
    endo_points: np.ndarray,
    thickness_px: float,
) -> np.ndarray:
    """Expand endocardial contour outward by thickness_px to create epicardium.

    For each point: epi = endo + normal * thickness_px.

    Args:
        endo_points: (M, 2) endocardial contour.
        thickness_px: wall thickness in pixels.

    Returns:
        (M, 2) epicardial contour points.
    """
    normals = _compute_normals(endo_points)
    return endo_points + normals * thickness_px


def create_myocardial_zone(
    endo_points: np.ndarray,
    pixel_spacing: tuple[float, float],
    thickness_mm: float = 8.0,
) -> MyocardialZone:
    """Create a myocardial zone from an endocardial contour.

    Args:
        endo_points: (M, 2) endocardial contour in pixel coordinates.
        pixel_spacing: (row_spacing, column_spacing) in mm/pixel.
        thickness_mm: myocardial wall thickness in mm.

    Returns:
        MyocardialZone with endo and epi contours.
    """
    avg_spacing = (pixel_spacing[0] + pixel_spacing[1]) / 2.0
    thickness_px = thickness_mm / avg_spacing
    epi_points = expand_contour_to_zone(endo_points, thickness_px)
    return MyocardialZone(
        endo_points=endo_points,
        epi_points=epi_points,
        thickness_mm=thickness_mm,
        pixel_spacing=pixel_spacing,
    )


def sample_kernels_in_zone(
    zone: MyocardialZone,
    num_kernels_per_ring: int = 32,
    num_rings: int = 3,
) -> list[TrackingKernel]:
    """Sample tracking kernels uniformly within the myocardial zone.

    Distributes kernels across num_rings layers from endo to epi.

    Args:
        zone: MyocardialZone with endo and epi contours.
        num_kernels_per_ring: kernels per ring along the contour.
        num_rings: number of concentric rings (default 3: endo, mid, epi).

    Returns:
        List of TrackingKernel instances.
    """
    n_endo = len(zone.endo_points)
    n_epi = len(zone.epi_points)
    n_pts = max(n_endo, n_epi)

    kernels: list[TrackingKernel] = []
    for ring in range(num_rings):
        t = ring / max(num_rings - 1, 1)
        for i in range(num_kernels_per_ring):
            idx = int(i * n_pts / num_kernels_per_ring) % n_pts
            endo_idx = int(i * n_endo / num_kernels_per_ring) % n_endo
            epi_idx = int(i * n_epi / num_kernels_per_ring) % n_epi

            pt_endo = zone.endo_points[endo_idx]
            pt_epi = zone.epi_points[epi_idx]
            center = pt_endo + t * (pt_epi - pt_endo)

            layer = "endo" if ring == 0 else ("epi" if ring == num_rings - 1 else "mid")
            kernels.append(
                TrackingKernel(
                    center=(float(center[0]), float(center[1])),
                    radius=10,
                    node_index=idx,
                    layer=layer,
                )
            )
    return kernels
