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
from pydicom.pixels.utils import pixel_array

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


def test_signed_16_pixels_match_pydicom(tmp_path: Path) -> None:
    path = write_synthetic_pixel_dicom(
        tmp_path / "signed16.dcm",
        np.array([[[-1024, -1], [0, 1000]]], dtype=np.int16),
    )

    _assert_session_matches_reference(path)
