"""Empirical per-vendor PHI mask profiles.

The table below is measured, not guessed: for every class of the 245-file
corpus the top row of the first ultrasound panel (``min RegionLocationMinY0``)
was compared with the rows that actually carry burned-in text.  Fractions are
of the frame height and are keyed by ``(vendor, height, width)`` — a single
per-vendor value does not fit even inside one vendor (Samsung needs 0.12 for
its B-mode classes, 0.14 for strain with no region sequence, and 0.0 for the
strain analysis screen where the top of the frame is UI, not a header).

Rules encoded here:

* Profiles are deliberately generous; when ``SequenceOfUltrasoundRegions`` is
  present the band is cut back to the panel's first row, so an overshoot costs
  nothing.
* Classes without region geometry (22 Samsung strain files) cannot be clamped,
  so their profile is already the exact measured header extent.
* ``preserve_ui`` classes must stay at zero: a text detector would otherwise
  propose masking "3 Point Contour" and friends.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from echo_personal_tool.domain.services.frame_panel_parser import parse_panels_from_dataset
from echo_personal_tool.domain.services.phi_mask import MaskSpec
from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor
from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor

logger = logging.getLogger(__name__)

# (vendor, frame height, frame width) -> profile.
_VENDOR_SIZE_PROFILES: dict[tuple[Vendor, int, int], MaskSpec] = {
    # Samsung RS85-RUS, B-mode/Doppler cines: text rows ~0-55, panel starts at 90.
    (Vendor.SAMSUNG, 800, 1276): MaskSpec(top=0.12),
    (Vendor.SAMSUNG, 884, 1180): MaskSpec(top=0.12),
    # Small cine: the header is proportionally much taller (panel at 90 of 480).
    (Vendor.SAMSUNG, 480, 640): MaskSpec(top=0.12),
    # Strain, 22 files with no SequenceOfUltrasoundRegions: info bar to y≈140.
    (Vendor.SAMSUNG, 1080, 1920): MaskSpec(top=0.14),
    # Strain analysis screen: the top is UI ("3 Point Contour"), never a header.
    (Vendor.SAMSUNG, 668, 1280): MaskSpec(top=0.0, preserve_ui=True),
    # Philips EPIQ: nothing but preset/probe/Hz above the sector.
    (Vendor.PHILIPS, 768, 1024): MaskSpec(top=0.0),
    (Vendor.PHILIPS, 600, 800): MaskSpec(top=0.0),
    # GE Vivid E95 (corpus already de-identified): depth ticks and "Soft" only.
    (Vendor.GE, 708, 1016): MaskSpec(top=0.0),
}

# Fallback for a known vendor at an unmeasured resolution: stay with what that
# vendor does in general rather than jumping to the global default.
_VENDOR_DEFAULTS: dict[Vendor, MaskSpec] = {
    Vendor.SAMSUNG: MaskSpec(top=0.12),
    Vendor.PHILIPS: MaskSpec(top=0.0),
    Vendor.GE: MaskSpec(top=0.0),
}

# Unknown vendor (or a plain video/photo): be conservative, the usual header
# band of an exported clip sits within the upper tenth of the frame.
_UNKNOWN_MASK_SPEC = MaskSpec(top=0.10)


def resolve_mask_spec(vendor: Vendor, height: int, width: int) -> MaskSpec:
    """Return the mask profile for a given vendor and frame size."""
    profile = _VENDOR_SIZE_PROFILES.get((vendor, int(height), int(width)))
    if profile is not None:
        return profile
    fallback = _VENDOR_DEFAULTS.get(vendor)
    if fallback is not None:
        return fallback
    return _UNKNOWN_MASK_SPEC


@dataclass(frozen=True)
class PhiMaskContext:
    """Everything the mask needs to know about one media file."""

    vendor: Vendor = Vendor.UNKNOWN
    #: First row of the topmost ultrasound panel, ``None`` when the file has no
    #: region geometry or is not a DICOM at all.
    panel_top: int | None = None
    #: Raw ``BurnedInAnnotation`` (0028,0301) when present, else ``None``.
    burned_in: str | None = None

    @property
    def is_dicom(self) -> bool:
        return self.burned_in is not None or self.panel_top is not None


_CONTEXT_CACHE: dict[str, PhiMaskContext] = {}
_CACHE_LIMIT = 256


def clear_phi_mask_context_cache() -> None:
    """Drop cached file headers (tests, and after a study is re-exported)."""
    _CONTEXT_CACHE.clear()


def phi_mask_context(path: Path | str | None) -> PhiMaskContext:
    """Read and cache the mask-relevant header of ``path``.

    Only the header is parsed (``stop_before_pixels``).  Non-DICOM files,
    missing files and unreadable headers all yield the unknown context, which
    means the conservative default profile and no panel clamping — never an
    exception reaching the render loop.
    """
    if path is None:
        return PhiMaskContext()

    key = str(path)
    cached = _CONTEXT_CACHE.get(key)
    if cached is not None:
        return cached

    context = _read_context(Path(key))
    if len(_CONTEXT_CACHE) >= _CACHE_LIMIT:
        _CONTEXT_CACHE.pop(next(iter(_CONTEXT_CACHE)), None)
    _CONTEXT_CACHE[key] = context
    return context


def _read_context(path: Path) -> PhiMaskContext:
    try:
        import pydicom
    except ImportError:  # pragma: no cover - pydicom is a hard dependency
        return PhiMaskContext()

    if path.suffix.lower() not in {".dcm", ".dicom"}:
        return PhiMaskContext()
    if not path.is_file():
        return PhiMaskContext()

    try:
        dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception:  # noqa: BLE001 - a broken header must not break rendering
        logger.debug("PHI mask: cannot read DICOM header of %s", path, exc_info=True)
        return PhiMaskContext()

    vendor = Vendor.UNKNOWN
    panel_top: int | None = None
    burned_in: str | None = None

    try:
        vendor = detect_vendor(dataset)
    except Exception:  # noqa: BLE001
        vendor = Vendor.UNKNOWN

    try:
        layout = parse_panels_from_dataset(dataset)
        if layout is not None and layout.panels:
            tops = [int(panel.bounds.y0) for panel in layout.panels]
            if tops:
                panel_top = max(min(tops), 0)
    except Exception:  # noqa: BLE001
        panel_top = None

    try:
        raw = dataset.get("BurnedInAnnotation")
        if raw is not None:
            burned_in = str(raw).strip().upper() or None
    except Exception:  # noqa: BLE001
        burned_in = None

    return PhiMaskContext(vendor=vendor, panel_top=panel_top, burned_in=burned_in)


def masks_disabled_by_header(context: PhiMaskContext) -> bool:
    """True when the file explicitly declares that no text is burned in.

    ``BurnedInAnnotation = NO`` is not trustworthy in general (the GE corpus is
    clean yet every Samsung file declares it), but when a file *does* carry the
    tag and says NO, masking would erase part of the sector for nothing.
    """
    return context.burned_in == "NO"
