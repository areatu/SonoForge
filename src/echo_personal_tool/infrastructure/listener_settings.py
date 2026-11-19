"""Persisted settings for the inbound interop listeners (#626).

MLLP listener (HL7 v2 ADT/ORM) and the MWL/MPPS SCP are opt-in and bind to
loopback by default; a non-loopback bind must pass
:func:`transport_policy.evaluate_listener_bind` (verified TLS or an explicit
allowlist entry). Persisted via QSettings like the PACS server profiles.
"""

from __future__ import annotations

from typing import Any

from echo_personal_tool.domain.models.listener_settings import (
    DEFAULT_HL7_PORT,
    DEFAULT_MWL_PORT,
    ListenerSettings,
)

__all__ = [
    "DEFAULT_HL7_PORT",
    "DEFAULT_MWL_PORT",
    "ListenerSettings",
    "load_listener_settings",
    "save_listener_settings",
]


def _store() -> Any:
    from PySide6.QtCore import QSettings

    return QSettings("SonoForge", "InteropListeners")


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_listener_settings() -> ListenerSettings:
    store = _store()
    return ListenerSettings(
        hl7_enabled=bool(store.value("hl7/enabled", False)),
        hl7_host=str(store.value("hl7/host", "127.0.0.1")),
        hl7_port=_coerce_int(store.value("hl7/port", DEFAULT_HL7_PORT), DEFAULT_HL7_PORT),
        hl7_use_tls=bool(store.value("hl7/use_tls", False)),
        hl7_tls_cert_path=str(store.value("hl7/tls_cert_path", "")),
        hl7_tls_key_path=str(store.value("hl7/tls_key_path", "")),
        mwl_enabled=bool(store.value("mwl/enabled", False)),
        mwl_host=str(store.value("mwl/host", "127.0.0.1")),
        mwl_port=_coerce_int(store.value("mwl/port", DEFAULT_MWL_PORT), DEFAULT_MWL_PORT),
        mwl_ae_title=str(store.value("mwl/ae_title", "SONOFORGE")),
        mwl_use_tls=bool(store.value("mwl/use_tls", False)),
        mwl_tls_cert_path=str(store.value("mwl/tls_cert_path", "")),
        mwl_tls_key_path=str(store.value("mwl/tls_key_path", "")),
        allowed_hosts=str(store.value("allowed_hosts", "")),
    )


def save_listener_settings(settings: ListenerSettings) -> None:
    store = _store()
    store.setValue("hl7/enabled", settings.hl7_enabled)
    store.setValue("hl7/host", settings.hl7_host)
    store.setValue("hl7/port", settings.hl7_port)
    store.setValue("hl7/use_tls", settings.hl7_use_tls)
    store.setValue("hl7/tls_cert_path", settings.hl7_tls_cert_path)
    store.setValue("hl7/tls_key_path", settings.hl7_tls_key_path)
    store.setValue("mwl/enabled", settings.mwl_enabled)
    store.setValue("mwl/host", settings.mwl_host)
    store.setValue("mwl/port", settings.mwl_port)
    store.setValue("mwl/ae_title", settings.mwl_ae_title)
    store.setValue("mwl/use_tls", settings.mwl_use_tls)
    store.setValue("mwl/tls_cert_path", settings.mwl_tls_cert_path)
    store.setValue("mwl/tls_key_path", settings.mwl_tls_key_path)
    store.setValue("allowed_hosts", settings.allowed_hosts)
    store.sync()
