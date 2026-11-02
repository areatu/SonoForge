"""Tests for %D and %S calculation logic."""

from echo_personal_tool.presentation.viewer_widget import _ComparisonState


def test_percent_d_smaller_second():
    s = _ComparisonState(kind="diameter", segment1_mm=10.0, segment2_mm=5.0)
    bigger = max(s.segment1_mm, s.segment2_mm)
    smaller = min(s.segment1_mm, s.segment2_mm)
    assert smaller / bigger * 100.0 == 50.0


def test_percent_d_equal():
    s = _ComparisonState(kind="diameter", segment1_mm=8.0, segment2_mm=8.0)
    bigger = max(s.segment1_mm, s.segment2_mm)
    smaller = min(s.segment1_mm, s.segment2_mm)
    assert smaller / bigger * 100.0 == 100.0


def test_percent_d_larger_second():
    s = _ComparisonState(kind="diameter", segment1_mm=6.0, segment2_mm=15.0)
    bigger = max(s.segment1_mm, s.segment2_mm)
    smaller = min(s.segment1_mm, s.segment2_mm)
    assert abs(smaller / bigger * 100.0 - 40.0) < 0.01


def test_overlay_not_shown_without_second_segment():
    s = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0), segment1_mm=10.0)
    assert s.first_segment_done
    assert s.segment2_mm is None


def test_percent_s_smaller_second():
    s = _ComparisonState(kind="area", contour1_area_cm2=10.0, contour2_area_cm2=5.0)
    bigger = max(s.contour1_area_cm2, s.contour2_area_cm2)
    smaller = min(s.contour1_area_cm2, s.contour2_area_cm2)
    assert smaller / bigger * 100.0 == 50.0


def test_percent_s_equal():
    s = _ComparisonState(kind="area", contour1_area_cm2=8.0, contour2_area_cm2=8.0)
    bigger = max(s.contour1_area_cm2, s.contour2_area_cm2)
    smaller = min(s.contour1_area_cm2, s.contour2_area_cm2)
    assert smaller / bigger * 100.0 == 100.0


def test_percent_s_larger_second():
    s = _ComparisonState(kind="area", contour1_area_cm2=3.0, contour2_area_cm2=15.0)
    bigger = max(s.contour1_area_cm2, s.contour2_area_cm2)
    smaller = min(s.contour1_area_cm2, s.contour2_area_cm2)
    assert abs(smaller / bigger * 100.0 - 20.0) < 0.01


def test_overlay_not_shown_without_second_contour():
    s = _ComparisonState(kind="area", contour1_points=[(0, 0), (10, 0), (10, 10)], contour1_area_cm2=5.0)
    assert s.first_contour_done
    assert s.contour2_area_cm2 is None
