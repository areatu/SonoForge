"""Tests for DIMSE C-FIND Dataset -> domain model mapper."""

from __future__ import annotations

from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.dimse_find_mapper import (
    map_instance,
    map_series,
    map_study,
)


def _make_study_ds() -> Dataset:
    ds = Dataset()
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.PatientName = "DOE^JOHN"
    ds.PatientID = "P001"
    ds.StudyDate = "20240115"
    ds.StudyDescription = "Echo"
    ds.NumberOfStudyRelatedSeries = 3
    return ds


def test_map_study() -> None:
    info = map_study(_make_study_ds())
    assert info.study_uid == "1.2.3.4.5"
    assert info.patient_name == "DOE^JOHN"
    assert info.patient_id == "P001"
    assert info.study_date == "20240115"
    assert info.study_description == "Echo"
    assert info.series_count == 3


def test_map_study_missing_tags() -> None:
    ds = Dataset()
    ds.StudyInstanceUID = "1.2.3"
    info = map_study(ds)
    assert info.patient_name == ""
    assert info.series_count is None


def test_map_series() -> None:
    ds = Dataset()
    ds.SeriesInstanceUID = "1.2.3.4.5.1"
    ds.Modality = "US"
    ds.SeriesDescription = "A4C"
    ds.NumberOfSeriesRelatedInstances = 30
    info = map_series(ds, study_uid="1.2.3.4.5")
    assert info.series_uid == "1.2.3.4.5.1"
    assert info.study_uid == "1.2.3.4.5"
    assert info.modality == "US"
    assert info.description == "A4C"
    assert info.instance_count == 30


def test_map_instance() -> None:
    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.4.5.1.1"
    info = map_instance(ds, study_uid="1.2.3.4.5", series_uid="1.2.3.4.5.1")
    assert info.sop_instance_uid == "1.2.3.4.5.1.1"
    assert info.series_uid == "1.2.3.4.5.1"
    assert info.study_uid == "1.2.3.4.5"
