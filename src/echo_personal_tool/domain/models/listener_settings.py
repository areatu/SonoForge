"""Listener settings value object (issue 626).

Pure domain model; persistence (QSettings) lives in the infrastructure layer,
so the presentation layer can type against this without importing it.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_HL7_PORT = 6761
DEFAULT_MWL_PORT = 11113


@dataclass
class ListenerSettings:
    hl7_enabled: bool = False
    hl7_host: str = "127.0.0.1"
    hl7_port: int = DEFAULT_HL7_PORT
    hl7_use_tls: bool = False
    hl7_tls_cert_path: str = ""
    hl7_tls_key_path: str = ""
    mwl_enabled: bool = False
    mwl_host: str = "127.0.0.1"
    mwl_port: int = DEFAULT_MWL_PORT
    mwl_ae_title: str = "SONOFORGE"
    mwl_use_tls: bool = False
    mwl_tls_cert_path: str = ""
    mwl_tls_key_path: str = ""
    #: Comma-separated explicit allowlist of non-loopback bind hosts.
    allowed_hosts: str = ""

    def allowed_hosts_list(self) -> tuple[str, ...]:
        return tuple(h.strip() for h in self.allowed_hosts.split(",") if h.strip())
