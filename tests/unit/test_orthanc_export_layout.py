"""Tests for exporting a downloaded Orthanc session (cache -> directory)."""

from __future__ import annotations

import io
from pathlib import Path

from pydicom.dataset import Dataset

from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog

STUDY_UID = "1.2.410.200001.1.1185.2062614048.1.20260929.1094518981.328.1"
SERIES_UID = "1.2.410.200001.1.1185.2062614048.2.20260929.1094519409.100.1"
SOP_UID = "1.2.410.200001.1.1185.2062614048.3.20260929.1094703762.595.3"


def _dicom_bytes(study_uid: str, series_uid: str, sop_uid: str) -> bytes:
    ds = Dataset()
    ds.file_meta = Dataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "US"
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


def test_series_name_uses_legacy_directory_name() -> None:
    assert OrthancStudyDialog._series_name_for(Path("x.dcm"), "1.2.3") == "1.2.3"


def test_series_name_read_from_header_for_flat_layout(tmp_path: Path) -> None:
    dcm = tmp_path / f"{SOP_UID}.dcm"
    dcm.write_bytes(_dicom_bytes(STUDY_UID, SERIES_UID, SOP_UID))
    assert OrthancStudyDialog._series_name_for(dcm, None) == SERIES_UID


def test_series_name_unreadable_file_falls_back_to_study_dir(tmp_path: Path) -> None:
    assert OrthancStudyDialog._series_name_for(tmp_path / "missing.dcm", None) == ""


def test_copy_session_files_flat_layout(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    study_dir = session_dir / STUDY_UID
    study_dir.mkdir(parents=True)
    (study_dir / f"{SOP_UID}.dcm").write_bytes(_dicom_bytes(STUDY_UID, SERIES_UID, SOP_UID))

    target = tmp_path / "export"
    copied = OrthancStudyDialog._copy_session_files(session_dir, target)

    assert copied == 1
    assert (target / STUDY_UID / SERIES_UID / f"{SOP_UID}.dcm").is_file()


def test_copy_session_files_legacy_layout(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    legacy_dir = session_dir / STUDY_UID / SERIES_UID
    legacy_dir.mkdir(parents=True)
    (legacy_dir / f"{SOP_UID}.dcm").write_bytes(_dicom_bytes(STUDY_UID, SERIES_UID, SOP_UID))

    target = tmp_path / "export"
    copied = OrthancStudyDialog._copy_session_files(session_dir, target)

    assert copied == 1
    assert (target / STUDY_UID / SERIES_UID / f"{SOP_UID}.dcm").is_file()
