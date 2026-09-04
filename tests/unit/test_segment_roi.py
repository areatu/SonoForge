"""Unit tests for DICOM vs cine segment ROI selection."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from echo_personal_tool.domain.services.segment_roi import (
    ECHONET_CROP_CENTER_SQUARE,
    echonet_crop_mode_for_media,
    resolve_cine_segment_roi_xyxy,
    resolve_dicom_segment_roi_xyxy,
    resolve_segment_roi_xyxy,
)


def _make_doppler_frame(
    height: int = 600,
    width: int = 800,
    tick_spacing_px: int = 30,
    spectral_mean: float = 25.0,
) -> np.ndarray:
    """Create a synthetic Doppler-like frame with tick marks in the bottom ruler area.

    Structure (top to bottom):
    - Top 55%: bright B-mode tissue (~140)
    - 55%-85%: dark spectral band (spectral_mean, near-black)
    - Bottom 15%: time ruler with periodic bright vertical ticks on dark background
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Bright B-mode tissue at top
    frame[: int(height * 0.55), :] = 140

    # Dark spectral band (above ruler)
    spectral_top = int(height * 0.55)
    spectral_bottom = int(height * 0.85)
    frame[spectral_top:spectral_bottom, :] = int(spectral_mean)

    # Time ruler region at bottom 15% with periodic bright vertical ticks
    ruler_top = int(height * 0.85)
    ruler_bottom = height
    ruler_height = ruler_bottom - ruler_top
    # Dark ruler background
    frame[ruler_top:ruler_bottom, :] = 20

    # Draw periodic bright vertical ticks (1-5 px wide, >4px apart)
    x = 20
    while x < width - 20:
        tick_w = np.random.randint(1, 6)
        frame[ruler_top:ruler_bottom, x : x + tick_w] = 200
        x += tick_spacing_px

    return frame


def _make_bmode_frame(
    height: int = 600,
    width: int = 800,
    top_mean: int = 140,
    bottom_mean: int = 40,
) -> np.ndarray:
    """Create a synthetic B-mode frame (no tick marks)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), :] = top_mean
    frame[int(height * 0.62) :, :] = bottom_mean
    return frame


def test_echonet_crop_mode_uses_center_square_for_cine_and_dicom() -> None:
    assert echonet_crop_mode_for_media("dicom") == ECHONET_CROP_CENTER_SQUARE
    assert echonet_crop_mode_for_media("mp4") == ECHONET_CROP_CENTER_SQUARE


def test_resolve_cine_roi_returns_none_for_bmode() -> None:
    """B-mode frames (no tick marks) should return None — no Doppler ROI."""
    frame = _make_bmode_frame(height=600, width=800)
    roi = resolve_cine_segment_roi_xyxy(frame)
    assert roi is None


def test_resolve_cine_roi_returns_none_for_plain_bmode_with_ui() -> None:
    """B-mode with UI elements but no periodic ticks → None."""
    height, width = 800, 1276
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), 350:910] = 130
    frame[: int(height * 0.62), 1220:1270] = 200
    frame[int(height * 0.62) :, :] = 40
    roi = resolve_cine_segment_roi_xyxy(frame)
    assert roi is None


def test_resolve_cine_roi_detects_doppler_frame() -> None:
    """Doppler frame with ticks → valid ROI."""
    frame = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    roi = resolve_cine_segment_roi_xyxy(frame)

    assert roi is not None
    x0, y0, x1, y1 = roi
    assert x0 >= 0.0
    assert y0 >= 0.0
    assert x1 <= 800.0
    assert y1 <= 600.0
    assert x1 > x0
    assert y1 > y0
    # ROI should cover most of the frame width (>= 90%)
    assert (x1 - x0) >= 800 * 0.9


def test_resolve_segment_roi_mp4_returns_none_for_bmode(tmp_path) -> None:
    """MP4 B-mode without DICOM tags → None (no Doppler content)."""
    frame = _make_bmode_frame(height=600, width=800)
    fake_path = tmp_path / "clip.mp4"

    roi = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        instance_path=fake_path,
    )
    assert roi is None


def test_resolve_segment_roi_mp4_returns_roi_for_doppler(tmp_path) -> None:
    """MP4 Doppler frame → valid ROI."""
    frame = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    fake_path = tmp_path / "clip.mp4"

    roi = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        instance_path=fake_path,
    )
    assert roi is not None


def test_frozen_cine_roi_reused_across_frames() -> None:
    """When frozen_cine_roi is provided, it is returned as-is for mp4 format."""
    frame_a = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    frame_b = _make_doppler_frame(height=600, width=800, tick_spacing_px=35)

    roi_a = resolve_cine_segment_roi_xyxy(frame_a)
    assert roi_a is not None

    roi_b_live = resolve_cine_segment_roi_xyxy(frame_b)
    assert roi_b_live is not None

    roi_b_frozen = resolve_segment_roi_xyxy(
        frame_b,
        media_format="mp4",
        frozen_cine_roi=roi_a,
    )
    assert roi_b_frozen == roi_a


def test_frozen_cine_roi_none_falls_back_to_heuristic() -> None:
    """When frozen_cine_roi is None, falls back to live detection."""
    frame = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    roi_live = resolve_cine_segment_roi_xyxy(frame)

    roi_result = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        frozen_cine_roi=None,
    )
    assert roi_result == roi_live


# ---------------------------------------------------------------------------
# DICOM panel priority (resolve_dicom_segment_roi_xyxy)
#
# The ROI returned here feeds ONNX LV segmentation, so on split-screen studies
# it MUST be the B-mode chamber panel and never the Doppler spectrum. These
# tests pin that ordering: the Doppler region is deliberately written FIRST in
# SequenceOfUltrasoundRegions, so a resolver that simply takes the first/any
# Doppler panel would fail them.
# ---------------------------------------------------------------------------

# DICOM PS3.3 C.8.5.5 RegionSpatialFormat / RegionDataType
_SPATIAL_2D = 1
_SPATIAL_SPECTRAL = 3
_DATA_TYPE_TISSUE = 1
_DATA_TYPE_PW_DOPPLER = 3

_BMODE_BOUNDS = (120, 60, 1060, 400)
_DOPPLER_BOUNDS = (40, 420, 1140, 860)


def _make_region(
    spatial_format: int,
    data_type: int,
    bounds: tuple[int, int, int, int],
) -> Dataset:
    x0, y0, x1, y1 = bounds
    region = Dataset()
    region.RegionSpatialFormat = spatial_format
    region.RegionDataType = data_type
    region.RegionLocationMinX0 = x0
    region.RegionLocationMinY0 = y0
    region.RegionLocationMaxX1 = x1
    region.RegionLocationMaxY1 = y1
    return region


def _write_dicom(path: Path, regions: list[Dataset] | None) -> Path:
    """Write a minimal tags-only US DICOM (read with stop_before_pixels=True)."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "US"
    if regions is not None:
        ds.SequenceOfUltrasoundRegions = regions

    ds.save_as(path, enforce_file_format=True)
    return path


def _bounds_to_xyxy(bounds: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bounds
    return (float(x0), float(y0), float(x1), float(y1))


def test_dicom_split_screen_prefers_bmode_over_doppler(tmp_path) -> None:
    """Split-screen (B-mode + Doppler): the LV segmentation ROI must be the
    B-mode panel, even though the Doppler region comes first in the sequence."""
    path = _write_dicom(
        tmp_path / "split_screen.dcm",
        [
            _make_region(_SPATIAL_SPECTRAL, _DATA_TYPE_PW_DOPPLER, _DOPPLER_BOUNDS),
            _make_region(_SPATIAL_2D, _DATA_TYPE_TISSUE, _BMODE_BOUNDS),
        ],
    )
    frame = _make_doppler_frame(height=900, width=1200)

    roi = resolve_dicom_segment_roi_xyxy(frame, path)

    assert roi == _bounds_to_xyxy(_BMODE_BOUNDS)
    assert roi != _bounds_to_xyxy(_DOPPLER_BOUNDS)


def test_dicom_bmode_only_returns_bmode_panel(tmp_path) -> None:
    """A plain B-mode study returns its single 2D panel."""
    path = _write_dicom(
        tmp_path / "bmode_only.dcm",
        [_make_region(_SPATIAL_2D, _DATA_TYPE_TISSUE, _BMODE_BOUNDS)],
    )
    frame = _make_bmode_frame(height=900, width=1200)

    roi = resolve_dicom_segment_roi_xyxy(frame, path)

    assert roi == _bounds_to_xyxy(_BMODE_BOUNDS)


def test_dicom_doppler_only_falls_back_to_doppler_panel(tmp_path) -> None:
    """Doppler-only studies still resolve: B-mode is preferred, not required."""
    path = _write_dicom(
        tmp_path / "doppler_only.dcm",
        [_make_region(_SPATIAL_SPECTRAL, _DATA_TYPE_PW_DOPPLER, _DOPPLER_BOUNDS)],
    )
    frame = _make_doppler_frame(height=900, width=1200)

    roi = resolve_dicom_segment_roi_xyxy(frame, path)

    assert roi == _bounds_to_xyxy(_DOPPLER_BOUNDS)


def test_dicom_without_regions_falls_back_to_cine_detection(tmp_path) -> None:
    """No SequenceOfUltrasoundRegions → heuristic cine path (None on B-mode)."""
    path = _write_dicom(tmp_path / "no_regions.dcm", None)
    frame = _make_bmode_frame(height=600, width=800)

    assert resolve_dicom_segment_roi_xyxy(frame, path) is None


def test_dicom_unreadable_path_falls_back_to_cine_detection(tmp_path) -> None:
    """An unparseable file must not raise — it degrades to cine detection."""
    path = tmp_path / "garbage.dcm"
    path.write_bytes(b"not a dicom file")
    frame = _make_doppler_frame(height=600, width=800)

    assert resolve_dicom_segment_roi_xyxy(frame, path) == resolve_cine_segment_roi_xyxy(frame)


def test_dicom_none_path_falls_back_to_cine_detection() -> None:
    frame = _make_doppler_frame(height=600, width=800)

    assert resolve_dicom_segment_roi_xyxy(frame, None) == resolve_cine_segment_roi_xyxy(frame)


def test_resolve_segment_roi_dicom_uses_panel_priority(tmp_path) -> None:
    """The public entry point routes DICOM to the panel-aware resolver."""
    path = _write_dicom(
        tmp_path / "split_screen.dcm",
        [
            _make_region(_SPATIAL_SPECTRAL, _DATA_TYPE_PW_DOPPLER, _DOPPLER_BOUNDS),
            _make_region(_SPATIAL_2D, _DATA_TYPE_TISSUE, _BMODE_BOUNDS),
        ],
    )
    frame = _make_doppler_frame(height=900, width=1200)

    roi = resolve_segment_roi_xyxy(frame, media_format="dicom", instance_path=path)

    assert roi == _bounds_to_xyxy(_BMODE_BOUNDS)
