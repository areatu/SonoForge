"""Unit tests for tag-independent DICOM frame count inference (issue #1)."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate

from echo_personal_tool.infrastructure.dicom_frame_count import infer_dicom_frame_count
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_instance_metadata
from echo_personal_tool.infrastructure.dicom_session import DicomSession


def _dataset(rows: int = 64, cols: int = 48, *, bits: int = 8, samples: int = 1) -> Dataset:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.preamble = b"\x00" * 128
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.SeriesInstanceUID = "1.2.3.4.6"
    ds.StudyInstanceUID = "1.2.3.4.7"
    ds.Modality = "US"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = bits
    ds.SamplesPerPixel = samples
    ds.PixelRepresentation = 0
    return ds


def _encap_item(data: bytes) -> bytes:
    """A single (FFFE,E000) Item element: tag + length + data."""
    return struct.pack("<II", 0xE000FFFE, len(data)) + data


def test_tag_wins_without_pixel_data() -> None:
    ds = _dataset()
    ds.NumberOfFrames = 20
    assert infer_dicom_frame_count(ds) == 20


def test_missing_tag_uncompressed_two_frames() -> None:
    ds = _dataset()
    # 2 whole frames of 8-bit data, tag absent
    pixel = np.zeros((2, 64, 48), dtype=np.uint8).tobytes()
    assert infer_dicom_frame_count(ds, pixel_data=pixel) == 2


def test_missing_tag_genuine_still_stays_one() -> None:
    ds = _dataset()
    pixel = np.zeros((64, 48), dtype=np.uint8).tobytes()
    assert infer_dicom_frame_count(ds, pixel_data=pixel) == 1


def test_tag_one_with_single_frame_stays_one() -> None:
    ds = _dataset()
    ds.NumberOfFrames = 1
    pixel = np.zeros((64, 48), dtype=np.uint8).tobytes()
    assert infer_dicom_frame_count(ds, pixel_data=pixel) == 1


def test_missing_tag_encapsulated_items() -> None:
    ds = _dataset()
    # Encapsulated stream: Basic Offset Table item + one item per frame.
    items = [_encap_item(b"")] + [_encap_item(b"frame-a"), _encap_item(b"frame-b"), _encap_item(b"frame-c")]
    pixel = b"".join(items)
    assert infer_dicom_frame_count(ds, pixel_data=pixel) == 3


def test_missing_tag_no_pixel_data_falls_back_to_one() -> None:
    ds = _dataset()
    assert infer_dicom_frame_count(ds) == 1
    assert infer_dicom_frame_count(ds, pixel_data=None) == 1


def test_missing_tag_multiframe_encapsulated_has_many_items() -> None:
    ds = _dataset()
    items = [_encap_item(b"")] + [_encap_item(b"frame") for _ in range(14)]
    assert infer_dicom_frame_count(ds, pixel_data=b"".join(items)) == 14


def test_map_instance_metadata_uses_pixel_inference(tmp_path: Path) -> None:
    ds = _dataset()
    pixel = np.zeros((3, 64, 48), dtype=np.uint8).tobytes()
    meta = map_instance_metadata(ds, path=tmp_path / "clip.dcm", pixel_data=pixel)
    assert meta.number_of_frames == 3


def _write_multiframe_without_tag(tmp_path: Path, n_frames: int, *, encapsulated: bool) -> Path:
    """Write a multi-frame clip with (0028,0008) omitted entirely, as many US
    vendors do.  The frame count must then be recovered from pixel data."""
    rows, cols = 8, 6
    ds = _dataset(rows=rows, cols=cols)
    if not encapsulated:
        ds.PixelData = np.zeros((n_frames, rows, cols), dtype=np.uint8).tobytes()
    else:
        frames = [np.full((rows, cols), i, dtype=np.uint8).tobytes() for i in range(n_frames)]
        ds.PixelData = encapsulate(frames)
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = pydicom.uid.JPEGBaseline8Bit
        ds.file_meta = meta
    path = tmp_path / f"vendor_{n_frames}_{'enc' if encapsulated else 'raw'}.dcm"
    pydicom.dcmwrite(path, ds)
    return path


def _write_multiframe_wrong_tag_value(tmp_path: Path, n_frames: int) -> Path:
    """Write a multi-frame clip whose NumberOfFrames is wrongly 1."""
    rows, cols = 8, 6
    ds = _dataset(rows=rows, cols=cols)
    ds.NumberOfFrames = 1  # WRONG on purpose — vendor bug
    ds.PixelData = np.zeros((n_frames, rows, cols), dtype=np.uint8).tobytes()
    path = tmp_path / f"wrongtag_{n_frames}.dcm"
    pydicom.dcmwrite(path, ds)
    return path


def test_dicom_session_recovers_uncompressed_count(tmp_path: Path) -> None:
    path = _write_multiframe_without_tag(tmp_path, n_frames=4, encapsulated=False)
    session = DicomSession()
    session.open(path)
    assert session.frame_count == 4
    session.release()


def test_dicom_session_recovers_encapsulated_count(tmp_path: Path) -> None:
    path = _write_multiframe_without_tag(tmp_path, n_frames=3, encapsulated=True)
    session = DicomSession()
    session.open(path)
    assert session.frame_count == 3
    session.release()


def test_dicom_session_corrects_wrong_tag_value(tmp_path: Path) -> None:
    """Tag present but wrong (1) must still be corrected from pixel data."""
    path = _write_multiframe_wrong_tag_value(tmp_path, n_frames=3)
    session = DicomSession()
    session.open(path)
    assert session.frame_count == 3
    session.release()


def test_dicom_session_true_still_stays_one(tmp_path: Path) -> None:
    ds = _dataset(rows=8, cols=6)
    ds.NumberOfFrames = 1
    ds.PixelData = np.zeros((8, 6), dtype=np.uint8).tobytes()
    path = tmp_path / "still.dcm"
    pydicom.dcmwrite(path, ds)
    session = DicomSession()
    session.open(path)
    assert session.frame_count == 1
    session.release()


def test_scanner_classifies_missing_tag_multiframe(tmp_path: Path) -> None:
    """End-to-end: a folder scan must report the real frame count."""
    from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner

    path = _write_multiframe_without_tag(tmp_path, n_frames=5, encapsulated=False)
    studies = LocalMediaDirectoryScanner().scan(tmp_path)
    instances = [inst for study in studies for series in study.series for inst in series.instances]
    assert len(instances) == 1
    assert instances[0].number_of_frames == 5
