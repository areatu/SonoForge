"""Tests for FakeDimseClient: parity with FakeDicomWebClient data."""

from __future__ import annotations

from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient


def test_c_echo_returns_true() -> None:
    client = FakeDimseClient()
    assert client.c_echo() is True


def test_c_find_studies_returns_all() -> None:
    client = FakeDimseClient()
    studies = client.c_find_studies()
    assert len(studies) >= 2


def test_c_find_studies_filters_by_patient_name() -> None:
    client = FakeDimseClient()
    studies = client.c_find_studies(patient_name="DOE")
    assert len(studies) == 1
    assert studies[0].patient_name == "DOE^JOHN"


def test_c_find_studies_filters_by_patient_id() -> None:
    client = FakeDimseClient()
    studies = client.c_find_studies(patient_id="MOCK002")
    assert len(studies) == 1
    assert studies[0].patient_id == "MOCK002"


def test_c_find_studies_filters_by_study_date() -> None:
    client = FakeDimseClient()
    studies = client.c_find_studies(study_date="20240115")
    assert len(studies) == 1


def test_c_find_series() -> None:
    client = FakeDimseClient()
    series = client.c_find_series("1.2.840.113619.2.55.3.12345")
    assert len(series) == 2
    assert series[0].modality == "US"


def test_c_find_instances() -> None:
    client = FakeDimseClient()
    instances = client.c_find_instances(
        "1.2.840.113619.2.55.3.12345",
        "1.2.840.113619.2.55.3.12345.1",
    )
    assert len(instances) >= 1


def test_c_store_returns_true() -> None:
    client = FakeDimseClient()
    assert client.c_store(b"\x00" * 100) is True
