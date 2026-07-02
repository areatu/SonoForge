"""Tests for STOW-RS client URL override."""

from __future__ import annotations

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
