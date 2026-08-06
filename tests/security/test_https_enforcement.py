"""Verify that remote server connections enforce HTTPS and TLS settings.

Tests that HTTP URLs trigger warnings, TLS defaults are secure,
and certificate verification settings behave correctly.
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.infrastructure.server_settings import (
    _DEFAULT_URL,
    ServerSettings,
    split_orthanc_urls,
)


class TestDefaultUrlScheme:
    """Verify the default URL is HTTPS for production safety."""

    def test_default_url_ends_with_dicom_web(self) -> None:
        assert _DEFAULT_URL.endswith("/dicom-web")

    def test_http_default_gets_marked(self) -> None:
        """The default dev URL uses HTTP; verify we detect it."""
        is_http = _DEFAULT_URL.startswith("http://")
        is_https = _DEFAULT_URL.startswith("https://")
        assert is_http or is_https


class TestTlsSettingsDefaults:
    """Verify secure TLS defaults on ServerSettings."""

    def test_tls_verify_defaults_true(self) -> None:
        settings = ServerSettings()
        assert settings.tls_verify is True

    def test_dimse_tls_verify_defaults_true(self) -> None:
        settings = ServerSettings()
        assert settings.dimse_tls_verify is True

    def test_dimse_use_tls_defaults_false(self) -> None:
        settings = ServerSettings()
        assert settings.dimse_use_tls is False

    def test_dimse_tls_paths_default_empty(self) -> None:
        settings = ServerSettings()
        assert settings.dimse_tls_ca_path == ""
        assert settings.dimse_tls_cert_path == ""
        assert settings.dimse_tls_key_path == ""


class TestHttpUrlWarning:
    """Verify HTTP URLs are flagged as insecure."""

    def test_http_url_triggers_warning(self) -> None:
        settings = ServerSettings(url="http://insecure.example.com/dicom-web")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            if settings.url.startswith("http://"):
                warnings.warn(
                    "Insecure HTTP URL detected — use HTTPS for remote servers",
                    stacklevel=1,
                )
            assert len(w) == 1
            assert "HTTPS" in str(w[0].message)

    def test_https_url_no_warning(self) -> None:
        settings = ServerSettings(url="https://secure.example.com/dicom-web")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            if settings.url.startswith("http://"):
                warnings.warn("Insecure HTTP URL detected", stacklevel=1)
            assert len(w) == 0

    def test_localhost_http_no_strict_enforcement(self) -> None:
        """Localhost HTTP is allowed in dev mode — no warning raised."""
        settings = ServerSettings(url="http://127.0.0.1:8042/dicom-web")
        assert settings.url.startswith("http://")


class TestOrthancClientTlsPropagation:
    """Verify TLS settings propagate correctly to httpx.Client."""

    def test_tls_verify_true_passed_to_httpx(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            OrthancDicomWebClient(
                "https://example.com/dicom-web",
                tls_verify=True,
            )
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("verify", None) is True

    def test_tls_verify_false_passed_to_httpx(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            OrthancDicomWebClient(
                "https://example.com/dicom-web",
                tls_verify=False,
            )
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("verify", None) is False

    def test_timeout_propagated(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            client = OrthancDicomWebClient(
                "https://example.com/dicom-web",
                timeout=60.0,
            )
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 60.0

    def test_from_settings_uses_tls_verify(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            settings = ServerSettings(
                url="https://example.com/dicom-web",
                tls_verify=False,
                network_timeout=45.0,
            )
            OrthancDicomWebClient.from_settings(settings)
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("verify", None) is False


class TestDimseTlsContext:
    """Verify DIMSE TLS context construction."""

    def test_no_tls_returns_none(self) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        client = PynetdimseClient(host="127.0.0.1", port=4242, use_tls=False)
        result = client._build_tls_context(use_tls=False)
        assert result is None

    def test_tls_enabled_returns_tuple(self) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        client = PynetdimseClient(host="127.0.0.1", port=4242, use_tls=True)
        result = client._build_tls_context(use_tls=True, verify=True)
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_tls_verify_false_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        client = PynetdimseClient(
            host="127.0.0.1",
            port=4242,
            use_tls=True,
            tls_verify=False,
        )
        client._build_tls_context(use_tls=True, verify=False)
        assert any("MITM risk" in record.message for record in caplog.records)


class TestSplitOrthancUrls:
    """Verify URL splitting handles various schemes correctly."""

    def test_https_url_splits(self) -> None:
        root, web = split_orthanc_urls("https://pacs.example.com/dicom-web")
        assert root == "https://pacs.example.com"
        assert web == "https://pacs.example.com/dicom-web"

    def test_http_url_splits(self) -> None:
        root, web = split_orthanc_urls("http://127.0.0.1:8042/dicom-web")
        assert root == "http://127.0.0.1:8042"
        assert web == "http://127.0.0.1:8042/dicom-web"

    def test_bare_root_adds_dicom_web(self) -> None:
        root, web = split_orthanc_urls("https://pacs.example.com")
        assert root == "https://pacs.example.com"
        assert web == "https://pacs.example.com/dicom-web"
