"""Application facade for persisted user preferences.

Presentation consumes this narrow preferences contract rather than importing
the Qt-backed persistence adapter. The infrastructure implementation is
loaded lazily on reads and writes, keeping the application API Qt-free.

The stable contract values (session-source markers, the clamped UI ranges and
the projector preset) are defined in :mod:`echo_personal_tool.application.preferences_contract`
and re-exported here, so the facade can expose them without pulling the
Qt-backed adapter at import time. The adapters read them from the contract
module directly: the facade loads them lazily, so importing the facade from an
adapter would close an import cycle (#328).
"""

from __future__ import annotations

from typing import Any, cast

from echo_personal_tool.application.preferences_contract import (
    DEFAULT_CALIPER_LINE_WIDTH,
    DEFAULT_CONTOUR_LINE_WIDTH,
    DEFAULT_MAGNETIC_RADIUS,
    DEFAULT_MAGNETIC_RELEASE,
    DEFAULT_MAGNETIC_WEIGHT,
    DEFAULT_MAGNIFIER_RADIUS_PX,
    DEFAULT_MAGNIFIER_ZOOM,
    DEFAULT_PDF_FONT_SIZE,
    DEFAULT_PLAYBACK_SPEED,
    DEFAULT_RESULTS_OVERLAY_FONT_SIZE,
    DEFAULT_RESULTS_OVERLAY_OPACITY,
    DEFAULT_RESULTS_OVERLAY_X_RATIO,
    DEFAULT_RESULTS_OVERLAY_Y_RATIO,
    DEFAULT_UI_FONT_SIZE,
    DEFAULT_WL_DR,
    DEFAULT_WL_LEVEL,
    DEFAULT_WL_WINDOW,
    MAX_LINE_WIDTH,
    MAX_MAGNETIC_RADIUS,
    MAX_MAGNETIC_RELEASE,
    MAX_MAGNETIC_WEIGHT,
    MAX_MAGNIFIER_RADIUS_PX,
    MAX_MAGNIFIER_ZOOM,
    MAX_OVERLAY_FONT_SIZE,
    MAX_OVERLAY_OPACITY,
    MAX_PDF_FONT_SIZE,
    MAX_PLAYBACK_SPEED,
    MAX_UI_FONT_SIZE,
    MIN_LINE_WIDTH,
    MIN_MAGNETIC_RADIUS,
    MIN_MAGNETIC_RELEASE,
    MIN_MAGNETIC_WEIGHT,
    MIN_MAGNIFIER_RADIUS_PX,
    MIN_MAGNIFIER_ZOOM,
    MIN_OVERLAY_FONT_SIZE,
    MIN_OVERLAY_OPACITY,
    MIN_PDF_FONT_SIZE,
    MIN_PLAYBACK_SPEED,
    MIN_UI_FONT_SIZE,
    PRESENTATION_PRESET_OVERRIDES,
    RESULTS_OVERLAY_EDGE_MARGIN,
    SESSION_SOURCE_FOLDER,
    SESSION_SOURCE_SERVER,
    UI_SCALE_AUTO,
    UI_SCALE_CHOICES,
    UserPreferences,
    normalize_ui_scale,
    resolve_wl_values,
)


def load_user_preferences() -> UserPreferences:
    """Load validated preferences from the profile-aware settings adapter."""
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences as load_adapter

    return cast(UserPreferences, load_adapter())


def save_user_preferences(preferences: UserPreferences) -> None:
    """Persist the current preferences without exposing the Qt adapter."""
    from echo_personal_tool.infrastructure.user_preferences import save_user_preferences as save_adapter

    save_adapter(cast(Any, preferences))


def default_user_preferences() -> UserPreferences:
    """Factory-default preferences (not read from disk)."""
    from echo_personal_tool.infrastructure.user_preferences import (
        default_user_preferences as default_adapter,
    )

    return cast(UserPreferences, default_adapter())


def default_measurement_persistence_enabled() -> bool:
    """Profile-aware default of the measurement autosave preference."""
    from echo_personal_tool.infrastructure.user_preferences import (
        default_measurement_persistence_enabled as default_adapter,
    )

    return default_adapter()


def restart_application() -> bool:
    """Start a detached copy of the application; the caller quits the current one."""
    from echo_personal_tool.infrastructure.ui_scale import restart_application as restart_adapter

    return restart_adapter()


def gold_annotation_enabled() -> bool:
    """Whether the gold-dataset export actions are enabled in this profile.

    Reads the stored flag through the settings adapter; the ``ECHO_GOLD_EXPORT``
    environment opt-in is honoured by the callers that also need a path.
    """
    from echo_personal_tool.infrastructure.user_preferences import _read_bool, _settings_store

    return _read_bool(_settings_store().value("gold_annotation_enabled"), False)


__all__ = [
    "DEFAULT_CALIPER_LINE_WIDTH",
    "DEFAULT_CONTOUR_LINE_WIDTH",
    "DEFAULT_MAGNETIC_RADIUS",
    "DEFAULT_MAGNETIC_RELEASE",
    "DEFAULT_MAGNETIC_WEIGHT",
    "DEFAULT_MAGNIFIER_RADIUS_PX",
    "DEFAULT_MAGNIFIER_ZOOM",
    "DEFAULT_PDF_FONT_SIZE",
    "DEFAULT_PLAYBACK_SPEED",
    "DEFAULT_RESULTS_OVERLAY_FONT_SIZE",
    "DEFAULT_RESULTS_OVERLAY_OPACITY",
    "DEFAULT_RESULTS_OVERLAY_X_RATIO",
    "DEFAULT_RESULTS_OVERLAY_Y_RATIO",
    "DEFAULT_UI_FONT_SIZE",
    "DEFAULT_WL_DR",
    "DEFAULT_WL_LEVEL",
    "DEFAULT_WL_WINDOW",
    "MAX_LINE_WIDTH",
    "MAX_MAGNETIC_RADIUS",
    "MAX_MAGNETIC_RELEASE",
    "MAX_MAGNETIC_WEIGHT",
    "MAX_MAGNIFIER_RADIUS_PX",
    "MAX_MAGNIFIER_ZOOM",
    "MAX_OVERLAY_FONT_SIZE",
    "MAX_OVERLAY_OPACITY",
    "MAX_PDF_FONT_SIZE",
    "MAX_PLAYBACK_SPEED",
    "MAX_UI_FONT_SIZE",
    "MIN_LINE_WIDTH",
    "MIN_MAGNETIC_RADIUS",
    "MIN_MAGNETIC_RELEASE",
    "MIN_MAGNETIC_WEIGHT",
    "MIN_MAGNIFIER_RADIUS_PX",
    "MIN_MAGNIFIER_ZOOM",
    "MIN_OVERLAY_FONT_SIZE",
    "MIN_OVERLAY_OPACITY",
    "MIN_PDF_FONT_SIZE",
    "MIN_PLAYBACK_SPEED",
    "MIN_UI_FONT_SIZE",
    "PRESENTATION_PRESET_OVERRIDES",
    "RESULTS_OVERLAY_EDGE_MARGIN",
    "SESSION_SOURCE_FOLDER",
    "SESSION_SOURCE_SERVER",
    "UI_SCALE_AUTO",
    "UI_SCALE_CHOICES",
    "UserPreferences",
    "default_measurement_persistence_enabled",
    "default_user_preferences",
    "gold_annotation_enabled",
    "load_user_preferences",
    "normalize_ui_scale",
    "resolve_wl_values",
    "restart_application",
    "save_user_preferences",
]
