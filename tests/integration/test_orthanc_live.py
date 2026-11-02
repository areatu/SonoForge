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


def test_live_dimse_c_get_instance(orthanc_dimse_settings: ServerSettings) -> None:
    """Test C-GET retrieval (requires local Orthanc with DIMSE enabled)."""
    if orthanc_dimse_settings.retrieval_source not in ("dimse", "auto"):
        pytest.skip("C-GET test requires retrieval_source=dimse or auto")
    client = PynetdimseClient.from_settings(orthanc_dimse_settings)
    studies = client.c_find_studies()
    if not studies:
        pytest.skip("No studies found")
    series_list = client.c_find_series(studies[0].study_uid)
    if not series_list:
        pytest.skip("No series found")
    instances = client.c_find_instances(studies[0].study_uid, series_list[0].series_uid)
    if not instances:
        pytest.skip("No instances found")
    data = client.c_get_instance(
        studies[0].study_uid,
        series_list[0].series_uid,
        instances[0].sop_instance_uid,
    )
    assert len(data) > 132
    assert b"DICM" in data[:132] or data.startswith(b"\x00")


def test_live_dimse_c_move_series(orthanc_dimse_settings: ServerSettings) -> None:
    """Test C-MOVE retrieval (requires local Orthanc with modality configured)."""
    if orthanc_dimse_settings.retrieval_source != "cmove":
        pytest.skip("C-MOVE test requires retrieval_source=cmove")
    client = PynetdimseClient.from_settings(orthanc_dimse_settings)
    from echo_personal_tool.infrastructure.embedded_storage_scp import (
        EmbeddedStorageSCP,
    )

    scp_host = orthanc_dimse_settings.dimse_scp_host
    scp_port = orthanc_dimse_settings.dimse_scp_port
    scp_ae = orthanc_dimse_settings.dimse_scp_ae_title or orthanc_dimse_settings.dimse_ae_title

    studies = client.c_find_studies()
    if not studies:
        pytest.skip("No studies found")
    series_list = client.c_find_series(studies[0].study_uid)
    if not series_list:
        pytest.skip("No series found")

    with EmbeddedStorageSCP(
        host=scp_host,
        port=scp_port,
        ae_title=scp_ae,
    ) as scp:
        received: dict[str, bytes] = {}
        result = client.c_move_series(
            studies[0].study_uid,
            series_list[0].series_uid,
            move_destination_ae=scp_ae,
            scp_host=scp_host,
            scp_port=scp_port,
            received=received,
        )
        assert result.completed > 0 or result.failed > 0
        # Instances arrive via embedded SCP (not the unused `received` param on client)
        if result.completed > 0:
            assert len(scp.instances) > 0


def test_live_dicom_retrieve_service_cget(orthanc_dimse_settings: ServerSettings) -> None:
    """Test DicomRetrieveService with C-GET adapter."""
    from echo_personal_tool.application.services.dicom_retrieve_service import (
        make_retrieve_service,
    )

    if orthanc_dimse_settings.retrieval_source not in ("dimse", "auto"):
        pytest.skip("Requires retrieval_source=dimse or auto")

    client = PynetdimseClient.from_settings(orthanc_dimse_settings)
    service = make_retrieve_service(
        orthanc_dimse_settings,
        dimse_client=client,
    )

    studies = client.c_find_studies()
    if not studies:
        pytest.skip("No studies found")
    series_list = client.c_find_series(studies[0].study_uid)
    if not series_list:
        pytest.skip("No series found")
    instances = client.c_find_instances(studies[0].study_uid, series_list[0].series_uid)
    if not instances:
        pytest.skip("No instances found")

    data = service.retrieve_instance(
        studies[0].study_uid,
        series_list[0].series_uid,
        instances[0].sop_instance_uid,
    )
    assert len(data) > 132
