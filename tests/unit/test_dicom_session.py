"""Unit tests for DicomSession."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.infrastructure.dicom_session import (
    DicomSession,
    get_thread_dicom_session,
)
from tests.fixtures.generate_synthetic_dicom import (
    write_synthetic_dicom,
    write_synthetic_multiframe_dicom,
)


def test_decode_single_frame_dicom(tmp_path: Path) -> None:
    path = tmp_path / "single.dcm"
    write_synthetic_dicom(path)
    session = DicomSession()
    session.open(path)
    frames = session.decode_all_frames()
    assert frames.shape == (1, 64, 64)
    frame = session.read_frame(0)
    assert frame.shape == (64, 64)
    session.release()
    assert session.frame_count == 0


def test_decode_multiframe_dicom(tmp_path: Path) -> None:
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=5, rows=32, cols=32)
    session = DicomSession()
    session.open(path)
    frames = session.decode_all_frames()
    assert frames.shape == (5, 32, 32)
    assert frames[3, 0, 0] == 3
    assert session.read_frame(2)[0, 0] == 2
    session.release()


def test_read_frame_out_of_range_raises(tmp_path: Path) -> None:
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=3)
    session = DicomSession()
    session.open(path)
    session.decode_all_frames()
    with pytest.raises(IndexError):
        session.read_frame(3)
    session.release()


def test_get_thread_dicom_session_returns_same_instance() -> None:
    first = get_thread_dicom_session()
    second = get_thread_dicom_session()
    assert first is second
