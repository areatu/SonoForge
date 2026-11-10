"""Contract values of the persisted user preferences (no Qt, no I/O).

The session-source markers, the clamped UI ranges, the UI-scale choices, the
projector preset and the :class:`UserPreferences` protocol are the settings
contract (S2-03, #307; completed in #477). They live in their own module
because two parties need them and neither may import the other: the Qt-free
facade (:mod:`echo_personal_tool.application.user_preferences`) re-exports them
for the presentation layer, while the Qt-backed adapters
(``infrastructure.user_preferences``, ``infrastructure.ui_scale``) read them
from here. Keeping the numbers below the facade stops the facade, which loads
the adapters lazily, from forming an import cycle with them (#328).

Ownership stays in ``application`` (#419): ``domain/ports.py`` does not own UI
preferences.
"""

from __future__ import annotations

from typing import Protocol

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


class WindowPreferences(Protocol):
    """Shell, theme, locale, layout, and shortcut preferences."""

    ui_scale_percent: int
    tabs_enabled: bool
    ui_font_size: int
    theme_mode: str
    accent_palette: str
    language: str
    reduce_motion: bool
    native_window_frame: bool
    shortcut_overrides_json: str
    layout_state_json: str
    layout_state_v2_json: str
    tool_panel_layout_json: str
    tool_layout_v3_json: str
    tool_panel_v2: bool
    panel_width: int
    confirm_reset: bool
    references_dir: str


class PlaybackPreferences(Protocol):
    """Playback loop, window/level, gallery, and DICOM tag inspector preferences."""

    playback_speed_multiplier: float
    playback_max_cache_mb: int
    auto_play: bool
    wl_window: int
    wl_level: int
    wl_dr: int
    despeckle_enabled: bool
    thumbnail_scale: str
    thumbnail_sort_mode: str
    show_dicom_tag_inspector: bool
    interesting_dicom_tags: str


class MeasurementDisplayPreferences(Protocol):
    """Overlay, caliper/contour rendering, calibration, and tool-input preferences."""

    results_overlay_x_ratio: float
    results_overlay_y_ratio: float
    results_overlay_custom_position: bool
    results_overlay_font_size: int
    results_overlay_opacity: float
    caliper_line_width: float
    contour_pen_manual_width: float
    contour_pen_ai_width: float
    contour_pen_simpson_width: float
    magnetic_snap_enabled: bool
    magnetic_snap_weight_threshold: float
    magnetic_snap_release_strength: float
    magnetic_snap_release_max_radial_px: float
    show_crosshair: bool
    magnifier_enabled: bool
    magnifier_zoom: float
    magnifier_radius_px: int
    magnifier_linear_persistent: bool
    show_panel_frames: bool
    show_caliper_labels_on_frame: bool
    show_caliper_inline_labels: bool
    show_doppler_calibration_roi: bool
    doppler_auto_calibration_enabled: bool
    calibration_tick_snap_enabled: bool
    auto_depth_calibration_enabled: bool
    length_display_unit: str
    measurement_precision_tenth_mm: bool
    area_tool_mode: str
    lv_contour_input: str
    atrial_contour_input: str
    label_picker_enabled: bool
    reference_norm_dots: bool
    show_strain: bool
    show_la_auto: bool
    show_heart_rate_tools: bool
    gold_annotation_enabled: bool
    gold_dataset_path: str


class SessionPreferences(Protocol):
    """Startup, last-session resume, cache cleanup, and study-profile preferences."""

    startup_mode: str
    last_opened_folder: str
    last_session_source: str
    last_session_date: str
    last_session_clip_count: int
    orthanc_cache_clear_on_exit: bool
    measurement_persistence_enabled: bool
    study_profile: str


class PrivacyPreferences(Protocol):
    """Burned-in PHI masking and start-page patient-name visibility preferences."""

    anonymize_frames: bool
    start_page_show_patient_data: bool
    phi_text_detector: bool
    phi_mask_top_percent: float


class ReportPreferences(Protocol):
    """Printable report sheet formatting, template, and header preferences."""

    pdf_font_size: int
    hide_report_draft_notice: bool
    report_show_inputs: bool
    report_template_json: str
    report_institution: str
    report_equipment: str
    report_physician: str


class PresenterPreferences(Protocol):
    """Second-screen audience presenter preferences."""

    presenter_screen: str
    presenter_visual_preset: bool
    presenter_pointer: bool
    presenter_audience_render: str


class UserPreferences(
    WindowPreferences,
    PlaybackPreferences,
    MeasurementDisplayPreferences,
    SessionPreferences,
    PrivacyPreferences,
    ReportPreferences,
    PresenterPreferences,
    Protocol,
):
    """Complete application-owned contract of persisted user preferences (#477)."""


def resolve_wl_values(preferences: PlaybackPreferences) -> tuple[int, int, int]:
    """Return the last-used window/level/DR. Soft/contrast presets are no longer applied."""
    return preferences.wl_window, preferences.wl_level, preferences.wl_dr


def normalize_ui_scale(value: object) -> int:
    """Return a value from :data:`UI_SCALE_CHOICES`, or Auto for anything else."""
    if not isinstance(value, (int, float, str)):
        return UI_SCALE_AUTO
    try:
        percent = int(value)
    except (TypeError, ValueError):
        return UI_SCALE_AUTO
    return percent if percent in UI_SCALE_CHOICES else UI_SCALE_AUTO
