"""Shared fixtures for Orthanc DICOMweb tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ORTHANC_FIXTURES = Path(__file__).parent


@pytest.fixture()
def orthanc_fixtures_dir() -> Path:
    """Return the path to orthanc fixtures directory."""
    return ORTHANC_FIXTURES


@pytest.fixture()
def qido_studies_single() -> list[dict]:
    """Load single study QIDO-RS response."""
    with open(ORTHANC_FIXTURES / "qido" / "studies_single.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_studies_multi() -> list[dict]:
    """Load multiple studies QIDO-RS response."""
    with open(ORTHANC_FIXTURES / "qido" / "studies_multi.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_studies_empty() -> list[dict]:
    """Load empty QIDO-RS response."""
    with open(ORTHANC_FIXTURES / "qido" / "studies_empty.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_series_echo() -> list[dict]:
    """Load echo series QIDO-RS response."""
    with open(ORTHANC_FIXTURES / "qido" / "series_echo.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_series_ct() -> list[dict]:
    """Load CT series QIDO-RS response."""
    with open(ORTHANC_FIXTURES / "qido" / "series_ct.json") as f:
        return json.load(f)


@pytest.fixture()
def wado_instance_metadata() -> dict:
    """Load WADO-RS instance metadata."""
    with open(ORTHANC_FIXTURES / "wado" / "instance_metadata.json") as f:
        return json.load(f)


@pytest.fixture()
def wado_instances_echo() -> list[dict]:
    """Load WADO-RS echo instances."""
    with open(ORTHANC_FIXTURES / "wado" / "instances_echo.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_success() -> dict:
    """Load successful STOW-RS response."""
    with open(ORTHANC_FIXTURES / "stow" / "success.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_partial_failure() -> dict:
    """Load partial failure STOW-RS response."""
    with open(ORTHANC_FIXTURES / "stow" / "partial_failure.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_all_failed() -> dict:
    """Load all-failed STOW-RS response."""
    with open(ORTHANC_FIXTURES / "stow" / "all_failed.json") as f:
        return json.load(f)


@pytest.fixture()
def error_500() -> dict:
    """Load 500 error response."""
    with open(ORTHANC_FIXTURES / "errors" / "500_internal.json") as f:
        return json.load(f)


@pytest.fixture()
def error_401() -> dict:
    """Load 401 error response."""
    with open(ORTHANC_FIXTURES / "errors" / "401_unauthorized.json") as f:
        return json.load(f)


@pytest.fixture()
def error_404() -> dict:
    """Load 404 error response."""
    with open(ORTHANC_FIXTURES / "errors" / "404_not_found.json") as f:
        return json.load(f)


@pytest.fixture()
def error_408() -> dict:
    """Load 408 error response."""
    with open(ORTHANC_FIXTURES / "errors" / "408_timeout.json") as f:
        return json.load(f)
