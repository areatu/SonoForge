"""Unit tests for FakeDicomWebClient."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient

FIXTURES = Path("tests/fixtures/orthanc")


def test_ping_returns_true() -> None:
    client = FakeDicomWebClient(FIXTURES)
    assert client.ping() is True


def test_query_studies_returns_fixture_data() -> None:
    client = FakeDicomWebClient(FIXTURES)
    studies = client.query_studies()
    assert len(studies) >= 1
    assert studies[0].patient_name == "TEST^PATIENT"
    assert studies[0].study_uid == ("1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1")


def test_query_studies_filters_by_patient_name() -> None:
    client = FakeDicomWebClient(FIXTURES)
    assert len(client.query_studies(patient_name="test")) == 1
    assert len(client.query_studies(patient_name="nomatch")) == 0


def test_download_instance_returns_bytes() -> None:
    client = FakeDicomWebClient(FIXTURES)
    study_uid = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"
    series_uid = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.2"
    instance_uid = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.3"
    data = client.download_instance(study_uid, series_uid, instance_uid)
    assert isinstance(data, bytes)
    assert len(data) > 0
    assert data[128:132] == b"DICM"
