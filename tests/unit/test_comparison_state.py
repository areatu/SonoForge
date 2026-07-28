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
