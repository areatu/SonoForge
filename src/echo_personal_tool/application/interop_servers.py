"""Composition of the inbound interop servers (#626).

Builds the SQLite worklist store, the :class:`WorklistService`, the inbound
HL7/FHIR facade, the MLLP listener and the MWL/MPPS SCP from
:class:`ListenerSettings`, and starts/stops them together. Bind addresses are
judged by the transport policy before any socket opens.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from echo_personal_tool.application.interop_inbound import InteropInboundService
from echo_personal_tool.application.worklist_service import WorklistService

logger = logging.getLogger(__name__)


from echo_personal_tool.domain.models.listener_settings import ListenerSettings as ListenerSettings


def load_listener_settings_facade() -> ListenerSettings:
    """Listener settings via the application layer (presentation never imports infrastructure)."""
    from echo_personal_tool.infrastructure.listener_settings import load_listener_settings

    return load_listener_settings()


def save_listener_settings_facade(settings: ListenerSettings) -> None:
    from echo_personal_tool.infrastructure.listener_settings import save_listener_settings

    save_listener_settings(settings)


class InteropServerRunner:
    """Owns the worklist store and the two inbound listeners."""

    def __init__(self, *, settings: Any, store_path: Path, session: Any = None) -> None:
        from echo_personal_tool.infrastructure.worklist_repository import WorklistRepository

        self._settings = settings
        self.store = WorklistRepository(store_path)
        self.worklist = WorklistService(store=self.store, session=session)
        self.inbound = InteropInboundService(worklist=self.worklist)
        self._hl7_server: Any = None
        self._mwl_scp: Any = None

    def start(self) -> None:
        from echo_personal_tool.infrastructure.hl7_mllp_server import Hl7MllpServer
        from echo_personal_tool.infrastructure.mwl_mpps_server import MwlMppsScp

        s = self._settings
        hosts = s.allowed_hosts_list()
        if s.hl7_enabled and self._hl7_server is None:
            self._hl7_server = Hl7MllpServer(
                host=s.hl7_host,
                port=s.hl7_port,
                handler=self.inbound.handle_hl7_message,
                use_tls=s.hl7_use_tls,
                tls_cert_path=s.hl7_tls_cert_path,
                tls_key_path=s.hl7_tls_key_path,
                allowed_hosts=hosts,
            )
            self._hl7_server.start()
        if s.mwl_enabled and self._mwl_scp is None:
            self._mwl_scp = MwlMppsScp(
                ae_title=s.mwl_ae_title,
                host=s.mwl_host,
                port=s.mwl_port,
                worklist=self.worklist,
                use_tls=s.mwl_use_tls,
                tls_cert_path=s.mwl_tls_cert_path,
                tls_key_path=s.mwl_tls_key_path,
                allowed_hosts=hosts,
            )
            self._mwl_scp.start()

    def stop(self) -> None:
        if self._hl7_server is not None:
            self._hl7_server.stop()
            self._hl7_server = None
        if self._mwl_scp is not None:
            self._mwl_scp.stop()
            self._mwl_scp = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def close(self) -> None:
        self.stop()
        self.store.close()

    @property
    def running(self) -> bool:
        return (self._hl7_server is not None and self._hl7_server.running) or (
            self._mwl_scp is not None and self._mwl_scp.running
        )
