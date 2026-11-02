"""Tests for RV crescent open-arc template."""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.services.contour_geometry import open_arc_polyline_length
from echo_personal_tool.domain.services.rv_shape_template import (
    RV_FAC_NODE_COUNT,
    warp_rv_crescent_open_arc,
)


def test_warp_rv_crescent_pins_endpoints_and_passes_through_apex() -> None:
    septal = (100.0, 20.0)
    lateral = (20.0, 20.0)
    apex = (60.0, 80.0)
    warped = warp_rv_crescent_open_arc(septal, lateral, apex, num_points=81)
    assert warped[0] == pytest.approx(septal, abs=1e-6)
    assert warped[-1] == pytest.approx(lateral, abs=1e-6)
    distances = [math.hypot(px - apex[0], py - apex[1]) for px, py in warped]
    assert min(distances) < 2.0


def test_warp_rv_crescent_no_sharp_midpoint_kink() -> None:
    """Crescent should not fold back like the old M-shaped piecewise template."""
    septal = (100.0, 20.0)
    lateral = (20.0, 20.0)
    apex = (55.0, 75.0)
    warped = warp_rv_crescent_open_arc(septal, lateral, apex, num_points=81)
    mid = warped[len(warped) // 2]
    assert mid[0] > lateral[0] - 5.0
    assert mid[0] < septal[0] + 5.0


def test_warp_rv_crescent_works_with_sloped_annulus() -> None:
    septal = (90.0, 30.0)
    lateral = (30.0, 10.0)
    apex = (40.0, 70.0)
    warped = warp_rv_crescent_open_arc(septal, lateral, apex, num_points=41)
    assert warped[0] == pytest.approx(septal, abs=1e-6)
    assert warped[-1] == pytest.approx(lateral, abs=1e-6)


def test_warp_rv_crescent_requires_valid_annulus() -> None:
    with pytest.raises(ValueError, match="annulus"):
        warp_rv_crescent_open_arc((0.0, 0.0), (0.0, 0.0), (10.0, 10.0))


def test_warp_rv_crescent_requires_apex_off_annulus() -> None:
    with pytest.raises(ValueError, match="off TV annulus"):
        warp_rv_crescent_open_arc((100.0, 20.0), (20.0, 20.0), (60.0, 20.0))


def test_warp_rv_crescent_arc_length_positive() -> None:
    warped = warp_rv_crescent_open_arc(
        (80.0, 20.0),
        (20.0, 20.0),
        (50.0, 70.0),
        num_points=41,
    )
    assert open_arc_polyline_length(warped) > 50.0


def test_rv_fac_node_count_is_modest() -> None:
    assert RV_FAC_NODE_COUNT <= 20
