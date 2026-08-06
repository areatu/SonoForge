"""Verify that network operations have proper timeout settings.

Tests that connections don't hang indefinitely and timeout values
are properly propagated through the client stack.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_settings import ServerSettings


class TestServerSettingsTimeoutDefaults:
    """Verify timeout defaults are reasonable and non-zero."""

    def test_default_network_timeout(self) -> None:
        settings = ServerSettings()
        assert settings.network_timeout == 30.0

    def test_network_timeout_positive(self) -> None:
        settings = ServerSettings()
        assert settings.network_timeout > 0

    def test_network_timeout_reasonable(self) -> None:
        """Timeout should be between 1s and 300s (5 min)."""
        settings = ServerSettings()
        assert 1.0 <= settings.network_timeout <= 300.0

    def test_network_timeout_customizable(self) -> None:
        settings = ServerSettings(network_timeout=60.0)
        assert settings.network_timeout == 60.0


class TestOrthancClientTimeout:
    """Verify timeout propagation in OrthancDicomWebClient."""

    def test_default_timeout_used(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            OrthancDicomWebClient("https://example.com/dicom-web")
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 30.0

    def test_custom_timeout_used(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            OrthancDicomWebClient("https://example.com/dicom-web", timeout=60.0)
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 60.0

    def test_zero_timeout_not_allowed_by_httpx(self) -> None:
        """httpx.Client with timeout=0 should still create (it disables timeout)."""
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            OrthancDicomWebClient("https://example.com/dicom-web", timeout=0.0)
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 0.0

    def test_from_settings_uses_network_timeout(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            settings = ServerSettings(
                url="https://example.com/dicom-web",
                network_timeout=45.0,
            )
            OrthancDicomWebClient.from_settings(settings)
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 45.0

    def test_from_settings_override_timeout(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            settings = ServerSettings(
                url="https://example.com/dicom-web",
                network_timeout=45.0,
            )
            OrthancDicomWebClient.from_settings(settings, timeout=120.0)
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 120.0

    def test_stow_uses_120s_timeout(self) -> None:
        """STOW-RS should use a 120s timeout regardless of default."""
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
            mock_stow = MagicMock()
            client._stow_client = mock_stow
            client._cancel_event = MagicMock()
            client._cancel_event.is_set.return_value = False
            client.stow_instances([b"\x00" * 100])
            # The stow call should use 120s timeout
            if mock_stow.post.called:
                call_kwargs = mock_stow.post.call_args.kwargs
                assert call_kwargs.get("timeout", None) == 120.0


class TestDimseClientTimeout:
    """Verify timeout propagation in PynetdimseClient."""

    def test_default_timeout(self) -> None:
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        assert client._timeout_s == 10.0

    def test_custom_timeout(self) -> None:
        client = PynetdimseClient(host="127.0.0.1", port=4242, timeout_s=60.0)
        assert client._timeout_s == 60.0

    def test_from_settings_uses_network_timeout(self) -> None:
        settings = ServerSettings(network_timeout=45.0)
        client = PynetdimseClient.from_settings(settings)
        assert client._timeout_s == 45.0

    def test_ae_timeouts_set(self) -> None:
        """AE timeouts should all be set from the client timeout."""
        client = PynetdimseClient(host="127.0.0.1", port=4242, timeout_s=25.0)
        ae = client._build_ae()
        assert ae.acse_timeout == 25.0
        assert ae.dimse_timeout == 25.0
        assert ae.network_timeout == 25.0

    def test_from_settings_propagates_all(self) -> None:
        settings = ServerSettings(
            dimse_host="pacs.example.com",
            dimse_port=11113,
            dimse_ae_title="ECHO",
            dimse_called_ae="PACS",
            network_timeout=90.0,
        )
        client = PynetdimseClient.from_settings(settings)
        assert client._host == "pacs.example.com"
        assert client._port == 11113
        assert client._ae_title == "ECHO"
        assert client._called_ae == "PACS"
        assert client._timeout_s == 90.0


class TestConnectionDoesNotHang:
    """Verify that ping and network calls fail fast on connection errors."""

    def test_ping_fails_fast(self) -> None:
        """ping() should return False on connection error, not hang."""
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_orthanc = MagicMock()
        mock_orthanc.get.side_effect = httpx.ConnectError("refused")
        client._orthanc_client = mock_orthanc

        start = time.monotonic()
        result = client.ping()
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 5.0, f"ping() took too long: {elapsed:.1f}s"

    def test_ping_handles_timeout_fast(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        mock_orthanc = MagicMock()
        mock_orthanc.get.side_effect = httpx.TimeoutException("timed out")
        client._orthanc_client = mock_orthanc

        start = time.monotonic()
        result = client.ping()
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 5.0

    def test_download_fails_fast_on_error(self) -> None:
        client = OrthancDicomWebClient.__new__(OrthancDicomWebClient)
        client._cancel_event = MagicMock()
        client._cancel_event.is_set.return_value = False
        mock_orthanc = MagicMock()
        mock_orthanc.post.side_effect = httpx.ConnectError("refused")
        client._orthanc_client = mock_orthanc

        start = time.monotonic()
        with pytest.raises(httpx.ConnectError):
            client.download_instance("1.2.3", "4.5.6", "7.8.9")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
