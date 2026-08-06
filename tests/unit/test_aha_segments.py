"""Tests for AHA segment assignment and GLS aggregation."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import TrackingKernel
from echo_personal_tool.domain.services.aha_segments import (
    assign_aha_segments,
    compute_aha_segment_strain,
    compute_gls_from_segments,
)


def test_assign_aha_segments_apical4ch():
    center = (100.0, 100.0)
    kernels = [
        TrackingKernel(center=(100, 50), node_index=0, layer="endo", arc_length_param=0.0),
        TrackingKernel(center=(150, 100), node_index=8, layer="endo", arc_length_param=0.25),
    ]
    assigned = assign_aha_segments(kernels, lv_center=center, view="A4C")
    assert all(k.aha_segment > 0 for k in assigned)


def test_gls_from_segments_excludes_low_quality():
    segment_strain = {1: -18.0, 2: -20.0, 3: -5.0}
    segment_quality = {1: 0.9, 2: 0.8, 3: 0.2}
    gls = compute_gls_from_segments(segment_strain, segment_quality, min_quality=0.4)
    assert gls == pytest.approx(-20.0, abs=0.1)


def test_compute_aha_segment_strain_min_per_segment():
    kernels = [
        TrackingKernel(center=(0, 0), node_index=0, layer="endo", aha_segment=1),
        TrackingKernel(center=(1, 0), node_index=1, layer="endo", aha_segment=1),
        TrackingKernel(center=(2, 0), node_index=2, layer="endo", aha_segment=2),
        TrackingKernel(center=(3, 0), node_index=3, layer="epi", aha_segment=1),
    ]
    per_kernel_strain = np.array([-10.0, -15.0, -20.0, -99.0])
    ncc_scores = np.array([0.8, 0.6, 0.9, 0.1])

    segment_strain, segment_quality = compute_aha_segment_strain(per_kernel_strain, kernels, ncc_scores)

    assert segment_strain[1] == -15.0
    assert segment_strain[2] == -20.0
    assert 1 not in segment_quality or segment_quality[1] == pytest.approx(0.7, abs=0.01)
    assert segment_quality[2] == pytest.approx(0.9, abs=0.01)


def test_assign_aha_segments_skips_non_endo():
    center = (100.0, 100.0)
    kernels = [
        TrackingKernel(center=(100, 50), node_index=0, layer="epi"),
    ]
    assigned = assign_aha_segments(kernels, lv_center=center, view="A4C")
    assert assigned[0].aha_segment == 0
