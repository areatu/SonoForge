"""Unit tests for ui/strain_curves_view.py."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    """Ensure QApplication exists for QWidget creation."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSegmentCurvePanel:
    def _make_panel(self):
        from echo_personal_tool.ui.strain_curves_view import SegmentCurvePanel

        return SegmentCurvePanel("TestPanel")

    def test_construction_creates_widgets(self):
        panel = self._make_panel()
        assert panel._title == "TestPanel"
        assert panel._plot is not None
        assert panel._ecg_plot is not None
        assert panel._curves == {}

    def test_set_strain_data_empty(self):
        panel = self._make_panel()
        panel.set_strain_data({})
        assert panel._curves == {}

    def test_set_strain_data_single_segment(self):
        panel = self._make_panel()
        data = {1: np.array([0.0, -5.0, -10.0])}
        panel.set_strain_data(data, ed_index=0, es_index=2, frame_time_ms=33.3)
        assert 1 in panel._curves
        assert panel._mean_curve is None  # single segment → no mean

    def test_set_strain_data_multiple_segments_creates_mean(self):
        panel = self._make_panel()
        data = {
            1: np.array([0.0, -5.0, -10.0]),
            2: np.array([0.0, -3.0, -8.0]),
        }
        panel.set_strain_data(data, frame_time_ms=33.3)
        assert 1 in panel._curves
        assert 2 in panel._curves
        assert panel._mean_curve is not None

    def test_set_strain_data_ignored_segment(self):
        panel = self._make_panel()
        data = {99: np.array([0.0, -5.0])}
        panel.set_strain_data(data)
        assert 99 not in panel._curves

    def test_set_strain_data_clears_old_curves(self):
        panel = self._make_panel()
        panel.set_strain_data({1: np.array([0.0, -5.0])})
        assert len(panel._curves) == 1
        panel.set_strain_data({2: np.array([0.0, -3.0])})
        assert 1 not in panel._curves
        assert 2 in panel._curves

    def test_set_strain_data_es_marker(self):
        panel = self._make_panel()
        panel.set_strain_data({1: np.array([0.0, -5.0, -10.0])}, es_index=2, frame_time_ms=33.3)
        assert panel._es_marker is not None

    def test_set_ecg_trace(self):
        panel = self._make_panel()
        ecg = np.array([0.0, 0.5, 1.0, 0.5, 0.0])
        panel.set_ecg_trace(ecg, frame_time_ms=33.3, current_frame=2)
        assert panel._ecg_item is not None
        assert panel._ecg_marker is not None

    def test_set_ecg_trace_empty(self):
        panel = self._make_panel()
        panel.set_ecg_trace(np.array([]))
        assert panel._ecg_item is None
        assert panel._ecg_marker is None

    def test_set_ecg_trace_none(self):
        panel = self._make_panel()
        panel.set_ecg_trace(None)
        assert panel._ecg_item is None

    def test_set_ecg_trace_clears_old(self):
        panel = self._make_panel()
        panel.set_ecg_trace(np.array([0.0, 1.0]))
        panel.set_ecg_trace(np.array([0.0, 2.0]))
        assert panel._ecg_item is not None

    def test_clear(self):
        panel = self._make_panel()
        panel.set_strain_data({1: np.array([0.0, -5.0, -10.0])}, es_index=1)
        panel.set_ecg_trace(np.array([0.0, 0.5, 1.0]))
        panel.clear()
        assert panel._curves == {}
        assert panel._mean_curve is None
        assert panel._es_marker is None
        assert panel._ecg_item is None
        assert panel._ecg_marker is None


class TestStrainCurvesView:
    def _make_view(self):
        from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

        return StrainCurvesView()

    def test_construction(self):
        view = self._make_view()
        assert view._panel_a4c is not None
        assert view._panel_a2c is not None
        assert view._panel_dao is not None

    def test_clear(self):
        view = self._make_view()
        view.clear()  # should not raise

    def test_generate_synthetic_ecg_normal(self):
        view = self._make_view()
        ecg = view._generate_synthetic_ecg(100, 72.0)
        assert ecg.shape == (100,)
        assert ecg.max() > 0.5  # R wave present

    def test_generate_synthetic_ecg_low_frames(self):
        view = self._make_view()
        ecg = view._generate_synthetic_ecg(1, 72.0)
        assert ecg.shape == (100,)  # pads to 100

    def test_generate_synthetic_ecg_zero_hr(self):
        view = self._make_view()
        ecg = view._generate_synthetic_ecg(50, 0.0)
        assert ecg.shape == (100,)
        assert np.allclose(ecg, 0.0)

    def test_generate_synthetic_ecg_negative_hr(self):
        view = self._make_view()
        ecg = view._generate_synthetic_ecg(50, -10.0)
        assert ecg.shape == (100,)

    def test_generate_synthetic_ecg_high_hr(self):
        view = self._make_view()
        ecg = view._generate_synthetic_ecg(200, 180.0)
        assert ecg.shape == (200,)
        # Should have non-zero values (QRS complexes)
        assert np.count_nonzero(ecg) > 0

    def _make_result(self, ecg: np.ndarray | None = None):
        from dataclasses import replace as dc_replace

        from echo_personal_tool.domain.models.speckle import StrainResult, TrackingKernel

        n, k = 12, 6
        positions = np.zeros((n, k, 2))
        for t in range(n):
            for i in range(k):
                positions[t, i] = [10 + i * 5, 40 + t]
        kernels = [TrackingKernel(center=(10 + i * 5, 40), node_index=i, layer="endo", aha_segment=i + 1) for i in range(k)]
        base = StrainResult(
            longitudinal=np.zeros(n),
            radial=np.zeros(n),
            gls=-15.0,
            segment_strain={1: -18.0, 2: -16.0, 3: -15.0, 4: -14.0, 5: -13.0, 6: -12.0},
            kernels=kernels,
            per_kernel_longitudinal=np.zeros((k, n)),
            tracked_positions_all=positions,
            ed_index=0,
            es_index=6,
            frame_time_ms=33.3,
        )
        return dc_replace(base, ecg_trace_for_display=ecg)

    def test_set_strain_data_no_ecg_hides_strips(self):
        view = self._make_view()
        view.set_strain_data(self._make_result(ecg=None))
        assert view._panel_a4c._ecg_plot.isHidden()
        # GLS header is filled from A4C segment strains
        assert "GLS" in view._panel_a4c._gls_label.text()
        # empty views show no ECG either
        assert view._panel_a2c._ecg_plot.isHidden()

    def test_set_strain_data_real_ecg_shows_strip(self):
        view = self._make_view()
        view.set_strain_data(self._make_result(ecg=np.sin(np.arange(200) / 10.0)))
        assert not view._panel_a4c._ecg_plot.isHidden()
        assert view._panel_a4c._ecg_item is not None


class TestConstants:
    def test_segment_colors_keys(self):
        from echo_personal_tool.ui.strain_curves_view import SEGMENT_COLORS

        assert set(SEGMENT_COLORS.keys()) == {1, 2, 3, 4, 5, 6}

    def test_segment_names_ru_keys(self):
        from echo_personal_tool.ui.strain_curves_view import SEGMENT_NAMES_RU

        assert set(SEGMENT_NAMES_RU.keys()) == {1, 2, 3, 4, 5, 6}

    def test_view_segments(self):
        from echo_personal_tool.ui.strain_curves_view import VIEW_SEGMENTS

        assert VIEW_SEGMENTS["A4C"] == [1, 2, 3, 4, 5, 6]
        assert VIEW_SEGMENTS["A2C"] == [7, 8, 9, 10, 11]
        assert VIEW_SEGMENTS["DAO"] == [12, 13, 14, 15, 16]
