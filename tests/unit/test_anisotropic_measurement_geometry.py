"""Line and area geometry at anisotropic pixel spacing (#555).

The audit asks for a systematic check of the ruler, angles and area on
anisotropic pixels: a pixel is not necessarily square, so the row spacing
scales the vertical axis and the column spacing the horizontal axis.  These
tests use exact reference shapes so a swapped axis or a ``(row + col) / 2``
average cannot pass.
"""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import pixel_to_mm_length
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2

#: 0.4 mm per row and 0.1 mm per column: the axes differ by a factor of four.
ANISOTROPIC = (0.4, 0.1)


def test_a_horizontal_ruler_uses_the_column_spacing() -> None:
    assert pixel_to_mm_length(100.0, 0.0, ANISOTROPIC) == pytest.approx(10.0)


def test_a_vertical_ruler_uses_the_row_spacing() -> None:
    assert pixel_to_mm_length(100.0, 90.0, ANISOTROPIC) == pytest.approx(40.0)


def test_a_diagonal_ruler_scales_each_axis_before_adding_the_squares() -> None:
    # 100 px along each axis: the line itself is hypot(100, 100) px long.
    expected = math.hypot(100.0 * 0.1, 100.0 * 0.4)
    assert pixel_to_mm_length(math.hypot(100.0, 100.0), 45.0, ANISOTROPIC) == pytest.approx(expected)
    assert expected == pytest.approx(41.23105625617661)


def test_the_same_pixel_length_is_not_one_number_in_two_directions() -> None:
    horizontal = pixel_to_mm_length(100.0, 0.0, ANISOTROPIC)
    vertical = pixel_to_mm_length(100.0, 90.0, ANISOTROPIC)
    assert horizontal != pytest.approx(vertical)
    assert vertical == pytest.approx(4.0 * horizontal)


def test_rectangle_area_scales_rows_and_columns_independently() -> None:
    # 100 px wide * 0.1 mm = 10 mm; 100 px high * 0.4 mm = 40 mm.
    rectangle = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    assert polygon_area_mm2(rectangle, ANISOTROPIC) == pytest.approx(400.0)


def test_planimeter_area_at_anisotropic_spacing_is_not_a_square_pixel_area() -> None:
    contour = Contour(
        phase="ED",
        chamber="AREA",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        measurement_label="Area1",
    )
    assert closed_polygon_area_cm2(contour, ANISOTROPIC) == pytest.approx(4.0)
    # The square-pixel reading is 100 x 100 mm = 100 cm²; averaging the two
    # spacings would give 25 cm² instead of the correct 4 cm².
    assert closed_polygon_area_cm2(contour, (0.25, 0.25)) == pytest.approx(6.25)


def test_area_does_not_depend_on_point_order_translation_or_a_mirror_flip() -> None:
    rectangle = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    transformed = [(-20.0 - x, 30.0 + y) for x, y in reversed(rectangle)]
    assert polygon_area_mm2(transformed, ANISOTROPIC) == pytest.approx(polygon_area_mm2(rectangle, ANISOTROPIC))


def test_uncalibrated_pixel_area_is_not_promoted_by_anisotropic_spacing() -> None:
    contour = Contour(
        phase="ED",
        chamber="AREA",
        points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        measurement_label="Area1",
    )
    assert closed_polygon_area_cm2(contour, (float("nan"), 0.1)) is None
    assert polygon_area_mm2(contour.points, (0.4, 0.1)) == pytest.approx(4.0)
