"""Extended unit tests for infrastructure/orthanc_client.py — covers ping, download, close, from_settings, cancel."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from echo_personal_tool.infrastructure.orthanc_client import (
    DownloadCancelled,
    OrthancDicomWebClient,
    _build_stow_multipart_body,
    _include_params,
    _parse_stow_response,
)


class TestIncludeParams:
    def test_empty_tags(self):
        assert _include_params(()) == []

    def test_with_tags(self):
        result = _include_params(("00100010", "0020000D"))
        assert result == [
            ("includefield", "00100010"),
            ("includefield", "0020000D"),
        ]


class TestBuildStowMultipartBody:
    def test_empty_files(self):
        body = _build_stow_multipart_body("boundary", [])
        assert b"boundary" in body
        assert body.endswith(b"--boundary--\r\n")

    def test_single_file(self):
        body = _build_stow_multipart_body("b1", [b"\x00\x01"])
        assert b"Content-Type: application/dicom" in body
        assert b"\x00\x01" in body

    def test_multiple_files(self):
        body = _build_stow_multipart_body("b1", [b"\x00", b"\x01", b"\x02"])
        assert body.count(b"Content-Type: application/dicom") == 3


class TestParseStowResponse:
    def test_non_list_input(self):
        result = _parse_stow_response("invalid", 5)
        assert result.success_count == 5
        assert result.failed_uids == []

    def test_empty_list(self):
        result = _parse_stow_response([], 3)
        assert result.success_count == 3

    def test_no_failures(self):
        result = _parse_stow_response([{}, {}], 2)
        assert result.success_count == 2

    def test_with_failures(self):
        data = [
            {"00081199": [{"00081155": {"Value": ["uid1"]}}]},
        ]
        result = _parse_stow_response(data, 3)
        assert result.success_count == 2
        assert result.failed_uids == ["uid1"]

    def test_non_dict_items_ignored(self):
        result = _parse_stow_response(["not a dict", 42], 2)
        assert result.success_count == 2

    def test_missing_uid_in_failure(self):
        data = [{"00081199": [{"00081155": {}}]}]
        result = _parse_stow_response(data, 1)
        assert result.success_count == 1

    def test_nested_failure_no_value_key(self):
        data = [{"00081199": [{"other_key": {}}]}]
        result = _parse_stow_response(data, 2)
        assert result.success_count == 2

    def test_failed_seq_not_list(self):
        data = [{"00081199": "not a list"}]
        result = _parse_stow_response(data, 1)
        assert result.success_count == 1


class TestOrthancDicomWebClientConstruction:
    def test_basic_construction(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        assert client._stow_client is None
        client.close()

    def test_with_stow_url(self):
        client = OrthancDicomWebClient(
            "http://localhost:8042/dicom-web",
            stow_dicom_web_url="http://other:8042/dicom-web",
        )
        assert client._stow_client is not None
        client.close()

    def test_with_auth(self):
        client = OrthancDicomWebClient(
            "http://localhost:8042/dicom-web",
            username="user",
            password="pass",
        )
        # httpx stores auth as a BasicAuth object when given tuple
        assert client._orthanc_client._auth is not None
        client.close()

    def test_no_auth_without_credentials(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        assert client._orthanc_client._auth is None
        client.close()

    def test_auth_header_overrides_basic(self):
        client = OrthancDicomWebClient(
            "http://localhost:8042/dicom-web",
            username="user",
            password="pass",
            http_headers={"Authorization": "Bearer token"},
        )
        assert client._orthanc_client._auth is None
        client.close()

    def test_from_settings(self):
        from echo_personal_tool.infrastructure.server_settings import ServerSettings

        settings = ServerSettings(
            url="http://10.0.0.1:8042/dicom-web",
            username="admin",
            password="secret",
            auth_mode="basic",
            stow_dicom_web_url="http://10.0.0.1:8043/dicom-web",
            network_timeout=15.0,
            tls_verify=False,
        )
        client = OrthancDicomWebClient.from_settings(settings)
        assert client._timeout == 15.0
        client.close()

    def test_from_settings_custom_timeout(self):
        from echo_personal_tool.infrastructure.server_settings import ServerSettings

        settings = ServerSettings(url="http://x:8042/dicom-web")
        client = OrthancDicomWebClient.from_settings(settings, timeout=5.0)
        assert client._timeout == 5.0
        client.close()


class TestOrthancPing:
    def test_ping_success(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        mock_response = MagicMock()
        mock_response.status_code = 200
        client._orthanc_client.get = MagicMock(return_value=mock_response)
        assert client.ping() is True
        client.close()

    def test_ping_failure_http_error(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        client._orthanc_client.get = MagicMock(side_effect=httpx.HTTPError("err"))
        assert client.ping() is False
        client.close()

    def test_ping_failure_status_code(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        mock_response = MagicMock()
        mock_response.status_code = 500
        client._orthanc_client.get = MagicMock(return_value=mock_response)
        assert client.ping() is False
        client.close()


class TestDownloadCancelled:
    def test_exception_message(self):
        exc = DownloadCancelled("test")
        assert str(exc) == "test"


class TestCancelInflight:
    def test_cancel_sets_event(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        client.cancel_inflight()
        assert client._cancel_event.is_set()
        client.close()

    def test_check_cancelled_raises(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        client._cancel_event.set()
        with pytest.raises(DownloadCancelled):
            client._check_cancelled()
        client.close()


class TestClose:
    def test_close_no_error(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        client.close()

    def test_close_with_stow(self):
        client = OrthancDicomWebClient(
            "http://localhost:8042/dicom-web",
            stow_dicom_web_url="http://other:8042/dicom-web",
        )
        client.close()


class TestStowInstances:
    def test_empty_files(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        result = client.stow_instances([])
        assert result.success_count == 0
        client.close()

    def test_stow_batching(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        client._stow_http_client = MagicMock(return_value=mock_http)
        files = [b"\x00" for _ in range(15)]
        result = client.stow_instances(files)
        assert result.success_count == 15
        client.close()

    def test_stow_http_error(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.HTTPError("timeout")
        client._stow_http_client = MagicMock(return_value=mock_http)
        result = client.stow_instances([b"\x00"])
        assert result.success_count == 0
        assert "timeout" in result.error_message
        client.close()

    def test_stow_non_200_status(self):
        client = OrthancDicomWebClient("http://localhost:8042/dicom-web")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        client._stow_http_client = MagicMock(return_value=mock_http)
        result = client.stow_instances([b"\x00"])
        assert result.success_count == 0
        client.close()
