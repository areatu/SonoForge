"""Acceptance: connect to mock Orthanc → query studies → download instances → display."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo

pytestmark = [pytest.mark.gui, pytest.mark.acceptance]


class TestOrthancWorkflow:
    def test_fake_client_ping(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient responds to ping."""
        assert fake_orthanc_client.ping() is True

    def test_fake_client_query_studies(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient returns study list from fixtures."""
        studies = fake_orthanc_client.query_studies()
        assert isinstance(studies, list)
        assert len(studies) > 0
        assert all(isinstance(s, StudyInfo) for s in studies)

    def test_fake_client_query_studies_filter_patient_name(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient filters studies by patient name."""
        studies = fake_orthanc_client.query_studies()
        if studies:
            first_name = studies[0].patient_name
            filtered = fake_orthanc_client.query_studies(patient_name=first_name.split("^")[0])
            assert len(filtered) > 0

    def test_fake_client_query_series(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient returns series for a study."""
        studies = fake_orthanc_client.query_studies()
        if studies:
            series = fake_orthanc_client.query_series(studies[0].study_uid)
            assert isinstance(series, list)
            assert all(isinstance(s, SeriesInfo) for s in series)

    def test_fake_client_query_instances(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient returns instances for a series."""
        studies = fake_orthanc_client.query_studies()
        if studies:
            series_list = fake_orthanc_client.query_series(studies[0].study_uid)
            if series_list:
                instances = fake_orthanc_client.query_instances(
                    studies[0].study_uid, series_list[0].series_uid
                )
                assert isinstance(instances, list)
                assert all(isinstance(i, InstanceInfo) for i in instances)

    def test_fake_client_download_instance(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient downloads a DICOM instance as bytes."""
        studies = fake_orthanc_client.query_studies()
        if studies:
            series_list = fake_orthanc_client.query_series(studies[0].study_uid)
            if series_list:
                instances = fake_orthanc_client.query_instances(
                    studies[0].study_uid, series_list[0].series_uid
                )
                if instances:
                    data = fake_orthanc_client.download_instance(
                        studies[0].study_uid,
                        series_list[0].series_uid,
                        instances[0].sop_instance_uid,
                    )
                    assert isinstance(data, bytes)
                    assert len(data) > 0

    def test_fake_client_stow_instances(self, fake_orthanc_client) -> None:
        """FakeDicomWebClient accepts STOW upload."""
        result = fake_orthanc_client.stow_instances([b"\x00" * 100, b"\x01" * 100])
        assert result.success_count == 2

    def test_mock_client_query_studies_returns_empty(self, mock_dicom_web_client) -> None:
        """Mock client returns empty list by default."""
        studies = mock_dicom_web_client.query_studies()
        assert studies == []

    def test_mock_client_ping(self, mock_dicom_web_client) -> None:
        """Mock client ping returns True."""
        assert mock_dicom_web_client.ping() is True

    def test_dicom_query_service_uses_web_source(self, fake_orthanc_client) -> None:
        """DicomQueryService routes queries through FakeDicomWebClient."""
        from echo_personal_tool.application.dicom_query_service import DicomQueryService
        from echo_personal_tool.domain.ports import QuerySource

        svc = DicomQueryService(web=fake_orthanc_client, dimse=None, source=QuerySource.DICOMWEB)
        studies = svc.query_studies()
        assert isinstance(studies, list)
        assert len(studies) > 0
