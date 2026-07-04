"""DICOM retrieval service with adapter pattern for WADO/DIMSE sources."""

from __future__ import annotations

import logging
from typing import Protocol

from echo_personal_tool.domain.ports import (
    DimseClient,
    DicomWebClient,
    RetrievalSource,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings

logger = logging.getLogger(__name__)


class RetrieveAdapter(Protocol):
    """Protocol for retrieval adapters."""

    def retrieve_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        """Download a single DICOM instance."""
        ...


class WadoRetrieveAdapter:
    """Adapter for WADO-RS retrieval."""

    def __init__(self, client: DicomWebClient):
        self._client = client

    def retrieve_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        return self._client.download_instance(study_uid, series_uid, instance_uid)


class CGetRetrieveAdapter:
    """Adapter for C-GET retrieval via DIMSE."""

    def __init__(self, client: DimseClient, settings: ServerSettings):
        self._client = client
        self._settings = settings

    def retrieve_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        tls_args = self._build_tls_args()
        return self._client.c_get_instance(
            study_uid,
            series_uid,
            instance_uid,
            tls_args=tls_args,
        )

    def _build_tls_args(self) -> tuple | None:
        if not self._settings.dimse_use_tls:
            return None
        import ssl

        ssl_cx = ssl.create_default_context()
        if self._settings.dimse_tls_ca_path:
            ssl_cx.load_verify_locations(cafile=self._settings.dimse_tls_ca_path)
        ssl_cx.verify_mode = (
            ssl.CERT_REQUIRED if self._settings.dimse_tls_verify else ssl.CERT_NONE
        )
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
        self._series_cache: dict[str, dict[str, bytes]] = {}  # series_uid -> {instance_uid: bytes}

    def retrieve_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        # Check series cache first
        if series_uid in self._series_cache:
            cached = self._series_cache[series_uid]
            if instance_uid in cached:
                return cached[instance_uid]

        # Single instance C-MOVE
        from echo_personal_tool.infrastructure.embedded_storage_scp import (
            EmbeddedStorageSCP,
        )

        scp_host = self._settings.dimse_scp_host
        scp_port = self._settings.dimse_scp_port
        scp_ae = self._settings.dimse_scp_ae_title or self._settings.dimse_ae_title

        with EmbeddedStorageSCP(
            host=scp_host,
            port=scp_port,
            ae_title=scp_ae,
        ) as scp:
            received: dict[str, bytes] = {}
            tls_args = self._build_tls_args()

            self._client.c_move_instances(
                study_uid,
                series_uid,
                [instance_uid],
                move_destination_ae=scp_ae,
                scp_host=scp_host,
                scp_port=scp_port,
                received=received,
                tls_args=tls_args,
            )

            if instance_uid not in received:
                raise RetrieveError(
                    f"C-MOVE: instance {instance_uid} not received"
                )
            return received[instance_uid]

    def retrieve_series(
        self, study_uid: str, series_uid: str
    ) -> dict[str, bytes]:
        """Download all instances in a series via C-MOVE (more efficient)."""
        if series_uid in self._series_cache:
            return self._series_cache[series_uid]

        from echo_personal_tool.infrastructure.embedded_storage_scp import (
            EmbeddedStorageSCP,
        )

        scp_host = self._settings.dimse_scp_host
        scp_port = self._settings.dimse_scp_port
        scp_ae = self._settings.dimse_scp_ae_title or self._settings.dimse_ae_title

        with EmbeddedStorageSCP(
            host=scp_host,
            port=scp_port,
            ae_title=scp_ae,
        ) as scp:
            received: dict[str, bytes] = {}
            tls_args = self._build_tls_args()

            self._client.c_move_series(
                study_uid,
                series_uid,
                move_destination_ae=scp_ae,
                scp_host=scp_host,
                scp_port=scp_port,
                received=received,
                tls_args=tls_args,
            )

            # Cache the result
            self._series_cache[series_uid] = received
            return received

    def _build_tls_args(self) -> tuple | None:
        if not self._settings.dimse_use_tls:
            return None
        import ssl

        ssl_cx = ssl.create_default_context()
        if self._settings.dimse_tls_ca_path:
            ssl_cx.load_verify_locations(cafile=self._settings.dimse_tls_ca_path)
        ssl_cx.verify_mode = (
            ssl.CERT_REQUIRED if self._settings.dimse_tls_verify else ssl.CERT_NONE
        )
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

    def __init__(self, adapters: dict[str, RetrieveAdapter], default_source: str = "auto"):
        self._adapters = adapters
        self._default_source = default_source

    def retrieve_instance(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        source: str | None = None,
    ) -> bytes:
        """Download a single DICOM instance using the specified source."""
        source = source or self._default_source
        adapter = self._resolve_adapter(source)
        return adapter.retrieve_instance(study_uid, series_uid, instance_uid)

    def _resolve_adapter(self, source: str) -> RetrieveAdapter:
        if source in self._adapters:
            return self._adapters[source]
        raise RetrieveError(f"No adapter for source: {source}")


def make_retrieve_service(
    settings: ServerSettings,
    web_client: DicomWebClient | None = None,
    dimse_client: DimseClient | None = None,
) -> DicomRetrieveService:
    """Factory function to create DicomRetrieveService with appropriate adapters."""
    adapters: dict[str, RetrieveAdapter] = {}
    default_source = settings.retrieval_source

    # Always add WADO adapter if web_client is provided
    if web_client is not None:
        adapters["wado"] = WadoRetrieveAdapter(web_client)

    # Add DIMSE adapters if dimse_client is provided
    if dimse_client is not None:
        adapters["dimse"] = CGetRetrieveAdapter(dimse_client, settings)
        adapters["cmove"] = CMoveRetrieveAdapter(dimse_client, settings)

    # Auto mode: prefer WADO if available, fallback to C-GET
    if default_source == "auto":
        if "wado" in adapters:
            adapters["auto"] = adapters["wado"]
        elif "dimse" in adapters:
            adapters["auto"] = adapters["dimse"]
    elif default_source not in adapters:
        # If configured source not available, fallback
        if "auto" in adapters:
            default_source = "auto"
        elif adapters:
            default_source = next(iter(adapters))
        else:
            raise RetrieveError("No retrieval adapters available")

    return DicomRetrieveService(adapters, default_source)
