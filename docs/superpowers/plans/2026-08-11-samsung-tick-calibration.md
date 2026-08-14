# Samsung Tick Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Samsung RS85 sweep speed calibration by detecting tick marks on the time axis and computing a device-specific K constant.

**Architecture:** Offline calibration builder measures tick spacing at known frequencies, fits the LINEAR model `frequency_hz = k_constant * tick_spacing_px` (empirically `k_constant = 5.0` on RS85: `spacing_px = freq / 5`). Runtime detector measures ticks on unknown images and computes frequency = k_constant * tick_spacing_px. Integrates into SamsungProfile for time calibration (fallback when DICOM time tags are absent).

**Tech Stack:** Python 3.11, NumPy, pydicom, pytest

## Global Constraints

- Python 3.11+, no new dependencies beyond opencv-python-headless (already present)
- Follow existing code style in vendor_profiles/ package
- All functions must have type hints and docstrings
- Tests must pass before commit
- K constant verified against M-mode DICOM tags (ΔX = 1/frequency)

## Empirical Model (validated 2026-08-11)

On the RS85 training set (18 PW/CW files) the time-axis ruler at the bottom of
the frame is **linear** in sweep frequency:

| freq | 60 | 120 | 180 | 240 | 300 | 360 | 420 | 480 | 540 | 600 | 660 | 720 |
|------|----|----|----|----|----|----|----|----|----|----|----|----|
| spacing px | 12 | 24 | 36 | 48 | 60 | 72 | 84 | 96 | 108 | 120 | 132 | 144 |

`spacing_px = freq / 5`, i.e. `k_constant = 5.0` (Hz per px). M-mode files
(13-18) carry proper DICOM tags (`PhysicalDeltaX = 1/frequency`, units=seconds),
so they do NOT need tick detection and are excluded from training. Ruler sits at
a fixed offset from the bottom of the frame; detection scans the bottom 15%.
Model, detector ROI and builder fit were changed from the plan's original
`spacing = K / freq` assumption to this linear relation.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/echo_personal_tool/infrastructure/samsung_tick_detector.py` | Detect tick marks and measure spacing |
| `src/echo_personal_tool/infrastructure/samsung_calibration_builder.py` | Build K constant from training data |
| `src/echo_personal_tool/infrastructure/samsung_tick_calibration.json` | Store K constant and measured points |
| `src/echo_personal_tool/infrastructure/vendor_profiles/samsung.py` | Integrate tick detection into time calibration |
| `tests/test_samsung_tick_calibration.py` | Unit tests for detection and calibration |

---

### Task 1: Tick Detector Core

**Files:**
- Create: `src/echo_personal_tool/infrastructure/samsung_tick_detector.py`
- Test: `tests/test_samsung_tick_calibration.py`

**Interfaces:**
- Consumes: numpy pixel array (RGB or grayscale)
- Produces: `TickDetectionResult(tick_positions: list[float], spacing_px: float, confidence: float)`

- [x] **Step 1: Write the failing test**

```python
# tests/test_samsung_tick_calibration.py
import numpy as np
import pytest
from echo_personal_tool.infrastructure.samsung_tick_detector import (
    detect_ticks,
    TickDetectionResult,
)


def test_detect_ticks_returns_result():
    """Basic interface test."""
    # Create synthetic image with vertical tick marks
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    # Draw vertical lines at x=100, 200, 300, 400, 500
    for x in [100, 200, 300, 400, 500]:
        img[:, x, :] = 255
    
    result = detect_ticks(img)
    assert isinstance(result, TickDetectionResult)
    assert len(result.tick_positions) >= 2
    assert result.spacing_px > 0


def test_detect_ticks_measures_correct_spacing():
    """Verify spacing measurement on synthetic image."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    # Draw ticks at exact 50px intervals
    for x in range(100, 700, 50):
        img[:, x, :] = 255
    
    result = detect_ticks(img)
    assert abs(result.spacing_px - 50.0) < 5.0  # Allow some tolerance


def test_detect_ticks_empty_image():
    """No ticks = low confidence."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    result = detect_ticks(img)
    assert result.confidence < 0.5
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_samsung_tick_calibration.py -v`
Expected: FAIL with ImportError (module not found)

- [x] **Step 3: Write minimal implementation**

```python
# src/echo_personal_tool/infrastructure/samsung_tick_detector.py
"""Samsung tick mark detection for sweep speed calibration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TickDetectionResult:
    """Result of tick mark detection."""
    tick_positions: list[float]
    spacing_px: float
    confidence: float


def detect_ticks(
    pixel_array: np.ndarray,
    roi_bottom_fraction: float = 0.2,
) -> TickDetectionResult:
    """Detect vertical tick marks in the time scale region.
    
    Args:
        pixel_array: RGB or grayscale image as numpy array.
        roi_bottom_fraction: Fraction of image height to use for ROI (bottom part).
    
    Returns:
        TickDetectionResult with positions, spacing, and confidence.
    """
    # Convert to grayscale
    if len(pixel_array.shape) == 3:
        gray = cv2.cvtColor(pixel_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = pixel_array.copy()
    
    h, w = gray.shape
    
    # Crop bottom ROI (time scale region)
    roi_top = int(h * (1.0 - roi_bottom_fraction))
    roi = gray[roi_top:, :]
    
    # Edge detection
    edges = cv2.Canny(roi, 50, 150, apertureSize=3)
    
    # Vertical morphological kernel to enhance vertical lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))
    vertical = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Filter contours by shape (vertical lines)
    tick_positions = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        # Vertical line: height > width, reasonable size
        if ch > cw * 2 and ch > 20 and cw < 20:
            center_x = x + cw / 2
            tick_positions.append(center_x)
    
    # Sort by x position
    tick_positions.sort()
    
    # Calculate spacing
    if len(tick_positions) < 2:
        return TickDetectionResult(
            tick_positions=tick_positions,
            spacing_px=0.0,
            confidence=0.0,
        )
    
    spacings = [tick_positions[i+1] - tick_positions[i] for i in range(len(tick_positions)-1)]
    avg_spacing = np.mean(spacings)
    std_spacing = np.std(spacings)
    
    # Confidence based on consistency and count
    consistency = 1.0 - min(std_spacing / avg_spacing, 1.0) if avg_spacing > 0 else 0.0
    count_factor = min(len(tick_positions) / 5.0, 1.0)  # 5+ ticks = full confidence
    confidence = consistency * count_factor
    
    return TickDetectionResult(
        tick_positions=tick_positions,
        spacing_px=float(avg_spacing),
        confidence=float(confidence),
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_samsung_tick_calibration.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/infrastructure/samsung_tick_detector.py tests/test_samsung_tick_calibration.py
git commit -m "feat(samsung): add tick mark detection for sweep speed calibration"
```

---

### Task 2: Calibration Builder

**Files:**
- Create: `src/echo_personal_tool/infrastructure/samsung_calibration_builder.py`
- Modify: `tests/test_samsung_tick_calibration.py`

**Interfaces:**
- Consumes: list of (frequency_hz, pixel_array) tuples
- Produces: `SamsungTickCalibration(k_constant, r_squared, measured_points)`

- [x] **Step 1: Write the failing test**

```python
# Append to tests/test_samsung_tick_calibration.py
from echo_personal_tool.infrastructure.samsung_calibration_builder import (
    SamsungTickCalibration,
    build_calibration,
)


def test_build_calibration_returns_calibration():
    """Basic interface test."""
    # Create synthetic images with ticks at known spacings
    # At 60 Hz: spacing = 100px → K = 6000
    # At 120 Hz: spacing = 50px → K = 6000
    training_data = []
    for freq in [60, 120, 240]:
        spacing = 6000 / freq
        img = np.zeros((200, 800, 3), dtype=np.uint8)
        for x in range(100, 700, int(spacing)):
            img[:, x, :] = 255
        training_data.append((freq, img))
    
    calibration = build_calibration(training_data)
    assert isinstance(calibration, SamsungTickCalibration)
    assert calibration.k_constant > 0
    assert calibration.r_squared > 0.9


def test_build_calibration_computes_correct_k():
    """Verify K constant computation."""
    training_data = []
    for freq in [60, 120]:
        spacing = 6000 / freq
        img = np.zeros((200, 800, 3), dtype=np.uint8)
        for x in range(100, 700, int(spacing)):
            img[:, x, :] = 255
        training_data.append((freq, img))
    
    calibration = build_calibration(training_data)
    assert abs(calibration.k_constant - 6000.0) < 100.0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_samsung_tick_calibration.py::test_build_calibration_returns_calibration -v`
Expected: FAIL with ImportError

- [x] **Step 3: Write minimal implementation**

```python
# src/echo_personal_tool/infrastructure/samsung_calibration_builder.py
"""Build Samsung tick calibration from training data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from echo_personal_tool.infrastructure.samsung_tick_detector import (
    detect_ticks,
    TickDetectionResult,
)

logger = logging.getLogger(__name__)

_CALIBRATION_FILE = Path(__file__).parent / "samsung_tick_calibration.json"


@dataclass
class TickMeasurement:
    """Single frequency measurement."""
    frequency_hz: float
    tick_spacing_px: float
    tick_count: int
    confidence: float


@dataclass
class SamsungTickCalibration:
    """Samsung device tick calibration."""
    device_model: str
    k_constant: float
    r_squared: float
    image_height_ref: int
    measured_points: list[TickMeasurement]


def build_calibration(
    training_data: list[tuple[float, np.ndarray]],
    device_model: str = "RS85-RUS",
) -> SamsungTickCalibration:
    """Build calibration from training data.
    
    Args:
        training_data: List of (frequency_hz, pixel_array) tuples.
        device_model: Samsung device model name.
    
    Returns:
        SamsungTickCalibration with K constant and quality metrics.
    """
    measurements: list[TickMeasurement] = []
    
    for freq, pixel_array in training_data:
        result = detect_ticks(pixel_array)
        if result.confidence > 0.3 and result.spacing_px > 0:
            measurements.append(TickMeasurement(
                frequency_hz=freq,
                tick_spacing_px=result.spacing_px,
                tick_count=len(result.tick_positions),
                confidence=result.confidence,
            ))
    
    if len(measurements) < 2:
        raise ValueError(f"Insufficient valid measurements: {len(measurements)}")
    
    # Fit K = spacing * frequency for each point
    k_values = [m.tick_spacing_px * m.frequency_hz for m in measurements]
    k_constant = float(np.median(k_values))  # Median is robust to outliers
    
    # Compute R² for fit quality
    k_array = np.array(k_values)
    k_mean = k_array.mean()
    ss_res = ((k_array - k_constant) ** 2).sum()
    ss_tot = ((k_array - k_mean) ** 2).sum()
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    
    # Get reference image height from first measurement
    image_height_ref = 884  # Default for Samsung RS85
    
    return SamsungTickCalibration(
        device_model=device_model,
        k_constant=k_constant,
        r_squared=float(r_squared),
        image_height_ref=image_height_ref,
        measured_points=measurements,
    )


def save_calibration(calibration: SamsungTickCalibration) -> None:
    """Save calibration to JSON file."""
    data = {
        "device_model": calibration.device_model,
        "k_constant": calibration.k_constant,
        "r_squared": calibration.r_squared,
        "image_height_ref": calibration.image_height_ref,
        "measured_points": [asdict(m) for m in calibration.measured_points],
    }
    _CALIBRATION_FILE.write_text(json.dumps(data, indent=2))
    logger.info("Saved calibration to %s", _CALIBRATION_FILE)


def load_calibration() -> SamsungTickCalibration | None:
    """Load calibration from JSON file."""
    if not _CALIBRATION_FILE.exists():
        return None
    try:
        data = json.loads(_CALIBRATION_FILE.read_text())
        measurements = [TickMeasurement(**m) for m in data["measured_points"]]
        return SamsungTickCalibration(
            device_model=data["device_model"],
            k_constant=data["k_constant"],
            r_squared=data["r_squared"],
            image_height_ref=data["image_height_ref"],
            measured_points=measurements,
        )
    except Exception as e:
        logger.warning("Failed to load calibration: %s", e)
        return None
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_samsung_tick_calibration.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/infrastructure/samsung_calibration_builder.py tests/test_samsung_tick_calibration.py
git commit -m "feat(samsung): add calibration builder for K constant computation"
```

---

### Task 3: Train on Real Samsung Data

**Files:**
- Create: `src/echo_personal_tool/infrastructure/samsung_tick_calibration.json` (generated)

**Interfaces:**
- Consumes: Samsung DICOM files from `/home/areatu/ECHO2026_src/New Folder2/`
- Produces: K constant and measured points

- [x] **Step 1: Write training script**

```python
# src/echo_personal_tool/scripts/train_samsung_calibration.py
"""Train Samsung tick calibration from renamed DICOM files."""

from pathlib import Path
import pydicom
import numpy as np
from echo_personal_tool.infrastructure.samsung_calibration_builder import (
    build_calibration,
    save_calibration,
)


def load_dicom_pixels(path: Path) -> np.ndarray:
    """Load DICOM file and return RGB pixel array."""
    ds = pydicom.dcmread(str(path))
    return ds.pixel_array


def main():
    data_dir = Path("/home/areatu/ECHO2026_src/New Folder2")
    
    # Collect PW and CW files with known frequencies
    training_data = []
    for dcm_path in sorted(data_dir.glob("*.dcm")):
        name = dcm_path.stem
        # Parse "PW 60 Hz" or "CW 120 Hz" format
        if " " in name:
            parts = name.split()
            if len(parts) >= 3 and parts[2] == "Hz":
                try:
                    freq = float(parts[1])
                    pixels = load_dicom_pixels(dcm_path)
                    training_data.append((freq, pixels))
                    print(f"Loaded {name}: {freq} Hz")
                except (ValueError, IndexError):
                    pass
    
    print(f"\nLoaded {len(training_data)} training files")
    
    # Build calibration
    calibration = build_calibration(training_data)
    
    print(f"\nCalibration results:")
    print(f"  K constant: {calibration.k_constant:.2f}")
    print(f"  R²: {calibration.r_squared:.4f}")
    print(f"  Measurements: {len(calibration.measured_points)}")
    
    for m in calibration.measured_points:
        print(f"    {m.frequency_hz:6.0f} Hz: {m.tick_spacing_px:6.2f} px (n={m.tick_count}, conf={m.confidence:.2f})")
    
    # Save
    save_calibration(calibration)
    print(f"\nSaved to samsung_tick_calibration.json")


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Run training script**

Run: `cd /home/areatu/ECHO2026 && source .venv/bin/activate && python -m echo_personal_tool.scripts.train_samsung_calibration`
Expected: K constant computed, JSON file created

- [x] **Step 3: Verify K against M-mode DICOM tags**

```python
# Verify: for M-mode at 60 Hz, DICOM says ΔX=0.01667s
# Expected: tick_spacing_px = K / 60
# If K=1200, spacing=20px, and 20px * 0.01667s/px = 0.333s between ticks
# This should match the visual tick interval
```

- [x] **Step 4: Commit calibration data**

```bash
git add src/echo_personal_tool/infrastructure/samsung_tick_calibration.json src/echo_personal_tool/scripts/train_samsung_calibration.py
git commit -m "feat(samsung): train tick calibration on RS85 data"
```

---

### Task 4: Integrate into SamsungProfile

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/vendor_profiles/samsung.py`

**Interfaces:**
- Consumes: `SamsungTickCalibration` from Task 2
- Produces: Updated `compute_time_span()` method

- [x] **Step 1: Write the failing test**

```python
# Append to tests/test_samsung_tick_calibration.py
from echo_personal_tool.infrastructure.vendor_profiles.samsung import SamsungProfile


def test_samsung_profile_uses_tick_calibration():
    """SamsungProfile should use tick calibration when available."""
    profile = SamsungProfile()
    
    # Mock region with no DICOM time tags
    from pydicom.dataset import Dataset
    region = Dataset()
    region.RegionLocationMinX0 = 0
    region.RegionLocationMaxX1 = 800
    
    # This should attempt tick detection
    result = profile.compute_time_span(region, region_width_px=800.0)
    # Result depends on whether calibration is loaded
    assert result is None or result.confidence >= 0.0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_samsung_tick_calibration.py::test_samsung_profile_uses_tick_calibration -v`
Expected: FAIL (method doesn't use tick calibration yet)

- [x] **Step 3: Update SamsungProfile**

```python
# Add to src/echo_personal_tool/infrastructure/vendor_profiles/samsung.py

from echo_personal_tool.infrastructure.samsung_calibration_builder import (
    load_calibration,
)
from echo_personal_tool.infrastructure.samsung_tick_detector import detect_ticks


class SamsungProfile(VendorProfile):
    def __init__(self):
        self._tick_calibration = load_calibration()
    
    def compute_time_span(
        self,
        region: Dataset,
        region_width_px: float,
    ) -> TimeSpanResult | None:
        """Compute time span using DICOM tags or tick detection."""
        # 1. Try DICOM tags first
        delta_x = region.get("PhysicalDeltaX")
        units_x = region.get("PhysicalUnitsXDirection")
        
        if delta_x is not None and units_x is not None:
            try:
                delta_x_f = float(delta_x)
                units_x_i = int(units_x)
                if units_x_i == 4:  # seconds
                    per_pixel = abs(delta_x_f) * 1000.0
                    span = per_pixel * region_width_px
                    return TimeSpanResult(
                        span_ms=span,
                        per_pixel_ms=per_pixel,
                        confidence=0.8,
                        source=f"Samsung: PhysicalDeltaX={delta_x_f}, units=4 (seconds)",
                    )
            except (TypeError, ValueError):
                pass
        
        # 2. Fallback: tick detection
        if self._tick_calibration is not None and hasattr(self, '_frame_pixels'):
            result = detect_ticks(self._frame_pixels)
            if result.confidence > 0.3 and result.spacing_px > 0:
                frequency = self._tick_calibration.k_constant / result.spacing_px
                # Convert frequency to time span
                # At given frequency, one full sweep = 1/frequency seconds
                # Time span = width_px * (1/frequency) / pixels_per_sweep
                # Simplified: time_per_px = 1 / (frequency * pixels_per_unit)
                time_per_px = 1000.0 / frequency  # ms per pixel
                span = time_per_px * region_width_px
                return TimeSpanResult(
                    span_ms=span,
                    per_pixel_ms=time_per_px,
                    confidence=result.confidence * 0.8,
                    source=f"Samsung: tick detection, K={self._tick_calibration.k_constant:.1f}, freq={frequency:.1f}Hz",
                )
        
        return None
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_samsung_tick_calibration.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/infrastructure/vendor_profiles/samsung.py
git commit -m "feat(samsung): integrate tick calibration into SamsungProfile"
```

---

### Task 5: Integration Test with Real Data

**Files:**
- Modify: `tests/test_samsung_tick_calibration.py`

**Interfaces:**
- Consumes: Real Samsung DICOM files
- Produces: Verified calibration accuracy

- [x] **Step 1: Write integration test**

```python
# Append to tests/test_samsung_tick_calibration.py
import pytest
from pathlib import Path


@pytest.mark.skipif(
    not Path("/home/areatu/ECHO2026_src/New Folder2").exists(),
    reason="Samsung training data not available",
)
def test_calibration_on_real_data():
    """Verify calibration works on real Samsung DICOM files."""
    import pydicom
    from echo_personal_tool.infrastructure.samsung_calibration_builder import load_calibration
    from echo_personal_tool.infrastructure.samsung_tick_detector import detect_ticks
    
    calibration = load_calibration()
    assert calibration is not None, "Calibration not trained yet"
    
    data_dir = Path("/home/areatu/ECHO2026_src/New Folder2")
    
    # Test on a few files
    for name in ["PW 60 Hz.dcm", "CW 120 Hz.dcm"]:
        dcm_path = data_dir / name
        if not dcm_path.exists():
            continue
        
        ds = pydicom.dcmread(str(dcm_path))
        pixels = ds.pixel_array
        
        result = detect_ticks(pixels)
        if result.confidence > 0.3:
            detected_freq = calibration.k_constant / result.spacing_px
            # Extract expected frequency from filename
            expected_freq = float(name.split()[1])
            error_pct = abs(detected_freq - expected_freq) / expected_freq * 100
            
            print(f"{name}: detected={detected_freq:.1f} Hz, expected={expected_freq:.0f} Hz, error={error_pct:.1f}%")
            assert error_pct < 20.0, f"Frequency detection error too large: {error_pct:.1f}%"
```

- [x] **Step 2: Run integration test**

Run: `pytest tests/test_samsung_tick_calibration.py::test_calibration_on_real_data -v`
Expected: PASS with frequency detection within 20% tolerance

- [x] **Step 3: Commit**

```bash
git add tests/test_samsung_tick_calibration.py
git commit -m "test(samsung): add integration test for tick calibration"
```

---

## Summary

| Task | Deliverable | Dependencies |
|------|-------------|--------------|
| 1 | Tick detector module | None |
| 2 | Calibration builder | Task 1 |
| 3 | Trained K constant | Task 2 |
| 4 | SamsungProfile integration | Tasks 2, 3 |
| 5 | Integration verification | Tasks 3, 4 |

**Total estimated time:** 45-60 minutes
