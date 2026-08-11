"""Samsung vendor profile for DICOM ultrasound calibration.

Samsung RS85 and similar models have quirks where Doppler regions
may be mis-tagged with SF=1 (2D) instead of SF=3 (Spectral Doppler).
"""

from __future__ import annotations

import logging

import numpy as np
from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.samsung_calibration_builder import load_calibration
from echo_personal_tool.infrastructure.samsung_tick_detector import detect_ticks
from echo_personal_tool.infrastructure.vendor_profiles.base import (
    BaselineResult,
    TimeSpanResult,
    VelocitySpanResult,
    Vendor,
    VendorProfile,
)

logger = logging.getLogger(__name__)


class SamsungProfile(VendorProfile):
    """Vendor profile for Samsung Medison Ultrasound.

    Samsung quirks:
    - Doppler regions sometimes mis-tagged as SF=1 (2D)
    - ReferencePixelY0 may be relative to region, not absolute
    - PhysicalUnitsY may vary by model/generation
    - Private groups: 0009, 0019
    """

    @property
    def vendor(self) -> Vendor:
        return Vendor.SAMSUNG

    @property
    def vendor_keywords(self) -> list[str]:
        return ["samsung", "medison"]

    @property
    def description(self) -> str:
        return "Samsung Medison Ultrasound (may mis-tag Doppler as 2D)"

    def matches_dataset(self, dataset: Dataset) -> bool:
        """Check if this dataset is from Samsung."""
        manufacturer = str(dataset.get("Manufacturer", "")).lower()
        model = str(dataset.get("ManufacturerModelName", "")).lower()
        return "samsung" in manufacturer or "medison" in manufacturer or "samsung" in model

    def compute_baseline(
        self,
        region: Dataset,
        frame_height: int,
        frame_pixels: np.ndarray | None = None,
    ) -> BaselineResult:
        """Compute baseline using Samsung convention.

        Samsung may use region-relative coordinates.
        """
        ref_y = region.get("ReferencePixelY0")
        if ref_y is None:
            return BaselineResult(
                baseline_y=frame_height / 2.0,
                confidence=0.0,
                source="Samsung: ReferencePixelY0 missing",
                velocity_sign=-1,
            )

        try:
            ref_y_f = float(ref_y)
        except (TypeError, ValueError):
            return BaselineResult(
                baseline_y=frame_height / 2.0,
                confidence=0.0,
                source="Samsung: ReferencePixelY0 invalid",
                velocity_sign=-1,
            )

        min_y = float(region.get("RegionLocationMinY0", 0) or 0)
        max_y = float(region.get("RegionLocationMaxY1", frame_height) or frame_height)

        # Samsung: baseline may be relative to region origin
        baseline_y = min_y + ref_y_f

        # Confidence: lower until we validate with real data
        if min_y <= baseline_y <= max_y:
            confidence = 0.6
            source = "Samsung: ReferencePixelY0 (within region, needs validation)"
        else:
            confidence = 0.3
            source = "Samsung: ReferencePixelY0 (outside region, needs validation)"

        return BaselineResult(
            baseline_y=baseline_y,
            confidence=confidence,
            source=source,
            velocity_sign=-1,  # Assume GE-like convention until validated
        )

    def compute_velocity_span(
        self,
        region: Dataset,
        region_height_px: float,
    ) -> VelocitySpanResult | None:
        """Compute velocity span.

        Samsung may use different unit conventions depending on model.
        """
        delta_y = region.get("PhysicalDeltaY")
        units_y = region.get("PhysicalUnitsYDirection")

        if delta_y is None or units_y is None:
            return None

        try:
            delta_y_f = float(delta_y)
            units_y_i = int(units_y)
        except (TypeError, ValueError):
            return None

        # Check for cm/sec (units_y=7)
        if units_y_i != 7:
            return None

        per_pixel = abs(delta_y_f)
        span = per_pixel * region_height_px

        return VelocitySpanResult(
            span_cm_s=span,
            per_pixel_cm_s=per_pixel,
            confidence=0.5,  # Lower confidence until validated
            source=f"Samsung: PhysicalDeltaY={delta_y_f}, units=7 (cm/sec), needs validation",
        )

    def __init__(self) -> None:
        """Load tick calibration on profile creation."""
        self._tick_calibration = load_calibration()

    def compute_time_span(
        self,
        region: Dataset,
        region_width_px: float,
        frame_pixels: np.ndarray | None = None,
    ) -> TimeSpanResult | None:
        """Compute time span from DICOM tags, falling back to tick detection.

        Samsung RS85 PW/CW frames often carry no usable time tags (only a
        mis-tagged 2D region). When that happens and ``frame_pixels`` is
        available, the time-axis ruler is detected visually and the sweep
        frequency is derived from the linear calibration
        (``frequency_hz = k_constant * spacing_px``).
        """
        delta_x = region.get("PhysicalDeltaX")
        units_x = region.get("PhysicalUnitsXDirection")

        if delta_x is not None and units_x is not None:
            try:
                delta_x_f = float(delta_x)
                units_x_i = int(units_x)
            except (TypeError, ValueError):
                delta_x_f = None
                units_x_i = None

            # Check for seconds (units_x=4)
            if units_x_i == 4 and delta_x_f is not None:
                per_pixel = abs(delta_x_f) * 1000.0  # Convert to ms
                span = per_pixel * region_width_px
                return TimeSpanResult(
                    span_ms=span,
                    per_pixel_ms=per_pixel,
                    confidence=0.5,  # Lower confidence until validated
                    source=f"Samsung: PhysicalDeltaX={delta_x_f}, units=4 (seconds), needs validation",
                )

        # Fallback: visual tick detection on the frame pixels
        if frame_pixels is None or self._tick_calibration is None:
            return None

        result = detect_ticks(np.asarray(frame_pixels))
        if result.confidence < 0.3 or result.spacing_px <= 0.0:
            logger.debug(
                "Samsung: tick detection failed on frame "
                "(conf=%.2f, spacing=%.2f)",
                result.confidence,
                result.spacing_px,
            )
            return None

        frequency_hz = self._tick_calibration.k_constant * result.spacing_px
        # One ruler tick spans TICK_SECONDS_PER_PX s per pixel at the detected
        # sweep frequency; equivalently per_pixel = 1/frequency seconds.
        per_pixel_ms = 1000.0 / frequency_hz
        span = per_pixel_ms * region_width_px

        logger.info(
            "Samsung: tick calibration, spacing=%.2f px, freq=%.1f Hz, "
            "per_pixel=%.3f ms, span=%.1f ms",
            result.spacing_px,
            frequency_hz,
            per_pixel_ms,
            span,
        )
        return TimeSpanResult(
            span_ms=span,
            per_pixel_ms=per_pixel_ms,
            confidence=result.confidence,
            source=(
                f"Samsung: tick detection, K={self._tick_calibration.k_constant:.2f}, "
                f"freq={frequency_hz:.1f} Hz"
            ),
        )
