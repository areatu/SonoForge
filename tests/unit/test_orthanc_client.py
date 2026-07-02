"""Unit tests for OrthancDicomWebClient."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

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
