"""GE Vingmed Ultrasound vendor profile.

Handles GE-specific quirks in DICOM ultrasound region calibration:

1. **Inverted velocity formula**: GE uses v = (RefY - y) × deltaY instead of
   the standard DICOM formula v = (y - RefY) × deltaY. This means positive
   velocity is displayed ABOVE the baseline (toward the transducer).

2. **ReferencePixelY0 can be outside the region**: GE sometimes writes refy
   values that are negative or above the region top. This is intentional —
   it represents a shifted baseline for measuring high-velocity flow.

3. **PhysicalUnitsY = 7 (cm/sec)**: GE correctly uses cm/sec per the DICOM
   standard, but the velocity sign convention differs.

4. **Private tags**: GE uses groups 6003 (GEMS_Ultrasound_ImageGroup) and
   7FE1 (GEMS_Ultrasound_MovieGroup) for additional calibration data.

5. **Image format**: GE Vivid exports single-frame JPEG screen captures
   with burned-in annotations (ImageType: DERIVED PRIMARY).

Key findings from GE Vivid E95 analysis:
- ReferencePixelPhysicalValueY is ALWAYS 0.0 (confirms refy = baseline)
- ReferencePixelY0 varies wildly: -2 to 319, sometimes inside region, sometimes above
- PhysicalDeltaY ranges 0.065-0.77 cm/sec/px (plausible when using inverted formula)
- Sweep time (deltaX) ranges 0.8-5.5 seconds
"""

from __future__ import annotations

import logging

from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.vendor_profiles.base import (
    BaselineResult,
    TimeSpanResult,
    VelocitySpanResult,
    Vendor,
    VendorProfile,
)

logger = logging.getLogger(__name__)

# DICOM PS3.3 C.8.5.5.1.15 Physical Units (correct per standard)
_PHYS_UNIT_CM = 3
_PHYS_UNIT_SEC = 4
_PHYS_UNIT_CM_PER_SEC = 7

# GE Vivid private tag groups
_GEMS_IMAGE_GROUP = 0x6003
_GEMS_MOVIE_GROUP = 0x7FE1


class GEProfile(VendorProfile):
    """GE Vingmed Ultrasound vendor profile.

    Encapsulates GE-specific calibration logic derived from analysis of
    GE Vivid E95 DICOM exports (118 files, all modes).
    """

    @property
    def vendor(self) -> Vendor:
        return Vendor.GE

    @property
    def vendor_keywords(self) -> list[str]:
        return ["ge", "vingmed", "vivid"]

    def matches_dataset(self, dataset: Dataset) -> bool:
        """Match by Manufacturer or private creator strings."""
        # Standard manufacturer check
        if super().matches_dataset(dataset):
            return True
        # Check for GE private tags
        for group in (_GEMS_IMAGE_GROUP, _GEMS_MOVIE_GROUP):
            tag = (group, 0x0010)
            try:
                creator = str(dataset[tag].value).upper()
                if "GEMS" in creator:
                    return True
            except (KeyError, AttributeError):
                continue
        return False

    # ── Baseline computation ───────────────────────────────────────────

    def compute_baseline(
        self,
        region: Dataset,
        frame_height: int,
        frame_pixels: object | None = None,
    ) -> BaselineResult:
        """Compute baseline using GE's inverted velocity convention.

        GE convention: positive velocity = upward (toward transducer).
        The baseline (zero velocity) is at ReferencePixelY0, in REGION-RELATIVE
        coordinates (same as Philips/Samsung/standard DICOM).

        Evidence (visual check on GE Vivid E95 exports):
        - Q8BA8BPK  min_y=212 refY=90  -> 302 vs visual line 301.5
        - Q8BATAG2  min_y=353 refY=187 -> 540 vs visual line 541.0
        - Q8BA7UHE  min_y=213 refY=178 -> 391 vs visual line 391.0

        The formula: v(y) = (RefY_abs - y) × deltaY,  RefY_abs = min_y + refY.
        """
        ref_y = region.get("ReferencePixelY0")
        if ref_y is None:
            return BaselineResult(
                baseline_y=frame_height / 2.0,
                confidence=0.0,
                source="GE: ReferencePixelY0 missing, using center",
                velocity_sign=-1,
            )

        ref_y_f = float(ref_y)
        min_y = float(region.get("RegionLocationMinY0", 0) or 0)
        max_y = float(region.get("RegionLocationMaxY1", frame_height) or frame_height)

        # ReferencePixelY0 is region-relative (DICOM C.8.5.5.1.4.2):
        # convert to absolute image coordinates.
        baseline_y = min_y + ref_y_f

        # Baseline is region-relative: absolute Y in the image.
        baseline_y = min_y + ref_y_f

        # Check if ReferencePixelPhysicalValueY = 0 (confirms refy = baseline)
        phys_val_y = region.get("ReferencePixelPhysicalValueY")
        has_zero_phys_val = phys_val_y is not None and float(phys_val_y) == 0.0

        # Compute confidence based on baseline position
        if has_zero_phys_val:
            # High confidence: physical value confirms baseline
            confidence = 0.95
            source = "GE: ReferencePixelY0 with PhysicalValueY=0 (confirmed baseline)"
        elif min_y <= baseline_y <= max_y:
            # Medium confidence: baseline inside region
            confidence = 0.8
            source = "GE: ReferencePixelY0 inside region"
        elif 0 <= baseline_y < min_y:
            # Low-medium confidence: baseline above region but within image
            confidence = 0.6
            source = "GE: ReferencePixelY0 above region (shifted baseline)"
        else:
            # Low confidence: baseline outside image bounds
            confidence = 0.4
            source = "GE: ReferencePixelY0 outside image bounds (extreme shift)"

        # GE uses inverted velocity convention (positive = up)
        velocity_sign = -1

        logger.debug(
            "GE baseline: refy=%s, region=[%s,%s], physValY=%s, conf=%.2f, abs=%.1f",
            ref_y_f,
            min_y,
            max_y,
            phys_val_y,
            confidence,
            baseline_y,
        )

        return BaselineResult(
            baseline_y=baseline_y,
            confidence=confidence,
            source=source,
            velocity_sign=velocity_sign,
        )

    # ── Velocity calibration ───────────────────────────────────────────

    def compute_velocity_span(
        self,
        region: Dataset,
        region_height_px: float,
    ) -> VelocitySpanResult | None:
        """Compute velocity span for GE Doppler.

        GE convention:
        - PhysicalUnitsY = 7 (cm/sec per DICOM standard)
        - PhysicalDeltaY is POSITIVE
        - Velocity increases UPWARD (inverted from standard DICOM)
        - Formula: v = (RefY - y) × deltaY

        Full velocity span = region_height × |deltaY|
        """
        delta_y = region.get("PhysicalDeltaY")
        units_y = region.get("PhysicalUnitsYDirection")

        if delta_y is None or units_y is None:
            return None

        delta_y_f = abs(float(delta_y))
        units_y_i = int(units_y)

        # GE uses units=7 (cm/sec) — correct per DICOM standard
        if units_y_i != _PHYS_UNIT_CM_PER_SEC:
            logger.debug("GE: Unexpected velocity units: %s", units_y_i)
            return None

        if delta_y_f <= 0.0 or region_height_px <= 0.0:
            return None

        span = region_height_px * delta_y_f
        per_pixel = delta_y_f

        # Validate plausibility: 0.1-10 m/s = 10-1000 cm/s full scale
        if span < 10.0 or span > 1000.0:
            logger.warning("GE: Implausible velocity span: %.1f cm/s", span)
            return None

        return VelocitySpanResult(
            span_cm_s=span,
            per_pixel_cm_s=per_pixel,
            confidence=0.9,
            source=f"GE: {span:.1f} cm/s full scale (deltaY={delta_y_f:.4f} cm/s/px)",
        )

    # ── Time calibration ───────────────────────────────────────────────

    def compute_time_span(
        self,
        region: Dataset,
        region_width_px: float,
        frame_pixels: object | None = None,
    ) -> TimeSpanResult | None:
        """Compute time span for GE Doppler or M-mode.

        GE convention:
        - PhysicalUnitsX = 4 (seconds per DICOM standard)
        - PhysicalDeltaX is POSITIVE
        - Time increases LEFTWARD (sweep from right to left)
        - Formula: time = (RefX - x) × deltaX (inverted)

        Full time span = region_width × deltaX
        """
        delta_x = region.get("PhysicalDeltaX")
        units_x = region.get("PhysicalUnitsXDirection")

        if delta_x is None or units_x is None:
            return None

        delta_x_f = abs(float(delta_x))
        units_x_i = int(units_x)

        # GE uses units=4 (seconds) — correct per DICOM standard
        if units_x_i != _PHYS_UNIT_SEC:
            logger.debug("GE: Unexpected time units: %s", units_x_i)
            return None

        if delta_x_f <= 0.0 or region_width_px <= 0.0:
            return None

        span_s = region_width_px * delta_x_f
        span_ms = span_s * 1000.0
        per_pixel_ms = delta_x_f * 1000.0

        # Validate plausibility: 0.1-30 seconds sweep
        if span_ms < 100.0 or span_ms > 30000.0:
            logger.warning("GE: Implausible time span: %.1f ms", span_ms)
            return None

        return TimeSpanResult(
            span_ms=span_ms,
            per_pixel_ms=per_pixel_ms,
            confidence=0.9,
            source=f"GE: {span_ms:.0f} ms sweep (deltaX={delta_x_f:.6f} s/px)",
        )

    # ── Reference pixel handling ───────────────────────────────────────

    def get_reference_pixel(
        self,
        region: Dataset,
    ) -> tuple[float, float] | None:
        """Extract reference pixel in absolute image coordinates.

        GE uses absolute coordinates (not region-relative).
        The reference pixel can be outside the region bounds.
        """
        return super().get_reference_pixel(region)

    # ── Private tag helpers ────────────────────────────────────────────

    def get_gems_image_group(self, dataset: Dataset) -> Dataset | None:
        """Extract GE GEMS Image Group (6003) sequence.

        Returns:
            The first item of the GEMS Image Group sequence, or None.
        """
        try:
            seq = dataset[(_GEMS_IMAGE_GROUP, 0x1010)].value
            if seq and len(seq) > 0:
                return seq[0]
        except (KeyError, AttributeError):
            pass
        return None

    def get_gems_movie_group(self, dataset: Dataset) -> Dataset | None:
        """Extract GE GEMS Movie Group (7FE1) sequence.

        Returns:
            The first item of the GEMS Movie Group sequence, or None.
        """
        try:
            seq = dataset[(_GEMS_MOVIE_GROUP, 0x1001)].value
            if seq and len(seq) > 0:
                return seq[0]
        except (KeyError, AttributeError):
            pass
        return None

    def get_scan_preset(self, dataset: Dataset) -> str | None:
        """Extract scan preset from GEMS Movie Group.

        Returns:
            Preset name (e.g., "Cardiac4", "fpa_80_2.5_M4S"), or None.
        """
        movie = self.get_gems_movie_group(dataset)
        if movie is None:
            return None
        # Search for label items (7FE1,1057) containing preset info
        for item_seq_key in [(0x7FE1, 0x1008)]:
            try:
                items = movie[item_seq_key].value
                for item in items:
                    try:
                        label = str(item[(0x7FE1, 0x1057)].value)
                        if label and label not in ("", "View", "IDUNN", "f1p0"):
                            return label
                    except (KeyError, AttributeError):
                        continue
            except (KeyError, AttributeError):
                continue
        return None

    def get_depth_cm(self, dataset: Dataset) -> float | None:
        """Extract imaging depth from GEMS Movie Group.

        Returns:
            Depth in centimeters, or None.
        """
        movie = self.get_gems_movie_group(dataset)
        if movie is None:
            return None
        try:
            items = movie[(0x7FE1, 0x1008)].value
            for item in items:
                try:
                    # Look for depth-related values (large FD values ~10-30)
                    fd_val = float(item[(0x7FE1, 0x1052)].value)
                    if 5.0 <= fd_val <= 40.0:
                        return fd_val
                except (KeyError, AttributeError, TypeError, ValueError):
                    continue
        except (KeyError, AttributeError):
            pass
        return None
