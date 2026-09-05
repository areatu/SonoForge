"""Myocardial zone generation: dual-contour (endo + epi) and kernel sampling."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    TrackingKernel,
)
from echo_personal_tool.domain.services.contour_utils import resample_contour


def _compute_normals(points: np.ndarray) -> np.ndarray:
    """Compute outward normals for LV contour using LV cavity center."""
    n = len(points)
    normals = np.zeros_like(points)
    septal_lateral_center = (points[0] + points[-1]) / 2.0

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
    normals = normals / norms

    to_cavity = septal_lateral_center - points
    dot = np.sum(normals * to_cavity, axis=1)
    flip = dot > 0
    normals[flip] *= -1.0

    return normals


def expand_contour_to_zone(
    endo_points: np.ndarray,
    thickness_px: float,
) -> np.ndarray:
    normals = _compute_normals(endo_points)
    return endo_points + normals * thickness_px


def create_myocardial_zone(
    endo_points: np.ndarray,
    pixel_spacing: tuple[float, float],
    thickness_mm: float = 8.0,
    epi_points: np.ndarray | None = None,
) -> MyocardialZone:
    avg_spacing = (pixel_spacing[0] + pixel_spacing[1]) / 2.0
    thickness_px = thickness_mm / avg_spacing
    endo_points = resample_contour(endo_points, n_points=128)
    if epi_points is None:
        epi_points = expand_contour_to_zone(endo_points, thickness_px)
    else:
        epi_points = resample_contour(np.asarray(epi_points, dtype=np.float64), n_points=128)
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
    kernel_radius: int = 6,
) -> list[TrackingKernel]:
    n_endo = len(zone.endo_points)

    kernels: list[TrackingKernel] = []
    for ring in range(num_rings):
        t = ring / max(num_rings - 1, 1)
        for i in range(num_kernels_per_ring):
            endo_idx = int(i * n_endo / num_kernels_per_ring) % n_endo

            pt_endo = zone.endo_points[endo_idx]
            pt_epi = zone.epi_points[endo_idx]
            center = pt_endo + t * (pt_epi - pt_endo)

            layer = "endo" if ring == 0 else ("epi" if ring == num_rings - 1 else "mid")
            kernels.append(
                TrackingKernel(
                    center=(float(center[0]), float(center[1])),
                    radius=kernel_radius,
                    node_index=endo_idx,
                    layer=layer,
                )
            )
    return kernels
