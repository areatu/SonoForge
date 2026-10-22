"""Vendor profile registry.

Maintains a mapping from Vendor enum values to VendorProfile instances.
Profiles are registered at import time and can be retrieved by vendor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor, VendorProfile

if TYPE_CHECKING:
    from pydicom.dataset import Dataset

logger = logging.getLogger(__name__)

# Registry: Vendor → VendorProfile instance
_PROFILES: dict[Vendor, VendorProfile] = {}

# Lazy-loaded flag
_initialized = False


def _ensure_initialized() -> None:
    """Lazily import and register all vendor profiles."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    # Import profile implementations
    from echo_personal_tool.infrastructure.vendor_profiles.ge import GEProfile
    from echo_personal_tool.infrastructure.vendor_profiles.philips import PhilipsProfile
    from echo_personal_tool.infrastructure.vendor_profiles.samsung import SamsungProfile

    # Register profiles (add new vendors here)
    _profiles_to_register: list[VendorProfile] = [
        GEProfile(),
        PhilipsProfile(),
        SamsungProfile(),
    ]

    for profile in _profiles_to_register:
        if profile.vendor in _PROFILES:
            logger.warning(
                "Duplicate profile for vendor %s: %s (keeping first)",
                profile.vendor.value,
                profile,
            )
            continue
        _PROFILES[profile.vendor] = profile
        logger.debug("Registered vendor profile: %s", profile)


def get_profile(vendor: Vendor) -> VendorProfile | None:
    """Get the vendor profile for a specific vendor.

    Args:
        vendor: The Vendor enum value.

    Returns:
        The VendorProfile instance, or None if no profile is registered.
    """
    _ensure_initialized()
    profile = _PROFILES.get(vendor)
    if profile is None:
        logger.debug("No profile registered for vendor: %s", vendor.value)
    return profile


def get_profile_for_dataset(dataset: Dataset) -> VendorProfile | None:
    """Detect vendor from dataset and return the appropriate profile.

    This is the main entry point for getting a vendor profile.
    It combines vendor detection with profile lookup.

    Args:
        dataset: The DICOM dataset to analyze.

    Returns:
        The VendorProfile for the detected vendor, or None if unknown.
    """
    from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor

    vendor = detect_vendor(dataset)
    if vendor == Vendor.UNKNOWN:
        return None
    return get_profile(vendor)


def register_profile(profile: VendorProfile) -> None:
    """Register a vendor profile (for testing or dynamic registration).

    Args:
        profile: The VendorProfile instance to register.
    """
    _ensure_initialized()
    if profile.vendor in _PROFILES:
        logger.warning(
            "Overwriting existing profile for vendor %s",
            profile.vendor.value,
        )
    _PROFILES[profile.vendor] = profile
    logger.debug("Registered vendor profile: %s", profile)


def list_profiles() -> dict[Vendor, VendorProfile]:
    """Return a copy of all registered profiles."""
    _ensure_initialized()
    return dict(_PROFILES)
