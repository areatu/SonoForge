"""Extended tests for DicomRetrieveService covering missing branches."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.application.services.dicom_retrieve_service import (
    CGetRetrieveAdapter,
    CMoveRetrieveAdapter,
    DicomRetrieveService,
    RetrieveError,
    WadoRetrieveAdapter,
    make_retrieve_service,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings

_STUDY = "1.2.3"
_SERIES = "1.2.3.4"
_INSTANCE = "1.2.3.4.5"
_BYTES = b"dicom"


class _MockWeb:
    def __init__(self, ping_return: bool = True):
        self._ping = ping_return

    def ping(self) -> bool:
        return self._ping

    def query_studies(self, **kwargs):
        return []

    def query_series(self, study_uid):
        return []

    def query_instances(self, study_uid, series_uid):
        return []

    def download_instance(self, study_uid, series_uid, instance_uid) -> bytes:
        return _BYTES

    def stow_instances(self, dicom_files):
        return None


class _MockDimse:
    def c_echo(self) -> bool:
        return True

    def c_find_studies(self, **kwargs):
        return []

    def c_find_series(self, study_uid):
        return []

    def c_find_instances(self, study_uid, series_uid):
        return []

    def c_store(self, dicom_bytes) -> bool:
        return True

    def c_get_instance(self, study_uid, series_uid, instance_uid, *, tls_args=None, is_cancelled=None) -> bytes:
        if is_cancelled and is_cancelled():
            raise Exception("cancelled")
        return _BYTES

    def c_move_instances(self, study_uid, series_uid, instance_uids, **kwargs):
        from echo_personal_tool.domain.ports import CMoveResult

        received = kwargs.get("received", {})
        for uid in instance_uids:
            received[uid] = _BYTES
        return CMoveResult(completed=len(instance_uids), failed=0, warning=0)

    def c_move_series(self, study_uid, series_uid, **kwargs):
        from echo_personal_tool.domain.ports import CMoveResult

        return CMoveResult(completed=0, failed=0, warning=0)


# ── DicomRetrieveService ─────────────────────────────────────────────


def test_service_default_source_property() -> None:
    svc = DicomRetrieveService(adapters={}, default_source="auto")
    assert svc.default_source == "auto"


def test_service_set_cancel_check() -> None:
    web = _MockWeb()
    cget = CGetRetrieveAdapter(_MockDimse(), ServerSettings())
    svc = DicomRetrieveService(
        adapters={"wado": WadoRetrieveAdapter(web), "dimse": cget},
        default_source="wado",
    )
    flag = {"cancelled": False}
    svc.set_cancel_check(lambda: flag["cancelled"])
    assert cget._is_cancelled is not None


def test_service_retrieve_cancelled_raises() -> None:
    svc = DicomRetrieveService(
        adapters={"wado": WadoRetrieveAdapter(_MockWeb())},
        default_source="wado",
        is_cancelled=lambda: True,
    )
    with pytest.raises(RetrieveError, match="cancelled"):
        svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)


def test_service_prefetch_series_cmove() -> None:
    dimse = _MockDimse()
    adapter = CMoveRetrieveAdapter(dimse, ServerSettings())
    svc = DicomRetrieveService(
        adapters={"cmove": adapter},
        default_source="cmove",
    )
    # Should not raise
    svc.prefetch_series(_STUDY, _SERIES)


def test_service_prefetch_series_non_cmove_is_noop() -> None:
    svc = DicomRetrieveService(
        adapters={"wado": WadoRetrieveAdapter(_MockWeb())},
        default_source="wado",
    )
    svc.prefetch_series(_STUDY, _SERIES)  # no-op


def test_service_unknown_source_raises() -> None:
    svc = DicomRetrieveService(adapters={"wado": WadoRetrieveAdapter(_MockWeb())}, default_source="wado")
    with pytest.raises(RetrieveError, match="No adapter for source"):
        svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE, source="nonexistent")


# ── make_retrieve_service edge cases ─────────────────────────────────


def test_make_service_empty_raises() -> None:
    settings = ServerSettings(retrieval_source="wado")
    with pytest.raises(RetrieveError, match="No retrieval adapters"):
        make_retrieve_service(settings)


def test_make_service_auto_fallback_to_dimse_only() -> None:
    """When wado is unreachable and dimse available, auto selects dimse."""
    dimse = _MockDimse()
    settings = ServerSettings(retrieval_source="auto")
    svc = make_retrieve_service(settings, dimse_client=dimse)
    result = svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


def test_make_service_default_source_not_in_adapters() -> None:
    """When retrieval_source is not in adapters, auto or first adapter is used."""
    dimse = _MockDimse()
    settings = ServerSettings(retrieval_source="dimse")
    svc = make_retrieve_service(settings, dimse_client=dimse)
    result = svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


def test_make_service_auto_wado_only() -> None:
    """auto mode with only wado adapter → wado is used."""
    web = _MockWeb(ping_return=False)
    settings = ServerSettings(retrieval_source="auto")
    svc = make_retrieve_service(settings, web_client=web)
    result = svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


def test_auto_falls_back_at_retrieval_time_when_wado_raises() -> None:
    """Auto fallback happens per-request, not only when a startup ping failed."""

    class _FailingWadoWeb(_MockWeb):
        def download_instance(self, study_uid, series_uid, instance_uid) -> bytes:
            raise ConnectionError("wado down mid-session")

    dimse = _MockDimse()
    settings = ServerSettings(retrieval_source="auto")
    svc = make_retrieve_service(settings, web_client=_FailingWadoWeb(), dimse_client=dimse)
    result = svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


def test_explicit_source_does_not_cross_fallback() -> None:
    """retrieval_source='dimse' must stay on DIMSE: a failure is reported,
    not silently rerouted to WADO (the user explicitly configured DIMSE)."""
    web = _MockWeb()
    dimse = _MockDimse()

    class _FailingDimse(_MockDimse):
        def c_get_instance(self, study_uid, series_uid, instance_uid, *, tls_args=None, is_cancelled=None) -> bytes:
            raise ConnectionError("dimse failed")

    settings = ServerSettings(retrieval_source="dimse")
    svc = make_retrieve_service(settings, web_client=web, dimse_client=_FailingDimse())
    with pytest.raises(RetrieveError, match="All retrieval sources failed"):
        svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)


def test_make_service_configured_source_missing_falls_to_auto() -> None:
    """retrieval_source='dimse' but only WADO available → auto (WADO) is used."""
    web = _MockWeb()
    settings = ServerSettings(retrieval_source="dimse")
    svc = make_retrieve_service(settings, web_client=web)
    result = svc.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


# ── CGetRetrieveAdapter TLS ──────────────────────────────────────────


def test_cget_adapter_no_tls() -> None:
    dimse = _MockDimse()
    settings = ServerSettings(dimse_use_tls=False)
    adapter = CGetRetrieveAdapter(dimse, settings)
    result = adapter.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


# ── CMoveRetrieveAdapter ─────────────────────────────────────────────


def test_cmove_adapter_cache_hit() -> None:
    dimse = _MockDimse()
    adapter = CMoveRetrieveAdapter(dimse, ServerSettings())
    adapter._series_cache[_SERIES] = {_INSTANCE: _BYTES}
    result = adapter.retrieve_instance(_STUDY, _SERIES, _INSTANCE)
    assert result == _BYTES


def test_cmove_adapter_series_cache() -> None:
    dimse = _MockDimse()
    adapter = CMoveRetrieveAdapter(dimse, ServerSettings())
    adapter._series_cache[_SERIES] = {_INSTANCE: _BYTES}
    result = adapter.retrieve_series(_STUDY, _SERIES)
    assert _INSTANCE in result


def test_cmove_adapter_series_cache_miss(tmp_path: Path) -> None:
    """retrieve_series without cache should call embedded SCP."""
    dimse = _MockDimse()
    settings = ServerSettings()
    adapter = CMoveRetrieveAdapter(dimse, settings)

    mock_scp = MagicMock()
    mock_scp.__enter__ = MagicMock(return_value=mock_scp)
    mock_scp.__exit__ = MagicMock(return_value=False)
    mock_scp.bound_port = settings.dimse_scp_port
    mock_scp.instances = {_INSTANCE: _BYTES}

    with patch(
        "echo_personal_tool.infrastructure.embedded_storage_scp.EmbeddedStorageSCP",
        return_value=mock_scp,
    ):
        result = adapter.retrieve_series(_STUDY, _SERIES)

    assert _INSTANCE in result
    assert _SERIES in adapter._series_cache
