"""Tests for GE vendor profile calibration.

Validates the GE vendor profile against real GE Vivid E95 data
from the analysis performed on 2026-08-11.
"""

from __future__ import annotations

from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.vendor_calibration_bridge import try_parse_with_vendor_profile
from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor
from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor
from echo_personal_tool.infrastructure.vendor_profiles.ge import GEProfile
from echo_personal_tool.infrastructure.vendor_profiles.registry import get_profile


class TestGEProfile:
    """Test GE vendor profile against known Vivid E95 data."""

    def setup_method(self):
        self.profile = GEProfile()

    def test_vendor_property(self):
        assert self.profile.vendor == Vendor.GE

    def test_vendor_bridge_returns_profile_calibration(self):
        ds = Dataset()
        ds.Manufacturer = "GE Vingmed Ultrasound"
        ds.Rows = 708
        region = Dataset()
        region.RegionSpatialFormat = 3
        region.RegionDataType = 3
        region.RegionLocationMinX0 = 20
        region.RegionLocationMinY0 = 212
        region.RegionLocationMaxX1 = 680
        region.RegionLocationMaxY1 = 671
        region.ReferencePixelY0 = 90
        region.PhysicalDeltaX = 0.005
        region.PhysicalUnitsXDirection = 4
        region.PhysicalDeltaY = 0.376316
        region.PhysicalUnitsYDirection = 7
        ds.SequenceOfUltrasoundRegions = [region]

        result = try_parse_with_vendor_profile(ds)

        assert result is not None
        assert result.baseline_y_px == 302.0
        assert result.velocity_sign == -1

    def test_vendor_bridge_sets_standard_sign_for_philips(self):
        ds = Dataset()
        ds.Manufacturer = "Philips Healthcare"
        ds.Rows = 600
        region = Dataset()
        region.RegionSpatialFormat = 3
        region.RegionDataType = 3
        region.RegionLocationMinX0 = 20
        region.RegionLocationMinY0 = 100
        region.RegionLocationMaxX1 = 580
        region.RegionLocationMaxY1 = 500
        region.ReferencePixelY0 = 200
        region.PhysicalDeltaX = 0.005
        region.PhysicalUnitsXDirection = 4
        region.PhysicalDeltaY = -0.25
        region.PhysicalUnitsYDirection = 7
        ds.SequenceOfUltrasoundRegions = [region]

        result = try_parse_with_vendor_profile(ds)

        assert result is not None
        assert result.velocity_sign == 1

    def test_vendor_keywords(self):
        assert "ge" in self.profile.vendor_keywords
        assert "vingmed" in self.profile.vendor_keywords
        assert "vivid" in self.profile.vendor_keywords

    def test_matches_dataset_manufacturer(self):
        ds = Dataset()
        ds.Manufacturer = "GE Vingmed Ultrasound"
        ds.ManufacturerModelName = "Vivid E95"
        assert self.profile.matches_dataset(ds) is True

    def test_matches_dataset_model(self):
        ds = Dataset()
        ds.Manufacturer = "Unknown"
        ds.ManufacturerModelName = "Vivid E95"
        assert self.profile.matches_dataset(ds) is True

    def test_matches_dataset_private_creator(self):
        ds = Dataset()
        ds.Manufacturer = "Unknown"
        # Add private creator tag
        ds.add_new(0x60030010, "LO", "GEMS_Ultrasound_ImageGroup_001")
        assert self.profile.matches_dataset(ds) is True

    def test_baseline_inside_region(self):
        """Q8BA5Q8Q: refy=228, region y0=212..671, physValY=0.0 → abs=440."""
        region = Dataset()
        region.ReferencePixelY0 = 228
        region.ReferencePixelPhysicalValueY = 0.0
        region.RegionLocationMinY0 = 212
        region.RegionLocationMaxY1 = 671

        result = self.profile.compute_baseline(region, frame_height=708)

        assert result.baseline_y == 212.0 + 228.0
        assert result.confidence >= 0.9
        assert result.velocity_sign == -1  # GE inverted convention
        assert "PhysicalValueY=0" in result.source

    def test_baseline_above_region(self):
        """Q8BA8BPK: refy=90, region y0=212..671 → abs=302 (visual line ~301.5)."""
        region = Dataset()
        region.ReferencePixelY0 = 90
        region.RegionLocationMinY0 = 212
        region.RegionLocationMaxY1 = 671

        result = self.profile.compute_baseline(region, frame_height=708)

        assert result.baseline_y == 302.0
        assert result.confidence == 0.8  # inside region (212..671)
        assert result.velocity_sign == -1

    def test_baseline_above_region_2(self):
        """Q8BATAG2: refy=187, region y0=353..668 → abs=540 (visual line ~541)."""
        region = Dataset()
        region.ReferencePixelY0 = 187
        region.RegionLocationMinY0 = 353
        region.RegionLocationMaxY1 = 668

        result = self.profile.compute_baseline(region, frame_height=708)

        assert result.baseline_y == 540.0
        assert result.confidence == 0.8  # inside region (353..668)
        assert result.velocity_sign == -1

    def test_baseline_above_region_3(self):
        """Q8BA7UHE: refy=178, region y0=213..668 → abs=391 (visual line ~391)."""
        region = Dataset()
        region.ReferencePixelY0 = 178
        region.RegionLocationMinY0 = 213
        region.RegionLocationMaxY1 = 668

        result = self.profile.compute_baseline(region, frame_height=708)

        assert result.baseline_y == 391.0
        assert result.confidence == 0.8  # inside region (213..668)
        assert result.velocity_sign == -1

    def test_baseline_negative(self):
        """Q8BA9K22: refy=-2, region y0=213..668 → abs=211 (inside frame, above region)."""
        region = Dataset()
        region.ReferencePixelY0 = -2
        region.RegionLocationMinY0 = 213
        region.RegionLocationMaxY1 = 668

        result = self.profile.compute_baseline(region, frame_height=708)

        assert result.baseline_y == 211.0
        assert result.confidence == 0.6  # above region but inside frame
        assert result.velocity_sign == -1

    def test_velocity_span_standard(self):
        """Q8BA5Q8Q: deltaY=0.3763, height=459 → span=172.7 cm/s."""
        region = Dataset()
        region.PhysicalDeltaY = 0.376316
        region.PhysicalUnitsYDirection = 7  # cm/sec

        result = self.profile.compute_velocity_span(region, region_height_px=459.0)

        assert result is not None
        assert abs(result.span_cm_s - 172.7) < 1.0
        assert abs(result.per_pixel_cm_s - 0.3763) < 0.001
        assert result.confidence >= 0.8

    def test_velocity_span_high_scale(self):
        """Q8BA9K22: deltaY=0.7673, height=455 → span=349.1 cm/s."""
        region = Dataset()
        region.PhysicalDeltaY = 0.767334
        region.PhysicalUnitsYDirection = 7

        result = self.profile.compute_velocity_span(region, region_height_px=455.0)

        assert result is not None
        assert abs(result.span_cm_s - 349.1) < 1.0

    def test_velocity_span_low_scale(self):
        """Q8BA7UHE: deltaY=0.0651, height=455 → span=29.6 cm/s."""
        region = Dataset()
        region.PhysicalDeltaY = 0.065069
        region.PhysicalUnitsYDirection = 7

        result = self.profile.compute_velocity_span(region, region_height_px=455.0)

        assert result is not None
        assert abs(result.span_cm_s - 29.6) < 1.0

    def test_velocity_span_wrong_units(self):
        """Reject regions with non-cm/sec units."""
        region = Dataset()
        region.PhysicalDeltaY = 0.376
        region.PhysicalUnitsYDirection = 3  # cm (not cm/sec)

        result = self.profile.compute_velocity_span(region, region_height_px=459.0)
        assert result is None

    def test_time_span_standard(self):
        """Q8BA5Q8Q: deltaX=0.00463, width=863 → span=3995.7 ms."""
        region = Dataset()
        region.PhysicalDeltaX = 0.004630
        region.PhysicalUnitsXDirection = 4  # seconds

        result = self.profile.compute_time_span(region, region_width_px=863.0)

        assert result is not None
        assert abs(result.span_ms - 3995.7) < 10.0
        assert abs(result.per_pixel_ms - 4.63) < 0.01

    def test_time_span_short_sweep(self):
        """Q8BA5E0K: deltaX=0.00694, width=792 → span=5496.6 ms."""
        region = Dataset()
        region.PhysicalDeltaX = 0.006944
        region.PhysicalUnitsXDirection = 4

        result = self.profile.compute_time_span(region, region_width_px=792.0)

        assert result is not None
        assert abs(result.span_ms - 5496.6) < 10.0

    def test_time_span_wrong_units(self):
        """Reject regions with non-seconds units."""
        region = Dataset()
        region.PhysicalDeltaX = 0.00463
        region.PhysicalUnitsXDirection = 3  # cm (not seconds)

        result = self.profile.compute_time_span(region, region_width_px=863.0)
        assert result is None


class TestVendorDetector:
    """Test vendor detection from DICOM datasets."""

    def test_detect_ge_manufacturer(self):
        ds = Dataset()
        ds.Manufacturer = "GE Vingmed Ultrasound"
        assert detect_vendor(ds) == Vendor.GE

    def test_detect_ge_model(self):
        ds = Dataset()
        ds.ManufacturerModelName = "Vivid E95"
        assert detect_vendor(ds) == Vendor.GE

    def test_detect_philips(self):
        ds = Dataset()
        ds.Manufacturer = "Philips"
        assert detect_vendor(ds) == Vendor.PHILIPS

    def test_detect_samsung(self):
        ds = Dataset()
        ds.Manufacturer = "Samsung"
        assert detect_vendor(ds) == Vendor.SAMSUNG

    def test_detect_unknown(self):
        ds = Dataset()
        ds.Manufacturer = "Unknown Vendor"
        assert detect_vendor(ds) == Vendor.UNKNOWN


class TestVendorRegistry:
    """Test vendor profile registry."""

    def test_get_ge_profile(self):
        profile = get_profile(Vendor.GE)
        assert profile is not None
        assert profile.vendor == Vendor.GE

    def test_get_unknown_profile(self):
        profile = get_profile(Vendor.UNKNOWN)
        assert profile is None
