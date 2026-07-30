"""Fuzz Orthanc API responses with malformed payloads.

Tests that the application handles malformed JSON, missing fields,
extremely large payloads, SQL injection in study descriptions,
and XSS in patient names without crashes or data corruption.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from echo_personal_tool.infrastructure.orthanc_client import (
    OrthancDicomWebClient,
    _parse_stow_response,
)
from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
    tag_value,
)

pytestmark = pytest.mark.security


class TestOrthancJsonFuzzing:
    """Fuzz DICOM JSON parsers with malformed payloads."""

    def test_empty_list(self) -> None:
        assert parse_studies([]) == []

    def test_empty_dict_element(self) -> None:
        result = parse_studies([{}])
        assert len(result) == 1
        assert result[0].study_uid == ""

    def test_missing_all_value_keys(self) -> None:
        payload = [{"some_random_key": {"vr": "LO", "Value": ["test"]}}]
        result = parse_studies(payload)
        assert len(result) == 1
        assert result[0].study_uid == ""

    def test_none_value_field(self) -> None:
        payload = [{"0020000D": {"vr": "UI", "Value": None}}]
        result = parse_studies(payload)
        assert len(result) == 1
        assert result[0].study_uid == ""

    def test_empty_value_array(self) -> None:
        payload = [{"0020000D": {"vr": "UI", "Value": []}}]
        result = parse_studies(payload)
        assert len(result) == 1
        assert result[0].study_uid == ""

    def test_nested_dict_value(self) -> None:
        """Patient name in DICOM JSON PersonName format."""
        payload = [
            {
                "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
                "00100010": {"vr": "PN", "Value": [{"Alphabetic": "Doe^John"}]},
                "00100020": {"vr": "LO", "Value": ["P001"]},
                "00080020": {"vr": "DA", "Value": ["20250101"]},
                "00081030": {"vr": "LO", "Value": ["Echo"]},
            }
        ]
        result = parse_studies(payload)
        assert result[0].patient_name == "Doe^John"

    def test_numeric_value_instead_of_string(self) -> None:
        payload = [{"0020000D": {"vr": "UI", "Value": [12345]}}]
        result = parse_studies(payload)
        assert result[0].study_uid == "12345"

    def test_boolean_value(self) -> None:
        payload = [{"0020000D": {"vr": "UI", "Value": [True]}}]
        result = parse_studies(payload)
        assert result[0].study_uid == "True"

    def test_huge_payload_list(self) -> None:
        payload = [{"0020000D": {"vr": "UI", "Value": [f"1.2.{i}"]}} for i in range(10000)]
        result = parse_studies(payload)
        assert len(result) == 10000

    def test_series_missing_optional_fields(self) -> None:
        payload = [{"0020000E": {"vr": "UI", "Value": ["1.2.3"]}}]
        result = parse_series(payload, "study1")
        assert len(result) == 1
        assert result[0].series_uid == "1.2.3"
        assert result[0].instance_count is None

    def test_instances_missing_fields(self) -> None:
        payload = [{}]
        result = parse_instances(payload, "study1", "series1")
        assert len(result) == 1
        assert result[0].sop_instance_uid == ""


class TestTagValueFuzzing:
    """Fuzz tag_value() with various malformed inputs."""

    def test_empty_item(self) -> None:
        assert tag_value({}, "0020000D") == ""

    def test_none_tag_node(self) -> None:
        assert tag_value({"0020000D": None}, "0020000D") == ""

    def test_missing_value_key(self) -> None:
        assert tag_value({"0020000D": {"vr": "UI"}}, "0020000D") == ""

    def test_nested_person_name(self) -> None:
        item = {"00100010": {"vr": "PN", "Value": [{"Alphabetic": "Smith^Jane", "Ideographic": "", "Phonetic": ""}]}}
        assert tag_value(item, "00100010") == "Smith^Jane"

    def test_default_return(self) -> None:
        assert tag_value({}, "missing", "fallback") == "fallback"


class TestStowResponseFuzzing:
    """Fuzz _parse_stow_response with various payloads."""

    def test_non_list_response(self) -> None:
        result = _parse_stow_response("not a list", 3)
        assert result.success_count == 3

    def test_dict_response(self) -> None:
        result = _parse_stow_response({"error": "bad"}, 2)
        assert result.success_count == 2

    def test_none_response(self) -> None:
        result = _parse_stow_response(None, 1)
        assert result.success_count == 1

    def test_empty_list(self) -> None:
        result = _parse_stow_response([], 5)
        assert result.success_count == 5

    def test_malformed_items_in_list(self) -> None:
        result = _parse_stow_response(["string", 123, None, {"random": "data"}], 4)
        assert result.success_count == 4

    def test_partial_failure_response(self) -> None:
        response = [
            {},
            {"00081199": [{"00081155": {"Value": ["uid1"]}}]},
            {"00081199": [{"00081155": {"Value": ["uid2"]}}]},
        ]
        result = _parse_stow_response(response, 3)
        assert result.success_count == 1
        assert len(result.failed_uids) == 2


class TestOrthancClientApiFuzzing:
    """Fuzz OrthancDicomWebClient with mocked httpx responses."""

    def _make_client(self) -> OrthancDicomWebClient:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client"):
            client = OrthancDicomWebClient(
                "http://localhost:8042/dicom-web",
                username="user",
                password="pass",
            )
        return client

    def test_ping_handles_connection_error(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_orthanc = MagicMock()
        mock_orthanc.get.side_effect = httpx.ConnectError("Connection refused")
        client._orthanc_client = mock_orthanc
        assert client.ping() is False

    def test_ping_handles_timeout(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_orthanc = MagicMock()
        mock_orthanc.get.side_effect = httpx.TimeoutException("timeout")
        client._orthanc_client = mock_orthanc
        assert client.ping() is False

    def test_query_studies_handles_invalid_json(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_client.get.return_value = mock_response
        client._client = mock_client

        with pytest.raises(json.JSONDecodeError):
            client.query_studies()

    def test_query_studies_handles_http_500(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_client.get.return_value = mock_response
        client._client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            client.query_studies()

    def test_download_instance_handles_connection_error(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        client._cancel_event = MagicMock()
        client._cancel_event.is_set.return_value = False
        mock_orthanc = MagicMock()
        mock_orthanc.post.side_effect = httpx.ConnectError("refused")
        client._orthanc_client = mock_orthanc

        with pytest.raises(httpx.ConnectError):
            client.download_instance("1.2.3", "4.5.6", "7.8.9")

    def test_stow_handles_empty_list(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        result = client.stow_instances([])
        assert result.success_count == 0


class TestSqlInjectionInApiParams:
    """Verify SQL injection payloads in API parameters don't cause issues."""

    @pytest.mark.parametrize(
        "payload",
        [
            "'; DROP TABLE studies; --",
            "1' OR '1'='1",
            "admin'--",
            "Robert'); DROP TABLE Users;--",
            "1; SELECT * FROM users",
        ],
    )
    def test_sql_injection_in_patient_name(self, payload: str) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []
        mock_client.get.return_value = mock_response
        client._client = mock_client

        client.query_studies(patient_name=payload)

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", []))
        # Find the PatientName param specifically (value wrapped with wildcards)
        patient_params = [(k, v) for k, v in params if k == "PatientName"]
        assert len(patient_params) >= 1, "PatientName param not found"
        _, patient_value = patient_params[0]
        assert payload in patient_value


class TestXssInApiResponses:
    """Verify XSS payloads in API responses are treated as plain text."""

    @pytest.mark.parametrize(
        "xss_payload",
        [
            '<script>alert("xss")</script>',
            "<img src=x onerror=alert(1)>",
            "javascript:alert(1)",
            '<svg onload=alert("xss")>',
            "{{7*7}}",
            "${7*7}",
        ],
    )
    def test_xss_in_patient_name(self, xss_payload: str) -> None:
        payload = [
            {
                "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
                "00100010": {"vr": "PN", "Value": [{"Alphabetic": xss_payload}]},
                "00100020": {"vr": "LO", "Value": ["P001"]},
                "00080020": {"vr": "DA", "Value": ["20250101"]},
                "00081030": {"vr": "LO", "Value": ["Test"]},
            }
        ]
        result = parse_studies(payload)
        assert result[0].patient_name == xss_payload
        assert isinstance(result[0].patient_name, str)

    def test_xss_in_study_description(self) -> None:
        xss = "<script>document.cookie</script>"
        payload = [
            {
                "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
                "00100010": {"vr": "PN", "Value": [{"Alphabetic": "Test"}]},
                "00100020": {"vr": "LO", "Value": ["P001"]},
                "00080020": {"vr": "DA", "Value": ["20250101"]},
                "00081030": {"vr": "LO", "Value": [xss]},
            }
        ]
        result = parse_studies(payload)
        assert result[0].study_description == xss
