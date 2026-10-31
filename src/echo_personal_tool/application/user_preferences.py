"""Application facade for persisted user preferences.

Presentation consumes this narrow preferences contract rather than importing
the Qt-backed persistence adapter. The infrastructure implementation is
loaded lazily on reads and writes, keeping the application API Qt-free.

The stable contract values (session-source markers, the clamped UI ranges and
the projector preset) live here so the facade can expose them without pulling
the Qt-backed adapter at import time; ``infrastructure.user_preferences`` and
``infrastructure.ui_scale`` re-export them from this module, keeping one
source of truth for the numbers.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

#: Values of :attr:`UserPreferences.last_session_source`.  ``""`` means "no
#: session recorded yet" (first run, or a version before the field existed).
SESSION_SOURCE_FOLDER = "folder"
SESSION_SOURCE_SERVER = "server"

# One logical unit for UI fonts: pixels, both in the QSS stylesheet and in the
# application font.  ``pt`` stays for PDF/print only.
MIN_UI_FONT_SIZE = 10
MAX_UI_FONT_SIZE = 24
DEFAULT_UI_FONT_SIZE = 13

# The results overlay has its own scale: it is sized against the frame, not
# against dialog text, so it goes further up for 4K screens.
MIN_OVERLAY_FONT_SIZE = 10
MAX_OVERLAY_FONT_SIZE = 40
DEFAULT_RESULTS_OVERLAY_FONT_SIZE = 20

MIN_OVERLAY_OPACITY = 0.1
MAX_OVERLAY_OPACITY = 1.0
DEFAULT_RESULTS_OVERLAY_OPACITY = 0.70

MIN_LINE_WIDTH = 1.0
MAX_LINE_WIDTH = 6.0
DEFAULT_CALIPER_LINE_WIDTH = 2.0
DEFAULT_CONTOUR_LINE_WIDTH = 2.0

DEFAULT_RESULTS_OVERLAY_X_RATIO = 0.68
DEFAULT_RESULTS_OVERLAY_Y_RATIO = 0.20
RESULTS_OVERLAY_EDGE_MARGIN = 8

MIN_PLAYBACK_SPEED = 0.25
MAX_PLAYBACK_SPEED = 4.0
DEFAULT_PLAYBACK_SPEED = 1.0

DEFAULT_WL_WINDOW = 100
DEFAULT_WL_LEVEL = 50
DEFAULT_WL_DR = 50

MIN_MAGNETIC_WEIGHT = 0.05
MAX_MAGNETIC_WEIGHT = 0.5
DEFAULT_MAGNETIC_WEIGHT = 0.15

MIN_MAGNETIC_RELEASE = 0.5
MAX_MAGNETIC_RELEASE = 1.0
DEFAULT_MAGNETIC_RELEASE = 0.9

MIN_MAGNETIC_RADIUS = 5.0
MAX_MAGNETIC_RADIUS = 40.0
DEFAULT_MAGNETIC_RADIUS = 15.0

MIN_MAGNIFIER_ZOOM = 2.0
MAX_MAGNIFIER_ZOOM = 6.0
DEFAULT_MAGNIFIER_ZOOM = 3.0
MIN_MAGNIFIER_RADIUS_PX = 40
MAX_MAGNIFIER_RADIUS_PX = 120
DEFAULT_MAGNIFIER_RADIUS_PX = 70

MIN_PDF_FONT_SIZE = 8
MAX_PDF_FONT_SIZE = 16
DEFAULT_PDF_FONT_SIZE = 10

#: ``0`` means "follow the operating system" (no QT_SCALE_FACTOR at all).
UI_SCALE_AUTO = 0
#: 25 % step: Qt recommends whole factors or a 25 % step over "exact physical DPI".
UI_SCALE_CHOICES: tuple[int, ...] = (UI_SCALE_AUTO, 100, 125, 150, 175, 200, 225, 250)

# ``presenter_visual_preset`` additionally applies (non-destructively, only
# while the mode is active) the projector-friendly overrides below: thicker
# lines, larger fonts and inline caliper labels that stay readable from the
# back of a room.  The user's own preferences are restored on exit.
PRESENTATION_PRESET_OVERRIDES: dict[str, object] = {
    "ui_font_size": 14,
    "results_overlay_font_size": 24,
    "results_overlay_opacity": 0.85,
    "caliper_line_width": 3.5,
    "contour_pen_manual_width": 3.5,
    "contour_pen_ai_width": 3.5,
    "contour_pen_simpson_width": 3.5,
    "show_caliper_labels_on_frame": True,
    "show_caliper_inline_labels": True,
    "show_crosshair": True,
}


class UserPreferences(Protocol):
    """Preferences fields used by the presentation clients behind this facade."""

    ui_scale_percent: int
    tabs_enabled: bool
    ui_font_size: int
    results_overlay_x_ratio: float
    results_overlay_y_ratio: float
    results_overlay_custom_position: bool
    results_overlay_font_size: int
    results_overlay_opacity: float
    caliper_line_width: float
    contour_pen_manual_width: float
    contour_pen_ai_width: float
    contour_pen_simpson_width: float
    playback_speed_multiplier: float
    wl_window: int
    wl_level: int
    wl_dr: int
    magnifier_enabled: bool
    magnifier_zoom: float
    magnifier_radius_px: int
    magnifier_linear_persistent: bool
    show_caliper_labels_on_frame: bool
    show_caliper_inline_labels: bool
    show_crosshair: bool
    reduce_motion: bool
    references_dir: str
    phi_text_detector: bool
    measurement_persistence_enabled: bool
    last_session_source: str
    language: str
    show_strain: bool
    theme_mode: str


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


def resolve_wl_values(preferences: UserPreferences) -> tuple[int, int, int]:
    """Return the last-used window/level/DR. Soft/contrast presets are no longer applied."""
    return preferences.wl_window, preferences.wl_level, preferences.wl_dr


def normalize_ui_scale(value: object) -> int:
    """Return a value from :data:`UI_SCALE_CHOICES`, or Auto for anything else."""
    from echo_personal_tool.infrastructure.ui_scale import normalize_ui_scale as normalize_adapter

    return normalize_adapter(value)


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
