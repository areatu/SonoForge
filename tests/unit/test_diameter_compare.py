"""Tests for %D calculation logic."""

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
