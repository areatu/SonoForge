"""Compatibility re-exports for the legacy ``pixel_utils`` path.

Pure array normalization lives in :mod:`echo_personal_tool.imaging.pixels`
(QH-4b) and the display/window-level helpers in
:mod:`echo_personal_tool.imaging.display` (S2-03, #307); this module only
keeps the legacy import path so workers, readers, benches and older tests
stay unchanged.  New code should import from ``imaging`` directly.
"""

from __future__ import annotations

from echo_personal_tool.imaging.display import (
    COLOR_CHANNEL_SPREAD,
    COLOR_PIXEL_SHARE,
    apply_window_level_rgb,
    apply_wl_lut,
    color_pixel_share,
    compute_display_levels,
    decolor_frame,
    despeckle_frame,
    dr_percentiles_from_slider,
    grayscale_source_array,
    is_color_frame,
    is_effective_grayscale,
    percentile_range,
    reference_wl_display_uint8,
    to_display_rgb,
    to_grayscale_array,
)
from echo_personal_tool.imaging.pixels import (
    ChannelOrder,
    bgr_to_rgb,
    to_bgr_uint8,
    to_grayscale_uint8,
)

#: Legacy private name used by older viewer code paths and kept importable.
_grayscale_source_array = grayscale_source_array

__all__ = [
    "COLOR_CHANNEL_SPREAD",
    "COLOR_PIXEL_SHARE",
    "ChannelOrder",
    "apply_wl_lut",
    "apply_window_level_rgb",
    "bgr_to_rgb",
    "color_pixel_share",
    "compute_display_levels",
    "decolor_frame",
    "despeckle_frame",
    "dr_percentiles_from_slider",
    "grayscale_source_array",
    "is_color_frame",
    "is_effective_grayscale",
    "percentile_range",
    "reference_wl_display_uint8",
    "to_bgr_uint8",
    "to_display_rgb",
    "to_grayscale_array",
    "to_grayscale_uint8",
]
