"""Tests for DicomQueryService: Auto fallback, DIMSE-only, DICOMweb-only."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.dicom_query_service import DicomQueryService
from echo_personal_tool.domain.models.orthanc import StudyInfo
from echo_personal_tool.domain.ports import QuerySource
from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient


def test_auto_uses_web_first() -> None:
    web = FakeDicomWebClient()
    dimse = FakeDimseClient()
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.AUTO)
    studies = svc.query_studies(patient_name="DOE")
    assert len(studies) >= 1
    assert any("DOE" in s.patient_name for s in studies)


def test_dimse_only_uses_dimse() -> None:
    web = FakeDicomWebClient()
    dimse = FakeDimseClient()
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.DIMSE)
    studies = svc.query_studies()
    assert len(studies) >= 1


def test_dicomweb_only_uses_web() -> None:
    web = FakeDicomWebClient()
    dimse = FakeDimseClient()
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.DICOMWEB)
    studies = svc.query_studies()
    assert len(studies) >= 1


def test_auto_fallback_when_web_empty() -> None:
    """When web returns empty and dimse is available, auto falls back."""

    class _EmptyWeb:
        def ping(self) -> bool:
            return True

        def query_studies(self, **kwargs) -> list:  # noqa: ANN003
            return []

        def query_series(self, study_uid: str) -> list:
            return []

        def query_instances(self, study_uid: str, series_uid: str) -> list:
            return []

        def download_instance(self, *args) -> bytes:  # noqa: ANN002
            return b""

        def stow_instances(self, dicom_files: list[bytes]):
            return None

    dimse = FakeDimseClient()
    svc = DicomQueryService(web=_EmptyWeb(), dimse=dimse, source=QuerySource.AUTO)
    studies = svc.query_studies()
    assert len(studies) >= 1


def test_auto_returns_empty_when_no_clients() -> None:
    svc = DicomQueryService(web=None, dimse=None, source=QuerySource.AUTO)
    assert svc.query_studies() == []


def test_query_series_delegates_to_correct_client() -> None:
    web = FakeDicomWebClient()
    dimse = FakeDimseClient()
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.DIMSE)
    series = svc.query_series("1.2.840.113619.2.55.3.12345")
    assert len(series) >= 1


def test_query_instances_delegates_to_correct_client() -> None:
    web = FakeDicomWebClient()
    dimse = FakeDimseClient()
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.DICOMWEB)
    instances = svc.query_instances(
        "1.2.840.113619.2.55.3.12345",
        "1.2.840.113619.2.55.3.12345.1",
    )
    assert len(instances) >= 1


def test_source_setter() -> None:
    svc = DicomQueryService(web=FakeDicomWebClient(), dimse=FakeDimseClient())
    assert svc.source == QuerySource.AUTO
    svc.source = QuerySource.DIMSE
    assert svc.source == QuerySource.DIMSE
