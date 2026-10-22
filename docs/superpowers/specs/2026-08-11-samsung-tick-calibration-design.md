# Samsung Tick Calibration Design

**Date:** 2026-08-11  
**Status:** Approved  
**Scope:** Samsung RS85 sweep speed calibration via tick mark detection

## Problem

Samsung RS85 mis-tags Doppler regions (PW/CW) as SF=1 (2D B-mode). DICOM tags don't contain sweep speed for PW/CW modes. Need to detect sweep speed from visual tick marks on the time axis.

## Key Insight

Tick spacing is inversely proportional to sweep speed:
```
tick_spacing_px = K / frequency_hz
```

Where K is a device-specific constant. For Samsung RS85, this relationship holds across all modes (PW, CW, M-mode, TDI) at the same frequency.

## Data Sources

- **PW files:** 12 files (60-720 Hz, step 60)
- **CW files:** 6 files (60-360 Hz, step 60)
- **M-mode files:** 6 files (60-360 Hz) — have DICOM tags for verification

## Architecture

### 1. Tick Detection Module

**File:** `src/echo_personal_tool/infrastructure/samsung_tick_detector.py`

```python
@dataclass
class TickMeasurement:
    frequency_hz: float
    tick_spacing_px: float
    tick_count: int
    confidence: float

@dataclass
class SamsungTickCalibration:
    k_constant: float  # tick_spacing_px * frequency_hz
    r_squared: float   # regression quality
    measured_points: list[TickMeasurement]
    image_height: int  # ROI reference height
```

**Algorithm:**
1. Crop bottom 15-20% of image (time scale region)
2. Convert to grayscale
3. Apply Canny edge detection
4. Apply vertical morphological kernel to enhance vertical lines
5. Find contours or use HoughLinesP
6. Filter by angle (vertical) and size (tick-like)
7. Sort by X position
8. Measure distances between adjacent ticks
9. Return average spacing and confidence

### 2. Calibration Builder

**File:** `src/echo_personal_tool/infrastructure/samsung_calibration_builder.py`

**Training phase (offline):**
1. Load all renamed files with known frequencies
2. Run tick detection on each
3. Collect (frequency, tick_spacing_px) pairs
4. Fit regression: `tick_spacing_px = K / frequency_hz`
5. Compute R² for quality metric
6. Save K constant to calibration file

**Runtime phase:**
1. Detect ticks on unknown image
2. Measure `tick_spacing_px`
3. Compute `frequency = K / tick_spacing_px`
4. Return frequency with confidence

### 3. SamsungProfile Integration

**File:** `src/echo_personal_tool/infrastructure/vendor_profiles/samsung.py`

Update `compute_time_span()`:
```python
def compute_time_span(self, region, region_width_px):
    # 1. Try DICOM tags first (M-mode has them)
    delta_x = region.get("PhysicalDeltaX")
    units_x = region.get("PhysicalUnitsXDirection")
    if delta_x is not None and units_x == 4:  # seconds
        # Standard DICOM calculation
        ...
    
    # 2. Fallback: detect ticks from image
    if self._tick_calibration is not None:
        tick_spacing = detect_tick_spacing(self._frame_pixels)
        if tick_spacing is not None:
            frequency = self._tick_calibration.k_constant / tick_spacing
            # Compute time span from frequency
            ...
    
    # 3. Last resort: center ROI
    return TimeSpanResult(span_ms=0, confidence=0.0, source="No calibration available")
```

### 4. Calibration Data Storage

**File:** `src/echo_personal_tool/infrastructure/samsung_tick_calibration.json`

```json
{
  "device_model": "RS85-RUS",
  "k_constant": 1234.5,
  "r_squared": 0.999,
  "image_height_ref": 884,
  "measured_points": [
    {"frequency_hz": 60, "tick_spacing_px": 20.58, "tick_count": 42},
    {"frequency_hz": 120, "tick_spacing_px": 10.29, "tick_count": 84},
    ...
  ]
}
```

## Data Flow

```
Training:
  Renamed DICOM files → Tick Detector → (freq, spacing) pairs → Regression → K constant

Runtime:
  Unknown DICOM → Pixel extraction → Tick Detector → tick_spacing_px
                                                    ↓
                              K / tick_spacing_px → frequency_hz
                                                    ↓
                              frequency_hz → time_span_ms via region width
```

## Error Handling

1. **No ticks detected:** Return confidence=0, fallback to DICOM tags or center ROI
2. **Low tick count (<3):** Reduce confidence proportionally
3. **Regression R² < 0.95:** Log warning, still use K with reduced confidence
4. **Image height mismatch:** Scale K proportionally (tick position may shift)

## Testing

1. Unit tests for tick detection on known images
2. Verify K constant across all 24 training files
3. Integration test: detect frequency on held-out test image
4. Compare M-mode DICOM tags vs tick-detected frequency

## Files to Create/Modify

- `src/echo_personal_tool/infrastructure/samsung_tick_detector.py` (new)
- `src/echo_personal_tool/infrastructure/samsung_calibration_builder.py` (new)
- `src/echo_personal_tool/infrastructure/vendor_profiles/samsung.py` (modify)
- `src/echo_personal_tool/infrastructure/samsung_tick_calibration.json` (generated)
- `tests/test_samsung_tick_calibration.py` (new)
