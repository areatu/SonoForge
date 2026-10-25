"""Application facade for PACS settings, clients, and download-cache access.

Presentation owns the dialogs and workers, but it should not construct
infrastructure clients or access server-settings persistence directly.  The
concrete adapters stay in ``infrastructure``; this module exposes their
application-facing API and intentionally has no Qt import.  Qt-backed settings
storage is reached only when a persistence function is called.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from echo_personal_tool.application.transport_policy import InsecureException, ProfileDecision
from echo_personal_tool.infrastructure import server_settings as _settings_adapter

if TYPE_CHECKING:
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.application.services.dicom_retrieve_service import DicomRetrieveService
    from echo_personal_tool.domain.ports import DicomUploadClient, DicomWebClient, DimseClient

ServerSettings = _settings_adapter.ServerSettings


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
        from echo_personal_tool.infrastructure.profile import orthanc_cache_root

        root = orthanc_cache_root()
    from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache

    return OrthancSessionCache(root)


def compute_insecure_exception_scope(settings: ServerSettings) -> str:
    """Return the canonical scoped-transport exception key for ``settings``."""
    return _settings_adapter.compute_insecure_exception_scope(settings)


def describe_insecure_transport_modes(settings: ServerSettings) -> list[str]:
    """Return localized names of insecure transports configured by ``settings``."""
    return _settings_adapter.describe_insecure_transport_modes(settings)


def effective_exceptions_for_settings(settings: ServerSettings) -> tuple[InsecureException, ...]:
    """Return active scoped transport exceptions for ``settings``."""
    return _settings_adapter.effective_exceptions_for_settings(settings)


def evaluate_server_settings(settings: ServerSettings) -> ProfileDecision:
    """Evaluate all configured transports before a PACS operation."""
    return _settings_adapter.evaluate_server_settings(settings)


def grant_insecure_exception(settings: ServerSettings) -> ServerSettings:
    """Return settings carrying an explicit exception for their current endpoints."""
    return _settings_adapter.grant_insecure_exception(settings)


def settings_requires_confirmation(settings: ServerSettings) -> bool:
    """Whether a network operation requires an explicit user confirmation."""
    return _settings_adapter.settings_requires_confirmation(settings)


def load_server_settings() -> ServerSettings:
    """Load the active PACS settings through the infrastructure persistence adapter."""
    return _settings_adapter.load_server_settings()


def save_server_settings(settings: ServerSettings) -> None:
    """Persist the active PACS settings through the infrastructure adapter."""
    _settings_adapter.save_server_settings(settings)


def list_profiles() -> dict[str, ServerSettings]:
    """Return saved PACS profiles, keyed by their display name."""
    return _settings_adapter.list_profiles()


def load_profile(name: str) -> ServerSettings | None:
    """Load a named PACS profile, if it still exists."""
    return _settings_adapter.load_profile(name)


def save_profile(name: str, settings: ServerSettings) -> None:
    """Persist a named PACS profile."""
    _settings_adapter.save_profile(name, settings)


def delete_profile(name: str) -> bool:
    """Delete a named PACS profile and report whether it existed."""
    return _settings_adapter.delete_profile(name)


def make_dimse_client(settings: ServerSettings) -> DimseClient | None:
    """Build the configured DIMSE adapter, or ``None`` when DIMSE is disabled."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dimse_client as build_client

    return build_client(settings)


def close_dicom_web_client(client: DicomWebClient) -> None:
    """Release a DICOMweb client when its adapter supports explicit cleanup."""
    close = getattr(client, "close", None)
    if callable(close):
        close()


def make_dicom_web_client(settings: ServerSettings) -> DicomWebClient:
    """Build the configured DICOMweb adapter."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dicom_web_client as build_client

    return build_client(settings)


def make_dicom_query_service(
    settings: ServerSettings,
    *,
    web: DicomWebClient | None = None,
    dimse: DimseClient | None = None,
) -> DicomQueryService:
    """Build the application query service, optionally sharing existing clients."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dicom_query_service as build_service

    return build_service(settings, web=web, dimse=dimse)


def make_dicom_retrieve_service(
    settings: ServerSettings,
    *,
    web_client: DicomWebClient | None = None,
    dimse_client: DimseClient | None = None,
) -> DicomRetrieveService:
    """Build the application retrieval service for the download worker."""
    from echo_personal_tool.infrastructure.server_client_factory import make_dicom_retrieve_service as build_service

    return build_service(
        settings,
        web_client=web_client,
        dimse_client=dimse_client,
    )


def make_upload_targets(
    settings: ServerSettings,
    protocol: str,
) -> tuple[DicomUploadClient | None, DicomWebClient | None]:
    """Build upload adapters for the selected STOW-RS or DIMSE protocol."""
    from echo_personal_tool.infrastructure.server_client_factory import make_upload_targets as build_targets

    return build_targets(settings, protocol)


def dimse_upload_available(settings: ServerSettings) -> bool:
    """Whether DIMSE upload can be configured for ``settings``."""
    from echo_personal_tool.infrastructure.server_client_factory import dimse_upload_available as check_available

    return check_available(settings)


def stow_upload_available(settings: ServerSettings) -> bool:
    """Whether STOW-RS upload can be configured for ``settings``."""
    from echo_personal_tool.infrastructure.server_client_factory import stow_upload_available as check_available

    return check_available(settings)


__all__ = [
    "OrthancCache",
    "ServerSettings",
    "close_dicom_web_client",
    "compute_insecure_exception_scope",
    "delete_profile",
    "describe_insecure_transport_modes",
    "dimse_upload_available",
    "effective_exceptions_for_settings",
    "evaluate_server_settings",
    "grant_insecure_exception",
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
]
