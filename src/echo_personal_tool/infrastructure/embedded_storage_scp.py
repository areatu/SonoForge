"""Embedded Storage SCP for receiving instances during C-MOVE."""

from __future__ import annotations

import ipaddress
import logging
from collections import OrderedDict
from typing import Any

from pynetdicom import AE, StoragePresentationContexts, evt

from echo_personal_tool.infrastructure.log_sanitizer import sanitize_uid

logger = logging.getLogger(__name__)

_INSTANCES_MAX = 500

_LOOPBACK_BIND_ERROR = (
    "Embedded Storage SCP is loopback-only; remote C-STORE reception is not "
    "supported until an explicit peer-admission policy exists"
)


class StorageSCPBindError(RuntimeError):
    """A bind address that the loopback-only SCP must refuse before opening a socket."""

    code = "scp_bind_rejected"

    def __init__(self) -> None:
        super().__init__(_LOOPBACK_BIND_ERROR)


def is_loopback_bind_host(host: str) -> bool:
    """Whether ``host`` is a bindable loopback address, parsed as a literal.

    Only loopback IP literals and the exact name ``localhost`` are accepted.
    Wildcard/unspecified addresses, DNS names, URL-like look-alikes and IPv6
    zone suffixes are refused: this SCP has no policy for admitting remote
    senders, so an ambiguous ``host`` must not become a listening socket.
    Mirrors the strict host parsing of ``application/transport_policy.py``.
    """
    text = (host or "").strip().lower()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text or "%" in text or text.endswith("."):
        return False
    if text == "localhost":
        return True
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return bool(address.is_loopback and not address.is_unspecified)


class EmbeddedStorageSCP:
    """Context manager that runs a temporary Storage SCP.

    Listens on a specified port, accumulates received DICOM instances
    in-memory, and shuts down when the context exits.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11112,
        ae_title: str = "ECHO2026",
    ):
        self._host = host
        self._port = port
        self._ae_title = ae_title
        self._ae: AE | None = None
        self._server: Any = None
        self.instances: OrderedDict[str, bytes] = OrderedDict()
        self._requested_port = port

    @property
    def bound_port(self) -> int:
        if self._server is not None and hasattr(self._server, "server_address"):
            return int(self._server.server_address[1])
        return self._port

    def start(self) -> None:
        """Start the SCP server in background mode (loopback only)."""
        # Reject before AE construction and before ``start_server`` binds a
        # socket. An AE title identifies a DICOM application, it does not
        # authenticate a peer; without a reviewed remote-peer policy the only
        # safe admission rule is "no remote listener at all".
        if not is_loopback_bind_host(self._host):
            logger.warning("EmbeddedStorageSCP: non-loopback bind refused before opening a socket")
            raise StorageSCPBindError()
        self._ae = AE(ae_title=self._ae_title)
        self._ae.supported_contexts = StoragePresentationContexts

        for attempt_port in (self._port, 0) if self._port != 0 else (0,):
            try:
                self._server = self._ae.start_server(
                    (self._host, attempt_port),
                    block=False,
                    evt_handlers=[(evt.EVT_C_STORE, self._handle_store)],
                )
                self._port = self.bound_port
                if attempt_port != 0 and self._port != self._requested_port:
                    logger.warning(
                        "EmbeddedStorageSCP: port %d busy, bound to %d",
                        self._requested_port,
                        self._port,
                    )
                break
            except OSError as exc:
                if attempt_port == 0:
                    raise
                logger.warning(
                    "EmbeddedStorageSCP: cannot bind %s:%d (%s), trying ephemeral port",
                    self._host,
                    attempt_port,
                    type(exc).__name__,
                )
        else:
            raise OSError(f"Cannot bind EmbeddedStorageSCP on {self._host}")

        logger.info(
            "EmbeddedStorageSCP started on %s:%d (AE: %s)",
            self._host,
            self._port,
            self._ae_title,
        )

    def _handle_store(self, event: evt.Event) -> int:
        """Handle incoming C-STORE request."""
        ds = event.dataset
        sop_uid = str(ds.SOPInstanceUID)

        # Use event.file_meta if available, otherwise create one
        file_meta = getattr(event, "file_meta", None)
        if file_meta is None:
            from pydicom.dataset import FileMetaDataset

            file_meta = FileMetaDataset()
        if not file_meta.get("TransferSyntaxUID"):
            from pydicom.uid import ExplicitVRLittleEndian

            file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.file_meta = file_meta

        from io import BytesIO

        buf = BytesIO()
        ds.save_as(buf, enforce_file_format=True)
        if len(self.instances) >= _INSTANCES_MAX:
            evicted_uid, _ = self.instances.popitem(last=False)
            logger.warning(
                "EmbeddedStorageSCP: evicting oldest instance %s (limit %d)",
                sanitize_uid(evicted_uid),
                _INSTANCES_MAX,
            )
        self.instances[sop_uid] = buf.getvalue()

        logger.debug("Received instance %s (%d bytes)", sanitize_uid(sop_uid), len(self.instances[sop_uid]))
        return 0x0000  # Success

    def shutdown(self) -> None:
        """Stop the SCP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            logger.info("EmbeddedStorageSCP shutdown")

    def __enter__(self) -> EmbeddedStorageSCP:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()
