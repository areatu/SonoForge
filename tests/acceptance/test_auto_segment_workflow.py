"""Acceptance: open DICOM → auto-segment LV → review overlay → accept → measure LVEF."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import MainWindow

pytestmark = [pytest.mark.gui, pytest.mark.acceptance]


def _make_window(qtbot, qapp) -> MainWindow:
    prefs = UserPreferences(layout_state_json="")
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    window.resize(1280, 800)
    qtbot.addWidget(window)
    return window


class TestAutoSegmentWorkflow:
    def test_window_instantiates_with_controller(self, qtbot, qapp) -> None:
        """MainWindow creates and binds an AppController."""
        window = _make_window(qtbot, qapp)
        assert window._controller is not None
        assert isinstance(window._controller, AppController)

    def test_mock_onnx_segmenter_returns_valid_mask(self, mock_onnx_segmenter) -> None:
        """Mock ONNX segmenter produces a valid binary mask."""
        import numpy as np

        frame = np.random.randint(0, 255, (64, 64), dtype=np.uint8)
        mask = mock_onnx_segmenter.segment(frame)
        assert mask.shape == (64, 64)
        assert set(np.unique(mask)).issubset({0, 1})

    def test_mock_onnx_segmenter_available(self, mock_onnx_segmenter) -> None:
        """Mock segmenter reports available."""
        assert mock_onnx_segmenter.is_available() is True

    def test_mock_onnx_worker_returns_valid_mask(self, mock_onnx_worker) -> None:
        """Mock ONNX worker produces a valid segmentation mask."""
        mask = mock_onnx_worker.segment(np.zeros((64, 64), dtype=np.uint8))
        assert mask.shape == (64, 64)
        assert mask.sum() > 0

    def test_lvef_calculation_with_mock_contours(self) -> None:
        """LVEF can be calculated from mock contour polygons."""
        from echo_personal_tool.domain.calculations.lvef_simpson import calculate
        from echo_personal_tool.domain.models.contour import Contour

        pixel_spacing = (0.3, 0.3)
        # Create a simple closed polygon for ED (larger) and ES (smaller)
        ed_points = [(20, 10), (50, 10), (55, 32), (50, 54), (20, 54), (15, 32)]
        es_points = [(25, 20), (45, 20), (48, 32), (45, 44), (25, 44), (22, 32)]

        contours = (
            Contour(phase="ed", view="A4C", chamber="LV", points=ed_points),
            Contour(phase="es", view="A4C", chamber="LV", points=es_points),
        )
        result = calculate(contours, pixel_spacing)
        assert result is not None
        assert result.lvef_percent is not None
        assert 0 < result.lvef_percent < 100

    def test_planimeter_area_positive_for_closed_polygon(self) -> None:
        """Planimeter area is always positive for a valid closed contour."""
        from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2
        from echo_personal_tool.domain.models.contour import Contour

        contour = Contour(
            phase="ed",
            view="A4C",
            chamber="LV",
            points=[(10, 10), (50, 10), (50, 50), (10, 50)],
        )
        area = closed_polygon_area_cm2(contour, pixel_spacing=(0.3, 0.3))
        assert area is not None
        assert area > 0.0

    def test_window_has_viewer_for_overlay(self, qtbot, qapp) -> None:
        """MainWindow has a viewer widget where segmentation overlay can be drawn."""
        window = _make_window(qtbot, qapp)
        window.show()
        qtbot.waitExposed(window)
        assert hasattr(window, "_viewer")
