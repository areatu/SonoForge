"""Abstract base class for vendor-specific DICOM ultrasound profiles.

Vendor profiles encapsulate the quirks each manufacturer introduces in how
they encode Doppler calibration, M-mode timing, and reference pixel semantics
within the DICOM Sequence of Ultrasound Regions (0018,6011).

The goal: given a region dataset, the profile returns vendor-corrected
calibration parameters (baseline position, velocity span, time span)
without the caller needing to know which vendor produced the file.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from enum import Enum

from pydicom.dataset import Dataset

logger = logging.getLogger(__name__)


class Vendor(str, Enum):
    """Known ultrasound scanner manufacturers."""

    GE = "GE Vingmed Ultrasound"
    PHILIPS = "Philips"
    SAMSUNG = "Samsung"
    SIEMENS = "Siemens"
    TOSHIBA = "Toshiba"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class BaselineResult:
    """Result of vendor-specific baseline computation.

    Attributes:
        baseline_y: Absolute Y coordinate of the baseline in image rows.
        confidence: 0.0-1.0 confidence in the baseline detection.
        source: Human-readable description of how baseline was determined.
        velocity_sign: +1 if positive velocity = downward (standard DICOM),
                       -1 if positive velocity = upward (GE convention).
    """

    baseline_y: float
    confidence: float
    source: str
    velocity_sign: int = 1


@dataclass(frozen=True)
class VelocitySpanResult:
    """Result of vendor-specific velocity span computation.

    Attributes:
        span_cm_s: Full velocity span in cm/s (always positive).
        per_pixel_cm_s: Velocity increment per pixel in cm/s.
        confidence: 0.0-1.0 confidence in the velocity scale.
        source: Human-readable description.
    """

    span_cm_s: float
    per_pixel_cm_s: float
    confidence: float
    source: str


@dataclass(frozen=True)
class TimeSpanResult:
    """Result of vendor-specific time span computation.

    Attributes:
        span_ms: Full time span in milliseconds (always positive).
        per_pixel_ms: Time increment per pixel in ms.
        confidence: 0.0-1.0 confidence in the time scale.
        source: Human-readable description.
    """

    span_ms: float
    per_pixel_ms: float
    confidence: float
    source: str


class VendorProfile(abc.ABC):
    """Abstract base class for vendor-specific DICOM ultrasound profiles.

    Subclasses must implement the abstract methods to provide vendor-specific
    calibration logic for Doppler, M-mode, and 2D regions.
    """

    @property
    @abc.abstractmethod
    def vendor(self) -> Vendor:
        """Return the vendor this profile handles."""

    @property
    @abc.abstractmethod
    def vendor_keywords(self) -> list[str]:
        """Return keywords for fuzzy vendor matching (e.g., ["ge", "vingmed"])."""

    # ── Vendor identification ──────────────────────────────────────────

    def matches_dataset(self, dataset: Dataset) -> bool:
        """Return True if this profile should handle the given dataset.

        Default implementation checks Manufacturer tag against vendor_keywords.
        Subclasses may override for more sophisticated matching (e.g., private
        creator strings).
        """
        manufacturer = str(dataset.get("Manufacturer", "")).lower()
        model = str(dataset.get("ManufacturerModelName", "")).lower()
        return any(kw in manufacturer or kw in model for kw in self.vendor_keywords)

    # ── Baseline computation ───────────────────────────────────────────

    @abc.abstractmethod
    def compute_baseline(
        self,
        region: Dataset,
        frame_height: int,
        frame_pixels: object | None = None,
    ) -> BaselineResult:
        """Compute the baseline (zero-velocity line) position for a spectral Doppler region.

        Args:
            region: The SequenceOfUltrasoundRegions item.
            frame_height: Height of the full image in pixels.
            frame_pixels: Optional numpy array of the image pixels for
                         visual baseline detection.

        Returns:
            BaselineResult with absolute Y coordinate and confidence.
        """

    # ── Velocity calibration ───────────────────────────────────────────

    @abc.abstractmethod
    def compute_velocity_span(
        self,
        region: Dataset,
        region_height_px: float,
    ) -> VelocitySpanResult | None:
        """Compute the full velocity span for a spectral Doppler region.

        Args:
            region: The SequenceOfUltrasoundRegions item.
            region_height_px: Height of the region in pixels.

        Returns:
            VelocitySpanResult or None if velocity calibration is not available.
        """

    # ── Time calibration ───────────────────────────────────────────────

    @abc.abstractmethod
    def compute_time_span(
        self,
        region: Dataset,
        region_width_px: float,
        frame_pixels: object | None = None,
    ) -> TimeSpanResult | None:
        """Compute the full time span for a spectral Doppler or M-mode region.

        Args:
            region: The SequenceOfUltrasoundRegions item.
            region_width_px: Width of the region in pixels.
            frame_pixels: Optional numpy array of the image pixels, enabling
                visual (tick-scale) time calibration when DICOM tags are absent.

        Returns:
            TimeSpanResult or None if time calibration is not available.
        """

    # ── Reference pixel handling ───────────────────────────────────────

    def get_reference_pixel(
        self,
        region: Dataset,
    ) -> tuple[float, float] | None:
        """Extract the reference pixel coordinates from the region.

        Returns:
            (x, y) tuple in image coordinates, or None if not available.

        Note:
            The interpretation of ReferencePixel varies by vendor:
            - GE: Absolute image coordinates, can be outside region.
            - Philips: Absolute image coordinates, usually inside region.
            - Samsung: Sometimes region-relative, sometimes absolute.
        """
        ref_x = region.get("ReferencePixelX0")
        ref_y = region.get("ReferencePixelY0")
        if ref_x is None or ref_y is None:
            return None
        return float(ref_x), float(ref_y)

    def get_reference_pixel_physical_values(
        self,
        region: Dataset,
    ) -> tuple[float, float] | None:
        """Extract the physical values at the reference pixel.

        Returns:
            (value_x, value_y) tuple, or None if not available.

        Note:
            - value_x: Time (seconds) at the reference pixel for Doppler/M-mode.
            - value_y: Velocity (cm/s) at the reference pixel (usually 0.0 = baseline).
        """
        val_x = region.get("ReferencePixelPhysicalValueX")
        val_y = region.get("ReferencePixelPhysicalValueY")
        if val_x is None or val_y is None:
            return None
        return float(val_x), float(val_y)

    # ── Private tag helpers ────────────────────────────────────────────

    def get_private_value(
        self,
        dataset: Dataset,
        group: int,
        element: int,
    ) -> object | None:
        """Safely extract a private tag value."""
        tag = (group, element)
        try:
            return dataset[tag].value
        except (KeyError, AttributeError):
            return None

    # ── Representation ─────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} vendor={self.vendor.value}>"
