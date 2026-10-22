from __future__ import annotations

from echo_personal_tool.presentation.caliper_label_item import (
    compute_caliper_label_layout,
    readable_text_angle,
)


def test_readable_text_angle_normalizes() -> None:
    assert readable_text_angle(0.0) == 0.0
    assert readable_text_angle(45.0) == 45.0
    assert readable_text_angle(135.0) == -45.0
    assert readable_text_angle(180.0) == 0.0
    assert readable_text_angle(270.0) == -90.0
    assert readable_text_angle(350.0) == -10.0


def test_horizontal_line_along_line() -> None:
    layout = compute_caliper_label_layout((0, 0), (100, 0), vertical_labels=frozenset(), label="LVEDD")
    assert layout.angle_deg == 0.0
    assert layout.offset_y < 0


def test_vertical_line_sideways() -> None:
    layout = compute_caliper_label_layout((50, 0), (50, 100), vertical_labels=frozenset(), label="TAPSE")
    assert layout.angle_deg == 0.0
    assert layout.offset_x < 0


def test_vertical_label_forces_sideways() -> None:
    layout = compute_caliper_label_layout((0, 0), (100, 50), vertical_labels=frozenset({"TAPSE"}), label="TAPSE")
    assert layout.angle_deg == 0.0


def test_diagonal_line_along_line() -> None:
    layout = compute_caliper_label_layout((0, 0), (100, 100), vertical_labels=frozenset(), label="Dist1")
    assert layout.angle_deg == 0.0


def test_midpoint_anchor() -> None:
    layout = compute_caliper_label_layout((10, 20), (30, 60), vertical_labels=frozenset(), label="Dist1")
    assert layout.anchor_x == pytest.approx(20.0)
    assert layout.anchor_y == pytest.approx(40.0)


import pytest
