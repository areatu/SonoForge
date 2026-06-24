"""Strain computation from speckle tracking results."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import (
    TrackingKernel,
    TrackingResult,
)


def compute_longitudinal_strain(
    tracking_results: list[TrackingResult],
    kernels: list[TrackingKernel],
    pixel_spacing: tuple[float, float],
) -> np.ndarray:
    """Compute longitudinal strain curve over time.

    Measures deformation along the endocardial contour using inter-node distances.

    Args:
        tracking_results: per-frame tracking results (N-1 items).
        kernels: initial kernel positions.
        pixel_spacing: (row_spacing, column_spacing) in mm/pixel.

    Returns:
        (num_frames,) array of cumulative longitudinal strain in percent.
        Frame 0 is reference (0%), subsequent frames show deformation.
    """
    n_frames = len(tracking_results) + 1
    endo_kernels = [k for k in kernels if k.layer == "endo"]
    if len(endo_kernels) < 2:
        return np.zeros(n_frames)

    n_kernels = len(endo_kernels)
    avg_spacing = np.mean(pixel_spacing)

    initial_positions = np.array([k.center for k in endo_kernels])
    all_positions = np.zeros((n_frames, n_kernels, 2))
    all_positions[0] = initial_positions

    for i, result in enumerate(tracking_results):
        endo_mask = [j for j, k in enumerate(kernels) if k.layer == "endo"]
        tracked = result.kernel_positions[endo_mask]
        if len(tracked) == n_kernels:
            all_positions[i + 1] = tracked
        else:
            all_positions[i + 1] = all_positions[i] + result.displacements[:n_kernels]

    initial_length = 0.0
    for i in range(n_kernels - 1):
        seg = initial_positions[i + 1] - initial_positions[i]
        initial_length += np.linalg.norm(seg) * avg_spacing

    strain = np.zeros(n_frames)
    for t in range(1, n_frames):
        current_length = 0.0
        for i in range(n_kernels - 1):
            seg = all_positions[t, i + 1] - all_positions[t, i]
            current_length += np.linalg.norm(seg) * avg_spacing
        if initial_length > 1e-6:
            strain[t] = (current_length - initial_length) / initial_length * 100.0

    return strain


def compute_radial_strain(
    tracking_results: list[TrackingResult],
    kernels: list[TrackingKernel],
    pixel_spacing: tuple[float, float],
) -> np.ndarray:
    """Compute radial (circumferential) strain from tracking.

    Measures wall thickening by comparing endo-epi distances.

    Args:
        tracking_results: per-frame tracking results.
        kernels: initial kernel positions with endo/epi layers.
        pixel_spacing: (row_spacing, column_spacing) in mm/pixel.

    Returns:
        (num_frames,) array of radial strain in percent.
    """
    n_frames = len(tracking_results) + 1
    avg_spacing = np.mean(pixel_spacing)

    endo_kernels = [k for k in kernels if k.layer == "endo"]
    epi_kernels = [k for k in kernels if k.layer == "epi"]
    n_pairs = min(len(endo_kernels), len(epi_kernels))

    if n_pairs < 1:
        return np.zeros(n_frames)

    endo_init = np.array([k.center for k in endo_kernels[:n_pairs]])
    epi_init = np.array([k.center for k in epi_kernels[:n_pairs]])

    initial_thickness = np.mean(np.linalg.norm(epi_init - endo_init, axis=1)) * avg_spacing

    endo_cumulative = np.zeros_like(endo_init)
    epi_cumulative = np.zeros_like(epi_init)

    strain = np.zeros(n_frames)
    for t in range(1, n_frames):
        result = tracking_results[t - 1]
        endo_indices = [i for i, k in enumerate(kernels) if k.layer == "endo"][:n_pairs]
        epi_indices = [i for i, k in enumerate(kernels) if k.layer == "epi"][:n_pairs]

        if len(endo_indices) == n_pairs:
            endo_pos = result.kernel_positions[endo_indices]
        else:
            endo_cumulative += result.displacements[:n_pairs]
            endo_pos = endo_init + endo_cumulative
        if len(epi_indices) == n_pairs:
            epi_pos = result.kernel_positions[epi_indices]
        else:
            epi_cumulative += result.displacements[:n_pairs]
            epi_pos = epi_init + epi_cumulative

        current_thickness = np.mean(np.linalg.norm(epi_pos - endo_pos, axis=1)) * avg_spacing
        if initial_thickness > 1e-6:
            strain[t] = (current_thickness - initial_thickness) / initial_thickness * 100.0

    return strain


def compute_gls(
    longitudinal_strain: np.ndarray,
    ed_index: int,
    es_index: int,
) -> float:
    """Global Longitudinal Strain: peak negative strain between ED and ES.

    Args:
        longitudinal_strain: strain curve over all frames.
        ed_index: end-diastole frame index.
        es_index: end-systole frame index.

    Returns:
        GLS as negative percentage (e.g., -18.5%).
    """
    if ed_index == es_index:
        return 0.0
    start, end = min(ed_index, es_index), max(ed_index, es_index)
    segment = longitudinal_strain[start : end + 1]
    if len(segment) == 0:
        return 0.0
    return float(np.min(segment))


def compute_strain_rate(
    strain_curve: np.ndarray,
    frame_times_ms: list[float] | np.ndarray,
) -> np.ndarray:
    """Time derivative of strain curve.

    Args:
        strain_curve: (N,) strain values in percent.
        frame_times_ms: per-frame time intervals in ms.

    Returns:
        (N,) strain rate in %/s.
    """
    n = len(strain_curve)
    rate = np.zeros(n)
    times = np.array(frame_times_ms, dtype=np.float64)
    if len(times) != n:
        times = np.full(n, 33.3)

    for i in range(1, n):
        dt_s = times[i] / 1000.0
        if dt_s > 1e-6:
            rate[i] = (strain_curve[i] - strain_curve[i - 1]) / dt_s

    return rate
