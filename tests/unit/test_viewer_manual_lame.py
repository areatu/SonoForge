"""Viewer tests for LV manual contour Lamé init."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    point_line_distance,
)
from echo_personal_tool.domain.services.mbs_lite_service import infer_apex_from_open_arc
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def test_finish_manual_lv_uses_lame_warp_not_triangle(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((120, 120), dtype=np.uint8))

    septal = (20.0, 90.0)
    lateral = (90.0, 90.0)
    apex = (55.0, 25.0)

    viewer._contour_mode_active = True
    viewer._contour_stage = "apex"
    viewer._active_contour_chamber = "LV"
    viewer._active_contour_phase = "ED"
    viewer._active_contour_view = "A4C"
    viewer._active_contour_source = "manual"
    viewer._active_mitral_annulus = (septal, lateral)

    finished = viewer._finish_manual_contour(apex=apex)
    assert finished is True

    contours = viewer.contours()
    assert len(contours) == 1
    contour = contours[0]
    assert contour.source == "manual"
    assert contour.chamber == "LV"
    assert len(contour.points) == DEFAULT_NODE_COUNT
    assert contour.points[0] == pytest.approx(septal, abs=1e-3)
    assert contour.points[-1] == pytest.approx(lateral, abs=1e-3)

    triangle_mid = (
        0.5 * (septal[0] + apex[0]),
        0.5 * (septal[1] + apex[1]),
    )
    interior = contour.points[DEFAULT_NODE_COUNT // 4]
    # Image y grows downward; Lamé body sits above the septal→apex chord.
    assert interior[1] < triangle_mid[1]

    inferred = infer_apex_from_open_arc(contour.points, septal, lateral)
    apex_height = point_line_distance(apex, septal, lateral)
    assert point_line_distance(inferred, septal, lateral) == pytest.approx(
        apex_height, rel=0.1, abs=5.0
    )
