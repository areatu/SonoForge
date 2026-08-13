"""Unified Doppler ROI validation.

Single point of validation for all ROI creation paths.
Prevents the recurring bug where fixes in one code path don't affect others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_grid_detector import detect_doppler_grid_lines

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoiValidationResult:
    """Result of ROI validation."""

    valid: bool
    reason: str
    grid_line_count: int = 0


def validate_doppler_roi(
    roi: DopplerSpectrogramRoi,
    frame: np.ndarray,
    *,
    check_grid_lines: bool = True,
    min_width_fraction: float = 0.9,
    min_height_fraction: float = 0.3,
    max_height_fraction: float = 0.7,
    require_lower_half: bool = True,
) -> RoiValidationResult:
    """Validate a Doppler spectrogram ROI against physical constraints.

    This is the SINGLE validation function used by all ROI creation paths.
    Changing validation logic here automatically applies everywhere.

    Args:
        roi: The ROI to validate.
        frame: The full frame (for grid line detection).
        check_grid_lines: If True, verify horizontal velocity grid lines exist.
        min_width_fraction: ROI width must be >= this fraction of frame width.
        min_height_fraction: ROI height must be >= this fraction of frame height.
        max_height_fraction: ROI height must be <= this fraction of frame height.
        require_lower_half: If True, ROI top must be in lower half of frame.

    Returns:
        RoiValidationResult with valid flag and reason string.
    """
    h, w = frame.shape[:2]

    # 1. Width check — Doppler spectrogram always spans most of the frame.
    if roi.width < w * min_width_fraction:
        return RoiValidationResult(
            valid=False,
            reason=f"width {roi.width:.0f}px < {min_width_fraction*100:.0f}% of {w}px",
        )

    # 2. Height check — spectrogram band is typically 30-70% of frame.
    if roi.height < h * min_height_fraction:
        return RoiValidationResult(
            valid=False,
            reason=f"height {roi.height:.0f}px < {min_height_fraction*100:.0f}% of {h}px",
        )
    if roi.height > h * max_height_fraction:
        return RoiValidationResult(
            valid=False,
            reason=f"height {roi.height:.0f}px > {max_height_fraction*100:.0f}% of {h}px",
        )

    # 3. Position check — Doppler is always in the lower portion of the frame.
    if require_lower_half and roi.y0 < h * 0.5:
        return RoiValidationResult(
            valid=False,
            reason=f"ROI top {roi.y0:.0f}px in upper half (frame height {h}px)",
        )

    # 4. Bounds check — ROI must be within the frame.
    if roi.x0 < 0 or roi.y0 < 0:
        return RoiValidationResult(
            valid=False,
            reason=f"ROI origin ({roi.x0:.0f}, {roi.y0:.0f}) is negative",
        )
    if roi.x0 + roi.width > w + 1 or roi.y0 + roi.height > h + 1:
        return RoiValidationResult(
            valid=False,
            reason="ROI extends beyond frame bounds",
        )

    # 5. Grid lines check — velocity scale markings must exist inside the ROI.
    # This is the primary filter against B-mode false positives.
    grid_line_count = 0
    if check_grid_lines:
        grid_lines = detect_doppler_grid_lines(
            frame,
            x0=int(roi.x0),
            y0=int(roi.y0),
            width=int(roi.width),
            height=int(roi.height),
        )
        grid_line_count = len(grid_lines)
        if grid_line_count < 1:
            return RoiValidationResult(
                valid=False,
                reason="no velocity grid lines detected inside ROI",
                grid_line_count=0,
            )

    return RoiValidationResult(valid=True, reason="ok", grid_line_count=grid_line_count)
