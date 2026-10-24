"""Unit tests for ui/strain_window and ui/strain_curves_view pure functions."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui


# ── strain_window pure functions ───────────────────────────────────


class TestSmoothContour:
    def test_too_few_points(self) -> None:
        from echo_personal_tool.ui.strain_window import _smooth_contour

        pts = np.array([[0, 0], [10, 10]])
        result = _smooth_contour(pts)
        np.testing.assert_array_equal(result, pts)

    def test_single_point(self) -> None:
        from echo_personal_tool.ui.strain_window import _smooth_contour

        pts = np.array([[5, 5]])
        result = _smooth_contour(pts)
        np.testing.assert_array_equal(result, pts)

    def test_normal_case(self) -> None:
        from echo_personal_tool.ui.strain_window import _smooth_contour

        angles = np.linspace(0, 2 * np.pi, 20, endpoint=False)
        pts = np.column_stack([np.cos(angles) * 10, np.sin(angles) * 10])
        result = _smooth_contour(pts, n_output=32)
        assert result.shape == (32, 2)

    def test_custom_output(self) -> None:
        from echo_personal_tool.ui.strain_window import _smooth_contour

        angles = np.linspace(0, 2 * np.pi, 20, endpoint=False)
        pts = np.column_stack([np.cos(angles) * 10, np.sin(angles) * 10])
        result = _smooth_contour(pts, n_output=64)
        assert result.shape == (64, 2)


class TestAhaSegmentNames:
    def test_has_6_segments(self) -> None:
        from echo_personal_tool.ui.strain_window import AHA_SEGMENT_NAMES_RU

        assert len(AHA_SEGMENT_NAMES_RU) == 6

    def test_ids_are_standard_aha_ids(self) -> None:
        from echo_personal_tool.ui.strain_window import AHA_SEGMENT_NAMES_RU

        # A4C names its own wall pair in the standard 18-segment numbering.
        assert set(AHA_SEGMENT_NAMES_RU) == {3, 6, 9, 12, 15, 18}

    def test_keys_are_integers(self) -> None:
        from echo_personal_tool.ui.strain_window import AHA_SEGMENT_NAMES_RU

        for key in AHA_SEGMENT_NAMES_RU:
            assert isinstance(key, int)


# ── strain_window classes ─────────────────────────────────────────


class TestCinePanel:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_window import CinePanel

        panel = CinePanel("Test Panel")
        qtbot.addWidget(panel)
        assert panel._title == "Test Panel"
        assert panel.objectName() == "cinePanel"


class TestBullseyeWidget:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        widget = BullseyeWidget()
        qtbot.addWidget(widget)
        assert widget._segment_strains == {}

    def test_segment_geometry_covers_all_18_segments(self) -> None:
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        # Standard 18-segment AHA model: every id has exactly one position and
        # the apex cap carries no segment (issue #C11).
        assert set(BullseyeWidget.SEGMENT_GEOMETRY) == set(range(1, 19))
        positions = list(BullseyeWidget.SEGMENT_GEOMETRY.values())
        assert len(set(positions)) == len(positions)

    def test_geometry_places_each_segment_on_its_own_ring(self) -> None:
        from echo_personal_tool.ui.strain_window import BullseyeWidget

        geometry = BullseyeWidget.SEGMENT_GEOMETRY
        # Ring 1 = apical (13..18), ring 2 = mid (7..12), ring 3 = basal (1..6)
        for seg, (ring, _angle) in geometry.items():
            if seg <= 6:
                assert ring == 3, f"segment {seg} must be basal"
            elif seg <= 12:
                assert ring == 2, f"segment {seg} must be mid"
            else:
                assert ring == 1, f"segment {seg} must be apical"


class TestSummaryTable:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_window import SummaryTable

        table = SummaryTable()
        qtbot.addWidget(table)
        assert table is not None


class TestControlPanel:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_window import ControlPanel

        panel = ControlPanel()
        qtbot.addWidget(panel)
        assert panel is not None


class TestStrainWindow:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_window import StrainWindow

        window = StrainWindow()
        qtbot.addWidget(window)
        assert window.windowTitle() != ""

    def test_palette_combo_drives_the_bullseye(self, qtbot) -> None:
        """The panel combo and the map must never disagree (plan §6.5)."""
        from echo_personal_tool.ui.strain_window import BullseyeWidget, StrainWindow

        window = StrainWindow()
        qtbot.addWidget(window)
        combo = window._control._cb_palette
        assert combo.count() == len(BullseyeWidget.PALETTES)
        combo.setCurrentIndex(1)
        assert window._panel_bullseye.palette_key == str(combo.itemData(1))

    def test_palette_shortcut_cycles_and_syncs_the_combo(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_window import BullseyeWidget, StrainWindow

        window = StrainWindow()
        qtbot.addWidget(window)
        combo = window._control._cb_palette
        start = window._panel_bullseye.palette_key
        window._cycle_bullseye_palette()
        first = window._panel_bullseye.palette_key
        assert first != start
        assert str(combo.currentData()) == first
        for _ in range(len(BullseyeWidget.PALETTES) - 1):
            window._cycle_bullseye_palette()
        assert window._panel_bullseye.palette_key == start
        assert str(combo.currentData()) == start


# ── strain_curves_view ────────────────────────────────────────────


class TestSegmentCurvePanel:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_curves_view import SegmentCurvePanel

        panel = SegmentCurvePanel("Test View")
        qtbot.addWidget(panel)
        assert panel._title == "Test View"


class TestStrainCurvesView:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

        view = StrainCurvesView()
        qtbot.addWidget(view)
        assert view is not None


class TestSegmentConstants:
    def test_segment_colors(self) -> None:
        from echo_personal_tool.ui.strain_curves_view import SEGMENT_COLORS

        assert len(SEGMENT_COLORS) == 18
        for key, val in SEGMENT_COLORS.items():
            assert isinstance(key, int)
            assert len(val) == 3

    def test_segment_names_ru(self) -> None:
        from echo_personal_tool.ui.strain_curves_view import SEGMENT_NAMES_RU

        assert len(SEGMENT_NAMES_RU) == 6

    def test_view_segments(self) -> None:
        from echo_personal_tool.ui.strain_curves_view import VIEW_SEGMENTS

        assert "A4C" in VIEW_SEGMENTS
        assert "A2C" in VIEW_SEGMENTS
        assert len(VIEW_SEGMENTS["A4C"]) == 6


class TestPhaseMarkers:
    """Task 3: systole / diastole markers on the frame timeline.

    The phase-evaluation mechanism is not designed yet, so the panel only owns
    the strip above the scrubber and the API a future detector will call. What
    the tests pin down is that the strip is a placeholder (it must not claim a
    phase the study does not have) and that a supplied frame lands above the
    frame the scrubber would show.
    """

    def test_the_strip_is_a_placeholder_without_a_detector(self, qtbot) -> None:
        from echo_personal_tool.ui.cine_panel import CinePanel

        panel = CinePanel("A4C")
        qtbot.addWidget(panel)
        panel.set_frames(np.random.rand(20, 40, 60).astype("float32"))
        bar = panel._phase_bar
        assert bar._placeholder, "no detector ran: the markers must stay muted placeholders"
        assert bar._total == 20

    def test_a_supplied_frame_moves_the_marker(self, qtbot) -> None:
        from echo_personal_tool.ui.cine_panel import CinePanel

        panel = CinePanel("A4C")
        qtbot.addWidget(panel)
        panel.resize(400, 300)
        panel.set_frames(np.random.rand(21, 40, 60).astype("float32"))
        # Frame 0 sits at the left end of the timeline, frame 20 at the right.
        panel.set_phase_markers(systole_frame=0, diastole_frame=20)
        bar = panel._phase_bar
        assert not bar._placeholder
        left = bar._x_for_frame(0, 0.33)
        middle = bar._x_for_frame(10, 0.5)
        right = bar._x_for_frame(20, 0.66)
        assert left < middle < right
        assert left <= bar._SLIDER_INSET + 0.5
        assert right >= bar.width() - bar._SLIDER_INSET - 0.5

    def test_clearing_restores_the_placeholders(self, qtbot) -> None:
        from echo_personal_tool.ui.cine_panel import CinePanel

        panel = CinePanel("A4C")
        qtbot.addWidget(panel)
        panel.set_frames(np.random.rand(10, 40, 60).astype("float32"))
        panel.set_phase_markers(systole_frame=2, diastole_frame=7)
        assert not panel._phase_bar._placeholder
        panel.set_phase_markers(None, None)
        assert panel._phase_bar._placeholder

    def test_the_strip_sits_above_the_scrubber(self, qtbot) -> None:
        """Placement is the point of task 3: above the scroll bar, not below."""
        from echo_personal_tool.ui.cine_panel import CinePanel

        panel = CinePanel("A4C")
        qtbot.addWidget(panel)
        panel.resize(500, 420)
        panel.show()
        qtbot.wait(10)
        bar_y = panel._phase_bar.mapTo(panel, panel._phase_bar.rect().topLeft()).y()
        slider_y = panel._frame_slider.mapTo(panel, panel._frame_slider.rect().topLeft()).y()
        assert bar_y < slider_y, "the markers belong above the frame scrubber"
        assert panel._phase_bar.width() == panel._frame_slider.width()
