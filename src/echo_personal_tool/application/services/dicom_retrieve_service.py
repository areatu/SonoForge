"""DICOM retrieval service with adapter pattern for WADO/DIMSE sources."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from echo_personal_tool.application.transport_policy import TransportPolicyError
from echo_personal_tool.domain.ports import DicomWebClient, DimseClient
from echo_personal_tool.infrastructure.dimse_client import DimseMoveDestinationError
from echo_personal_tool.infrastructure.orthanc_client import DownloadCancelled
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure
from echo_personal_tool.infrastructure.server_settings import ServerSettings

logger = logging.getLogger(__name__)

#: Fallback priority used when retrieval_source == "auto".
#: The chain is resolved at *retrieval time*: if the first adapter fails,
#: the next available one is tried, so a server that goes down mid-session
#: (or a misconfigured URL) is handled instead of being bound once at startup.
_AUTO_SOURCE_ORDER = ("wado", "dimse", "cmove")


class RetrieveAdapter(Protocol):
    """Protocol for retrieval adapters."""

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        """Download a single DICOM instance."""
        ...


def _looks_cancelled(exc: BaseException) -> bool:
    """True when the exception is a cancellation signal that must stop fallbacks.

    Typed cancellation wins; the message sniff stays only for transport
    errors raised by an aborted socket, which carry no cancellation type.
    """
    if isinstance(exc, DownloadCancelled):
        return True
    return "cancell" in str(exc).lower()


class WadoRetrieveAdapter:
    """Adapter for HTTP retrieval (Orthanc REST / WADO)."""

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
        self._series_cache: dict[str, dict[str, bytes]] = {}

    def _cancel_requested(self) -> bool:
        return self._is_cancelled is not None and self._is_cancelled()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested():
            raise RetrieveError("Download cancelled", code="cancelled")

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        self._raise_if_cancelled()
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
                    is_cancelled=self._is_cancelled,
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
                    raise RetrieveError("C-MOVE: instance not received", code="not_received")
                return received[instance_uid]
        except DimseMoveDestinationError as exc:
            raise RetrieveError(str(exc), code="move_destination") from exc

    def retrieve_series(self, study_uid: str, series_uid: str) -> dict[str, bytes]:
        """Download all instances in a series via C-MOVE (more efficient)."""
        self._raise_if_cancelled()
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
                    is_cancelled=self._is_cancelled,
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
            raise RetrieveError(str(exc), code="move_destination") from exc

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
    """Raised when retrieval fails.

    QH-4a ER-09: ``code`` is a stable non-localized token (``cancelled``,
    ``no_adapter``, ``not_received``, ``move_destination``,
    ``all_sources_failed``, ``no_adapters``, ``unexpected``) so the UI can
    render failures without formatting raw exception text. The message stays
    human-readable but must not carry UIDs, hosts or paths.
    """

    def __init__(self, message: str, *, code: str = "unexpected") -> None:
        super().__init__(message)
        self.code = code


def retrieve_failure_code(exc: BaseException) -> str:
    """Stable failure code for any retrieval/download exception (ER-09)."""
    if isinstance(exc, DownloadCancelled) or _looks_cancelled(exc):
        return "cancelled"
    if isinstance(exc, RetrieveError):
        return exc.code
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "io"
    return "unexpected"


class DicomRetrieveService:
    """Unified retrieval service that selects the appropriate adapter.

    ``auto`` is resolved at retrieval time: adapters are tried in priority
    order (wado → dimse → cmove) and the first successful result wins, so a
    transient failure of the preferred protocol falls back to the next one
    instead of being pinned to a single probe done at startup.
    """

    def __init__(
        self,
        adapters: dict[str, RetrieveAdapter],
        default_source: str = "auto",
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self._adapters = dict(adapters)
        self._default_source = default_source
        self._is_cancelled = is_cancelled
        self._cancel_web_hook: Callable[[], None] | None = None

    @property
    def default_source(self) -> str:
        return self._default_source

    def set_cancel_check(self, is_cancelled: Callable[[], bool] | None) -> None:
        """Propagate the cancel check to all adapters that support it."""
        self._is_cancelled = is_cancelled
        for adapter in self._adapters.values():
            if isinstance(adapter, (CGetRetrieveAdapter, CMoveRetrieveAdapter)):
                adapter._is_cancelled = is_cancelled  # noqa: SLF001

    def set_cancel_web_hook(self, hook: Callable[[], None] | None) -> None:
        """Register a hook that aborts in-flight HTTP operations (socket close)."""
        self._cancel_web_hook = hook

    def cancel_inflight(self) -> None:
        """Abort in-flight network operations immediately (no waiting for timeout)."""
        if self._cancel_web_hook is not None:
            try:
                self._cancel_web_hook()
            except Exception as exc:  # noqa: BLE001
                log_boundary_failure(logger, "dicom.retrieve", exc, code="cleanup", level=logging.DEBUG)

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
        """Download a single DICOM instance using the specified source.

        For ``source="auto"`` every available adapter is tried in priority
        order; a cancellation aborts the chain immediately.
        """
        if self._is_cancelled and self._is_cancelled():
            raise RetrieveError("Download cancelled", code="cancelled")
        source = source or self._default_source
        adapters = self._resolve_adapters(source)
        if not adapters:
            raise RetrieveError(f"No adapter for source: {source}", code="no_adapter")

        last_error: Exception | None = None
        for adapter in adapters:
            if self._is_cancelled and self._is_cancelled():
                raise RetrieveError("Download cancelled", code="cancelled")
            try:
                return adapter.retrieve_instance(study_uid, series_uid, instance_uid)
            except TransportPolicyError:
                raise
            except Exception as exc:  # noqa: BLE001
                if _looks_cancelled(exc):
                    raise RetrieveError("Download cancelled", code="cancelled") from exc
                last_error = exc
                log_boundary_failure(logger, "dicom.retrieve", exc, code="io", level=logging.WARNING)

        # The chained cause keeps the raw adapter error for logs; the message
        # itself stays stable so dialogs never render hosts, paths or UIDs.
        raise RetrieveError("All retrieval sources failed", code="all_sources_failed") from last_error

    def _resolve_adapters(self, source: str) -> list[RetrieveAdapter]:
        if source in self._adapters:
            return [self._adapters[source]]
        if source == "auto":
            return [self._adapters[name] for name in _AUTO_SOURCE_ORDER if name in self._adapters]
        return []


def make_retrieve_service(
    settings: ServerSettings,
    web_client: DicomWebClient | None = None,
    dimse_client: DimseClient | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> DicomRetrieveService:
    """Factory function to create DicomRetrieveService with appropriate adapters.

    Note: no network I/O happens here (no ping/probe) — opening the server
    dialog must never block on the network. Reachability is handled at
    retrieval time by the auto fallback chain.
    """
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
        adapters["cmove"] = CMoveRetrieveAdapter(
            dimse_client,
            settings,
            is_cancelled=is_cancelled,
        )

    if not adapters:
        raise RetrieveError("No retrieval adapters available", code="no_adapters")

    # If the configured source is not available (e.g. DIMSE disabled while
    # retrieval_source == "dimse"), fall back to runtime auto resolution
    # instead of failing hard.
    if default_source != "auto" and default_source not in adapters:
        default_source = "auto"

    return DicomRetrieveService(
        adapters,
        default_source,
        is_cancelled=is_cancelled,
    )
