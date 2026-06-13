"""Unit tests for Gaussian RBF contour deformation."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    SENSITIVITY_K,
    SIGMA_SCREEN_PX,
    apply_gaussian_displacement,
    gaussian_weights,
    sigma_from_view_range,
)


def test_sigma_from_view_range_scales_with_view_range() -> None:
    narrow = sigma_from_view_range(100.0, 200.0, sigma_screen_px=40.0)
    wide = sigma_from_view_range(400.0, 200.0, sigma_screen_px=40.0)
    assert narrow == pytest.approx(20.0)
    assert wide == pytest.approx(80.0)
    assert wide == pytest.approx(4.0 * narrow)


def test_sigma_from_view_range_default_screen_constant() -> None:
    result = sigma_from_view_range(800.0, 400.0)
    assert result == pytest.approx(SIGMA_SCREEN_PX * 2.0)


def test_gaussian_weights_peak_at_cursor() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = gaussian_weights(points, cursor=(10.0, 0.0), sigma=5.0)
    assert weights[1] == pytest.approx(1.0)
    assert weights[0] < weights[1]
    assert weights[2] < weights[1]


def test_gaussian_weights_decay_with_distance() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = gaussian_weights(points, cursor=(0.0, 0.0), sigma=5.0)
    assert weights[0] == pytest.approx(1.0)
    assert weights[1] < weights[0]
    assert weights[2] < weights[1]


def test_gaussian_weights_pinned_indices_zero() -> None:
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    weights = gaussian_weights(
        points,
        cursor=(5.0, 5.0),
        sigma=5.0,
        pinned_indices=frozenset({0, 2}),
    )
    assert weights[0] == pytest.approx(0.0)
    assert weights[2] == pytest.approx(0.0)
    assert weights[1] == pytest.approx(1.0)


def test_apply_gaussian_displacement_moves_weighted_points() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = np.array([0.0, 1.0, 0.5])
    moved = apply_gaussian_displacement(
        points,
        delta=(0.0, 2.0),
        weights=weights,
        sensitivity_k=1.0,
    )
    assert moved[0] == (0.0, 0.0)
    assert moved[1] == (10.0, 2.0)
    assert moved[2] == (20.0, 1.0)


def test_apply_gaussian_displacement_open_arc_endpoints_pinned() -> None:
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    weights = gaussian_weights(
        points,
        cursor=(5.0, 5.0),
        sigma=5.0,
        pinned_indices=frozenset({0, 2}),
    )
    moved = apply_gaussian_displacement(
        points,
        delta=(1.0, 2.0),
        weights=weights,
        sensitivity_k=SENSITIVITY_K,
    )
    assert moved[0] == (0.0, 0.0)
    assert moved[2] == (10.0, 0.0)
    assert moved[1][1] > 5.0


def test_apply_gaussian_displacement_empty_points() -> None:
    assert apply_gaussian_displacement([], delta=(1.0, 1.0), weights=np.array([])) == []
