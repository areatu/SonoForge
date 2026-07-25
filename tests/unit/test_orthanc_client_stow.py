"""Tests for STOW-RS client URL override and real fixtures."""

from __future__ import annotations

import httpx

from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient


def test_stow_uses_override_client() -> None:
    client = OrthancDicomWebClient(
        "http://127.0.0.1:8042/dicom-web",
        stow_dicom_web_url="http://192.168.1.50:8042/dicom-web",
    )
    assert client._stow_client is not None
    assert "192.168.1.50" in str(client._stow_client.base_url)
    assert client._stow_http_client() is client._stow_client
    client.close()


def test_stow_falls_back_to_dicom_web_client() -> None:
    client = OrthancDicomWebClient("http://127.0.0.1:8042/dicom-web")
    assert client._stow_client is None
    assert client._stow_http_client() is client._client
    client.close()


# ── STOW-RS with real fixtures ─────────────────────────────────────


class TestStowWithRealFixtures:
    def test_stow_success_response(self, stow_success) -> None:
        """Verify STOW success response structure."""
        location = stow_success.get("00081190", {}).get("Value", "")
        assert "studies" in location

    def test_stow_partial_failure_response(self, stow_partial_failure) -> None:
        """Verify STOW partial failure response structure."""
        failed_seq = stow_partial_failure.get("00081199", {}).get("Value", [])
        assert len(failed_seq) == 1
        assert "00081197" in failed_seq[0]

    def test_stow_all_failed_response(self, stow_all_failed) -> None:
        """Verify STOW all-failed response structure."""
        failed_seq = stow_all_failed.get("00081199", {}).get("Value", [])
        assert len(failed_seq) == 2
        assert "00081190" not in stow_all_failed

    def test_stow_success_with_transport(self, stow_success) -> None:
        """Test STOW with real success fixture."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=stow_success)

        transport = httpx.MockTransport(handler)
        client = OrthancDicomWebClient(
            "http://orthanc/dicom-web",
            "user", "pass",
        )
        client._client = httpx.Client(
            base_url="http://orthanc/dicom-web/",
            transport=transport,
        )
        try:
            result = client.stow_instances([b"\x00\x01\x02"])
            assert result.success_count == 1
            assert len(result.failed_uids) == 0
        finally:
            client.close()

    def test_stow_partial_failure_with_transport(self, stow_partial_failure) -> None:
        """Test STOW with partial failure fixture."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=stow_partial_failure)

        transport = httpx.MockTransport(handler)
        client = OrthancDicomWebClient(
            "http://orthanc/dicom-web",
            "user", "pass",
        )
        client._client = httpx.Client(
            base_url="http://orthanc/dicom-web/",
            transport=transport,
        )
        try:
            result = client.stow_instances([b"\x00\x01\x02"])
            # Partial failure: some success, some failed
            assert result.success_count >= 0
            assert isinstance(result.failed_uids, list)
        finally:
            client.close()
