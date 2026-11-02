"""Classify SequenceOfUltrasoundRegions items into acquisition mode labels.

The loader dialog shows "2D / Color / M / PW / CW" chips and badges, so the
region geometry tags must be reduced to those labels.  Region items arrive as
DICOM JSON (hex-tagged dicts) from QIDO-RS ``includefield`` answers; the
mapping follows the same semantics as
:mod:`echo_personal_tool.domain.services.ultrasound_region_physics`, including
the Samsung RS85 quirk that mis-tags spectral/tissue Doppler as SF=1 regions.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from echo_personal_tool.domain.services.ultrasound_region_physics import (
    COLOR_FLOW_DATA_TYPE,
    DOPPLER_DATA_TYPES,
    SPATIAL_2D,
    SPATIAL_M_MODE,
    SPATIAL_SPECTRAL,
)

MODE_2D = "2D"
MODE_COLOR = "Color"
MODE_M = "M"
MODE_PW = "PW"
MODE_CW = "CW"

#: Display order for mode chips, badges and filter labels (DICOM terms).
MODE_ORDER = (MODE_2D, MODE_COLOR, MODE_M, MODE_PW, MODE_CW)

TAG_REGION_SPATIAL_FORMAT = "00186012"
TAG_REGION_DATA_TYPE = "00186014"

_CW_DATA_TYPE = 4


def _int_field(item: Any, tag: str, keyword: str) -> int:
    """Read one region item field as int.

    Accepts DICOM JSON items (``{"00186012": {"Value": [1], "vr": "US"}}``)
    and pydicom-like objects exposing keyword access.
    """
    raw = None
    if hasattr(item, "get"):
        raw = item.get(tag)
        if raw is None:
            raw = item.get(keyword)
    if isinstance(raw, dict):
        values = raw.get("Value") or []
        raw = values[0] if values else None
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def mode_for_region(spatial_format: int, data_type: int) -> str | None:
    """Map one region's (RegionSpatialFormat, RegionDataType) to a mode label.

    Returns ``None`` for regions that carry no useful mode information.
    """
    if spatial_format == SPATIAL_M_MODE:
        return MODE_M
    if spatial_format == SPATIAL_SPECTRAL or data_type in DOPPLER_DATA_TYPES:
        # Includes the Samsung mis-tag (SF=1 with Doppler data types).
        return MODE_CW if data_type == _CW_DATA_TYPE else MODE_PW
    if spatial_format == SPATIAL_2D:
        if data_type == COLOR_FLOW_DATA_TYPE:
            return MODE_COLOR
        return MODE_2D
    return None


def classify_region_items(items: Iterable[Any] | None) -> frozenset[str]:
    """Mode labels for a whole SequenceOfUltrasoundRegions value list."""
    modes: set[str] = set()
    for item in items or ():
        mode = mode_for_region(
            _int_field(item, TAG_REGION_SPATIAL_FORMAT, "RegionSpatialFormat"),
            _int_field(item, TAG_REGION_DATA_TYPE, "RegionDataType"),
        )
        if mode is not None:
            modes.add(mode)
    return frozenset(modes)
