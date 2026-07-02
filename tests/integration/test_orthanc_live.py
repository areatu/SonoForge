"""Live Orthanc integration tests (DICOMweb + optional local DIMSE).

Run against the public UCLouvain demo (read-only):

  ECHO_ORTHANC=1 pytest tests/integration/test_orthanc_live.py -v

Optional overrides:

  ECHO_ORTHANC_URL=https://orthanc.uclouvain.be/demo/dicom-web

Local DIMSE (C-ECHO / C-FIND) additionally requires:

  ECHO_ORTHANC_DIMSE=1 ECHO_ORTHANC_DIMSE_HOST=127.0.0.1
"""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_settings import ServerSettings
from tests.integration.conftest import (
    orthanc_integration_enabled,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not orthanc_integration_enabled(),
        reason="Set ECHO_ORTHANC=1 to run live Orthanc integration tests",
    ),
]


@pytest.fixture
def live_client(orthanc_server_settings: ServerSettings) -> OrthancDicomWebClient:
    client = OrthancDicomWebClient.from_settings(orthanc_server_settings)
    yield client
    client.close()


def test_live_orthanc_ping(live_client: OrthancDicomWebClient) -> None:
    assert live_client.ping() is True


def test_live_qido_query_studies(live_client: OrthancDicomWebClient) -> None:
    studies = live_client.query_studies()
    assert isinstance(studies, list)
    assert len(studies) >= 1
    assert studies[0].study_uid


def test_live_qido_query_series(live_client: OrthancDicomWebClient) -> None:
    studies = live_client.query_studies()
    assert studies
    series = live_client.query_series(studies[0].study_uid)
    assert isinstance(series, list)
    assert len(series) >= 1
    assert series[0].series_uid


def test_live_wado_download_instance(live_client: OrthancDicomWebClient) -> None:
    studies = live_client.query_studies()
    assert studies
    series_list = live_client.query_series(studies[0].study_uid)
    assert series_list
    instances = live_client.query_instances(
        studies[0].study_uid,
        series_list[0].series_uid,
    )
    if not instances:
        pytest.skip("Demo server returned no instances for first series")
    payload = live_client.download_instance(
        studies[0].study_uid,
        series_list[0].series_uid,
        instances[0].sop_instance_uid,
    )
    assert len(payload) > 132
    assert payload.startswith(b"\x00") or b"DICM" in payload[:132]


def test_live_dimse_c_echo(orthanc_dimse_settings: ServerSettings) -> None:
    client = PynetdimseClient.from_settings(orthanc_dimse_settings)
    assert client.c_echo() is True


def test_live_dimse_c_find_studies(orthanc_dimse_settings: ServerSettings) -> None:
    client = PynetdimseClient.from_settings(orthanc_dimse_settings)
    studies = client.c_find_studies()
    assert isinstance(studies, list)
