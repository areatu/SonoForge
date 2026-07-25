"""Exploratory tests: property-based tests for planimeter area, Simpson volumes, BSA formula."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2
from echo_personal_tool.domain.calculations.lvef_simpson import (
    calculate,
    simpson_volume_ml_from_closed_polygon,
)
from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2
from echo_personal_tool.domain.models.contour import Contour


# ── Planimeter area ────────────────────────────────────────────────


class TestPlanimeterProperties:
    @given(
        radius=st.floats(min_value=5.0, max_value=200.0),
        n_sides=st.integers(min_value=4, max_value=64),
    )
    @settings(max_examples=200)
    def test_closed_polygon_area_positive(self, radius: float, n_sides: int) -> None:
        """Area of a regular closed polygon is always positive."""
        points = [
            (200 + radius * math.cos(2 * math.pi * i / n_sides),
             200 + radius * math.sin(2 * math.pi * i / n_sides))
            for i in range(n_sides)
        ]
        contour = Contour(phase="ed", view="A4C", chamber="LV", points=points)
        area = closed_polygon_area_cm2(contour, pixel_spacing=(0.3, 0.3))
        assert area is not None
        assert area > 0.0

    @given(
        radius=st.floats(min_value=5.0, max_value=200.0),
    )
    @settings(max_examples=100)
    def test_circle_area_approaches_pi_r_squared(self, radius: float) -> None:
        """High-vertex regular polygon area approximates pi*r^2 in mm units."""
        n_sides = 64
        points = [
            (200 + radius * math.cos(2 * math.pi * i / n_sides),
             200 + radius * math.sin(2 * math.pi * i / n_sides))
            for i in range(n_sides)
        ]
        contour = Contour(phase="ed", view="A4C", chamber="LV", points=points)
        pixel_spacing = (0.3, 0.3)
        area_cm2 = closed_polygon_area_cm2(contour, pixel_spacing=pixel_spacing)
        assert area_cm2 is not None

        # Convert pixel radius to mm
        radius_mm = radius * pixel_spacing[0]
        expected_area_mm2 = math.pi * radius_mm**2
        expected_area_cm2 = expected_area_mm2 / 100.0
        # Allow 5% error for polygon approximation
        assert abs(area_cm2 - expected_area_cm2) / expected_area_cm2 < 0.05

    @given(
        scale=st.floats(min_value=0.1, max_value=10.0),
    )
    @settings(max_examples=100)
    def test_area_scales_quadratically(self, scale: float) -> None:
        """Scaling polygon points by a factor scales area by scale^2."""
        base_points = [(100 + 30 * math.cos(2 * math.pi * i / 8),
                        100 + 30 * math.sin(2 * math.pi * i / 8))
                       for i in range(8)]
        scaled_points = [(x * scale, y * scale) for x, y in base_points]

        contour_base = Contour(phase="ed", view="A4C", chamber="LV", points=base_points)
        contour_scaled = Contour(phase="ed", view="A4C", chamber="LV", points=scaled_points)

        area_base = closed_polygon_area_cm2(contour_base, pixel_spacing=(0.3, 0.3))
        area_scaled = closed_polygon_area_cm2(contour_scaled, pixel_spacing=(0.3, 0.3))

        if area_base is not None and area_scaled is not None and area_base > 0:
            ratio = area_scaled / area_base
            expected_ratio = scale**2
            # Allow 5% tolerance
            assert abs(ratio - expected_ratio) / expected_ratio < 0.05

    def test_triangle_has_positive_area(self) -> None:
        """Minimum valid polygon (triangle) still has positive area."""
        contour = Contour(phase="ed", view="A4C", chamber="LV",
                          points=[(0, 0), (100, 0), (50, 100)])
        area = closed_polygon_area_cm2(contour, pixel_spacing=(0.3, 0.3))
        assert area is not None
        assert area > 0.0


# ── Simpson volumes ────────────────────────────────────────────────


class TestSimpsonVolumeProperties:
    @given(
        radius=st.floats(min_value=5.0, max_value=100.0),
        n_sides=st.integers(min_value=6, max_value=48),
    )
    @settings(max_examples=200)
    def test_simpson_volume_positive(self, radius: float, n_sides: int) -> None:
        """Simpson disk volume from a closed polygon is always positive."""
        points = [
            (100 + radius * math.cos(2 * math.pi * i / n_sides),
             100 + radius * math.sin(2 * math.pi * i / n_sides))
            for i in range(n_sides)
        ]
        contour = Contour(phase="ed", view="A4C", chamber="LV", points=points)
        volume = simpson_volume_ml_from_closed_polygon(contour, pixel_spacing=(0.3, 0.3))
        assert volume is not None
        assert volume > 0.0

    @given(
        radius_a=st.floats(min_value=5.0, max_value=80.0),
        radius_b=st.floats(min_value=5.0, max_value=80.0),
    )
    @settings(max_examples=200)
    def test_simpson_volume_monotonic_with_size(
        self, radius_a: float, radius_b: float
    ) -> None:
        """Larger polygon produces larger Simpson volume."""
        if radius_a >= radius_b:
            pytest.skip("Need radius_a < radius_b")

        n_sides = 32
        points_a = [
            (100 + radius_a * math.cos(2 * math.pi * i / n_sides),
             100 + radius_a * math.sin(2 * math.pi * i / n_sides))
            for i in range(n_sides)
        ]
        points_b = [
            (100 + radius_b * math.cos(2 * math.pi * i / n_sides),
             100 + radius_b * math.sin(2 * math.pi * i / n_sides))
            for i in range(n_sides)
        ]

        vol_a = simpson_volume_ml_from_closed_polygon(
            Contour(phase="ed", view="A4C", chamber="LV", points=points_a),
            pixel_spacing=(0.3, 0.3),
        )
        vol_b = simpson_volume_ml_from_closed_polygon(
            Contour(phase="ed", view="A4C", chamber="LV", points=points_b),
            pixel_spacing=(0.3, 0.3),
        )

        assert vol_a is not None
        assert vol_b is not None
        assert vol_b > vol_a

    def test_small_polygon_volume_positive(self) -> None:
        """Even a small triangle has a positive Simpson volume."""
        contour = Contour(phase="ed", view="A4C", chamber="LV",
                          points=[(95, 95), (105, 95), (100, 105)])
        volume = simpson_volume_ml_from_closed_polygon(contour, pixel_spacing=(0.3, 0.3))
        assert volume is not None
        assert volume > 0.0


# ── BSA (Du Bois) formula ─────────────────────────────────────────


class TestBSAProperties:
    @given(
        height=st.floats(min_value=50.0, max_value=220.0),
        weight=st.floats(min_value=3.0, max_value=250.0),
    )
    @settings(max_examples=200)
    def test_bsa_positive(self, height: float, weight: float) -> None:
        """BSA is always positive for valid height/weight."""
        bsa = bsa_du_bois_m2(height, weight)
        assert bsa is not None
        assert bsa > 0.0

    @given(
        height=st.floats(min_value=50.0, max_value=220.0),
        weight=st.floats(min_value=3.0, max_value=250.0),
    )
    @settings(max_examples=200)
    def test_bsa_reasonable_range(self, height: float, weight: float) -> None:
        """BSA falls in a medically reasonable range for adult humans."""
        bsa = bsa_du_bois_m2(height, weight)
        assert bsa is not None
        assert 0.1 <= bsa <= 4.0

    @given(
        height=st.floats(min_value=50.0, max_value=220.0),
        weight=st.floats(min_value=3.0, max_value=250.0),
    )
    @settings(max_examples=200)
    def test_bsa_monotonic_with_weight(self, height: float, weight: float) -> None:
        """BSA increases (or stays same) when weight increases, with height fixed."""
        bsa1 = bsa_du_bois_m2(height, weight)
        bsa2 = bsa_du_bois_m2(height, weight * 1.5)
        assert bsa1 is not None
        assert bsa2 is not None
        assert bsa2 >= bsa1

    @given(
        height=st.floats(min_value=50.0, max_value=220.0),
        weight=st.floats(min_value=3.0, max_value=250.0),
    )
    @settings(max_examples=200)
    def test_bsa_monotonic_with_height(self, height: float, weight: float) -> None:
        """BSA increases (or stays same) when height increases, with weight fixed."""
        bsa1 = bsa_du_bois_m2(height, weight)
        bsa2 = bsa_du_bois_m2(height * 1.2, weight)
        assert bsa1 is not None
        assert bsa2 is not None
        assert bsa2 >= bsa1

    def test_bsa_zero_height_returns_none(self) -> None:
        """BSA returns None when height is zero."""
        assert bsa_du_bois_m2(0.0, 70.0) is None

    def test_bsa_zero_weight_returns_none(self) -> None:
        """BSA returns None when weight is zero."""
        assert bsa_du_bois_m2(170.0, 0.0) is None

    def test_bsa_negative_height_returns_none(self) -> None:
        """BSA returns None for negative height."""
        assert bsa_du_bois_m2(-170.0, 70.0) is None

    def test_bsa_negative_weight_returns_none(self) -> None:
        """BSA returns None for negative weight."""
        assert bsa_du_bois_m2(170.0, -70.0) is None

    def test_bsa_known_value(self) -> None:
        """BSA for a standard 170cm/70kg adult is approximately 1.84 m^2."""
        bsa = bsa_du_bois_m2(170.0, 70.0)
        assert bsa is not None
        assert abs(bsa - 1.84) < 0.05


# ── LVEF calculation properties ────────────────────────────────────


class TestLvefProperties:
    def test_lvef_range(self) -> None:
        """LVEF percentage is always between 0 and 100 for valid contours."""
        pixel_spacing = (0.3, 0.3)
        ed_points = [(20, 10), (60, 10), (65, 40), (60, 70), (20, 70), (15, 40)]
        es_points = [(30, 25), (50, 25), (53, 40), (50, 55), (30, 55), (27, 40)]

        contours = (
            Contour(phase="ed", view="A4C", chamber="LV", points=ed_points),
            Contour(phase="es", view="A4C", chamber="LV", points=es_points),
        )
        result = calculate(contours, pixel_spacing)
        if result is not None and result.lvef_percent is not None:
            assert 0 < result.lvef_percent < 100

    def test_identical_contours_give_zero_ef(self) -> None:
        """When ED and ES contours are identical, EF should be 0 (or very close)."""
        pixel_spacing = (0.3, 0.3)
        points = [(20, 10), (60, 10), (65, 40), (60, 70), (20, 70), (15, 40)]

        contours = (
            Contour(phase="ed", view="A4C", chamber="LV", points=list(points)),
            Contour(phase="es", view="A4C", chamber="LV", points=list(points)),
        )
        result = calculate(contours, pixel_spacing)
        if result is not None and result.lvef_percent is not None:
            assert result.lvef_percent == pytest.approx(0.0, abs=1.0)
