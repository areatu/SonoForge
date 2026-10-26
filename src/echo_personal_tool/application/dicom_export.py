"""Qt-free application API for DICOM de-identification policy.

Presentation consumes the export options and measured mask-profile policy from
this module; the concrete DICOM cleaning and header adapters remain in
infrastructure.
"""

from __future__ import annotations

from echo_personal_tool.infrastructure import dicom_deidentifier as _deidentifier
from echo_personal_tool.infrastructure import phi_mask_profiles as _mask_profiles

DeidentificationOptions = _deidentifier.DeidentificationOptions
PhiMaskContext = _mask_profiles.PhiMaskContext
clear_phi_mask_context_cache = _mask_profiles.clear_phi_mask_context_cache
masks_disabled_by_header = _mask_profiles.masks_disabled_by_header
phi_mask_context = _mask_profiles.phi_mask_context
profile_recommends_pixel_masking = _mask_profiles.profile_recommends_pixel_masking
resolve_mask_spec = _mask_profiles.resolve_mask_spec

__all__ = [
    "DeidentificationOptions",
    "PhiMaskContext",
    "clear_phi_mask_context_cache",
    "masks_disabled_by_header",
    "phi_mask_context",
    "profile_recommends_pixel_masking",
    "resolve_mask_spec",
]
