"""Persistent user interface and viewer preferences."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

_SETTINGS_ORG = "echo-personal-tool"
_SETTINGS_APP = "preferences"

MIN_UI_FONT_SIZE = 9
MAX_UI_FONT_SIZE = 18
DEFAULT_UI_FONT_SIZE = 12

MIN_OVERLAY_FONT_SIZE = 10
MAX_OVERLAY_FONT_SIZE = 28
DEFAULT_RESULTS_OVERLAY_FONT_SIZE = 20

MIN_OVERLAY_OPACITY = 0.2
MAX_OVERLAY_OPACITY = 1.0
DEFAULT_RESULTS_OVERLAY_OPACITY = 0.84

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

WL_PRESET_SOFT = (70, 40, 35)
WL_PRESET_CONTRAST = (140, 55, 65)
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

MIN_PDF_FONT_SIZE = 8
MAX_PDF_FONT_SIZE = 16
DEFAULT_PDF_FONT_SIZE = 10

DEFAULT_INTERESTING_DICOM_TAGS = (
    "PatientName,PatientID,StudyDate,SeriesDescription,HeartRate,FrameRate"
)


@dataclass
class UserPreferences:
    ui_font_size: int = DEFAULT_UI_FONT_SIZE
    results_overlay_x_ratio: float = DEFAULT_RESULTS_OVERLAY_X_RATIO
    results_overlay_y_ratio: float = DEFAULT_RESULTS_OVERLAY_Y_RATIO
    results_overlay_custom_position: bool = False
    results_overlay_font_size: int = DEFAULT_RESULTS_OVERLAY_FONT_SIZE
    results_overlay_opacity: float = DEFAULT_RESULTS_OVERLAY_OPACITY
    caliper_line_width: float = DEFAULT_CALIPER_LINE_WIDTH
    contour_pen_manual_width: float = DEFAULT_CONTOUR_LINE_WIDTH
    contour_pen_ai_width: float = DEFAULT_CONTOUR_LINE_WIDTH
    contour_pen_simpson_width: float = DEFAULT_CONTOUR_LINE_WIDTH
    magnetic_snap_enabled: bool = True
    playback_speed_multiplier: float = DEFAULT_PLAYBACK_SPEED
    wl_preset: str = "last_used"
    wl_window: int = DEFAULT_WL_WINDOW
    wl_level: int = DEFAULT_WL_LEVEL
    wl_dr: int = DEFAULT_WL_DR
    show_crosshair: bool = True
    show_panel_frames: bool = False
    show_caliper_labels_on_frame: bool = True
    show_caliper_inline_labels: bool = False
    thumbnail_scale: str = "medium"
    magnetic_snap_weight_threshold: float = DEFAULT_MAGNETIC_WEIGHT
    magnetic_snap_release_strength: float = DEFAULT_MAGNETIC_RELEASE
    magnetic_snap_release_max_radial_px: float = DEFAULT_MAGNETIC_RADIUS
    doppler_auto_calibration_enabled: bool = True
    calibration_tick_snap_enabled: bool = True
    auto_depth_calibration_enabled: bool = True
    length_display_unit: str = "mm"
    show_dicom_tag_inspector: bool = False
    interesting_dicom_tags: str = DEFAULT_INTERESTING_DICOM_TAGS
    confirm_reset: bool = True
    pdf_font_size: int = DEFAULT_PDF_FONT_SIZE
    startup_mode: str = "empty"
    last_opened_folder: str = ""
    theme_mode: str = "dark"
    language: str = "ru"
    auto_play: bool = False
    layout_state_json: str = ""
    reduce_motion: bool = False


def _settings_store() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _clamp_float(value: object, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _read_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _read_choice(value: object, default: str, choices: set[str]) -> str:
    if isinstance(value, str) and value in choices:
        return value
    return default


def resolve_wl_values(preferences: UserPreferences) -> tuple[int, int, int]:
    if preferences.wl_preset == "soft":
        return WL_PRESET_SOFT
    if preferences.wl_preset == "contrast":
        return WL_PRESET_CONTRAST
    return preferences.wl_window, preferences.wl_level, preferences.wl_dr


def load_user_preferences() -> UserPreferences:
    store = _settings_store()
    overlay_x_ratio = _clamp_float(
        store.value("results_overlay_x_ratio"),
        DEFAULT_RESULTS_OVERLAY_X_RATIO,
        0.0,
        1.0,
    )
    overlay_y_ratio = _clamp_float(
        store.value("results_overlay_y_ratio"),
        DEFAULT_RESULTS_OVERLAY_Y_RATIO,
        0.0,
        1.0,
    )
    overlay_custom = _read_bool(store.value("results_overlay_custom_position"), False)
    if overlay_custom and overlay_x_ratio < 0.15:
        overlay_custom = False
    return UserPreferences(
        ui_font_size=_clamp_int(
            store.value("ui_font_size"),
            DEFAULT_UI_FONT_SIZE,
            MIN_UI_FONT_SIZE,
            MAX_UI_FONT_SIZE,
        ),
        results_overlay_x_ratio=overlay_x_ratio,
        results_overlay_y_ratio=overlay_y_ratio,
        results_overlay_custom_position=overlay_custom,
        results_overlay_font_size=_clamp_int(
            store.value("results_overlay_font_size"),
            DEFAULT_RESULTS_OVERLAY_FONT_SIZE,
            MIN_OVERLAY_FONT_SIZE,
            MAX_OVERLAY_FONT_SIZE,
        ),
        results_overlay_opacity=_clamp_float(
            store.value("results_overlay_opacity"),
            DEFAULT_RESULTS_OVERLAY_OPACITY,
            MIN_OVERLAY_OPACITY,
            MAX_OVERLAY_OPACITY,
        ),
        caliper_line_width=_clamp_float(
            store.value("caliper_line_width"),
            DEFAULT_CALIPER_LINE_WIDTH,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        contour_pen_manual_width=_clamp_float(
            store.value("contour_pen_manual_width"),
            DEFAULT_CONTOUR_LINE_WIDTH,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        contour_pen_ai_width=_clamp_float(
            store.value("contour_pen_ai_width"),
            DEFAULT_CONTOUR_LINE_WIDTH,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        contour_pen_simpson_width=_clamp_float(
            store.value("contour_pen_simpson_width"),
            DEFAULT_CONTOUR_LINE_WIDTH,
            MIN_LINE_WIDTH,
            MAX_LINE_WIDTH,
        ),
        magnetic_snap_enabled=_read_bool(store.value("magnetic_snap_enabled"), True),
        playback_speed_multiplier=_clamp_float(
            store.value("playback_speed_multiplier"),
            DEFAULT_PLAYBACK_SPEED,
            MIN_PLAYBACK_SPEED,
            MAX_PLAYBACK_SPEED,
        ),
        wl_preset=_read_choice(
            store.value("wl_preset"),
            "last_used",
            {"soft", "contrast", "last_used"},
        ),
        wl_window=_clamp_int(store.value("wl_window"), DEFAULT_WL_WINDOW, 1, 400),
        wl_level=_clamp_int(store.value("wl_level"), DEFAULT_WL_LEVEL, 0, 100),
        wl_dr=_clamp_int(store.value("wl_dr"), DEFAULT_WL_DR, 0, 100),
        show_crosshair=_read_bool(store.value("show_crosshair"), True),
        show_panel_frames=_read_bool(store.value("show_panel_frames"), False),
        show_caliper_labels_on_frame=_read_bool(store.value("show_caliper_labels_on_frame"), True),
        show_caliper_inline_labels=_read_bool(store.value("show_caliper_inline_labels"), False),
        thumbnail_scale=_read_choice(
            store.value("thumbnail_scale"),
            "medium",
            {"small", "medium", "large"},
        ),
        magnetic_snap_weight_threshold=_clamp_float(
            store.value("magnetic_snap_weight_threshold"),
            DEFAULT_MAGNETIC_WEIGHT,
            MIN_MAGNETIC_WEIGHT,
            MAX_MAGNETIC_WEIGHT,
        ),
        magnetic_snap_release_strength=_clamp_float(
            store.value("magnetic_snap_release_strength"),
            DEFAULT_MAGNETIC_RELEASE,
            MIN_MAGNETIC_RELEASE,
            MAX_MAGNETIC_RELEASE,
        ),
        magnetic_snap_release_max_radial_px=_clamp_float(
            store.value("magnetic_snap_release_max_radial_px"),
            DEFAULT_MAGNETIC_RADIUS,
            MIN_MAGNETIC_RADIUS,
            MAX_MAGNETIC_RADIUS,
        ),
        doppler_auto_calibration_enabled=_read_bool(
            store.value("doppler_auto_calibration_enabled"),
            True,
        ),
        calibration_tick_snap_enabled=_read_bool(
            store.value("calibration_tick_snap_enabled"),
            True,
        ),
        auto_depth_calibration_enabled=_read_bool(
            store.value("auto_depth_calibration_enabled"),
            True,
        ),
        length_display_unit=_read_choice(
            store.value("length_display_unit"),
            "mm",
            {"mm", "cm"},
        ),
        show_dicom_tag_inspector=_read_bool(store.value("show_dicom_tag_inspector"), False),
        interesting_dicom_tags=str(
            store.value("interesting_dicom_tags", DEFAULT_INTERESTING_DICOM_TAGS)
        ),
        confirm_reset=_read_bool(store.value("confirm_reset"), True),
        pdf_font_size=_clamp_int(
            store.value("pdf_font_size"),
            DEFAULT_PDF_FONT_SIZE,
            MIN_PDF_FONT_SIZE,
            MAX_PDF_FONT_SIZE,
        ),
        startup_mode=_read_choice(store.value("startup_mode"), "empty", {"empty", "last_folder"}),
        last_opened_folder=str(store.value("last_opened_folder", "")),
        theme_mode=_read_choice(
            store.value("theme_mode"), "dark", {"dark", "light", "system", "vscode_dark", "vscode_light"}
        ),
        language=_read_choice(store.value("language"), "ru", {"ru", "en"}),
        auto_play=_read_bool(store.value("auto_play"), False),
        layout_state_json=str(store.value("layout_state_json", "")),
        reduce_motion=_read_bool(store.value("reduce_motion"), False),
    )


def default_user_preferences() -> UserPreferences:
    """Factory-default preferences (not read from disk)."""
    return UserPreferences()


def interesting_dicom_tag_list(preferences: UserPreferences) -> list[str]:
    return [part.strip() for part in preferences.interesting_dicom_tags.split(",") if part.strip()]


def save_user_preferences(preferences: UserPreferences) -> None:
    store = _settings_store()
    for key, value in preferences.__dict__.items():
        store.setValue(key, value)
    store.sync()
