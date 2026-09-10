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
