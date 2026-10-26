"""Application facade for profile selection and feature capabilities.

Presentation should ask the application which profile is active and which
features it enables, rather than reading the infrastructure configuration
module directly. The profile adapter is imported only when a query is made;
this module remains Qt-free and safe to import during early startup.
"""

from __future__ import annotations

from typing import Protocol, cast


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


def active_profile_name() -> str:
    """Return the selected runtime profile name (normally ``full`` or ``presenter``)."""
    from echo_personal_tool.infrastructure.profile import profile

    return profile()


def get_profile_capabilities(profile_name: str | None = None) -> ProfileCapabilities:
    """Return the immutable feature policy for ``profile_name`` or the active profile."""
    from echo_personal_tool.infrastructure.profile import capabilities_for

    return cast(ProfileCapabilities, capabilities_for(profile_name))


__all__ = ["ProfileCapabilities", "active_profile_name", "get_profile_capabilities"]
