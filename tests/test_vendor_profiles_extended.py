"""Additional tests for vendor profile registry and detection."""

from __future__ import annotations

import pytest
from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor
from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor
from echo_personal_tool.infrastructure.vendor_profiles.registry import (
    get_profile,
    get_profile_for_dataset,
    list_profiles,
)


class TestVendorRegistry:
    """Test vendor profile registry with all vendors."""

    def test_list_profiles_has_all_vendors(self):
        profiles = list_profiles()
        assert Vendor.GE in profiles
        assert Vendor.PHILIPS in profiles
        assert Vendor.SAMSUNG in profiles

    def test_get_profile_ge(self):
        profile = get_profile(Vendor.GE)
        assert profile is not None
        assert profile.vendor == Vendor.GE
        assert "ge" in profile.vendor_keywords

    def test_get_profile_philips(self):
        profile = get_profile(Vendor.PHILIPS)
        assert profile is not None
        assert profile.vendor == Vendor.PHILIPS
        assert "philips" in profile.vendor_keywords

    def test_get_profile_samsung(self):
        profile = get_profile(Vendor.SAMSUNG)
        assert profile is not None
        assert profile.vendor == Vendor.SAMSUNG
        assert "samsung" in profile.vendor_keywords

    def test_get_profile_for_dataset_ge(self):
        ds = Dataset()
        ds.Manufacturer = "GE Vingmed Ultrasound"
        ds.ManufacturerModelName = "Vivid E95"
        profile = get_profile_for_dataset(ds)
        assert profile is not None
        assert profile.vendor == Vendor.GE

    def test_get_profile_for_dataset_philips(self):
        ds = Dataset()
        ds.Manufacturer = "Philips"
        ds.ManufacturerModelName = "EPIQ 7C"
        profile = get_profile_for_dataset(ds)
        assert profile is not None
        assert profile.vendor == Vendor.PHILIPS

    def test_get_profile_for_dataset_samsung(self):
        ds = Dataset()
        ds.Manufacturer = "Samsung"
        ds.ManufacturerModelName = "RS85"
        profile = get_profile_for_dataset(ds)
        assert profile is not None
        assert profile.vendor == Vendor.SAMSUNG

    def test_get_profile_for_dataset_unknown(self):
        ds = Dataset()
        ds.Manufacturer = "Unknown Vendor"
        profile = get_profile_for_dataset(ds)
        assert profile is None


class TestVendorDetector:
    """Test vendor detection edge cases."""

    def test_detect_philips_model(self):
        ds = Dataset()
        ds.ManufacturerModelName = "Philips EPIQ 7C"
        assert detect_vendor(ds) == Vendor.PHILIPS

    def test_detect_samsung_model(self):
        ds = Dataset()
        ds.ManufacturerModelName = "Samsung RS85"
        assert detect_vendor(ds) == Vendor.SAMSUNG

    def test_detect_empty_dataset(self):
        ds = Dataset()
        assert detect_vendor(ds) == Vendor.UNKNOWN
