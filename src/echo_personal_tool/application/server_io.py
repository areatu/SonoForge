"""Application facade for PACS settings, clients, and download-cache access.

Presentation owns the dialogs and workers, while PACS connection settings and
password-save status are owned here as application DTOs (#477) instead of
re-exporting infrastructure adapter classes. Concrete adapters stay in
``infrastructure``; this module intentionally has no Qt import, and Qt-backed
settings storage is reached only when a persistence function is called.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeGuard, cast

from echo_personal_tool.application.transport_policy import InsecureException, ProfileDecision
from echo_personal_tool.infrastructure import server_settings as _settings_adapter

if TYPE_CHECKING:
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.application.services.dicom_retrieve_service import DicomRetrieveService
    from echo_personal_tool.domain.ports import DicomUploadClient, DicomWebClient, DimseClient


@dataclass
class ServerSettings:
    """Application-owned PACS connection and transport-policy settings."""

    description: str = ""
    url: str = "http://127.0.0.1:8042/dicom-web"
    username: str = ""
    password: str = ""
    auth_mode: str = "basic"
    http_headers: str = ""
    use_mock: bool = False
    # DIMSE
    dimse_enabled: bool = False
    dimse_ae_title: str = "ECHO2026"
    dimse_called_ae: str = "ORTHANC"
    dimse_host: str = "127.0.0.1"
    dimse_port: int = 4242
    # STOW-RS override
    stow_dicom_web_url: str = ""
    # Query source preference
    query_source: str = "dicomweb"
    # Retrieval source preference
    retrieval_source: str = "auto"  # wado | dimse | cmove | auto
    dimse_retrieval_mode: str = "cget"  # cget | cmove
    # TLS
    dimse_use_tls: bool = False
    dimse_tls_verify: bool = True
    dimse_tls_ca_path: str = ""
    dimse_tls_cert_path: str = ""  # optional client cert
    dimse_tls_key_path: str = ""
    # Embedded Storage SCP for C-MOVE
    dimse_scp_port: int = 11112
    dimse_scp_host: str = "127.0.0.1"
    dimse_scp_ae_title: str = ""
    # Network
    network_timeout: float = 30.0
    tls_verify: bool = True
    tls_ca_path: str = ""
    allow_insecure_transport: bool = False
    insecure_exception_scope: str = ""
    needs_confirmation: bool = False

    def __post_init__(self) -> None:
        if self.allow_insecure_transport and not self.insecure_exception_scope and not self.needs_confirmation:
            self.insecure_exception_scope = compute_insecure_exception_scope(self)


@dataclass(frozen=True)
class PasswordSaveStatus:
    """Application-owned outcome of a credential write."""

    saved: bool
    error_code: str | None = None


def is_server_settings(value: object) -> TypeGuard[ServerSettings]:
    """Whether ``value`` is a real server-settings record (rejecting test mocks)."""
    return isinstance(value, (ServerSettings, _settings_adapter.ServerSettings))


def is_password_save_status(value: object) -> TypeGuard[PasswordSaveStatus]:
    """Whether ``value`` is a credential-write status (rejecting test mocks)."""
    return isinstance(value, (PasswordSaveStatus, _settings_adapter.PasswordSaveStatus))


def to_adapter_server_settings(
    settings: ServerSettings | _settings_adapter.ServerSettings,
) -> _settings_adapter.ServerSettings:
    """Convert application settings to the persistence/client adapter DTO."""
    if isinstance(settings, _settings_adapter.ServerSettings):
        return settings
    if is_dataclass(settings) and not isinstance(settings, type):
        payload = {field.name: getattr(settings, field.name) for field in fields(_settings_adapter.ServerSettings)}
        return _settings_adapter.ServerSettings(**payload)
    return cast(_settings_adapter.ServerSettings, settings)


def _from_adapter_settings(settings: _settings_adapter.ServerSettings) -> ServerSettings:
    if isinstance(settings, ServerSettings):
        return settings
    if is_dataclass(settings) and not isinstance(settings, type):
        payload = {field.name: getattr(settings, field.name) for field in fields(ServerSettings)}
        return ServerSettings(**payload)
    return cast(ServerSettings, settings)


def _from_adapter_status(status: _settings_adapter.PasswordSaveStatus) -> PasswordSaveStatus:
    if isinstance(status, PasswordSaveStatus):
        return status
    if isinstance(status, _settings_adapter.PasswordSaveStatus):
        return PasswordSaveStatus(saved=status.saved, error_code=status.error_code)
    return PasswordSaveStatus(saved=True)


class OrthancCache(Protocol):
    """Application-facing operations required by the PACS cache consumers."""

    @property
    def root(self) -> Path: ...

    @property
    def max_size_bytes(self) -> int: ...

    def create_session(self) -> str: ...

    def session_id_for_path(self, path: Path) -> str | None: ...

    def session_path(self, session_id: str) -> Path: ...

    def study_path(self, session_id: str, study_uid: str) -> Path: ...

    def legacy_study_path(self, session_id: str, study_uid: str) -> Path: ...

    def save_instance(
        self,
        session_id: str,
        study_uid: str,
        series_uid: str,
        sop_uid: str,
        data: bytes,
    ) -> Path: ...

    def clear_session(self, session_id: str) -> None: ...

    def clear_all(self, preserve_session_ids: Iterable[str] = ()) -> int: ...

    def clear_stale(self, max_age_days: int = 7) -> int: ...

    def size_bytes(self) -> int: ...


def make_orthanc_session_cache(root: Path | None = None) -> OrthancCache:
    """Create the filesystem cache behind the application server-I/O boundary."""
    if root is None:
        from echo_personal_tool.infrastructure.paths import orthanc_cache_root

        root = orthanc_cache_root()
    from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache

    return OrthancSessionCache(root)


def compute_insecure_exception_scope(settings: ServerSettings) -> str:
    """Return the canonical scoped-transport exception key for ``settings``."""
    return _settings_adapter.compute_insecure_exception_scope(to_adapter_server_settings(settings))


def describe_insecure_transport_modes(settings: ServerSettings) -> list[str]:
    """Return localized names of insecure transports configured by ``settings``."""
    return _settings_adapter.describe_insecure_transport_modes(to_adapter_server_settings(settings))


def effective_exceptions_for_settings(settings: ServerSettings) -> tuple[InsecureException, ...]:
    """Return active scoped transport exceptions for ``settings``."""
    return _settings_adapter.effective_exceptions_for_settings(to_adapter_server_settings(settings))


def evaluate_server_settings(settings: ServerSettings) -> ProfileDecision:
    """Evaluate all configured transports before a PACS operation."""
    return _settings_adapter.evaluate_server_settings(to_adapter_server_settings(settings))


def grant_insecure_exception(settings: ServerSettings) -> ServerSettings:
    """Return settings carrying an explicit exception for their current endpoints."""
    return _from_adapter_settings(_settings_adapter.grant_insecure_exception(to_adapter_server_settings(settings)))


def settings_requires_confirmation(settings: ServerSettings) -> bool:
    """Whether a network operation requires an explicit user confirmation."""
    return _settings_adapter.settings_requires_confirmation(to_adapter_server_settings(settings))


def load_server_settings() -> ServerSettings:
    """Load the active PACS settings through the infrastructure persistence adapter."""
    return _from_adapter_settings(_settings_adapter.load_server_settings())


def is_loopback_scp_bind(host: str) -> bool:
    """Whether the embedded C-MOVE Storage SCP may bind to ``host``.

    The pure check lives with the listener; presentation asks the application
    facade instead of importing infrastructure directly.
    """
    from echo_personal_tool.infrastructure.embedded_storage_scp import is_loopback_bind_host

    return is_loopback_bind_host(host)


def save_server_settings(settings: ServerSettings) -> PasswordSaveStatus:
    """Persist the active PACS settings, reporting whether the password was stored."""
    return _from_adapter_status(_settings_adapter.save_server_settings(to_adapter_server_settings(settings)))


def list_profiles() -> dict[str, ServerSettings]:
    """Return saved PACS profiles, keyed by their display name."""
    return {name: _from_adapter_settings(profile) for name, profile in _settings_adapter.list_profiles().items()}


def load_profile(name: str) -> ServerSettings | None:
    """Load a named PACS profile, if it still exists."""
    loaded = _settings_adapter.load_profile(name)
    return None if loaded is None else _from_adapter_settings(loaded)


def save_profile(name: str, settings: ServerSettings) -> PasswordSaveStatus:
    """Persist a named PACS profile, reporting whether its password was stored."""
    return _from_adapter_status(_settings_adapter.save_profile(name, to_adapter_server_settings(settings)))


def delete_profile(name: str) -> bool:
    """Delete a named PACS profile and report whether it existed."""
    return _settings_adapter.delete_profile(name)


def make_dimse_client(settings: ServerSettings) -> DimseClient | None:
    """Build the configured DIMSE adapter, or ``None`` when DIMSE is disabled."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dimse_client as build_client

    return build_client(to_adapter_server_settings(settings))


def close_dicom_web_client(client: DicomWebClient) -> None:
    """Release a DICOMweb client when its adapter supports explicit cleanup."""
    close = getattr(client, "close", None)
    if callable(close):
        close()


def make_dicom_web_client(settings: ServerSettings) -> DicomWebClient:
    """Build the configured DICOMweb adapter."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dicom_web_client as build_client

    return build_client(to_adapter_server_settings(settings))


def make_dicom_query_service(
    settings: ServerSettings,
    *,
    web: DicomWebClient | None = None,
    dimse: DimseClient | None = None,
) -> DicomQueryService:
    """Build the application query service, optionally sharing existing clients."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dicom_query_service as build_service

    return build_service(to_adapter_server_settings(settings), web=web, dimse=dimse)


def make_dicom_retrieve_service(
    settings: ServerSettings,
    *,
    web_client: DicomWebClient | None = None,
    dimse_client: DimseClient | None = None,
) -> DicomRetrieveService:
    """Build the application retrieval service for the download worker."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dicom_retrieve_service as build_service

    return build_service(
        to_adapter_server_settings(settings),
        web_client=web_client,
        dimse_client=dimse_client,
    )


def make_upload_targets(
    settings: ServerSettings,
    protocol: str,
) -> tuple[DicomUploadClient | None, DicomWebClient | None]:
    """Build upload adapters for the selected STOW-RS or DIMSE protocol."""
    from echo_personal_tool.infrastructure.server_client_factory import make_upload_targets as build_targets

    return build_targets(to_adapter_server_settings(settings), protocol)


def dimse_upload_available(settings: ServerSettings) -> bool:
    """Whether DIMSE upload can be configured for ``settings``."""
    from echo_personal_tool.infrastructure.server_client_factory import dimse_upload_available as check_available

    return check_available(to_adapter_server_settings(settings))


def stow_upload_available(settings: ServerSettings) -> bool:
    """Whether STOW-RS upload can be configured for ``settings``."""
    from echo_personal_tool.infrastructure.server_client_factory import stow_upload_available as check_available

    return check_available(to_adapter_server_settings(settings))


__all__ = [
    "OrthancCache",
    "PasswordSaveStatus",
    "ServerSettings",
    "close_dicom_web_client",
    "compute_insecure_exception_scope",
    "delete_profile",
    "describe_insecure_transport_modes",
    "dimse_upload_available",
    "effective_exceptions_for_settings",
    "evaluate_server_settings",
    "grant_insecure_exception",
    "is_loopback_scp_bind",
    "is_password_save_status",
    "is_server_settings",
    "list_profiles",
    "load_profile",
    "load_server_settings",
    "make_dicom_query_service",
    "make_dicom_retrieve_service",
    "make_dicom_web_client",
    "make_dimse_client",
    "make_orthanc_session_cache",
    "make_upload_targets",
    "save_profile",
    "save_server_settings",
    "settings_requires_confirmation",
    "stow_upload_available",
    "to_adapter_server_settings",
]
