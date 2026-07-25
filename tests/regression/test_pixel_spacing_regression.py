"""Regression tests for pixel spacing resolution."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    PixelSpacingResolution,
    effective_pixel_spacing,
    pixel_length_along_angle,
    resolve_pixel_spacing,
    spacing_from_known_distance,
)


class TestSpacingFromKnownDistanceRegression:
    """spacing_from_known_distance produces exact expected outputs."""

    def test_known_distance_normal(self) -> None:
        row, col = spacing_from_known_distance(100.0, 15.0)
        assert row == pytest.approx(0.15)
        assert col == pytest.approx(0.15)

    def test_known_distance_1_to_1(self) -> None:
        row, col = spacing_from_known_distance(1.0, 1.0)
        assert row == pytest.approx(1.0)
        assert col == pytest.approx(1.0)

    def test_known_distance_large_pixels(self) -> None:
        row, col = spacing_from_known_distance(1000.0, 100.0)
        assert row == pytest.approx(0.1)
        assert col == pytest.approx(0.1)

    def test_known_distance_small_calibration(self) -> None:
        row, col = spacing_from_known_distance(50.0, 5.0)
        assert row == pytest.approx(0.1)
        assert col == pytest.approx(0.1)

    def test_known_distance_zero_pixel_raises(self) -> None:
        with pytest.raises(ValueError, match="pixel_length must be positive"):
            spacing_from_known_distance(0.0, 15.0)

    def test_known_distance_zero_mm_raises(self) -> None:
        with pytest.raises(ValueError, match="known_mm must be positive"):
            spacing_from_known_distance(100.0, 0.0)

    def test_known_distance_negative_pixel_raises(self) -> None:
        with pytest.raises(ValueError, match="pixel_length must be positive"):
            spacing_from_known_distance(-100.0, 15.0)

    def test_known_distance_negative_mm_raises(self) -> None:
        with pytest.raises(ValueError, match="known_mm must be positive"):
            spacing_from_known_distance(100.0, -15.0)

    def test_isotropic_output(self) -> None:
        row, col = spacing_from_known_distance(200.0, 30.0)
        assert row == col


class TestEffectivePixelSpacingRegression:
    """effective_pixel_spacing priority rules produce exact results."""

    def test_manual_overrides_dicom(self) -> None:
        result = effective_pixel_spacing((0.2, 0.2), (0.1, 0.1))
        assert result == (0.1, 0.1)

    def test_manual_only(self) -> None:
        result = effective_pixel_spacing(None, (0.15, 0.15))
        assert result == (0.15, 0.15)

    def test_dicom_only(self) -> None:
        result = effective_pixel_spacing((0.2, 0.2), None)
        assert result == (0.2, 0.2)

    def test_both_none(self) -> None:
        result = effective_pixel_spacing(None, None)
        assert result is None


class TestPixelLengthAlongAngleRegression:
    """pixel_length_along_angle produces exact expected results."""

    def test_zero_degrees(self) -> None:
        assert pixel_length_along_angle(100.0, 0.0) == pytest.approx(100.0)

    def test_90_degrees(self) -> None:
        assert pixel_length_along_angle(100.0, 90.0) == pytest.approx(100.0)

    def test_45_degrees(self) -> None:
        expected = (100.0**2 * 0.5 + 100.0**2 * 0.5) ** 0.5
        assert pixel_length_along_angle(100.0, 45.0) == pytest.approx(expected)

    def test_negative_angle(self) -> None:
        assert pixel_length_along_angle(100.0, -90.0) == pytest.approx(100.0)

    def test_zero_length(self) -> None:
        assert pixel_length_along_angle(0.0, 45.0) == pytest.approx(0.0)

    def test_180_degrees(self) -> None:
        assert pixel_length_along_angle(100.0, 180.0) == pytest.approx(100.0)


class TestResolvePixelSpacingRegression:
    """resolve_pixel_spacing with mock DICOM datasets."""

    def _make_dataset(self, **attrs) -> dict:
        """Create a dict-like object that mimics pydicom Dataset for testing."""
        class MockDataset(dict):
            def get(self, key, default=None):
                return super().get(key, default)
        return MockDataset(attrs)

    def test_pixel_spacing_tag(self) -> None:
        from unittest.mock import MagicMock
        ds = MagicMock()
        ds.get.return_value = [0.15, 0.15]
        result = resolve_pixel_spacing(ds)
        assert result is not None
        assert result.spacing == (0.15, 0.15)
        assert result.source == "PixelSpacing"

    def test_imager_pixel_spacing(self) -> None:
        from unittest.mock import MagicMock
        ds = MagicMock()
        ds.get.side_effect = lambda key, *a: [0.2, 0.2] if key == "ImagerPixelSpacing" else None
        result = resolve_pixel_spacing(ds)
        assert result is not None
        assert result.spacing == (0.2, 0.2)
        assert result.source == "ImagerPixelSpacing"

    def test_no_spacing_returns_none(self) -> None:
        from unittest.mock import MagicMock
        ds = MagicMock()
        ds.get.return_value = None
        result = resolve_pixel_spacing(ds)
        assert result is None

    def test_invalid_spacing_values(self) -> None:
        from unittest.mock import MagicMock
        ds = MagicMock()
        ds.get.side_effect = lambda key, *a: [-1.0, 0.1] if key == "PixelSpacing" else None
        result = resolve_pixel_spacing(ds)
        assert result is None


class TestPixelSpacingResolutionRegression:
    """PixelSpacingResolution dataclass properties."""

    def test_creation(self) -> None:
        res = PixelSpacingResolution(spacing=(0.15, 0.15), source="PixelSpacing")
        assert res.spacing == (0.15, 0.15)
        assert res.source == "PixelSpacing"

    def test_frozen(self) -> None:
        res = PixelSpacingResolution(spacing=(0.15, 0.15), source="test")
        with pytest.raises(AttributeError):
            res.spacing = (0.1, 0.1)  # type: ignore[misc]
