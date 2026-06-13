"""Unit tests for MBS-lite contour fitting."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT
from echo_personal_tool.domain.services.lv_shape_template import (
    ARC_WARP_A2C,
    ARC_WARP_A4C,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    _warp_truncated_oval_arc,
    fit_contour_from_landmarks,
    refine_model_contour,
    refine_open_arc_contour,
)


def test_fit_contour_from_landmarks_basic() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)

    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )

    assert contour.is_open_arc
    assert contour.source == "model"
    assert contour.mitral_annulus == (septal, lateral)
    assert len(contour.points) == DEFAULT_NODE_COUNT
    assert contour.points[0] == pytest.approx(septal, abs=1e-3)
    assert contour.points[-1] == pytest.approx(lateral, abs=1e-3)


def test_dome_arc_is_not_septal_apex_lateral_triangle() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = _warp_truncated_oval_arc(septal, lateral, apex, view="A4C", num_points=81)
    quarter = warped[len(warped) // 4]
    triangle_x = 0.25 * apex[0]
    triangle_y = 0.25 * apex[1]
    assert quarter[0] > triangle_x + 10.0
    assert quarter[1] > triangle_y + 5.0


def test_fit_contour_dome_includes_lateral_blend_before_apex() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = _warp_truncated_oval_arc(septal, lateral, apex, view="A4C", num_points=81)
    quarter = warped[len(warped) // 4]
    assert 0.0 < quarter[0] < 100.0
    assert quarter[1] > 0.0


def test_fit_contour_apex_near_user_landmark() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)

    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )
    apex_on_arc = max(contour.points, key=lambda point: point[1])
    apex_dist = math.hypot(apex_on_arc[0] - apex[0], apex_on_arc[1] - apex[1])
    assert apex_dist < 5.0


def test_fit_contour_rejects_short_annulus() -> None:
    with pytest.raises(ValueError, match="mitral annulus length"):
        fit_contour_from_landmarks(
            septal=(0.0, 0.0),
            lateral=(5.0, 0.0),
            apex=(2.0, 20.0),
            phase="ED",
        )


def test_fit_contour_rejects_apex_on_annulus() -> None:
    with pytest.raises(ValueError, match="apex must be"):
        fit_contour_from_landmarks(
            septal=(0.0, 0.0),
            lateral=(50.0, 0.0),
            apex=(25.0, 0.0),
            phase="ED",
        )


def test_a2c_warp_profile_differs_from_a4c() -> None:
    assert ARC_WARP_A2C.peak_bias != pytest.approx(ARC_WARP_A4C.peak_bias)


def test_fit_contour_uses_a2c_profile_for_a2c_view() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)
    a4c = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
        view="A4C",
    )
    a2c = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
        view="A2C",
    )
    mid_a4c = a4c.points[len(a4c.points) // 2]
    mid_a2c = a2c.points[len(a2c.points) // 2]
    assert mid_a4c != pytest.approx(mid_a2c, abs=0.5)


def test_refine_model_contour_opt_in() -> None:
    frame = np.zeros((120, 120), dtype=np.float64)
    frame[20:100, 20:100] = 200.0
    contour = fit_contour_from_landmarks(
        septal=(30.0, 90.0),
        lateral=(90.0, 90.0),
        apex=(60.0, 20.0),
        phase="ED",
    )
    refined = refine_model_contour(frame, contour)
    assert refined.source == "model"
    assert len(refined.points) == DEFAULT_NODE_COUNT


def test_refine_open_arc_contour_preserves_manual_source() -> None:
    frame = np.zeros((120, 120), dtype=np.float64)
    frame[20:100, 20:100] = 200.0
    contour = fit_contour_from_landmarks(
        septal=(30.0, 90.0),
        lateral=(90.0, 90.0),
        apex=(60.0, 20.0),
        phase="ED",
    )
    contour.source = "manual"
    refined = refine_open_arc_contour(frame, contour)
    assert refined.source == "manual"
    assert len(refined.points) == DEFAULT_NODE_COUNT


def test_fit_contour_simpson_volume_positive() -> None:
    ed = fit_contour_from_landmarks(
        septal=(10.0, 40.0),
        lateral=(50.0, 40.0),
        apex=(30.0, 10.0),
        phase="ED",
    )
    es = fit_contour_from_landmarks(
        septal=(12.0, 40.0),
        lateral=(48.0, 40.0),
        apex=(30.0, 15.0),
        phase="ES",
    )
    result = calculate((ed, es), (0.5, 0.5))
    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml > 0.0
    assert result.a4c.esv_ml > 0.0
    assert result.lvef_percent > 0.0
