"""Unit tests for OrthancDicomWebClient."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient


def _client_with_transport(handler) -> OrthancDicomWebClient:
    transport = httpx.MockTransport(handler)
    client = OrthancDicomWebClient(
        "http://orthanc/dicom-web",
        "user",
        "pass",
        auth_mode="basic",
    )
    client._orthanc_client = httpx.Client(
        base_url="http://orthanc/",
        transport=transport,
    )
    client._client = httpx.Client(
        base_url="http://orthanc/dicom-web/",
        auth=("user", "pass"),
        transport=transport,
    )
    return client


# ── Existing tests (using legacy fixtures) ──────────────────────────


def test_ping_returns_true_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/system"
        return httpx.Response(200)

    client = _client_with_transport(handler)
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_ping_returns_false_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_with_transport(handler)
    try:
        assert client.ping() is False
    finally:
        client.close()


def test_query_studies_parses_dicom_json() -> None:
    raw = Path("tests/fixtures/orthanc/studies.json").read_text(encoding="utf-8")
    payload = json.loads(raw)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/dicom-web/studies" in str(request.url)
        assert request.headers["Accept"] == "application/dicom+json"
        assert "PatientName" not in request.url.params
        include_fields = request.url.params.get_list("includefield")
        assert "00100010" in include_fields
        assert "0020000D" in include_fields
        return httpx.Response(200, json=payload)

    client = _client_with_transport(handler)
    try:
        studies = client.query_studies()
        assert len(studies) == 1
        assert studies[0].patient_name == "TEST^PATIENT"
        assert studies[0].study_uid.startswith("1.2.")
    finally:
        client.close()


def test_query_studies_filters_by_patient_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["PatientName"] == "*IVAN*"
        return httpx.Response(200, json=[])

    client = _client_with_transport(handler)
    try:
        assert client.query_studies(patient_name="IVAN") == []
    finally:
        client.close()


# ── New tests using real-world fixtures ─────────────────────────────


class TestQueryStudiesWithRealFixtures:
    def test_single_study(self, qido_studies_single) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=qido_studies_single)

        client = _client_with_transport(handler)
        try:
            studies = client.query_studies()
            assert len(studies) == 1
            assert studies[0].patient_name == "Doe^John"
            assert studies[0].patient_id == "P001"
            assert studies[0].study_date == "20250115"
        finally:
            client.close()

    def test_multi_studies(self, qido_studies_multi) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=qido_studies_multi)

        client = _client_with_transport(handler)
        try:
            studies = client.query_studies()
            assert len(studies) == 2
            assert studies[0].patient_name == "Doe^John"
            assert studies[1].patient_name == "Smith^Jane"
        finally:
            client.close()

    def test_empty_studies(self, qido_studies_empty) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=qido_studies_empty)

        client = _client_with_transport(handler)
        try:
            studies = client.query_studies()
            assert len(studies) == 0
        finally:
            client.close()


class TestQuerySeriesWithRealFixtures:
    def test_echo_series(self, qido_series_echo) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=qido_series_echo)

        client = _client_with_transport(handler)
        try:
            series = client.query_series(study_uid="1.2.3")
            assert len(series) == 3
            assert series[0].modality == "US"
            assert series[0].description == "A4C Cine"
        finally:
            client.close()

    def test_ct_series(self, qido_series_ct) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=qido_series_ct)

        client = _client_with_transport(handler)
        try:
            series = client.query_series(study_uid="1.2.3")
            assert len(series) == 1
            assert series[0].modality == "CT"
            assert series[0].instance_count == 250
        finally:
            client.close()


class TestQueryInstancesWithRealFixtures:
    def test_echo_instances(self, wado_instances_echo) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=wado_instances_echo)

        client = _client_with_transport(handler)
        try:
            instances = client.query_instances(
                study_uid="1.2.3", series_uid="1.2.4"
            )
            assert len(instances) == 3
        finally:
            client.close()


class TestErrorHandling:
    def test_500_error(self, error_500) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json=error_500)

        client = _client_with_transport(handler)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                client.query_studies()
        finally:
            client.close()

    def test_401_error(self, error_401) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json=error_401)

        client = _client_with_transport(handler)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                client.query_studies()
        finally:
            client.close()
