"""Application-facing DICOM read APIs used by presentation."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.application.dicom_io import (
    load_dicom_preview_frame,
    read_all_dicom_tag_rows,
    read_patient_demographics,
)
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom


def test_header_and_tag_readers_return_application_models(tmp_path: Path) -> None:
    path = write_synthetic_dicom(tmp_path / "patient.dcm")

    demographics = read_patient_demographics(path)
    rows = read_all_dicom_tag_rows(path)

    assert demographics.name == "Patient Synthetic"
    assert demographics.patient_id == "SYN001"
    patient_name = next(row for row in rows if row.keyword == "PatientName")
    assert patient_name.value == "Synthetic^Patient"


def test_preview_frame_is_a_detached_copy(tmp_path: Path) -> None:
    path = write_synthetic_dicom(tmp_path / "preview.dcm")

    first = load_dicom_preview_frame(path)
    assert first is not None and first.shape == (64, 64)
    first[0, 0] = 255

    second = load_dicom_preview_frame(path)
    assert second is not None
    assert second[0, 0] == 0
