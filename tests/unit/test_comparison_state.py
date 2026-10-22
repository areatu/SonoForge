"""Tests for _ComparisonState lifecycle."""

from echo_personal_tool.presentation.viewer_widget import _ComparisonState


def test_empty_state_is_not_active():
    state = _ComparisonState()
    assert not state.is_active
    assert not state.first_segment_done


def test_diameter_state_is_active():
    state = _ComparisonState(kind="diameter")
    assert state.is_active


def test_first_segment_done_after_both_endpoints():
    state = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0), segment1_mm=5.0)
    assert state.first_segment_done


def test_first_segment_not_done_without_mm():
    state = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0))
    assert not state.first_segment_done


def test_reset_clears_all():
    state = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0), segment1_mm=5.0)
    state.reset()
    assert not state.is_active
    assert state.segment1_start is None
    assert state.segment1_mm is None


def test_area_state_is_active():
    state = _ComparisonState(kind="area")
    assert state.is_active


def test_area_first_contour_done():
    state = _ComparisonState(kind="area", contour1_points=[(0, 0), (10, 0), (10, 10)], contour1_area_cm2=5.0)
    assert state.first_contour_done
    assert not state.contour2_points


def test_area_first_contour_not_done_without_area():
    state = _ComparisonState(kind="area", contour1_points=[(0, 0), (10, 0), (10, 10)])
    assert not state.first_contour_done


def test_area_reset_clears_contours():
    state = _ComparisonState(
        kind="area",
        contour1_points=[(0, 0), (10, 0), (10, 10)],
        contour1_area_cm2=5.0,
        contour2_points=[(0, 0), (5, 0), (5, 5)],
        contour2_area_cm2=2.5,
    )
    state.reset()
    assert not state.is_active
    assert state.contour1_points is None
    assert state.contour1_area_cm2 is None
    assert state.contour2_points is None
    assert state.contour2_area_cm2 is None
