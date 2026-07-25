"""Unit tests for Orthanc DICOMweb query result models."""

from __future__ import annotations

import dataclasses

import pytest

from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyInfo,
)


class TestStudyInfo:
    def test_creation(self) -> None:
        info = StudyInfo(
            study_uid="1.2.3",
            patient_name="Doe^John",
            patient_id="P001",
            study_date="20250115",
            study_description="Echo study",
        )
        assert info.study_uid == "1.2.3"
        assert info.patient_name == "Doe^John"
        assert info.patient_id == "P001"
        assert info.study_date == "20250115"
        assert info.study_description == "Echo study"
        assert info.series_count is None

    def test_with_series_count(self) -> None:
        info = StudyInfo(
            study_uid="1", patient_name="X", patient_id="P",
            study_date="20250101", study_description="d", series_count=5,
        )
        assert info.series_count == 5

    def test_frozen(self) -> None:
        info = StudyInfo(
            study_uid="1", patient_name="X", patient_id="P",
            study_date="20250101", study_description="d",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.patient_name = "Y"  # type: ignore[misc]


class TestSeriesInfo:
    def test_creation(self) -> None:
        info = SeriesInfo(
            series_uid="s1", study_uid="st1", modality="US",
            description="A4C",
        )
        assert info.series_uid == "s1"
        assert info.modality == "US"
        assert info.instance_count is None

    def test_with_instance_count(self) -> None:
        info = SeriesInfo(
            series_uid="s1", study_uid="st1", modality="US",
            description="d", instance_count=30,
        )
        assert info.instance_count == 30

    def test_frozen(self) -> None:
        info = SeriesInfo(
            series_uid="s1", study_uid="st1", modality="US", description="d",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.modality = "CT"  # type: ignore[misc]


class TestInstanceInfo:
    def test_creation(self) -> None:
        info = InstanceInfo(
            sop_instance_uid="1.2.3", series_uid="1.2.4", study_uid="1.2.5",
        )
        assert info.sop_instance_uid == "1.2.3"
        assert info.series_uid == "1.2.4"
        assert info.study_uid == "1.2.5"

    def test_frozen(self) -> None:
        info = InstanceInfo(sop_instance_uid="1", series_uid="2", study_uid="3")
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.sop_instance_uid = "x"  # type: ignore[misc]


class TestStowResult:
    def test_success(self) -> None:
        result = StowResult(success_count=10)
        assert result.success_count == 10
        assert result.failed_uids == []
        assert result.error_message == ""

    def test_with_failures(self) -> None:
        result = StowResult(
            success_count=8,
            failed_uids=["uid1", "uid2"],
            error_message="2 files rejected",
        )
        assert result.success_count == 8
        assert len(result.failed_uids) == 2
        assert result.error_message == "2 files rejected"

    def test_is_frozen(self) -> None:
        result = StowResult(success_count=0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success_count = 5  # type: ignore[misc]
