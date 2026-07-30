"""Extended tests for dicom_upload_utils covering annotation injection path."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from echo_personal_tool.application.dicom_upload_utils import collect_dicom_bytes
from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def _make_study(path: Path, sop_uid: str = "1.2.3") -> StudyMetadata:
    inst = InstanceMetadata(
        sop_instance_uid=sop_uid,
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        media_format="dicom",
    )
    series = SeriesMetadata(
        series_uid="1.2.3.4",
        study_uid="1.2.3.5",
        modality="US",
        description="S",
        instances=(inst,),
    )
    return StudyMetadata(
        study_uid="1.2.3.5",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(series,),
    )


def _make_instance(path: Path | None, sop_uid: str = "1.2.3") -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=sop_uid,
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        media_format="dicom",
    )


def test_collect_skips_nonexistent_file(tmp_path: Path) -> None:
    """Files that don't exist on disk are skipped."""
    study = _make_study(tmp_path / "nonexistent.dcm")
    payloads = collect_dicom_bytes([study])
    assert payloads == []


def test_collect_skips_none_path() -> None:
    """Instances with path=None are skipped."""
    inst = _make_instance(path=None)
    series = SeriesMetadata(
        series_uid="1.2.3.4",
        study_uid="1.2.3.5",
        modality="US",
        description="S",
        instances=(inst,),
    )
    study = StudyMetadata(
        study_uid="1.2.3.5",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(series,),
    )
    payloads = collect_dicom_bytes([study])
    assert payloads == []


def test_collect_empty_studies() -> None:
    payloads = collect_dicom_bytes([])
    assert payloads == []


def test_collect_multiple_studies(tmp_path: Path) -> None:
    dcm1 = tmp_path / "a.dcm"
    dcm1.write_bytes(b"DICM-a")
    dcm2 = tmp_path / "b.dcm"
    dcm2.write_bytes(b"DICM-b")

    mock_ds = MagicMock()

    with patch("echo_personal_tool.application.dicom_upload_utils.pydicom.dcmread", return_value=mock_ds):
        study1 = _make_study(dcm1, sop_uid="uid1")
        study2 = _make_study(dcm2, sop_uid="uid2")
        payloads = collect_dicom_bytes([study1, study2])

    assert len(payloads) == 2


def test_collect_skips_non_dicom_format(tmp_path: Path) -> None:
    """Instances with media_format != 'dicom' are skipped."""
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"mp4data")
    study = _make_study(mp4, sop_uid="uid1")
    # Override the instance to be mp4 format
    inst = _make_instance(mp4, sop_uid="uid1")
    series = SeriesMetadata(
        series_uid="1.2.3.4",
        study_uid="1.2.3.5",
        modality="US",
        description="S",
        instances=(inst,),
    )
    study = StudyMetadata(
        study_uid="1.2.3.5",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(series,),
    )
    # Override media_format
    from dataclasses import replace

    study_inst = inst
    mp4_inst = replace(study_inst, media_format="mp4")
    mp4_series = replace(series, instances=(mp4_inst,))
    mp4_study = replace(study, series=(mp4_series,))
    payloads = collect_dicom_bytes([mp4_study])
    assert payloads == []


def test_collect_with_annotations_calls_annotate(tmp_path: Path) -> None:
    dcm = tmp_path / "annotated.dcm"
    dcm.write_bytes(b"DICM-annotated")
    study = _make_study(dcm, sop_uid="uid1")
    caliper = LinearMeasurement(label="LVEDD", pixel_length=100, millimeter_length=50, sop_instance_uid="uid1")
    contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(0, 0)], sop_instance_uid="uid1")
    annotations = {"uid1": [caliper, contour]}

    mock_ds = MagicMock()
    with patch("echo_personal_tool.application.dicom_upload_utils.pydicom.dcmread", return_value=mock_ds):
        with patch(
            "echo_personal_tool.application.dicom_upload_utils.annotate_dicom",
            return_value=mock_ds,
        ) as mock_annotate:
            result = collect_dicom_bytes([study], annotations=annotations)

    mock_annotate.assert_called_once()
    assert len(result) == 1


def test_collect_annotations_empty_for_instance(tmp_path: Path) -> None:
    dcm = tmp_path / "no_annot.dcm"
    dcm.write_bytes(b"DICM-no-annot")
    study = _make_study(dcm, sop_uid="uid1")
    annotations = {"other_uid": [LinearMeasurement(label="X", pixel_length=1, millimeter_length=1)]}

    mock_ds = MagicMock()
    with patch("echo_personal_tool.application.dicom_upload_utils.pydicom.dcmread", return_value=mock_ds):
        with patch(
            "echo_personal_tool.application.dicom_upload_utils.annotate_dicom",
        ) as mock_annotate:
            result = collect_dicom_bytes([study], annotations=annotations)

    mock_annotate.assert_not_called()
    assert len(result) == 1


def test_collect_no_annotations_passes_none(tmp_path: Path) -> None:
    """When annotations=None, annotate_dicom is never called."""
    dcm = tmp_path / "test.dcm"
    dcm.write_bytes(b"DICM")
    study = _make_study(dcm)

    mock_ds = MagicMock()
    with patch("echo_personal_tool.application.dicom_upload_utils.pydicom.dcmread", return_value=mock_ds):
        with patch(
            "echo_personal_tool.application.dicom_upload_utils.annotate_dicom",
        ) as mock_annotate:
            result = collect_dicom_bytes([study], annotations=None)

    mock_annotate.assert_not_called()
    assert len(result) == 1
