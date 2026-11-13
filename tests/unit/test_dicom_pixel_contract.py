"""Correct pixel interpretation at the DicomSession boundary (#541).

The fast path reads the native pixel block directly. That is only correct for a narrow,
tested set of metadata: little-endian, full-width 8/16-bit samples, monochrome or
interleaved RGB. Everything else must use pydicom's indexed decoder, which handles
signedness, BitsStored/HighBit, planar configuration, YBR, big endian, 1-bit and float
pixels. These tests compare single-frame, bulk and random-access results with pydicom.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.pixels.utils import pixel_array
from pydicom.uid import ExplicitVRBigEndian, ExplicitVRLittleEndian, generate_uid

from echo_personal_tool.infrastructure.dicom_session import DicomSession
from tests.fixtures.generate_synthetic_dicom import write_synthetic_pixel_dicom


def _reference_frames(path: Path) -> np.ndarray:
    dataset = pydicom.dcmread(path)
    frame_count = int(getattr(dataset, "NumberOfFrames", 1))
    frames = [pixel_array(str(path), index=index, number_of_frames=frame_count) for index in range(frame_count)]
    return np.stack(frames)


def _assert_session_matches_reference(path: Path) -> None:
    expected = _reference_frames(path)
    session = DicomSession()
    try:
        session.open(path)
        np.testing.assert_array_equal(session.decode_first_frame(), expected[0])
        np.testing.assert_array_equal(session.decode_single_frame(0), expected[0])
        bulk = session.decode_all_frames()

        np.testing.assert_array_equal(bulk, expected)
        for index in range(expected.shape[0]):
            np.testing.assert_array_equal(session.decode_single_frame(index), expected[index])
            np.testing.assert_array_equal(session.read_frame(index), expected[index])
    finally:
        session.release()


RGB_PIXELS = np.array(
    [
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [1, 2, 3]],
        ]
    ],
    dtype=np.uint8,
)
YBR_PIXELS = np.array(
    [
        [
            [[76, 85, 255], [150, 44, 21]],
            [[29, 255, 107], [0, 0, 0]],
        ]
    ],
    dtype=np.uint8,
)


@pytest.mark.parametrize(
    ("name", "pixels", "options"),
    [
        pytest.param("signed16", np.array([[[-1024, -1], [0, 1000]]], dtype=np.int16), {}, id="signed-16"),
        pytest.param("unsigned16", np.array([[[0, 1], [4095, 65535]]], dtype=np.uint16), {}, id="unsigned-16"),
        pytest.param("signed8", np.array([[[-128, -1], [0, 127]]], dtype=np.int8), {}, id="signed-8"),
        pytest.param("unsigned8", np.array([[[0, 1], [254, 255]]], dtype=np.uint8), {}, id="unsigned-8"),
        pytest.param(
            "signed12",
            np.array([[[-2048, -1], [0, 2047]]], dtype=np.int16),
            {"bits_stored": 12},
            id="signed-12-in-16",
        ),
        pytest.param(
            "unsigned12",
            np.array([[[0, 1], [2048, 4095]]], dtype=np.uint16),
            {"bits_stored": 12},
            id="unsigned-12-in-16",
        ),
        pytest.param("rgb", RGB_PIXELS, {"photometric_interpretation": "RGB"}, id="rgb-interleaved"),
        pytest.param(
            "rgb_planar",
            RGB_PIXELS,
            {"photometric_interpretation": "RGB", "planar_configuration": 1},
            id="rgb-planar",
        ),
        pytest.param(
            "rgb16",
            np.array([[[[0, 1, 65535], [256, 257, 511]]]], dtype=np.uint16),
            {"photometric_interpretation": "RGB"},
            id="rgb-16",
        ),
        pytest.param(
            "big_endian",
            np.array([[[0, -1], [1000, 2000]]], dtype=np.int16),
            {"transfer_syntax": ExplicitVRBigEndian},
            id="big-endian-signed-16",
        ),
        pytest.param(
            "ybr",
            YBR_PIXELS,
            {"photometric_interpretation": "YBR_FULL"},
            id="ybr-full",
        ),
    ],
)
def test_decoded_pixels_match_pydicom(
    tmp_path: Path,
    name: str,
    pixels: np.ndarray,
    options: dict[str, object],
) -> None:
    path = write_synthetic_pixel_dicom(tmp_path / f"{name}.dcm", pixels, **options)

    _assert_session_matches_reference(path)


def _write_file_dataset(path: Path, *, bits_allocated: int) -> FileDataset:
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset: FileDataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.is_little_endian = True
    dataset.is_implicit_VR = False
    dataset.SOPClassUID = pydicom.uid.UltrasoundImageStorage
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.Modality = "US"
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.BitsAllocated = bits_allocated
    dataset.BitsStored = bits_allocated
    dataset.HighBit = bits_allocated - 1
    dataset.PixelRepresentation = 0
    dataset.NumberOfFrames = 1
    return dataset


def test_one_bit_pixels_match_pydicom(tmp_path: Path) -> None:
    path = tmp_path / "one_bit.dcm"
    dataset = _write_file_dataset(path, bits_allocated=1)
    dataset.BitsStored = 1
    dataset.HighBit = 0
    dataset.PixelData = b"\x0a"  # row-major 0,1,0,1
    dataset.save_as(path, write_like_original=False)

    _assert_session_matches_reference(path)


def test_float_pixel_data_matches_pydicom(tmp_path: Path) -> None:
    path = tmp_path / "float.dcm"
    dataset = _write_file_dataset(path, bits_allocated=32)
    dataset.FloatPixelData = np.array([[1.5, -2.25], [0.0, 3.0]], dtype="<f4").tobytes()
    dataset.save_as(path, write_like_original=False)

    _assert_session_matches_reference(path)


@pytest.mark.parametrize(
    ("pixels", "options"),
    [
        pytest.param(np.array([[[-2048, -1], [0, 2047]]], dtype=np.int16), {"bits_stored": 12}, id="12-bit"),
        pytest.param(RGB_PIXELS, {"photometric_interpretation": "RGB", "planar_configuration": 1}, id="planar"),
        pytest.param(YBR_PIXELS, {"photometric_interpretation": "YBR_FULL"}, id="ybr"),
        pytest.param(
            np.array([[[0, -1], [1000, 2000]]], dtype=np.int16),
            {"transfer_syntax": ExplicitVRBigEndian},
            id="big-endian",
        ),
    ],
)
def test_unsupported_layouts_do_not_take_the_fast_path(
    tmp_path: Path,
    pixels: np.ndarray,
    options: dict[str, object],
) -> None:
    path = write_synthetic_pixel_dicom(tmp_path / "fallback.dcm", pixels, **options)
    session = DicomSession()
    try:
        session.open(path)
        assert session._uncompressed_layout() is None
    finally:
        session.release()
