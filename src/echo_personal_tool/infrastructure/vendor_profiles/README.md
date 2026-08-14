# Vendor Profiles for DICOM Ultrasound Calibration

## Overview

This module provides vendor-specific profiles for handling DICOM ultrasound
calibration differences between scanner manufacturers (GE, Philips, Samsung).

Each vendor encodes Doppler calibration, M-mode timing, and reference pixel
semantics differently within the DICOM `SequenceOfUltrasound Regions`
(0018,6011). This module normalizes these differences into a consistent
interface for the calibration pipeline.

## Architecture

```
vendor_profiles/
├── __init__.py          # Package exports
├── base.py              # Abstract base class (VendorProfile)
├── ge.py                # GE Vingmed Ultrasound implementation
├── detector.py          # Vendor detection from DICOM tags
└── registry.py          # Profile registry and lookup
```

## Usage

### Basic Usage

```python
from echo_personal_tool.infrastructure.vendor_profiles import detect_vendor, get_profile

# Detect vendor from dataset
vendor = detect_vendor(dataset)

# Get vendor-specific profile
profile = get_profile(vendor)

# Use profile for calibration
baseline = profile.compute_baseline(region, frame_height)
velocity = profile.compute_velocity_span(region, region_height)
time = profile.compute_time_span(region, region_width)
```

### Integration with Calibration Pipeline

```python
from echo_personal_tool.infrastructure.vendor_calibration_bridge import (
    try_parse_with_vendor_profile,
)

# Vendor-aware calibration (replaces generic approach)
calibration = try_parse_with_vendor_profile(dataset, frame_pixels)
```

## GE Vivid E95 Profile

The GE profile handles these specific quirks:

### 1. Inverted Velocity Formula

GE uses: `v(y) = (RefY - y) × deltaY` (positive velocity = upward)

Standard DICOM: `v(y) = (y - RefY) × deltaY` (positive velocity = downward)

### 2. ReferencePixelY0 Can Be Outside Region

GE sometimes writes `ReferencePixelY0` values that are:
- Inside the region (baseline within visible band)
- Above the region (baseline off-screen, shifted baseline)
- Negative (baseline above image top)

This is intentional for measuring high-velocity flow.

### 3. PhysicalUnitsY = 7 (cm/sec)

GE correctly uses `cm/sec` per DICOM standard, but the velocity sign
convention differs from the standard.

### 4. Private Tags

GE uses private groups:
- `6003` (GEMS_Ultrasound_ImageGroup) - image metadata
- `7FE1` (GEMS_Ultrasound_MovieGroup) - scan parameters

## Philips Profile

Philips generally follows standard DICOM conventions:
- Negative PhysicalDeltaY for positive velocity = upward
- ReferencePixelY0 relative to region origin
- Private groups: 0033, 0029, 0071

## Samsung Profile

Samsung has quirks similar to GE but needs validation:
- Doppler regions sometimes mis-tagged as SF=1 (2D)
- ReferencePixelY0 may be region-relative
- Lower confidence until real data validation

## Adding New Vendors

To add a new vendor profile:

1. Create a new file `vendor_profiles/{vendor}.py`
2. Implement the `VendorProfile` abstract class
3. Register the profile in `vendor_profiles/registry.py`

Example:

```python
from echo_personal_tool.infrastructure.vendor_profiles.base import (
    Vendor,
    VendorProfile,
    BaselineResult,
)


class PhilipsProfile(VendorProfile):
    @property
    def vendor(self) -> Vendor:
        return Vendor.PHILIPS

    @property
    def vendor_keywords(self) -> list[str]:
        return ["philips"]

    def compute_baseline(self, region, frame_height, frame_pixels=None):
        # Philips uses standard DICOM convention
        ref_y = region.get("ReferencePixelY0")
        if ref_y is None:
            return BaselineResult(
                baseline_y=frame_height / 2.0,
                confidence=0.0,
                source="Philips: ReferencePixelY0 missing",
                velocity_sign=1,  # Standard convention
            )
        return BaselineResult(
            baseline_y=float(ref_y),
            confidence=0.9,
            source="Philips: ReferencePixelY0 (standard convention)",
            velocity_sign=1,
        )
```

## Testing

Run the test suite:

```bash
python3 -m pytest tests/test_vendor_profiles.py -v
```

## Vendor Comparison

| Aspect | GE | Philips | Samsung |
|--------|-----|---------|---------|
| Velocity formula | Inverted | Standard | Mixed |
| PhysicalDeltaY sign | Positive | Negative | Variable |
| ReferencePixel coords | Absolute | Absolute | Region-relative |
| Private groups | 6003, 7FE1 | 0033, 0029 | 0009, 0019 |
| Image format | Single-frame SC | Multi-frame | Multi-frame |
