"""Vendor-specific DICOM ultrasound profiles.

Each vendor (GE, Philips, Samsung) has unique quirks in how they encode
Doppler calibration, M-mode timing, and reference pixel semantics. This
package provides vendor-specific handlers that normalize these differences
into a consistent interface for the calibration pipeline.

Usage:
    from echo_personal_tool.infrastructure.vendor_profiles import detect_vendor, get_profile

    vendor = detect_vendor(dataset)
    profile = get_profile(vendor)
    baseline_y = profile.compute_baseline(region, frame_height)
"""

from echo_personal_tool.infrastructure.vendor_profiles.base import (
    BaselineResult,
    TimeSpanResult,
    VelocitySpanResult,
    Vendor,
    VendorProfile,
)
from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor
from echo_personal_tool.infrastructure.vendor_profiles.registry import (
    get_profile,
    get_profile_for_dataset,
    list_profiles,
)

__all__ = [
    "BaselineResult",
    "TimeSpanResult",
    "VelocitySpanResult",
    "Vendor",
    "VendorProfile",
    "detect_vendor",
    "get_profile",
    "get_profile_for_dataset",
    "list_profiles",
]
