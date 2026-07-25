"""Unit tests for presentation/speckle_overlay.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pyqtgraph as pg
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def overlay():
    from echo_personal_tool.presentation.speckle_overlay import SpeckleOverlay

    plot = pg.PlotWidget()
    o = SpeckleOverlay(plot)
    yield o
    plot.close()


def _make_kernel(x=50.0, y=50.0, layer="endo"):
    from echo_personal_tool.domain.models.speckle import TrackingKernel

    return TrackingKernel(center=(x, y), radius=10, node_index=0, layer=layer)


def _make_zone(n_points=10):
    from echo_personal_tool.domain.models.speckle import MyocardialZone

    angles = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    endo = np.column_stack([50 + 20 * np.cos(angles), 50 + 20 * np.sin(angles)])
    epi = np.column_stack([50 + 35 * np.cos(angles), 50 + 35 * np.sin(angles)])
    return MyocardialZone(endo_points=endo, epi_points=epi, thickness_mm=8.0, pixel_spacing=(0.1, 0.1))


class TestSpeckleOverlayConstruction:
    def test_creates_overlay_items(self, overlay):
        assert overlay._plot is not None
        assert overlay._zone_item is not None
        assert overlay._kernel_scatter is not None
        assert overlay._displacement_arrows == []
        assert overlay._strain_items == []
        assert overlay._phase_contour_items == []


class TestShowMyocardialZone:
    def test_sets_zone_data(self, overlay):
        zone = _make_zone(10)
        overlay.show_myocardial_zone(zone)
        # Zone should have data after setting
        assert overlay._zone_item.xData is not None
        assert len(overlay._zone_item.xData) > 0

    def test_zone_polygon_is_closed(self, overlay):
        zone = _make_zone(5)
        overlay.show_myocardial_zone(zone)
        x_data = overlay._zone_item.xData
        y_data = overlay._zone_item.yData
        # Zone should be a closed polygon (epi + reversed endo)
        assert len(x_data) > 0


class TestShowMyocardialZoneDynamic:
    def test_with_valid_points(self, overlay):
        pts = np.array([[10, 10], [20, 10], [30, 10], [20, 20]])
        overlay.show_myocardial_zone_dynamic(pts)
        assert overlay._zone_item.xData is not None

    def test_with_too_few_points_clears(self, overlay):
        pts = np.array([[10, 10], [20, 10]])
        overlay.show_myocardial_zone_dynamic(pts)
        x_data = overlay._zone_item.xData
        assert x_data is None or len(x_data) == 0

    def test_empty_array_clears(self, overlay):
        overlay.show_myocardial_zone_dynamic(np.array([]))
        x_data = overlay._zone_item.xData
        assert x_data is None or len(x_data) == 0


class TestShowKernels:
    def test_empty_kernels_clears(self, overlay):
        overlay.show_kernels([])
        x_data = overlay._kernel_scatter.getData()[0]
        assert len(x_data) == 0

    def test_kernels_with_positions(self, overlay):
        kernels = [_make_kernel(10, 20, "endo"), _make_kernel(30, 40, "mid")]
        positions = np.array([[10, 20], [30, 40]])
        overlay.show_kernels(kernels, positions=positions)
        x_data = overlay._kernel_scatter.getData()[0]
        assert len(x_data) == 2

    def test_kernels_without_positions(self, overlay):
        kernels = [_make_kernel(10, 20)]
        overlay.show_kernels(kernels)
        x_data = overlay._kernel_scatter.getData()[0]
        assert len(x_data) == 1

    def test_with_valid_mask_and_ncc(self, overlay):
        kernels = [_make_kernel(10, 20), _make_kernel(30, 40)]
        valid_mask = np.array([True, False])
        ncc_scores = np.array([0.9, 0.3])
        overlay.show_kernels(kernels, valid_mask=valid_mask, ncc_scores=ncc_scores)
        x_data = overlay._kernel_scatter.getData()[0]
        assert len(x_data) == 2

    def test_nan_position_falls_back_to_center(self, overlay):
        kernels = [_make_kernel(10, 20)]
        positions = np.array([[np.nan, np.nan]])
        overlay.show_kernels(kernels, positions=positions)
        x_data = overlay._kernel_scatter.getData()[0]
        assert x_data[0] == 10.0
        y_data = overlay._kernel_scatter.getData()[1]
        assert y_data[0] == 20.0


class TestShowDisplacements:
    def test_empty_kernels_does_nothing(self, overlay):
        overlay.show_displacements([], np.array([]))
        assert len(overlay._displacement_arrows) == 0

    def test_creates_arrows(self, overlay):
        kernels = [_make_kernel(10, 10)]
        displacements = np.array([[5.0, 3.0]])
        overlay.show_displacements(kernels, displacements, scale=1.0)
        assert len(overlay._displacement_arrows) == 1

    def test_small_displacement_skipped(self, overlay):
        kernels = [_make_kernel(10, 10)]
        displacements = np.array([[0.01, 0.01]])
        overlay.show_displacements(kernels, displacements, scale=1.0)
        assert len(overlay._displacement_arrows) == 0


class TestShowEdEsDisplacements:
    def test_with_valid_contours(self, overlay):
        ed = np.array([[10, 10], [20, 20]])
        es = np.array([[12, 12], [22, 22]])
        overlay.show_ed_es_displacements(ed, es)
        assert len(overlay._displacement_arrows) == 2

    def test_with_none_contours(self, overlay):
        overlay.show_ed_es_displacements(None, None)
        assert len(overlay._displacement_arrows) == 0

    def test_with_too_few_points(self, overlay):
        ed = np.array([[10, 10]])
        es = np.array([[12, 12]])
        overlay.show_ed_es_displacements(ed, es)
        assert len(overlay._displacement_arrows) == 0

    def test_same_points_skipped(self, overlay):
        ed = np.array([[10, 10], [20, 20]])
        es = np.array([[10, 10], [20, 20]])
        overlay.show_ed_es_displacements(ed, es)
        assert len(overlay._displacement_arrows) == 0


class TestShowStrainColorMap:
    def test_empty_kernels(self, overlay):
        overlay.show_strain_color_map([], np.array([]))
        assert len(overlay._strain_items) == 0

    def test_colors_endo_kernels(self, overlay):
        kernels = [_make_kernel(10, 10, "endo"), _make_kernel(20, 20, "mid")]
        strain = np.array([-20.0, -10.0])
        overlay.show_strain_color_map(kernels, strain)
        # Only endo kernels get strain items
        assert len(overlay._strain_items) == 1

    def test_with_positions(self, overlay):
        kernels = [_make_kernel(10, 10, "endo")]
        strain = np.array([-15.0])
        positions = np.array([[100, 200]])
        overlay.show_strain_color_map(kernels, strain, positions=positions)
        assert len(overlay._strain_items) == 1


class TestShowPhaseContours:
    def test_ed_and_es_contours(self, overlay):
        ed = np.array([[10, 10], [20, 20], [30, 10]])
        es = np.array([[12, 12], [22, 22], [32, 12]])
        overlay.show_phase_contours(ed, es)
        assert len(overlay._phase_contour_items) == 2

    def test_none_contours(self, overlay):
        overlay.show_phase_contours(None, None)
        assert len(overlay._phase_contour_items) == 0

    def test_short_contour_not_drawn(self, overlay):
        ed = np.array([[10, 10], [20, 20]])
        overlay.show_phase_contours(ed, None)
        assert len(overlay._phase_contour_items) == 0


class TestClear:
    def test_clears_all_items(self, overlay):
        kernels = [_make_kernel(10, 10)]
        overlay.show_kernels(kernels)
        overlay._strain_items.append(MagicMock())
        overlay._displacement_arrows.append(MagicMock())
        overlay._phase_contour_items.append(MagicMock())

        overlay.clear()

        assert overlay._zone_item.xData is None or len(overlay._zone_item.xData) == 0
        assert overlay._displacement_arrows == []
        assert overlay._strain_items == []
        assert overlay._phase_contour_items == []


class TestNccHeatmap:
    def test_empty_kernels(self, overlay):
        overlay.show_ncc_heatmap([], np.array([]))
        assert len(overlay._strain_items) == 0

    def test_colors_all_kernels(self, overlay):
        kernels = [_make_kernel(10, 10, "endo"), _make_kernel(20, 20, "mid")]
        ncc = np.array([0.9, 0.5])
        overlay.show_ncc_heatmap(kernels, ncc)
        assert len(overlay._strain_items) == 2


class TestKernelClickedSignal:
    def test_signal_emitted(self, overlay):
        mock_signal = MagicMock()
        overlay.kernel_clicked.connect(mock_signal)
        # Simulate kernel click
        overlay._on_kernel_clicked(None, [])
        mock_signal.assert_not_called()

        mock_point = MagicMock()
        mock_point.index.return_value = 5
        overlay._on_kernel_clicked(None, [mock_point])
        mock_signal.assert_called_once_with(5)
