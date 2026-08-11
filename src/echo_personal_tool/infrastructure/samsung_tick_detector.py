"""Samsung tick mark detection for sweep speed calibration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Detection parameters (tuned for Samsung RS85 time scale)
_CANNY_LOW = 50
_CANNY_HIGH = 150
_MORPH_KERNEL_HEIGHT = 15
_MERGE_DISTANCE_PX = 10
_TICK_MIN_HEIGHT_PX = 20
_TICK_MAX_WIDTH_PX = 20
_TICK_HEIGHT_WIDTH_RATIO = 2.0
_FULL_CONFIDENCE_TICK_COUNT = 5


@dataclass
class TickDetectionResult:
    """Result of tick mark detection."""
    tick_positions: list[float]
    spacing_px: float
    confidence: float


def detect_ticks(
    pixel_array: np.ndarray,
    roi_bottom_fraction: float = 0.2,
    channel_order: str = "rgb",
) -> TickDetectionResult:
    """Detect vertical tick marks in the time scale region.

    Args:
        pixel_array: RGB or grayscale image as numpy array.
        roi_bottom_fraction: Fraction of image height to use for ROI (bottom part).
        channel_order: Color channel order for 3D input: "rgb" (default) or "bgr".

    Returns:
        TickDetectionResult with positions, spacing, and confidence.
    """
    if pixel_array.ndim not in (2, 3):
        raise ValueError(f"Expected 2D or 3D array, got shape {pixel_array.shape}")
    if pixel_array.size == 0:
        raise ValueError("Input array is empty")

    # Convert to grayscale
    if len(pixel_array.shape) == 3:
        if channel_order == "bgr":
            gray = cv2.cvtColor(pixel_array, cv2.COLOR_BGR2GRAY)
        else:
            gray = cv2.cvtColor(pixel_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = pixel_array.copy()

    h, w = gray.shape

    # Crop bottom ROI (time scale region)
    roi_top = int(h * (1.0 - roi_bottom_fraction))
    roi = gray[roi_top:, :]

    if roi.size == 0 or roi.shape[0] == 0:
        return TickDetectionResult(
            tick_positions=[],
            spacing_px=0.0,
            confidence=0.0,
        )
    
    # Edge detection
    edges = cv2.Canny(roi, _CANNY_LOW, _CANNY_HIGH, apertureSize=3)

    # Vertical morphological kernel to enhance vertical lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, _MORPH_KERNEL_HEIGHT))
    vertical = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Filter contours by shape (vertical lines)
    raw_positions = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        # Vertical line: height > width, reasonable size
        if ch > cw * _TICK_HEIGHT_WIDTH_RATIO and ch > _TICK_MIN_HEIGHT_PX and cw < _TICK_MAX_WIDTH_PX:
            center_x = x + cw / 2
            raw_positions.append(center_x)
    
    # Sort by x position
    raw_positions.sort()
    
    # Merge nearby positions (within threshold) to avoid duplicates
    tick_positions = []
    for pos in raw_positions:
        if not tick_positions or pos - tick_positions[-1] > _MERGE_DISTANCE_PX:
            tick_positions.append(pos)
    
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
    count_factor = min(len(tick_positions) / _FULL_CONFIDENCE_TICK_COUNT, 1.0)
    confidence = consistency * count_factor
    
    return TickDetectionResult(
        tick_positions=tick_positions,
        spacing_px=float(avg_spacing),
        confidence=float(confidence),
    )
