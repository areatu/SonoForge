"""Unit tests for shared Simpson contour grouping and mm conversion (issue 483)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.simpson_contours import (
    GroupedSimpsonContours,
    contour_to_mm,
    group_simpson_contours,
)
from echo_personal_tool.domain.models import Contour


class TestSimpsonContours:
    def test_contour_to_mm_scales_col_and_row_anisotropically_with_annulus(self) -> None:
        contour = Contour(
            phase="ed",
            view="A4C",
            chamber="LV",
            points=[(10.0, 20.0), (30.0, 20.0), (20.0, 50.0)],
            mitral_annulus=((10.0, 20.0), (30.0, 20.0)),
        )
        # row_spacing=0.5 mm/px, col_spacing=0.25 mm/px -> (col * 0.25, row * 0.5)
        points_mm, annulus_mm = contour_to_mm(contour, pixel_spacing=(0.5, 0.25))

        assert points_mm[0] == pytest.approx((2.5, 10.0))
        assert points_mm[1] == pytest.approx((7.5, 10.0))
        assert points_mm[2] == pytest.approx((5.0, 25.0))
        assert annulus_mm is not None
        assert annulus_mm[0] == pytest.approx((2.5, 10.0))
        assert annulus_mm[1] == pytest.approx((7.5, 10.0))

    def test_contour_to_mm_preserves_none_annulus(self) -> None:
        contour = Contour(
            phase="es",
            view="A2C",
            chamber="LV",
            points=[(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)],
            mitral_annulus=None,
        )
        points_mm, annulus_mm = contour_to_mm(contour, pixel_spacing=(0.4, 0.4))

        assert len(points_mm) >= 3
        assert annulus_mm is None

    def test_group_simpson_contours_filters_chamber_pending_invalid_and_keeps_latest(self) -> None:
        first_ed = Contour(phase="ED", view="a4c", chamber="lv", points=[(0, 0), (10, 0), (5, 10)])
        latest_ed = Contour(phase="ed", view="A4C", chamber="LV", points=[(0, 0), (20, 0), (10, 20)])
        pending_es = Contour(
            phase="es",
            view="A4C",
            chamber="LV",
            points=[(0, 0), (8, 0), (4, 8)],
            review_pending=True,
        )
        wrong_chamber = Contour(phase="es", view="A4C", chamber="LA", points=[(0, 0), (8, 0), (4, 8)])
        wrong_view = Contour(phase="es", view="PLAX", chamber="LV", points=[(0, 0), (8, 0), (4, 8)])
        wrong_phase = Contour(phase="mid", view="A2C", chamber="LV", points=[(0, 0), (8, 0), (4, 8)])
        valid_a2c_es = Contour(phase="ES", view="A2C", chamber="LV", points=[(0, 0), (12, 0), (6, 12)])

        grouped = group_simpson_contours(
            [first_ed, latest_ed, pending_es, wrong_chamber, wrong_view, wrong_phase, valid_a2c_es],
            chamber="LV",
            pixel_spacing=(0.5, 0.5),
        )

        assert isinstance(grouped, GroupedSimpsonContours)
        assert grouped.contours_by_view["A4C"] == {"ed": latest_ed}
        assert grouped.contours_by_view["A2C"] == {"es": valid_a2c_es}
        assert "ed" in grouped.geometry_mm_by_view["A4C"]
        assert "es" not in grouped.geometry_mm_by_view["A4C"]
        assert "es" in grouped.geometry_mm_by_view["A2C"]
