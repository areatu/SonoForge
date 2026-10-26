"""Application facade for persisted user preferences.

Presentation consumes this narrow preferences contract rather than importing
the Qt-backed persistence adapter. The infrastructure implementation is
loaded lazily on reads and writes, keeping the application API Qt-free.
"""

from __future__ import annotations

from typing import Any, Protocol, cast


class UserPreferences(Protocol):
    """Preferences fields used by the presentation clients behind this facade."""

    tabs_enabled: bool
    reduce_motion: bool
    references_dir: str
    phi_text_detector: bool
    measurement_persistence_enabled: bool
    ui_font_size: int
    playback_speed_multiplier: float
    language: str
    show_strain: bool


def load_user_preferences() -> UserPreferences:
    """Load validated preferences from the profile-aware settings adapter."""
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences as load_adapter

    return cast(UserPreferences, load_adapter())


def save_user_preferences(preferences: UserPreferences) -> None:
    """Persist the current preferences without exposing the Qt adapter."""
    from echo_personal_tool.infrastructure.user_preferences import save_user_preferences as save_adapter

    save_adapter(cast(Any, preferences))


__all__ = ["UserPreferences", "load_user_preferences", "save_user_preferences"]
