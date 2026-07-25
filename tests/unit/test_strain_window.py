"""Unit tests for ui/strain_window.py — CinePanel, BullseyeWidget, SummaryTable, ControlPanel, StrainWindow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSmoothContour:
    def test_smooth_contour_fewer_than_4_points(self):
        from echo_personal_tool.ui.strain_window import _smooth_contour

        pts = np.array([[0, 0], [1, 0], [0, 1]])
        result = _smooth_contour(pts, n_output=64)
        np.testing.assert_array_equal(result, pts)

    def test_smooth_contour_normal(self):
        from echo_personal_tool.ui.strain_window import _smooth_contour

        # 4+ distinct points needed for CubicSpline periodic BC
        pts = np.array([[0, 0], [5, 0], [5, 5], [0, 5]], dtype=float)
        result = _smooth_contour(pts, n_output=32)
        assert result.shape == (32, 2)

    def test_smooth_contour_degenerate_all_same(self):
        from echo_personal_tool.ui.strain_window import _smooth_contour

        pts = np.array([[0, 0], [0, 0], [0, 0], [0, 0]], dtype=float)
        result = _smooth_contour(pts, n_output=32)
        # total_len < 1e-6 → returns original
        np.testing.assert_array_equal(result, pts)


class TestCinePanel:
    def _make_panel(self, title: str = "A4C"):
        from echo_personal_tool.ui.strain_window import CinePanel

        return CinePanel(title)

    def test_construction(self):
        panel = self._make_panel()
        assert panel._title == "A4C"
        assert panel._edit_mode is False
        assert panel._kernel_positions is None

    def test_set_title_info(self):
        panel = self._make_panel()
        panel.set_title_info("GLS: -20.0%")
        assert panel._info_label.text() == "GLS: -20.0%"

    def test_set_hr(self):
        panel = self._make_panel()
        panel.set_hr(72.5)
        assert "72" in panel._hr_label.text()

    def test_set_frame(self):
        panel = self._make_panel()
        panel.set_frame(15, 30)
        assert panel._frame_label.text() == "15/30"

    def test_show_contour_too_few_points(self):
        panel = self._make_panel()
        panel.show_contour(np.array([[0, 0], [1, 0]]))
        assert panel._ed_contour_item is None

    def test_show_contour_valid(self):
        panel = self._make_panel()
        pts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        panel.show_contour(pts, smooth=False)
        assert panel._ed_contour_item is not None

    def test_show_contour_smooth(self):
        panel = self._make_panel()
        pts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        panel.show_contour(pts, smooth=True)
        assert panel._ed_contour_item is not None

    def test_show_contour_replaces_old(self):
        panel = self._make_panel()
        pts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        panel.show_contour(pts, smooth=False)
        old_item = panel._ed_contour_item
        panel.show_contour(pts, smooth=False)
        assert panel._ed_contour_item is not old_item

    def test_show_es_contour_none(self):
        panel = self._make_panel()
        panel.show_es_contour(None)
        assert panel._es_contour_item is None

    def test_show_es_contour_valid(self):
        panel = self._make_panel()
        pts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        panel.show_es_contour(pts, smooth=False)
        assert panel._es_contour_item is not None

    def test_show_kernels_empty(self):
        panel = self._make_panel()
        panel.show_kernels(np.array([]).reshape(0, 2))
        assert panel._kernel_scatter is None

    def test_show_kernels_with_scores(self):
        panel = self._make_panel()
        pos = np.array([[10.0, 20.0], [30.0, 40.0]])
        ncc = np.array([0.8, 0.2])
        valid = np.array([True, False])
        panel.show_kernels(pos, ncc, valid)
        assert panel._kernel_scatter is not None
        assert panel._kernel_positions is not None

    def test_show_kernels_without_scores(self):
        panel = self._make_panel()
        pos = np.array([[10.0, 20.0]])
        panel.show_kernels(pos)
        assert panel._kernel_scatter is not None

    def test_set_edit_mode(self):
        panel = self._make_panel()
        panel.set_edit_mode(True)
        assert panel._edit_mode is True
        panel.set_edit_mode(False)
        assert panel._edit_mode is False

    def test_select_kernel(self):
        panel = self._make_panel()
        pos = np.array([[10.0, 20.0], [30.0, 40.0]])
        panel.show_kernels(pos)
        panel._select_kernel(0)
        assert panel._selected_kernel_idx == 0
        assert panel._selected_kernel_item is not None

    def test_deselect_kernel(self):
        panel = self._make_panel()
        pos = np.array([[10.0, 20.0], [30.0, 40.0]])
        panel.show_kernels(pos)
        panel._select_kernel(0)
        panel._deselect_kernel()
        assert panel._selected_kernel_idx is None
        assert panel._selected_kernel_item is None

    def test_move_selected_kernel(self):
        panel = self._make_panel()
        pos = np.array([[10.0, 20.0], [30.0, 40.0]])
        panel.show_kernels(pos)
        panel._select_kernel(0)
        signal_received = []
        panel.kernel_moved.connect(lambda idx, x, y: signal_received.append((idx, x, y)))
        panel.move_selected_kernel(50.0, 60.0)
        assert signal_received == [(0, 50.0, 60.0)]
        assert panel._kernel_positions[0, 0] == 50.0
        assert panel._kernel_positions[0, 1] == 60.0

    def test_move_selected_kernel_no_selection(self):
        panel = self._make_panel()
        panel.move_selected_kernel(50.0, 60.0)  # no-op, no crash

    def test_show_segment_labels(self):
        from echo_personal_tool.ui.strain_window import CinePanel

        panel = self._make_panel()
        kernels = [MagicMock(aha_segment=1), MagicMock(aha_segment=2)]
        pos = np.array([[10.0, 20.0], [30.0, 40.0]])
        panel.show_segment_labels(kernels, pos)
        assert len(panel._segment_labels) == 2

    def test_show_segment_labels_empty(self):
        panel = self._make_panel()
        panel.show_segment_labels([], np.array([]).reshape(0, 2))
        assert len(panel._segment_labels) == 0

    def test_show_ecg_trace(self):
        panel = self._make_panel()
        ecg = np.array([0.0, 0.5, 1.0, 0.5, 0.0])
        panel.show_ecg_trace(ecg, current_frame=2)
        assert panel._ecg_item is not None
        assert panel._ecg_marker is not None

    def test_show_ecg_trace_none(self):
        panel = self._make_panel()
        panel.show_ecg_trace(None)
        assert panel._ecg_item is None

    def test_show_ecg_trace_clears_old(self):
        panel = self._make_panel()
        panel.show_ecg_trace(np.array([0.0, 1.0]))
        panel.show_ecg_trace(np.array([0.0, 2.0]))
        assert panel._ecg_item is not None

    def test_clear(self):
        panel = self._make_panel()
        pts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        panel.show_contour(pts, smooth=False)
        panel.show_es_contour(pts, smooth=False)
        panel.show_kernels(np.array([[10.0, 20.0]]))
        panel.show_ecg_trace(np.array([0.0, 1.0]))
        panel.clear()
        assert panel._ed_contour_item is None
        assert panel._es_contour_item is None
        assert panel._kernel_scatter is None
        assert panel._ecg_item is None
        assert panel._hr_label.text() == "HR: --"
        assert panel._frame_label.text() == "--/--"

    def test_on_mouse_clicked_not_edit_mode(self):
        panel = self._make_panel()
        # Should not crash when edit_mode is False
        event = MagicMock()
        panel._on_mouse_clicked(event)

    def test_on_mouse_clicked_no_kernel_positions(self):
        panel = self._make_panel()
        panel.set_edit_mode(True)
        event = MagicMock()
        panel._on_mouse_clicked(event)  # _kernel_positions is None

    def test_kernel_selected_signal(self):
        panel = self._make_panel()
        pos = np.array([[10.0, 20.0], [30.0, 40.0]])
        panel.show_kernels(pos)
        received = []
        panel.kernel_selected.connect(lambda idx: received.append(idx))
        panel._select_kernel(1)
        assert received == [1]


class TestBullseyeWidget:
    def _make_widget(self):
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        return BullseyeWidget()

    def test_construction(self):
        w = self._make_widget()
        assert w._segment_strains == {}
        assert w._segment_quality == {}

    def test_update_data(self):
        w = self._make_widget()
        data = {1: -20.0, 2: -15.0, 3: -10.0}
        w.update_data(data, {1: 0.8, 2: 0.9})
        assert w._segment_strains == data
        assert w._segment_quality == {1: 0.8, 2: 0.9}

    def test_update_qc(self):
        w = self._make_widget()
        w.update_qc({1: -20.0}, {1: 0.8}, {1})
        assert w._qc_accepted_segments == {1}

    def test_clear(self):
        w = self._make_widget()
        w.update_data({1: -20.0})
        w.clear()
        assert w._segment_strains == {}
        assert w._segment_quality == {}

    def test_strain_to_color_negative(self):
        w = self._make_widget()
        c = w._strain_to_color(-25.0)
        assert c.red() == 255
        assert c.green() == 0
        assert c.blue() == 0

    def test_strain_to_color_zero(self):
        w = self._make_widget()
        c = w._strain_to_color(0.0)
        assert c.red() == 255
        assert c.green() == 255
        assert c.blue() == 255

    def test_strain_to_color_positive(self):
        w = self._make_widget()
        c = w._strain_to_color(10.0)
        assert c.red() == 0
        assert c.green() == 0
        assert c.blue() == 255

    def test_strain_to_color_clamped_high(self):
        w = self._make_widget()
        c = w._strain_to_color(100.0)
        assert c.blue() == 255

    def test_strain_to_color_clamped_low(self):
        w = self._make_widget()
        c = w._strain_to_color(-100.0)
        assert c.red() == 255

    def test_segment_geometry_has_17_segments(self):
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        assert len(BullseyeWidget.SEGMENT_GEOMETRY) == 17

    def test_paint_event(self):
        from PySide6.QtGui import QImage, QPainter

        w = self._make_widget()
        w.update_data({1: -15.0, 17: -10.0})
        w.resize(300, 300)
        # Trigger paint by creating a QImage
        img = QImage(300, 300, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        event = MagicMock()
        w.paintEvent(event)
        painter.end()


class TestSummaryTable:
    def _make_table(self):
        from echo_personal_tool.ui.strain_window import SummaryTable

        return SummaryTable()

    def test_construction(self):
        table = self._make_table()
        assert "gls" in table._rows
        assert "hr" in table._rows

    def test_update_values_percentage(self):
        table = self._make_table()
        table.update_values(gls=-20.5)
        assert "-20.5%" in table._rows["gls"][1].text()

    def test_update_values_ml(self):
        table = self._make_table()
        table.update_values(edv=120.3)
        assert "120.3 мл" in table._rows["edv"][1].text()

    def test_update_values_ms(self):
        table = self._make_table()
        table.update_values(autozak=350)
        assert "350 мс" in table._rows["autozak"][1].text()

    def test_update_values_bpm(self):
        table = self._make_table()
        table.update_values(hr=72.0)
        assert "72 bpm" in table._rows["hr"][1].text()

    def test_update_values_none(self):
        table = self._make_table()
        table.update_values(gls=None)
        assert table._rows["gls"][1].text() == "--"

    def test_update_values_string(self):
        table = self._make_table()
        table.update_values(gls="N/A")
        assert table._rows["gls"][1].text() == "N/A"

    def test_update_values_unknown_key(self):
        table = self._make_table()
        table.update_values(nonexistent=42)  # should not crash


class TestControlPanel:
    def _make_panel(self):
        from echo_personal_tool.ui.strain_window import ControlPanel

        return ControlPanel()

    def test_construction(self):
        panel = self._make_panel()
        assert panel._mode_contour.isChecked()
        assert panel._metric_deformation.isChecked()

    def test_update_quality(self):
        panel = self._make_panel()
        panel.update_quality(80, 100, 20)
        assert "80 / 100 (80%)" in panel._quality_label.text()
        assert "20 kernels rejected" in panel._rejected_label.text()

    def test_update_quality_zero_total(self):
        panel = self._make_panel()
        panel.update_quality(0, 0, 0)
        assert panel._quality_label.text() == "-- / --"
        assert panel._rejected_label.text() == ""

    def test_update_quality_no_rejected(self):
        panel = self._make_panel()
        panel.update_quality(10, 10, 0)
        assert panel._rejected_label.text() == ""

    def test_view_toggled_signal(self):
        panel = self._make_panel()
        received = []
        panel.view_toggled.connect(lambda name, checked: received.append((name, checked)))
        panel._cb_a4c.toggled.emit(False)
        assert ("A4C", False) in received

    def test_display_mode_changed_signal(self):
        panel = self._make_panel()
        received = []
        panel.display_mode_changed.connect(lambda mode: received.append(mode))
        panel._mode_curves.setChecked(True)
        assert "curves" in received


class TestStrainWindow:
    def _make_window(self):
        from echo_personal_tool.ui.strain_window import StrainWindow

        return StrainWindow()

    def test_construction(self):
        w = self._make_window()
        assert w.windowTitle() == "Strain Analysis"
        assert w._qc_accepted_segments == set(range(1, 18))
        assert w._undo_stack == []

    def test_on_view_toggled(self):
        w = self._make_window()
        w._on_view_toggled("A4C", False)
        assert w._panel_a4c.isHidden()
        w._on_view_toggled("A4C", True)
        assert not w._panel_a4c.isHidden()

    def test_on_display_mode_contour(self):
        w = self._make_window()
        w._on_display_mode_changed("contour")
        assert w._stacked.currentIndex() == 0

    def test_on_display_mode_curves(self):
        w = self._make_window()
        w._on_display_mode_changed("curves")
        assert w._stacked.currentIndex() == 1

    def test_on_display_mode_edit(self):
        w = self._make_window()
        w._on_display_mode_changed("edit_mode")
        assert w._stacked.currentIndex() == 0
        assert w._panel_a4c._edit_mode is True

    def test_on_strain_metric_no_result(self):
        w = self._make_window()
        w._on_strain_metric_changed("deformation")  # should not crash

    def test_on_qc_segment_toggled(self):
        w = self._make_window()
        w._on_qc_segment_toggled(5, False)
        assert 5 not in w._qc_accepted_segments
        w._on_qc_segment_toggled(5, True)
        assert 5 in w._qc_accepted_segments

    def test_generate_synthetic_ecg(self):
        w = self._make_window()
        ecg = w._generate_synthetic_ecg(100, 72.0)
        assert ecg.shape == (100,)
        assert ecg.max() > 0.5

    def test_generate_synthetic_ecg_zero_hr(self):
        w = self._make_window()
        ecg = w._generate_synthetic_ecg(50, 0.0)
        assert ecg.shape == (100,)
        assert np.allclose(ecg, 0.0)

    def test_undo_redo_empty_stacks(self):
        w = self._make_window()
        w._undo_kernel_move()  # no-op
        w._redo_kernel_move()  # no-op

    def test_on_kernel_moved_no_result(self):
        w = self._make_window()
        w._on_kernel_moved("A4C", 0, 100.0, 200.0)  # no-op, _result is None

    def test_close_event(self):
        w = self._make_window()
        received = []
        w.closed.connect(lambda: received.append(True))
        from PySide6.QtGui import QCloseEvent

        event = QCloseEvent()
        w.closeEvent(event)
        assert received == [True]
