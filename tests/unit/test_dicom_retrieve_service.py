"""Tests for DicomRetrieveService and adapters."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.services.dicom_retrieve_service import (
    CGetRetrieveAdapter,
    CMoveRetrieveAdapter,
    DicomRetrieveService,
    RetrieveError,
    WadoRetrieveAdapter,
    make_retrieve_service,
)
from echo_personal_tool.domain.ports import CMoveResult
from echo_personal_tool.infrastructure.server_settings import ServerSettings

_STUDY_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.1"
_SERIES_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.2"
_INSTANCE_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.3"
_MOCK_BYTES = b"mock dicom bytes"


class MockDicomWebClient:
    """Mock DicomWebClient for testing."""

    def __init__(self, data: bytes = _MOCK_BYTES):
        self._data = data
        self.download_calls: list[tuple[str, str, str]] = []

    def ping(self) -> bool:
        return True

    def query_studies(self, **kwargs):  # noqa: ANN002, ANN003
        return []

    def query_series(self, study_uid: str):
        return []

    def query_instances(self, study_uid: str, series_uid: str):
        return []

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        self.download_calls.append((study_uid, series_uid, instance_uid))
        return self._data

    def stow_instances(self, dicom_files: list[bytes]):
        pass


class MockDimseClient:
    """Mock DimseClient for testing."""

    def __init__(self, data: bytes = _MOCK_BYTES):
        self._data = data
        self.c_get_calls: list[tuple[str, str, str]] = []
        self.c_move_calls: list[tuple[str, str, list[str], str]] = []

    def c_echo(self) -> bool:
        return True

    def c_find_studies(self, **kwargs):  # noqa: ANN002, ANN003
        return []

    def c_find_series(self, study_uid: str):
        return []

    def c_find_instances(self, study_uid: str, series_uid: str):
        return []

    def c_store(self, dicom_bytes: bytes) -> bool:
        return True

    def c_get_instance(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        *,
        tls_args: tuple | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> bytes:
        self.c_get_calls.append((study_uid, series_uid, instance_uid))
        if is_cancelled and is_cancelled():
            raise DimseAssociationError("C-GET cancelled")
        return self._data

    def c_move_instances(
        self,
        study_uid: str,
        series_uid: str,
        instance_uids: list[str],
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
    ) -> CMoveResult:
        self.c_move_calls.append((study_uid, series_uid, instance_uids, move_destination_ae))
        for uid in instance_uids:
            received[uid] = self._data
        return CMoveResult(completed=len(instance_uids), failed=0, warning=0)


def test_wado_adapter() -> None:
    web_client = MockDicomWebClient()
    adapter = WadoRetrieveAdapter(web_client)

    result = adapter.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)

    assert result == _MOCK_BYTES
    assert web_client.download_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]


def test_cget_adapter() -> None:
    dimse_client = MockDimseClient()
    settings = ServerSettings()
    adapter = CGetRetrieveAdapter(dimse_client, settings)

    result = adapter.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)

    assert result == _MOCK_BYTES
    assert dimse_client.c_get_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]


def test_cmove_adapter() -> None:
    dimse_client = MockDimseClient()
    settings = ServerSettings()
    adapter = CMoveRetrieveAdapter(dimse_client, settings)

    result = adapter.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)

    assert result == _MOCK_BYTES
    assert len(dimse_client.c_move_calls) == 1
    assert dimse_client.c_move_calls[0][2] == [_INSTANCE_UID]


def test_service_with_wado() -> None:
    web_client = MockDicomWebClient()
    service = DicomRetrieveService(
        adapters={"wado": WadoRetrieveAdapter(web_client)},
        default_source="wado",
    )

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID, source="wado")

    assert result == _MOCK_BYTES
    assert web_client.download_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]


def test_service_with_dimse() -> None:
    dimse_client = MockDimseClient()
    service = DicomRetrieveService(
        adapters={"dimse": CGetRetrieveAdapter(dimse_client, ServerSettings())},
        default_source="dimse",
    )

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID, source="dimse")

    assert result == _MOCK_BYTES
    assert dimse_client.c_get_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]


def test_service_auto_mode_wado_preferred() -> None:
    web_client = MockDicomWebClient()
    dimse_client = MockDimseClient()
    service = DicomRetrieveService(
        adapters={
            "wado": WadoRetrieveAdapter(web_client),
            "dimse": CGetRetrieveAdapter(dimse_client, ServerSettings()),
            "auto": WadoRetrieveAdapter(web_client),
        },
        default_source="auto",
    )

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)

    assert result == _MOCK_BYTES
    assert web_client.download_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]
    assert dimse_client.c_get_calls == []


def test_service_unknown_source_raises() -> None:
    service = DicomRetrieveService(adapters={}, default_source="wado")

    with pytest.raises(RetrieveError, match="No adapter for source: wado"):
        service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)


def test_make_retrieve_service_wado_only() -> None:
    web_client = MockDicomWebClient()
    settings = ServerSettings(retrieval_source="wado")

    service = make_retrieve_service(settings, web_client=web_client)

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)
    assert result == _MOCK_BYTES


def test_make_retrieve_service_dimse_only() -> None:
    dimse_client = MockDimseClient()
    settings = ServerSettings(retrieval_source="dimse")

    service = make_retrieve_service(settings, dimse_client=dimse_client)

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)
    assert result == _MOCK_BYTES
    assert dimse_client.c_get_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]


def test_make_retrieve_service_auto_with_wado() -> None:
    web_client = MockDicomWebClient()
    dimse_client = MockDimseClient()
    settings = ServerSettings(retrieval_source="auto")

    service = make_retrieve_service(settings, web_client=web_client, dimse_client=dimse_client)

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)
    assert result == _MOCK_BYTES
    # WADO should be preferred in auto mode when ping succeeds
    assert web_client.download_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]
    assert dimse_client.c_get_calls == []


def test_make_retrieve_service_auto_falls_back_to_dimse_when_wado_unreachable() -> None:
    web_client = MockDicomWebClient()

    class _NoPingWeb(MockDicomWebClient):
        def ping(self) -> bool:
            return False

    web_client = _NoPingWeb()
    dimse_client = MockDimseClient()
    settings = ServerSettings(retrieval_source="auto")

    service = make_retrieve_service(settings, web_client=web_client, dimse_client=dimse_client)

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)
    assert result == _MOCK_BYTES
    assert web_client.download_calls == []
    assert dimse_client.c_get_calls == [(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)]


def test_retrieve_service_cancel_check_propagates_to_cget() -> None:
    dimse_client = MockDimseClient()
    cancelled = {"v": False}

    service = make_retrieve_service(
        ServerSettings(retrieval_source="dimse"),
        dimse_client=dimse_client,
    )
    service.set_cancel_check(lambda: cancelled["v"])
    cancelled["v"] = True

    with pytest.raises(RetrieveError, match="cancelled"):
        service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)


def test_stow_upload_available_requires_url() -> None:
    from echo_personal_tool.infrastructure.server_client_factory import (
        stow_upload_available,
    )

    assert stow_upload_available(ServerSettings(use_mock=True))
    assert not stow_upload_available(ServerSettings(use_mock=False, url=""))
    assert stow_upload_available(ServerSettings(use_mock=False, url="http://x/dicom-web"))


def test_make_retrieve_service_cmove() -> None:
    dimse_client = MockDimseClient()
    settings = ServerSettings(retrieval_source="cmove")

    service = make_retrieve_service(settings, dimse_client=dimse_client)

    result = service.retrieve_instance(_STUDY_UID, _SERIES_UID, _INSTANCE_UID)
    assert result == _MOCK_BYTES
    assert len(dimse_client.c_move_calls) == 1
