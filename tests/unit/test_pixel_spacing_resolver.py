"""Unit tests for pixel spacing resolution and manual calibration."""

from __future__ import annotations

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset

from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    PixelSpacingResolution,
    effective_pixel_spacing,
    resolve_pixel_spacing,
    spacing_from_known_distance,
)


def _base_dataset() -> Dataset:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    return ds


def test_resolve_pixel_spacing_from_pixel_spacing_tag() -> None:
    ds = _base_dataset()
    ds.PixelSpacing = [0.25, 0.25]
    result = resolve_pixel_spacing(ds)
    assert result == PixelSpacingResolution((0.25, 0.25), "PixelSpacing")


def test_pixel_spacing_takes_priority_over_imager() -> None:
    ds = _base_dataset()
    ds.PixelSpacing = [0.2, 0.2]
    ds.ImagerPixelSpacing = [0.5, 0.5]
    result = resolve_pixel_spacing(ds)
    assert result is not None
    assert result.source == "PixelSpacing"
    assert result.spacing == (0.2, 0.2)


def test_resolve_from_imager_pixel_spacing() -> None:
    ds = _base_dataset()
    ds.ImagerPixelSpacing = [0.31, 0.31]
    result = resolve_pixel_spacing(ds)
    assert result == PixelSpacingResolution((0.31, 0.31), "ImagerPixelSpacing")


def test_resolve_from_nominal_scanned_pixel_spacing() -> None:
    ds = _base_dataset()
    ds.NominalScannedPixelSpacing = [0.28, 0.28]
    result = resolve_pixel_spacing(ds)
    assert result == PixelSpacingResolution((0.28, 0.28), "NominalScannedPixelSpacing")


def test_resolve_from_ultrasound_region_2d_tissue() -> None:
    ds = _base_dataset()
    region = Dataset()
    region.RegionSpatialFormat = 1
    region.RegionDataType = 1
    region.PhysicalDeltaX = 0.03
    region.PhysicalDeltaY = 0.03
    ds.SequenceOfUltrasoundRegions = [region]
    result = resolve_pixel_spacing(ds)
    assert result is not None
    assert result.source == "SequenceOfUltrasoundRegions"
    assert result.spacing == (0.3, 0.3)


def test_ultrasound_region_prefers_2d_tissue_over_spectral() -> None:
    ds = _base_dataset()
    spectral = Dataset()
    spectral.RegionSpatialFormat = 3
    spectral.RegionDataType = 3
    spectral.PhysicalDeltaX = 0.01
    spectral.PhysicalDeltaY = 0.05
    tissue = Dataset()
    tissue.RegionSpatialFormat = 1
    tissue.RegionDataType = 1
    tissue.PhysicalDeltaX = 0.025
    tissue.PhysicalDeltaY = 0.025
    ds.SequenceOfUltrasoundRegions = [spectral, tissue]
    result = resolve_pixel_spacing(ds)
    assert result is not None
    assert result.spacing == (0.25, 0.25)


def test_resolve_from_shared_functional_groups() -> None:
    ds = _base_dataset()
    pixel_measures = Dataset()
    pixel_measures.PixelSpacing = [0.22, 0.22]
    shared = Dataset()
    shared.PixelMeasuresSequence = [pixel_measures]
    ds.SharedFunctionalGroupsSequence = [shared]
    result = resolve_pixel_spacing(ds)
    assert result is not None
    assert result.source == "SharedFunctionalGroupsSequence/PixelSpacing"
    assert result.spacing == (0.22, 0.22)


def test_resolve_from_per_frame_functional_groups() -> None:
    ds = _base_dataset()
    pixel_measures = Dataset()
    pixel_measures.PixelSpacing = [0.18, 0.19]
    frame_group = Dataset()
    frame_group.PixelMeasuresSequence = [pixel_measures]
    ds.PerFrameFunctionalGroupsSequence = [frame_group]
    result = resolve_pixel_spacing(ds)
    assert result is not None
    assert result.spacing == (0.18, 0.19)


def test_returns_none_when_no_spacing_tags() -> None:
    ds = _base_dataset()
    assert resolve_pixel_spacing(ds) is None


def test_spacing_from_known_distance_is_isotropic() -> None:
    assert spacing_from_known_distance(100.0, 30.0) == (0.3, 0.3)


def test_effective_pixel_spacing_manual_overrides_dicom() -> None:
    assert effective_pixel_spacing((0.5, 0.5), (0.3, 0.3)) == (0.3, 0.3)
    assert effective_pixel_spacing((0.5, 0.5), None) == (0.5, 0.5)
    assert effective_pixel_spacing(None, None) is None
