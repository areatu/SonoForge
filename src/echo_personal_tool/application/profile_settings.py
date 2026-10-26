"""Application facades for profile selection, capabilities, and settings.

Presentation should ask the application which profile is active and which
features it enables, rather than reading infrastructure configuration
directly. The settings adapter stays Qt-free; infrastructure is imported only
when a profile or settings query is made.
"""

from __future__ import annotations

from typing import Any, Protocol, cast


class ProfileCapabilities(Protocol):
    """Read-only feature policy for the active Full or Presenter profile."""

    @property
    def ai_segmentation(self) -> bool: ...

    @property
    def reference_ui(self) -> bool: ...

    @property
    def recent_folders(self) -> bool: ...

    @property
    def recent_studies(self) -> bool: ...

    @property
    def continue_last_session(self) -> bool: ...

    @property
    def measurement_storage(self) -> bool: ...

    @property
    def measurement_storage_default(self) -> bool: ...

    @property
    def tabs(self) -> bool: ...

    @property
    def calculators(self) -> bool: ...

    @property
    def server_dialog(self) -> bool: ...

    @property
    def presenter_view(self) -> bool: ...

    @property
    def extended_start_page(self) -> bool: ...

    @property
    def portable_storage_default(self) -> bool: ...


class _SettingsBackend(Protocol):
    """Structural adapter for the infrastructure settings implementation."""

    def value(self, key: str, default_value: Any = None) -> Any: ...

    def setValue(self, key: str, value: Any) -> None: ...

    def sync(self) -> None: ...


class SettingsStore:
    """Qt-free key/value settings port consumed by presentation components."""

    def __init__(self, backend: _SettingsBackend) -> None:
        self._backend = backend

    def read(self, key: str, default: Any = None) -> Any:
        """Read a stored value, returning ``default`` when the key is absent."""
        return self._backend.value(key, default)

    def write(self, key: str, value: Any) -> None:
        """Persist a settings value."""
        self._backend.setValue(key, value)

    def sync(self) -> None:
        """Flush pending settings writes to the backing store."""
        self._backend.sync()


def active_profile_name() -> str:
    """Return the selected runtime profile name (normally ``full`` or ``presenter``)."""
    from echo_personal_tool.infrastructure.profile import profile

    return profile()


def profile_display_name() -> str:
    """Return the human-visible application name for the active profile."""
    from echo_personal_tool.infrastructure.profile import display_name

    return display_name()


def get_profile_capabilities(profile_name: str | None = None) -> ProfileCapabilities:
    """Return the immutable feature policy for ``profile_name`` or the active profile."""
    from echo_personal_tool.infrastructure.profile import capabilities_for

    return cast(ProfileCapabilities, capabilities_for(profile_name))


def settings_store_for(organization: str, application: str) -> SettingsStore:
    """Return a portable-aware key/value store for one settings namespace."""
    from echo_personal_tool.infrastructure.profile import qsettings_for

    return SettingsStore(cast(_SettingsBackend, qsettings_for(organization, application)))


def default_settings_store() -> SettingsStore:
    """Return the Qt default settings store, portable-aware for Presenter builds."""
    from echo_personal_tool.infrastructure.profile import qsettings_default

    return SettingsStore(cast(_SettingsBackend, qsettings_default()))


__all__ = [
    "ProfileCapabilities",
    "SettingsStore",
    "active_profile_name",
    "default_settings_store",
    "get_profile_capabilities",
    "profile_display_name",
    "settings_store_for",
]
