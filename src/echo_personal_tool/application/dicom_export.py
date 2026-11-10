"""Qt-free application API for DICOM de-identification policy.

Presentation consumes the application-owned export options and mask-context
protocol below; the concrete DICOM cleaning and header adapters remain in
infrastructure (#477).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from echo_personal_tool.domain.services.phi_mask import MaskSpec
from echo_personal_tool.infrastructure import phi_mask_profiles as _mask_profiles


class VendorId(Protocol):
    """Read-only vendor identifier used by the PHI mask profile table."""

    @property
    def value(self) -> str: ...


class PhiMaskContext(Protocol):
    """Application-facing PHI mask header context for one media file."""

    @property
    def vendor(self) -> VendorId: ...

    @property
    def panel_top(self) -> int | None: ...

    @property
    def burned_in(self) -> str | None: ...

    @property
    def has_regions(self) -> bool: ...

    @property
    def is_dicom(self) -> bool: ...


@dataclass(frozen=True)
class DeidentificationOptions:
    """Application-owned de-identification choices for one instance export."""

    mask_pixels: bool = True
    clean_quasi_identifiers: bool = False
    clean_private_tags: bool = False
    pseudonym: str = "ANON"
    verify_pixels: bool = False


def clear_phi_mask_context_cache() -> None:
    """Drop cached file headers (tests, and after a study is re-exported)."""
    _mask_profiles.clear_phi_mask_context_cache()


def phi_mask_context(path: Path | str | None) -> PhiMaskContext:
    """Read and cache the mask-relevant header of ``path``."""
    return cast(PhiMaskContext, _mask_profiles.phi_mask_context(path))


def masks_disabled_by_header(context: PhiMaskContext) -> bool:
    """True when the file explicitly declares that no text is burned in."""
    return _mask_profiles.masks_disabled_by_header(cast(Any, context))


def profile_recommends_pixel_masking(
    context: PhiMaskContext,
    height: int,
    width: int,
) -> tuple[bool, str]:
    """Whether this file's class should have its pixels masked by default, and why."""
    return _mask_profiles.profile_recommends_pixel_masking(cast(Any, context), height, width)


def resolve_mask_spec(vendor: VendorId, height: int, width: int) -> MaskSpec:
    """Return the mask profile for a given vendor and frame size."""
    return _mask_profiles.resolve_mask_spec(cast(Any, vendor), height, width)


__all__ = [
    "DeidentificationOptions",
    "PhiMaskContext",
    "VendorId",
    "clear_phi_mask_context_cache",
    "masks_disabled_by_header",
    "phi_mask_context",
    "profile_recommends_pixel_masking",
    "resolve_mask_spec",
]
