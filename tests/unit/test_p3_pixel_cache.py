"""Tests for P3: decoded pixel cache in DicomReaderImpl.

Caching decoded frames avoids redundant DICOM parsing when both
ThumbnailLoaderWorker and DicomDecodeWorker read the same file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl, _pixel_cache


def _make_test_dicom(path: Path, *, width: int = 4, height: int = 3) -> Path:
    """Create a minimal DICOM file with known pixel data."""
    import io

    from pydicom.dataset import Dataset

    pixels = np.arange(width * height, dtype=np.uint16).reshape(height, width)
    ds = Dataset()
    ds.file_meta = Dataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    ds.file_meta.MediaStorageSOPInstanceUID = "1.2.3"
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    ds.SOPInstanceUID = "1.2.3"
    ds.StudyInstanceUID = "1.2.4"
    ds.SeriesInstanceUID = "1.2.5"
    ds.Modality = "US"
    ds.PatientName = "Test"
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    ds.Rows = height
    ds.Columns = width
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()

    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    dcm_path = path / "test.dcm"
    dcm_path.parent.mkdir(parents=True, exist_ok=True)
    dcm_path.write_bytes(buf.getvalue())
    return dcm_path


def test_pixel_cache_returns_same_array(tmp_path: Path) -> None:
    """Second read of same path+frame returns cached array (same identity)."""
    dcm_path = _make_test_dicom(tmp_path)
    _pixel_cache.clear()

    reader = DicomReaderImpl()
    first = reader.read_pixels(dcm_path, frame_index=0)
    second = reader.read_pixels(dcm_path, frame_index=0)

    assert first is second  # same object, not a copy
    _pixel_cache.clear()


def test_pixel_cache_different_paths_are_distinct(tmp_path: Path) -> None:
    """Different files produce different cached entries."""
    _pixel_cache.clear()

    dcm1 = _make_test_dicom(tmp_path / "a")
    dcm2 = _make_test_dicom(tmp_path / "b")

    reader = DicomReaderImpl()
    arr1 = reader.read_pixels(dcm1, frame_index=0)
    arr2 = reader.read_pixels(dcm2, frame_index=0)

    assert arr1 is not arr2
    assert np.array_equal(arr1, arr2)  # same pixel values, different objects
    _pixel_cache.clear()


def test_pixel_cache_evicts_oldest(tmp_path: Path) -> None:
    """Cache evicts oldest entry when max_bytes is reached."""
    from echo_personal_tool.infrastructure.dicom_reader import _DecodedPixelCache

    # Each arr = 4 × uint16 = 8 bytes; max_bytes=20 holds two, evicts on third
    cache = _DecodedPixelCache(max_bytes=20)
    p1 = tmp_path / "1.dcm"
    p2 = tmp_path / "2.dcm"
    p3 = tmp_path / "3.dcm"
    arr = np.zeros(4, dtype=np.uint16)

    cache.put(p1, 0, arr)
    cache.put(p2, 0, arr)
    assert cache.get(p1, 0) is not None
    assert cache.get(p2, 0) is not None

    # Adding third evicts first
    cache.put(p3, 0, arr)
    assert cache.get(p1, 0) is None  # evicted
    assert cache.get(p2, 0) is not None
    assert cache.get(p3, 0) is not None


def test_pixel_cache_clear(tmp_path: Path) -> None:
    """Clear removes all entries."""
    dcm_path = _make_test_dicom(tmp_path)
    _pixel_cache.clear()

    reader = DicomReaderImpl()
    reader.read_pixels(dcm_path, frame_index=0)
    assert _pixel_cache.get(dcm_path, 0) is not None

    _pixel_cache.clear()
    assert _pixel_cache.get(dcm_path, 0) is None
