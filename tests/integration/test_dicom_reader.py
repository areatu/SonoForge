"""Integration tests for DICOM reading pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom


@pytest.mark.integration
def test_read_pixels_shape(tmp_path: Path) -> None:
    path = tmp_path / "frame.dcm"
    write_synthetic_dicom(path, rows=48, cols=64)
    reader = DicomReaderImpl()
    pixels = reader.read_pixels(path)
    assert pixels.shape == (48, 64)
    meta = reader.read_metadata(path)
    assert meta.modality == "US"
