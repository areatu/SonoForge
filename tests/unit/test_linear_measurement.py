"""Unit tests for linear measurement helpers."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import pixel_to_mm_length


def test_pixel_to_mm_length_uses_axis_spacing() -> None:
    assert pixel_to_mm_length(10.0, 0.0, (0.5, 0.25)) == 2.5
    assert pixel_to_mm_length(10.0, 90.0, (0.5, 0.25)) == 5.0

