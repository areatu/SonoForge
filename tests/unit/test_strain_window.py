"""Unit tests for ui/strain_window.py — CinePanel, BullseyeWidget, SummaryTable, ControlPanel, StrainWindow."""

from __future__ import annotations

from unittest.mock import MagicMock

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

    def test_set_tracked_overlay_renders_and_plays(self):
        panel = self._make_panel()
        frames = np.zeros((10, 100, 100), dtype=np.uint8)
        panel.set_frames(frames, index=0)
        pos = np.zeros((10, 6, 2))
        for f in range(10):
            for k in range(6):
                pos[f, k] = [20 + k * 10, 30 + f]
        layers = ["endo", "endo", "endo", "mid", "mid", "epi"]
        panel.set_tracked_overlay(pos, layers=layers, ed_index=0, es_index=5)
        assert panel._anim_scatter is not None
        assert panel._anim_contour_item is not None  # >= 3 endo kernels

        # scrubbing moves the animated overlay
        panel._show_frame(3)
        assert panel._anim_scatter is not None

        # play toggles the timer and advances frames
        panel._toggle_play()
        assert panel._play_timer.isActive()
        panel._toggle_play()
        assert not panel._play_timer.isActive()

        # clear removes animated items
        panel.clear()
        assert panel._anim_scatter is None
        assert panel._anim_contour_item is None
        assert panel._tracked_positions_all is None

    def test_set_tracked_overlay_nan_frame_renders_red_only(self):
        panel = self._make_panel()
        frames = np.zeros((5, 100, 100), dtype=np.uint8)
        panel.set_frames(frames, index=0)
        pos = np.full((5, 4, 2), np.nan)
        for k in range(4):
            pos[0, k] = [10 + k * 10, 20]
        panel.set_tracked_overlay(pos, layers=["endo", "endo", "mid", "epi"])
        panel._show_frame(1)  # all-NaN frame → nothing drawn
        assert panel._anim_scatter is None

    def test_set_ecg_visible(self):
        panel = self._make_panel()
        panel.set_ecg_visible(False)
        assert panel._ecg_plot.isHidden()
        panel.set_ecg_visible(True)
        assert not panel._ecg_plot.isHidden()

    def test_show_ecg_trace_with_sample_rate_and_markers(self):
        panel = self._make_panel()
        ecg = np.sin(np.arange(100) / 5.0)
        panel.show_ecg_trace(
            ecg,
            frame_time_ms=33.3,
            current_frame=3,
            ecg_sample_rate=500.0,
            r_peak_times_ms=np.array([200.0, 800.0]),
            ed_frame=1,
            es_frame=5,
        )
        assert panel._ecg_item is not None
        assert len(panel._ecg_rpeak_items) == 2
        assert len(panel._ecg_phase_items) == 2
        # real time axis: 500 Hz → last sample at 198 ms
        assert panel._ecg_time_ms[-1] == pytest.approx(198.0)

        # frame marker moves when the frame changes
        panel._update_ecg_marker(7)
        assert panel._ecg_marker.pos().x() == pytest.approx(7 * 33.3)

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

    # The palette follows the clinical GE/EchoPAC bull's-eye convention
    # (plan §6.5): bright red = normal (|ε| ≥ 16 %), pale pink = borderline,
    # blue = positive strain. The tests below replaced the older
    # "red/white/blue" expectations of the pre-phase-3 widget.
    def test_strain_to_color_normal_is_bright_red(self):
        w = self._make_widget()
        c = w._strain_to_color(-25.0)
        assert (c.red(), c.green(), c.blue()) == (214, 24, 24)

    def test_strain_to_color_borderline_is_pale_pink(self):
        w = self._make_widget()
        c = w._strain_to_color(-3.0)
        assert (c.red(), c.green(), c.blue()) == (252, 224, 228)

    def test_strain_to_color_positive_is_blue(self):
        w = self._make_widget()
        c = w._strain_to_color(10.0)
        assert (c.red(), c.green(), c.blue()) == (66, 133, 244)

    def test_strain_to_color_clamped_high(self):
        w = self._make_widget()
        assert w._strain_to_color(100.0).blue() == 244

    def test_strain_to_color_clamped_low(self):
        w = self._make_widget()
        assert w._strain_to_color(-100.0).red() == 214

    def test_ttp_palette_is_blue_to_red(self):
        """Late activation must read red on the time-to-peak map (plan §6.5)."""
        w = self._make_widget()
        early = w._ttp_to_color(150.0)
        late = w._ttp_to_color(500.0)
        assert early.blue() > early.red()
        assert late.red() > late.blue()

    def test_segment_geometry_covers_the_aha_model(self):
        from echo_personal_tool.domain.services.segment_map import view_segment_ids
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        geometry = BullseyeWidget.SEGMENT_GEOMETRY
        assert len(geometry) == 18
        for view in ("A4C", "A2C", "A3C"):
            assert set(view_segment_ids(view)) <= set(geometry)

    # ── bull's-eye v2 (plan §6.5): palettes, colourbar, hover ──────────────
    def test_default_palette_is_ge(self):
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        w = self._make_widget()
        assert w.palette_key == "palette.ge"
        assert BullseyeWidget.PALETTES[0][0] == "palette.ge"

    def test_cycle_palette_walks_all_ramps_and_wraps(self):
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        w = self._make_widget()
        seen = [w.palette_key]
        for _ in range(len(BullseyeWidget.PALETTES) - 1):
            seen.append(w.cycle_palette())
        assert seen == [key for key, _ramp in BullseyeWidget.PALETTES]
        assert w.cycle_palette() == "palette.ge"  # wraps back to the default

    def test_set_palette_changes_the_colours(self):
        w = self._make_widget()
        ge = w._strain_to_color(-25.0)
        w.set_palette("palette.rainbow")
        rainbow = w._strain_to_color(-25.0)
        assert (ge.red(), ge.green(), ge.blue()) != (rainbow.red(), rainbow.green(), rainbow.blue())
        w.set_palette("no.such.palette")  # unknown names must not break the map
        assert w.palette_key == "palette.rainbow"

    def test_monochrome_threshold_keeps_normal_bright(self):
        w = self._make_widget()
        w.set_palette("palette.monochrome")
        normal = w._strain_to_color(-20.0)
        reduced = w._strain_to_color(-8.0)
        assert normal.red() > reduced.red()

    def test_colorbar_ticks_span_the_strain_scale(self):
        """Plan §6.5: −20…+20 % with 0/−5/−10/−15/−20 divisions, blue on top."""
        w = self._make_widget()
        labels = [label for _value, label in w._colorbar_ticks(ttp_mode=False)]
        assert labels[0] == "20"
        assert {"0", "-5", "-10", "-15", "-20"} <= set(labels)
        # TTP map scales to the study and stays readable
        w.update_data({1: -18.0}, {1: 0.9}, {1: 612.0})
        ttp_labels = [label for _value, label in w._colorbar_ticks(ttp_mode=True)]
        assert ttp_labels[0] == "700" and ttp_labels[-1] == "0"

    def test_missing_excluded_and_low_confidence_segments_are_marked(self):
        """State styling (plan §6.5): hatch / slash / dashed frame."""
        from PySide6.QtGui import QImage

        w = self._make_widget()
        w.resize(400, 400)
        # Segment 1 measured well, 2 excluded by QC, 3 low confidence, 4 missing.
        w.update_data({1: -20.0, 2: -20.0, 3: -20.0}, {1: 0.9, 2: 0.9, 3: 0.2})
        w.update_qc({1: -20.0, 2: -20.0, 3: -20.0}, {1: 0.9, 2: 0.9, 3: 0.2}, {1, 3})
        image = QImage(400, 400, QImage.Format.Format_ARGB32)
        w.render(image)  # must not raise

        def colours(seg):
            rect = w._segment_polygons[seg].boundingRect()
            x, y = int(rect.center().x()), int(rect.center().y())
            return {image.pixelColor(int(x + dx), int(y + dy)).name() for dx in (-6, 0, 6) for dy in (-6, 0, 6)}

        # Never measured: dark fill plus the hatch strokes.
        assert len(colours(4)) > 1
        # Excluded: grey fill plus the white slash.
        assert len(colours(2)) > 1
        # Low confidence: dashed frame drawn over the fill.
        assert len(colours(3)) > 1

    def test_colorbar_paints_without_error(self):
        from PySide6.QtGui import QImage, QPainter

        w = self._make_widget()
        w.resize(420, 320)
        w.update_data({seg: -18.0 for seg in range(1, 19)})
        # The QImage must stay referenced while the painter is alive.
        for ttp_mode in (False, True):
            image = QImage(420, 320, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            w._paint_colorbar(painter, 420, 320, 130.0, ttp_mode)
            painter.end()

    def test_hover_finds_the_segment_under_a_point(self):
        from PySide6.QtGui import QImage

        w = self._make_widget()
        w.resize(320, 320)
        w.update_data({seg: -18.0 for seg in range(1, 19)})
        w.render(QImage(320, 320, QImage.Format.Format_ARGB32))  # builds the polygons
        assert len(w._segment_polygons) == 18
        ring = w._segment_polygons[7]
        centre = ring.boundingRect().center()
        assert w.segment_at(centre.x(), centre.y()) == 7
        assert w.segment_at(-50.0, -50.0) is None

    def test_tooltip_reports_value_quality_and_ttp(self):
        w = self._make_widget()
        w.update_data({7: -17.4}, {7: 0.86}, {7: 340.0})
        text = w.segment_tooltip(7)
        assert "-17.4" in text and "0.86" in text and "340" in text

    def test_tooltip_says_no_data_instead_of_inventing_a_value(self):
        from echo_personal_tool.infrastructure.i18n import tr

        w = self._make_widget()
        assert tr("strain.no_data").lower() in w.segment_tooltip(12).lower()

    def test_ttp_mode_tooltip_uses_milliseconds(self):
        from echo_personal_tool.infrastructure.i18n import tr

        w = self._make_widget()
        w.update_data({7: -17.4}, {7: 0.9}, {7: 340.0})
        w.set_ttp_mode(True)
        text = w.segment_tooltip(7)
        assert "340" in text and tr("strain.unit_ms") in text

    def test_anterior_wall_is_centred_on_top_and_ring_runs_clockwise(self):
        """Segments must sit where the AHA model puts them (vendors centre the
        anterior wall on 12 o'clock, not merely start there)."""
        from PySide6.QtGui import QImage

        from echo_personal_tool.ui.strain_window import BullseyeWidget

        w = self._make_widget()
        w.resize(400, 400)
        w.update_data({seg: -18.0 for seg in range(1, 19)})
        w.render(QImage(400, 400, QImage.Format.Format_ARGB32))

        map_w = 400 - (BullseyeWidget.COLORBAR_WIDTH + 46)
        cx, cy = map_w / 2, 200.0
        anterior = w._segment_polygons[1].boundingRect().center()
        assert abs(anterior.x() - cx) < 2.0
        assert anterior.y() < cy  # above the centre
        # Clockwise from anterior: 6 = anterolateral is to the right of 1 …
        assert w._segment_polygons[6].boundingRect().center().x() > cx
        # … and 2 = anteroseptal is to its left.
        assert w._segment_polygons[2].boundingRect().center().x() < cx

    def test_paint_event(self):
        from PySide6.QtGui import QImage

        w = self._make_widget()
        w.update_data({1: -15.0, 17: -10.0})
        w.resize(300, 300)
        image = QImage(300, 300, QImage.Format.Format_ARGB32)
        w.render(image)  # runs the real paint pass
        assert len(w._segment_polygons) == 18


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

    def test_per_view_rows_carry_the_qc_mark(self):
        """The vendor review screen marks every analysed view with its status."""
        table = self._make_table()
        table.set_view_statuses({"A4C": "valid", "A2C": "review", "A3C": "invalid"})
        table.update_values(gls_a4c=-19.0, gls_a2c=-20.0, gls_dao=-14.5, gls_av=-17.8)
        assert table._rows["gls_a4c"][1].text().endswith("●")
        assert table._rows["gls_a2c"][1].text().endswith("⚠")
        assert table._rows["gls_dao"][1].text().endswith("■")
        # The average row is not a view and must stay unmarked.
        assert table._rows["gls_av"][1].text().endswith("%")
        assert table._rows["gls_a2c"][1].toolTip() != ""

    def test_unmeasured_view_keeps_dash_and_no_mark(self):
        table = self._make_table()
        table.set_view_statuses({"A4C": "valid"})
        table.update_values(gls_a4c=-19.0, gls_a2c=None, gls_dao=None)
        assert table._rows["gls_a2c"][1].text() == "--"
        assert table._rows["gls_dao"][1].text() == "--"
        assert table._rows["gls_a4c"][1].text().endswith("●")

    def test_statuses_can_be_cleared(self):
        table = self._make_table()
        table.set_view_statuses({"A4C": "invalid"})
        table.update_values(gls_a4c=-19.0)
        assert table._rows["gls_a4c"][1].text().endswith("■")
        table.set_view_statuses({})
        table.update_values(gls_a4c=-19.0)
        assert table._rows["gls_a4c"][1].text() == "-19.0%"

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

    def test_set_position(self):
        w = self._make_window()
        assert w._position == "A4C"
        w.set_position("A2C")
        assert w._position == "A2C"
        assert w._control._pos_a2c.isChecked()
        # invalid view is ignored
        w.set_position("XX")
        assert w._position == "A2C"

    def test_position_radio_updates_state(self):
        w = self._make_window()
        w._control._pos_a3c.setChecked(True)
        assert w._position == "A3C"

    def test_show_curves_switches_stacked(self):
        w = self._make_window()
        w.show_curves()
        assert w._stacked.currentIndex() == 1
        assert w._control._mode_curves.isChecked()

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
