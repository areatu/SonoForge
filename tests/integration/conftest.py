"""Shared fixtures for live Orthanc integration tests."""

from __future__ import annotations

import os

import pytest

from echo_personal_tool.infrastructure.server_settings import ServerSettings

# Public read-only demo (UCLouvain) — default for CI/manual smoke tests.
DEFAULT_ORTHANC_DICOM_WEB_URL = "https://orthanc.uclouvain.be/demo/dicom-web"
DEFAULT_ORTHANC_ORTHANC_ROOT = "https://orthanc.uclouvain.be/demo"


def orthanc_integration_enabled() -> bool:
    return os.environ.get("ECHO_ORTHANC", "") == "1"


def orthanc_dimse_integration_enabled() -> bool:
    return os.environ.get("ECHO_ORTHANC_DIMSE", "") == "1"


def orthanc_retrieval_mode() -> str:
    """Return retrieval mode: 'wado', 'dimse', or 'cmove'."""
    return os.environ.get("ECHO_ORTHANC_RETRIEVAL", "wado").lower()


@pytest.fixture
def orthanc_dicom_web_url() -> str:
    return os.environ.get("ECHO_ORTHANC_URL", DEFAULT_ORTHANC_DICOM_WEB_URL).strip()


@pytest.fixture
def orthanc_server_settings(orthanc_dicom_web_url: str) -> ServerSettings:
    return ServerSettings(
        url=orthanc_dicom_web_url,
        use_mock=False,
        auth_mode="none",
        dimse_enabled=False,
    )


@pytest.fixture
def orthanc_dimse_settings() -> ServerSettings:
    if not orthanc_dimse_integration_enabled():
        pytest.skip("Set ECHO_ORTHANC_DIMSE=1 for live DIMSE tests")
    host = os.environ.get("ECHO_ORTHANC_DIMSE_HOST", "127.0.0.1")
    port = int(os.environ.get("ECHO_ORTHANC_DIMSE_PORT", "4242"))
    called_ae = os.environ.get("ECHO_ORTHANC_DIMSE_CALLED_AE", "ORTHANC")
    retrieval_source = orthanc_retrieval_mode()
    return ServerSettings(
        url=os.environ.get("ECHO_ORTHANC_URL", DEFAULT_ORTHANC_DICOM_WEB_URL),
        use_mock=False,
        dimse_enabled=True,
        dimse_host=host,
        dimse_port=port,
        dimse_called_ae=called_ae,
        dimse_ae_title=os.environ.get("ECHO_ORTHANC_DIMSE_AE", "ECHO2026"),
        retrieval_source=retrieval_source,
        dimse_scp_host=os.environ.get("ECHO_ORTHANC_DIMSE_SCP_HOST", "127.0.0.1"),
        dimse_scp_port=int(os.environ.get("ECHO_ORTHANC_DIMSE_SCP_PORT", "11112")),
        dimse_scp_ae_title=os.environ.get("ECHO_ORTHANC_DIMSE_SCP_AE", "ECHO2026"),
    )
