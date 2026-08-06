"""DICOM retrieval service with adapter pattern for WADO/DIMSE sources."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from echo_personal_tool.domain.ports import DicomWebClient, DimseClient
from echo_personal_tool.infrastructure.dimse_client import DimseMoveDestinationError
from echo_personal_tool.infrastructure.server_settings import ServerSettings

logger = logging.getLogger(__name__)


class RetrieveAdapter(Protocol):
    """Protocol for retrieval adapters."""

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        """Download a single DICOM instance."""
        ...


class WadoRetrieveAdapter:
    """Adapter for WADO-RS retrieval."""

    def __init__(self, client: DicomWebClient):
        self._client = client

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        return self._client.download_instance(study_uid, series_uid, instance_uid)


class CGetRetrieveAdapter:
    """Adapter for C-GET retrieval via DIMSE."""

    def __init__(
        self,
        client: DimseClient,
        settings: ServerSettings,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self._client = client
        self._settings = settings
        self._is_cancelled = is_cancelled

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        tls_args = self._build_tls_args()
        return self._client.c_get_instance(
            study_uid,
            series_uid,
            instance_uid,
            tls_args=tls_args,
            is_cancelled=self._is_cancelled,
        )

    def _build_tls_args(self) -> tuple | None:
        if not self._settings.dimse_use_tls:
            return None
        import ssl

        ssl_cx = ssl.create_default_context()
        if self._settings.dimse_tls_ca_path:
            ssl_cx.load_verify_locations(cafile=self._settings.dimse_tls_ca_path)
        ssl_cx.verify_mode = ssl.CERT_REQUIRED if self._settings.dimse_tls_verify else ssl.CERT_NONE
        if self._settings.dimse_tls_cert_path and self._settings.dimse_tls_key_path:
            ssl_cx.load_cert_chain(
                certfile=self._settings.dimse_tls_cert_path,
                keyfile=self._settings.dimse_tls_key_path,
            )
        return (ssl_cx, self._settings.dimse_host)


class CMoveRetrieveAdapter:
    """Adapter for C-MOVE retrieval with embedded Storage SCP."""

    def __init__(self, client: DimseClient, settings: ServerSettings):
        self._client = client
        self._settings = settings
        self._series_cache: dict[str, dict[str, bytes]] = {}

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        if series_uid in self._series_cache:
            cached = self._series_cache[series_uid]
            if instance_uid in cached:
                return cached[instance_uid]

        from echo_personal_tool.infrastructure.embedded_storage_scp import (
            EmbeddedStorageSCP,
        )

        scp_host = self._settings.dimse_scp_host
        scp_port = self._settings.dimse_scp_port
        scp_ae = self._settings.dimse_scp_ae_title or self._settings.dimse_ae_title

        try:
            with EmbeddedStorageSCP(
                host=scp_host,
                port=scp_port,
                ae_title=scp_ae,
            ) as scp:
                received: dict[str, bytes] = {}
                tls_args = self._build_tls_args()
                bound_port = scp.bound_port

                self._client.c_move_instances(
                    study_uid,
                    series_uid,
                    [instance_uid],
                    move_destination_ae=scp_ae,
                    scp_host=scp_host,
                    scp_port=bound_port,
                    received=received,
                    tls_args=tls_args,
                )
                received.update(scp.instances)

                if bound_port != scp_port:
                    logger.warning(
                        "C-MOVE used ephemeral SCP port %d (requested %d) — "
                        "update Orthanc DicomModalities if retrieval fails",
                        bound_port,
                        scp_port,
                    )

                if instance_uid not in received:
                    raise RetrieveError(f"C-MOVE: instance {instance_uid} not received")
                return received[instance_uid]
        except DimseMoveDestinationError as exc:
            raise RetrieveError(str(exc)) from exc

    def retrieve_series(self, study_uid: str, series_uid: str) -> dict[str, bytes]:
        """Download all instances in a series via C-MOVE (more efficient)."""
        if series_uid in self._series_cache:
            return self._series_cache[series_uid]

        from echo_personal_tool.infrastructure.embedded_storage_scp import (
            EmbeddedStorageSCP,
        )

        scp_host = self._settings.dimse_scp_host
        scp_port = self._settings.dimse_scp_port
        scp_ae = self._settings.dimse_scp_ae_title or self._settings.dimse_ae_title

        try:
            with EmbeddedStorageSCP(
                host=scp_host,
                port=scp_port,
                ae_title=scp_ae,
            ) as scp:
                received: dict[str, bytes] = {}
                tls_args = self._build_tls_args()
                bound_port = scp.bound_port

                self._client.c_move_series(
                    study_uid,
                    series_uid,
                    move_destination_ae=scp_ae,
                    scp_host=scp_host,
                    scp_port=bound_port,
                    received=received,
                    tls_args=tls_args,
                )
                received.update(scp.instances)

                if bound_port != scp_port:
                    logger.warning(
                        "C-MOVE series used ephemeral SCP port %d (requested %d)",
                        bound_port,
                        scp_port,
                    )

                self._series_cache[series_uid] = received
                return received
        except DimseMoveDestinationError as exc:
            raise RetrieveError(str(exc)) from exc

    def _build_tls_args(self) -> tuple | None:
        if not self._settings.dimse_use_tls:
            return None
        import ssl

        ssl_cx = ssl.create_default_context()
        if self._settings.dimse_tls_ca_path:
            ssl_cx.load_verify_locations(cafile=self._settings.dimse_tls_ca_path)
        ssl_cx.verify_mode = ssl.CERT_REQUIRED if self._settings.dimse_tls_verify else ssl.CERT_NONE
        if self._settings.dimse_tls_cert_path and self._settings.dimse_tls_key_path:
            ssl_cx.load_cert_chain(
                certfile=self._settings.dimse_tls_cert_path,
                keyfile=self._settings.dimse_tls_key_path,
            )
        return (ssl_cx, self._settings.dimse_host)


class RetrieveError(Exception):
    """Raised when retrieval fails."""


class DicomRetrieveService:
    """Unified retrieval service that selects the appropriate adapter."""

    def __init__(
        self,
        adapters: dict[str, RetrieveAdapter],
        default_source: str = "auto",
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self._adapters = adapters
        self._default_source = default_source
        self._is_cancelled = is_cancelled

    @property
    def default_source(self) -> str:
        return self._default_source

    def set_cancel_check(self, is_cancelled: Callable[[], bool] | None) -> None:
        self._is_cancelled = is_cancelled
        for adapter in self._adapters.values():
            if isinstance(adapter, CGetRetrieveAdapter):
                adapter._is_cancelled = is_cancelled

    def prefetch_series(self, study_uid: str, series_uid: str) -> None:
        """Pre-fetch a full series when using C-MOVE (batch retrieval)."""
        adapter = self._adapters.get("cmove")
        if isinstance(adapter, CMoveRetrieveAdapter):
            adapter.retrieve_series(study_uid, series_uid)

    def retrieve_instance(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        source: str | None = None,
    ) -> bytes:
        """Download a single DICOM instance using the specified source."""
        if self._is_cancelled and self._is_cancelled():
            raise RetrieveError("Download cancelled")
        source = source or self._default_source
        adapter = self._resolve_adapter(source)
        return adapter.retrieve_instance(study_uid, series_uid, instance_uid)

    def _resolve_adapter(self, source: str) -> RetrieveAdapter:
        if source in self._adapters:
            return self._adapters[source]
        raise RetrieveError(f"No adapter for source: {source}")


def _wado_reachable(web_client: DicomWebClient) -> bool:
    try:
        return web_client.ping()
    except Exception:  # noqa: BLE001
        logger.debug("WADO ping failed in auto retrieval mode", exc_info=True)
        return False


def make_retrieve_service(
    settings: ServerSettings,
    web_client: DicomWebClient | None = None,
    dimse_client: DimseClient | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> DicomRetrieveService:
    """Factory function to create DicomRetrieveService with appropriate adapters."""
    adapters: dict[str, RetrieveAdapter] = {}
    default_source = settings.retrieval_source

    if web_client is not None:
        adapters["wado"] = WadoRetrieveAdapter(web_client)

    if dimse_client is not None:
        adapters["dimse"] = CGetRetrieveAdapter(
            dimse_client,
            settings,
            is_cancelled=is_cancelled,
        )
        adapters["cmove"] = CMoveRetrieveAdapter(dimse_client, settings)

    if "wado" in adapters or "dimse" in adapters:
        if web_client is not None and _wado_reachable(web_client):
            adapters["auto"] = adapters["wado"]
        elif "dimse" in adapters:
            adapters["auto"] = adapters["dimse"]
        elif "wado" in adapters:
            adapters["auto"] = adapters["wado"]

    if default_source == "auto" and "auto" not in adapters:
        default_source = next(iter(adapters), default_source)
    elif default_source not in adapters:
        if "auto" in adapters:
            default_source = "auto"
        elif adapters:
            default_source = next(iter(adapters))
        else:
            raise RetrieveError("No retrieval adapters available")

    return DicomRetrieveService(
        adapters,
        default_source,
        is_cancelled=is_cancelled,
    )
