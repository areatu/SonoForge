"""Vendor detection from DICOM dataset.

Identifies the ultrasound scanner manufacturer from standard DICOM tags
and private creator strings, returning the appropriate Vendor enum value.
"""

from __future__ import annotations

import logging

from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor

logger = logging.getLogger(__name__)

# Manufacturer name patterns → Vendor mapping (order matters: first match wins)
_MANUFACTURER_PATTERNS: list[tuple[str, Vendor]] = [
    # GE
    ("ge", Vendor.GE),
    ("vingmed", Vendor.GE),
    ("vivid", Vendor.GE),
    # Philips
    ("philips", Vendor.PHILIPS),
    ("ultrasound", Vendor.PHILIPS),  # Philips sometimes uses generic
    # Samsung
    ("samsung", Vendor.SAMSUNG),
    ("medison", Vendor.SAMSUNG),
    # Siemens
    ("siemens", Vendor.SIEMENS),
    ("acuson", Vendor.SIEMENS),
    # Toshiba
    ("toshiba", Vendor.TOSHIBA),
    ("canon", Vendor.TOSHIBA),  # Canon acquired Toshiba medical
]

# Private creator strings that indicate specific vendors
_PRIVATE_CREATORS: list[tuple[str, Vendor]] = [
    ("GEMS", Vendor.GE),
    ("GEUltrasound", Vendor.GE),
    ("PHILIPS", Vendor.PHILIPS),
    ("Philips", Vendor.PHILIPS),
    ("SAMSUNG", Vendor.SAMSUNG),
    ("SV_MG", Vendor.SAMSUNG),
    ("SIEMENS", Vendor.SIEMENS),
    ("TOSHIBA", Vendor.TOSHIBA),
]


def detect_vendor(dataset: Dataset) -> Vendor:
    """Detect ultrasound scanner manufacturer from DICOM dataset.

    Checks, in order:
    1. Manufacturer tag (0008,0070) — most reliable
    2. ManufacturerModelName tag (0008,1090) — fallback
    3. Private creator strings — last resort

    Returns:
        Vendor enum value, or Vendor.UNKNOWN if detection fails.
    """
    # 1. Check Manufacturer tag
    manufacturer = str(dataset.get("Manufacturer", "")).lower()
    if manufacturer:
        for pattern, vendor in _MANUFACTURER_PATTERNS:
            if pattern in manufacturer:
                logger.debug("Vendor detected from Manufacturer='%s': %s", manufacturer, vendor.value)
                return vendor

    # 2. Check ManufacturerModelName
    model = str(dataset.get("ManufacturerModelName", "")).lower()
    if model:
        for pattern, vendor in _MANUFACTURER_PATTERNS:
            if pattern in model:
                logger.debug("Vendor detected from ModelName='%s': %s", model, vendor.value)
                return vendor

    # 3. Check private creator strings
    for tag in dataset:
        if tag.tag.group & 0xFF00 == 0x0000:  # Skip non-private groups
            continue
        if tag.tag.element != 0x0010:  # Private creator is always element 0010
            continue
        try:
            creator = str(tag.value).upper()
            for pattern, vendor in _PRIVATE_CREATORS:
                if pattern.upper() in creator:
                    logger.debug("Vendor detected from private creator='%s': %s", creator, vendor.value)
                    return vendor
        except (AttributeError, TypeError):
            continue

    logger.debug("Vendor detection failed, returning UNKNOWN")
    return Vendor.UNKNOWN
