"""Embedded Storage SCP for receiving instances during C-MOVE."""

from __future__ import annotations

import logging
import socket
from typing import Any

from pynetdicom import AE, StoragePresentationContexts, evt

logger = logging.getLogger(__name__)


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
        self.instances: dict[str, bytes] = {}

    def start(self) -> None:
        """Start the SCP server in background mode."""
        self._ae = AE(ae_title=self._ae_title)
        self._ae.supported_contexts = StoragePresentationContexts

        self._server = self._ae.start_server(
            (self._host, self._port),
            block=False,
            evt_handlers=[(evt.EVT_C_STORE, self._handle_store)],
        )
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
        self.instances[sop_uid] = buf.getvalue()

        logger.debug("Received instance %s (%d bytes)", sop_uid, len(self.instances[sop_uid]))
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
