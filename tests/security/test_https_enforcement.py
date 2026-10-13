"""Verify that remote server connections enforce HTTPS and TLS settings.

Tests that the shipped defaults are judged by the transport policy (QH-2b),
TLS defaults are secure, and certificate verification settings propagate
into every transport the clients build.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.application.transport_policy import (
    HostKind,
    InsecureException,
    evaluate_dicomweb_url,
    evaluate_dimse,
    evaluate_profile,
    parse_dicomweb_endpoint,
)
from echo_personal_tool.infrastructure.server_settings import (
    _DEFAULT_URL,
    ServerSettings,
    split_orthanc_urls,
)


class TestDefaultUrlScheme:
    """The shipped default profile is a loopback DICOMweb root, judged as such by the policy."""

    def test_default_url_ends_with_dicom_web(self) -> None:
        assert _DEFAULT_URL.endswith("/dicom-web")

    def test_default_profile_is_a_parsed_loopback_local_profile(self) -> None:
        """Plaintext is tolerated for the default only because the parsed host is loopback."""
        settings = ServerSettings()
        endpoint = parse_dicomweb_endpoint(settings.url, tls_verify=settings.tls_verify)
        assert endpoint.scheme == "http"
        assert endpoint.host_kind is HostKind.LOOPBACK
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.allowed
        assert decision.code == "allow-loopback"
        profile = evaluate_profile(
            url=settings.url,
            tls_verify=settings.tls_verify,
            tls_ca_path=settings.tls_ca_path,
            stow_url=settings.stow_dicom_web_url,
            dimse_enabled=True,
            dimse_host=settings.dimse_host,
            dimse_port=settings.dimse_port,
            dimse_use_tls=settings.dimse_use_tls,
            dimse_tls_verify=settings.dimse_tls_verify,
        )
        assert profile.allowed
        assert profile.insecure is False


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


class TestHttpUrlPolicy:
    """Remote plaintext / unverified profiles are blocked by the policy, not merely warned about.

    The decision comes from the real evaluator (QH-2b slice 1); the production
    clients adopt it in slice 2 (0 network requests before the user decides).
    """

    def test_remote_http_profile_is_blocked_until_a_scoped_exception(self) -> None:
        settings = ServerSettings(url="http://insecure.example.com/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.blocked
        assert decision.code == "block-plaintext-remote"
        assert decision.requires_exception is True
        assert "https://" in decision.findings[0].message

    def test_private_lan_http_profile_is_remote_too(self) -> None:
        """The settings-dialog placeholder address is RFC1918 — a LAN is not evidence of trust."""
        settings = ServerSettings(url="http://192.168.1.111:8042/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.blocked and decision.code == "block-plaintext-remote"

    def test_https_profile_with_verification_is_allowed_without_findings(self) -> None:
        settings = ServerSettings(url="https://secure.example.com/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.allowed and decision.code == "allow"
        assert decision.findings == ()

    def test_https_profile_with_verification_disabled_is_blocked(self) -> None:
        settings = ServerSettings(url="https://secure.example.com/dicom-web", tls_verify=False)
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.blocked and decision.code == "block-tls-unverified"

    def test_loopback_http_profile_stays_a_local_profile(self) -> None:
        settings = ServerSettings(url="http://127.0.0.1:8042/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.allowed and decision.code == "allow-loopback"

    def test_loopback_look_alike_profile_is_not_a_local_profile(self) -> None:
        for url in ("http://localhost.attacker.example:8042/dicom-web", "http://127.0.0.1.nip.io:8042/dicom-web"):
            settings = ServerSettings(url=url)
            decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
            assert decision.blocked, url

    def test_exception_is_scoped_to_the_exact_endpoint(self) -> None:
        settings = ServerSettings(url="http://insecure.example.com:8042/dicom-web")
        exception = InsecureException.for_endpoint(parse_dicomweb_endpoint(settings.url))
        assert evaluate_dicomweb_url(settings.url, exceptions=[exception]).code == "allow-by-exception"
        moved = ServerSettings(url="http://insecure.example.com:8043/dicom-web")
        assert evaluate_dicomweb_url(moved.url, exceptions=[exception]).blocked

    def test_remote_clear_dimse_profile_is_blocked(self) -> None:
        settings = ServerSettings(dimse_enabled=True, dimse_host="192.168.1.20", dimse_port=104, dimse_use_tls=False)
        decision = evaluate_dimse(settings.dimse_host, settings.dimse_port, use_tls=settings.dimse_use_tls)
        assert decision.blocked and decision.code == "block-dimse-clear-remote"


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
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
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
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
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
            assert client is not None
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
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
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
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
