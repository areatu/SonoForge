"""Persistent user interface and viewer preferences."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QSettings

from echo_personal_tool.application.user_preferences import (
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
    PRESENTATION_PRESET_OVERRIDES,  # noqa: F401 - re-exported for tests
    SESSION_SOURCE_FOLDER,
    SESSION_SOURCE_SERVER,
    UI_SCALE_AUTO,
    resolve_wl_values,  # noqa: F401 - re-exported for tests and older callers
)
from echo_personal_tool.infrastructure.ui_scale import normalize_ui_scale

_SETTINGS_ORG = "sonoforge"
_SETTINGS_APP = "preferences"

# The clamped UI ranges, session-source markers and the presenter preset are
# part of the application settings contract (S2-03, #307); they are defined in
# the Qt-free application facade and re-exported here for the adapter and its
# existing callers.
SESSION_SOURCES = frozenset({"", SESSION_SOURCE_FOLDER, SESSION_SOURCE_SERVER})

DEFAULT_INTERESTING_DICOM_TAGS = "StudyDate,SeriesDescription,HeartRate,FrameRate"


@dataclass
class UserPreferences:
    #: Global multiplier applied through QT_SCALE_FACTOR before QApplication;
    #: 0 = Auto (follow the operating system).  Меняется только перезапуском.
    ui_scale_percent: int = UI_SCALE_AUTO
    tabs_enabled: bool = True
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
    playback_max_cache_mb: int = 64
    wl_window: int = DEFAULT_WL_WINDOW
    wl_level: int = DEFAULT_WL_LEVEL
    wl_dr: int = DEFAULT_WL_DR
    show_crosshair: bool = True
    magnifier_enabled: bool = True
    magnifier_zoom: float = DEFAULT_MAGNIFIER_ZOOM
    magnifier_radius_px: int = DEFAULT_MAGNIFIER_RADIUS_PX
    magnifier_linear_persistent: bool = False
    show_panel_frames: bool = False
    show_caliper_labels_on_frame: bool = True
    show_caliper_inline_labels: bool = False
    show_doppler_calibration_roi: bool = False
    # Mask burned-in patient data (name/ID/date) on displayed frames.  Kept
    # switchable at runtime: the band geometry is empirical and can be wrong on
    # a scanner we have never measured.
    anonymize_frames: bool = True
    #: Explicit opt-in; family names come from available DICOM metadata in RAM.
    start_page_show_patient_data: bool = False
    #: User bindings by stable action ID (portable Qt key sequences).
    shortcut_overrides_json: str = ""
    # Experimental (§9 of the de-identification spec): run the text detector as
    # a verification layer over masked export pixels and show its finding in the
    # DICOM export dialog.  Off by default: the detector is calibrated on a
    # corpus, not proven, and it never changes the mask by itself.
    phi_text_detector: bool = False
    #: Override the top PHI mask band as a fraction of the frame height.
    #: 0 (default) keeps the measured vendor profile; a positive value shrinks
    #: or grows the band for layouts the profile over-masks (e.g. strain
    #: screens where the header is only the top few percent).
    phi_mask_top_percent: float = 0.0
    thumbnail_scale: str = "medium"
    #: Thumbnail panel order: "created" (as performed, earliest first) or "filename".
    thumbnail_sort_mode: str = "created"
    magnetic_snap_weight_threshold: float = DEFAULT_MAGNETIC_WEIGHT
    magnetic_snap_release_strength: float = DEFAULT_MAGNETIC_RELEASE
    magnetic_snap_release_max_radial_px: float = DEFAULT_MAGNETIC_RADIUS
    doppler_auto_calibration_enabled: bool = True
    calibration_tick_snap_enabled: bool = True
    auto_depth_calibration_enabled: bool = True
    length_display_unit: str = "mm"
    area_tool_mode: str = "click"
    #: Manual LV contour input: "landmarks" (septal/lateral/apex) or "trace" (freehand).
    lv_contour_input: str = "landmarks"
    #: Manual LA/RA contour input: "landmarks" or "trace" (freehand).
    atrial_contour_input: str = "landmarks"
    show_dicom_tag_inspector: bool = False
    interesting_dicom_tags: str = DEFAULT_INTERESTING_DICOM_TAGS
    confirm_reset: bool = True
    pdf_font_size: int = DEFAULT_PDF_FONT_SIZE
    startup_mode: str = "empty"
    last_opened_folder: str = ""
    #: Where the last opened study came from: ``""`` (unknown/first run),
    #: ``"folder"`` (a directory on disk) or ``"server"`` (downloaded from a
    #: PACS).  The PACS cache is cleared on exit (decision D-27), so "Last
    #: session" cannot reopen server images from disk — it reopens the server
    #: load dialog instead.
    last_session_source: str = ""
    #: Date (ISO) and clip count of the last opened session, shown on the
    #: Start Page «Продолжить» label (Э5 §7.1: «папка или сервер · дата ·
    #: число клипов»).  Missing values degrade the label gracefully.
    last_session_date: str = ""
    last_session_clip_count: int = 0
    # Orthanc downloads contain raw DICOM/PHI. Preserve the existing normal-exit
    # cleanup behavior by default; the cache UI lets users opt out explicitly.
    orthanc_cache_clear_on_exit: bool = True
    # Experimental until the full WP4 platform acceptance matrix has passed.
    measurement_persistence_enabled: bool = False
    #: The concept palette (``docs/images/ui-redesign``, «Графит»): near-black
    #: surfaces with a teal accent.  It replaced ``vscode_dark`` as the default in
    #: 0.3.4 — the grey-blue VS Code palette was never the design, only the
    #: palette that happened to be pinned first (ТЗ 2026-10-23, п. 4).
    theme_mode: str = "graphite"  # = DEFAULT_THEME_MODE (concept palette)
    #: Window control accents, independent of theme and clinical overlay colours.
    accent_palette: str = "theme"
    language: str = "en"
    auto_play: bool = False
    layout_state_json: str = ""
    # Layout document, version 2 (UI-2 PR-1, spec §8.1): preset, tool buttons and
    # labels. Written to a new key; the version-1 key above stays untouched so a
    # rollback to an older build still reads its own flags.
    layout_state_v2_json: str = ""
    reduce_motion: bool = False
    # Fallback OS window frame (UI-1 PR-1, spec §4.3, §8.2, UA-20): restores the
    # standard operating system frame for Remote Desktop or display-driver issues.
    native_window_frame: bool = False
    gold_annotation_enabled: bool = False
    gold_dataset_path: str = ""
    references_dir: str = ""
    # Experimental features visibility (only LV strain is gated)
    show_strain: bool = False
    show_la_auto: bool = False
    despeckle_enabled: bool = False
    # JSON layout of the tool panel: section order, per-section tool order and
    # per-tool visibility. Empty string = built-in default layout.
    tool_panel_layout_json: str = ""
    # JSON layout of the tool panel, version 3 (TP-0 PR-2, spec TP §8.2):
    # profiles × contexts, stable catalog ids, unknown items kept aside.
    # Written to a separate key so that a rollback to an older build still
    # reads its own version-2 settings.
    tool_layout_v3_json: str = ""
    #: Measurement panel 2.0 (TP-2): contextual sections, quick tiles,
    #: favourites and search.  Default on since the TP-2 gate; the flag
    #: stays in «Экспериментальных» for one release as a rollback switch.
    tool_panel_v2: bool = True
    #: Width of the measurement panel in the default layout (0 = auto:
    #: 280 px for the legacy menu, 320 px for the 2.0 panel).
    panel_width: int = 0
    #: Show the «Label measurement» popup after a free caliper or trace (TP-4, spec §4.4, §9).
    label_picker_enabled: bool = True
    #: Norm dots in the measurement list (UI-5, UD-14/UQ-03, spec §8.2).  Off by
    #: default — colour must never read as a diagnosis — and the switch position
    #: is remembered.
    reference_norm_dots: bool = False
    # Presenter mode (second-display window for the audience)
    presenter_screen: str = ""
    presenter_visual_preset: bool = True
    presenter_pointer: bool = True
    # Rendering backend of the AUDIENCE viewer only (the speaker's viewer
    # keeps its auto-detected backend).  Raster by default: GL viewports in
    # a second top-level window have been observed to stay black on real
    # multi-monitor Linux setups (Debian 12 / Qt 6.4 / Intel) while every
    # raster overlay in the same window renders fine.
    presenter_audience_render: str = "raster"


def _settings_store() -> QSettings:
    # Presenter defaults to portable; Full may opt in with SONOFORGE_PORTABLE=1.
    # Both cases keep an INI next to the executable instead of using host QSettings.
    from echo_personal_tool.infrastructure.profile import qsettings_for

    return qsettings_for(_SETTINGS_ORG, _SETTINGS_APP)


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        parsed = int(value)
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


#: Theme of a fresh profile — the palette of the redesign concept.
DEFAULT_THEME_MODE = "graphite"
#: The default of the previous releases.  A stored value equal to it is treated
#: as «never chosen» once, so an update brings the concept palette to existing
#: installations; a deliberate switch back to it sticks (see :func:`_read_theme_mode`).
PREVIOUS_DEFAULT_THEME_MODE = "vscode_dark"
THEME_MODES = {"dark", "light", "system", "vscode_dark", "vscode_light", "graphite"}
#: Marker of the one-time default move; also the «user meant it» flag.
_THEME_DEFAULT_MARKER = "theme_mode_default_graphite"


def _read_theme_mode(store: Any) -> str:
    """Read the theme, moving the old default to the concept palette once.

    ``vscode_dark`` was the default until 0.3.4, so a stored value of it is far
    more likely «the app's default» than a decision; it is migrated once and the
    marker makes a later explicit choice of it permanent.
    """
    value = store.value("theme_mode")
    chosen = _read_choice(value, DEFAULT_THEME_MODE, THEME_MODES)
    migrated = _read_bool(store.value(_THEME_DEFAULT_MARKER), False)
    if chosen != PREVIOUS_DEFAULT_THEME_MODE or migrated:
        return chosen
    store.setValue("theme_mode", DEFAULT_THEME_MODE)
    store.setValue(_THEME_DEFAULT_MARKER, True)
    sync = getattr(store, "sync", None)
    if callable(sync):
        sync()
    return DEFAULT_THEME_MODE


def _read_choice(value: object, default: str, choices: set[str]) -> str:
    if isinstance(value, str) and value in choices:
        return value
    return default


def _read_measurement_persistence(store: Any, allowed: bool) -> bool:
    return allowed and _read_bool(
        store.value("measurement_persistence_enabled"), default_measurement_persistence_enabled()
    )


def load_user_preferences() -> UserPreferences:
    store = _settings_store()
    from echo_personal_tool.infrastructure.profile import capabilities_for

    capabilities = capabilities_for()
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
        tabs_enabled=_read_bool(store.value("tabs_enabled"), True) if capabilities.tabs else False,
        ui_scale_percent=normalize_ui_scale(store.value("ui_scale_percent")),
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
        playback_max_cache_mb=_clamp_int(
            store.value("playback_max_cache_mb"),
            64,
            8,
            512,
        ),
        # ``wl_preset`` (soft/contrast/last_used) is ignored if an older build stored it.
        wl_window=_clamp_int(store.value("wl_window"), DEFAULT_WL_WINDOW, 1, 400),
        wl_level=_clamp_int(store.value("wl_level"), DEFAULT_WL_LEVEL, 0, 100),
        wl_dr=_clamp_int(store.value("wl_dr"), DEFAULT_WL_DR, 0, 100),
        show_crosshair=_read_bool(store.value("show_crosshair"), True),
        magnifier_enabled=_read_bool(store.value("magnifier_enabled"), True),
        magnifier_zoom=_clamp_float(
            store.value("magnifier_zoom"),
            DEFAULT_MAGNIFIER_ZOOM,
            MIN_MAGNIFIER_ZOOM,
            MAX_MAGNIFIER_ZOOM,
        ),
        magnifier_radius_px=_clamp_int(
            store.value("magnifier_radius_px"),
            DEFAULT_MAGNIFIER_RADIUS_PX,
            MIN_MAGNIFIER_RADIUS_PX,
            MAX_MAGNIFIER_RADIUS_PX,
        ),
        magnifier_linear_persistent=_read_bool(store.value("magnifier_linear_persistent"), False),
        show_panel_frames=_read_bool(store.value("show_panel_frames"), False),
        show_caliper_labels_on_frame=_read_bool(store.value("show_caliper_labels_on_frame"), True),
        show_caliper_inline_labels=_read_bool(store.value("show_caliper_inline_labels"), False),
        show_doppler_calibration_roi=_read_bool(store.value("show_doppler_calibration_roi"), False),
        **_read_privacy_preferences(store),
        shortcut_overrides_json=str(store.value("shortcut_overrides_json", "") or ""),
        thumbnail_scale=_read_choice(
            store.value("thumbnail_scale"),
            "medium",
            {"small", "medium", "large"},
        ),
        thumbnail_sort_mode=_read_choice(
            store.value("thumbnail_sort_mode"),
            "created",
            {"created", "filename"},
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
        interesting_dicom_tags=str(store.value("interesting_dicom_tags", DEFAULT_INTERESTING_DICOM_TAGS)),
        confirm_reset=_read_bool(store.value("confirm_reset"), True),
        pdf_font_size=_clamp_int(
            store.value("pdf_font_size"),
            DEFAULT_PDF_FONT_SIZE,
            MIN_PDF_FONT_SIZE,
            MAX_PDF_FONT_SIZE,
        ),
        startup_mode=(
            _read_choice(store.value("startup_mode"), "empty", {"empty", "last_folder"})
            if capabilities.continue_last_session
            else "empty"
        ),
        last_opened_folder=str(store.value("last_opened_folder", "")) if capabilities.continue_last_session else "",
        last_session_source=(
            _read_choice(store.value("last_session_source"), "", SESSION_SOURCES)  # type: ignore
            if capabilities.continue_last_session
            else ""
        ),
        last_session_date=str(store.value("last_session_date", "")) if capabilities.continue_last_session else "",
        last_session_clip_count=(
            _clamp_int(store.value("last_session_clip_count"), 0, 0, 10_000)
            if capabilities.continue_last_session
            else 0
        ),
        measurement_persistence_enabled=_read_measurement_persistence(store, capabilities.measurement_storage),
        orthanc_cache_clear_on_exit=_read_bool(store.value("orthanc_cache_clear_on_exit"), True),
        theme_mode=_read_theme_mode(store),
        accent_palette=_read_choice(
            store.value("accent_palette"), "theme", {"theme", "blue", "teal", "violet", "amber"}
        ),
        language=_read_choice(store.value("language"), "en", {"ru", "en"}),
        auto_play=_read_bool(store.value("auto_play"), False),
        layout_state_json=str(store.value("layout_state_json", "")),
        layout_state_v2_json=str(store.value("layout_state_v2_json", "")),
        reduce_motion=_read_bool(store.value("reduce_motion"), False),
        native_window_frame=_read_bool(store.value("native_window_frame"), False),
        gold_annotation_enabled=_read_bool(store.value("gold_annotation_enabled"), False),
        gold_dataset_path=str(store.value("gold_dataset_path", "")),
        references_dir=str(store.value("references_dir", "")),
        show_strain=_read_bool(store.value("show_strain"), False),
        show_la_auto=_read_bool(store.value("show_la_auto"), False),
        despeckle_enabled=_read_bool(store.value("despeckle_enabled"), False),
        tool_panel_layout_json=str(store.value("tool_panel_layout_json", "")),
        tool_layout_v3_json=str(store.value("tool_layout_v3_json", "")),
        tool_panel_v2=_read_bool(store.value("tool_panel_v2"), True),
        panel_width=_clamp_int(store.value("panel_width"), 0, 0, 1000),
        label_picker_enabled=_read_bool(store.value("label_picker_enabled"), True),
        reference_norm_dots=_read_bool(store.value("reference_norm_dots"), False),
        area_tool_mode=_read_choice(store.value("area_tool_mode"), "click", {"click", "freehand"}),
        lv_contour_input=_read_choice(store.value("lv_contour_input"), "landmarks", {"landmarks", "trace"}),
        atrial_contour_input=_read_choice(store.value("atrial_contour_input"), "landmarks", {"landmarks", "trace"}),
        presenter_screen=str(store.value("presenter_screen", "")),
        presenter_visual_preset=_read_bool(store.value("presenter_visual_preset"), True),
        presenter_pointer=_read_bool(store.value("presenter_pointer"), True),
    )


def _read_privacy_preferences(store: Any) -> dict[str, Any]:
    return dict(
        anonymize_frames=_read_bool(store.value("anonymize_frames"), True),
        start_page_show_patient_data=_read_bool(store.value("start_page_show_patient_data"), False),
        phi_text_detector=_read_bool(store.value("phi_text_detector"), False),
        phi_mask_top_percent=_clamp_float(store.value("phi_mask_top_percent"), 0.0, 0.0, 0.30),
    )


def default_user_preferences() -> UserPreferences:
    """Factory-default preferences (not read from disk)."""
    return UserPreferences()


def default_measurement_persistence_enabled() -> bool:
    """W41-02 (decided 2026-10-09): measurement autosave is on by default in
    the full profile; the Presenter build stays opt-in (portable media, other
    people's machines). An explicitly stored preference always wins.

    Under pytest the answer is always False: test suites construct real
    controllers, and none of them may start writing measurement records into
    the host profile (a CI runner included). Tests of this default unset
    ``PYTEST_CURRENT_TEST`` explicitly.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    from echo_personal_tool.infrastructure.profile import capabilities_for

    return capabilities_for().measurement_storage_default


def measurement_persistence_notice_shown() -> bool:
    store = _settings_store()
    value = store.value("measurement_persistence_notice_shown", False)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def mark_measurement_persistence_notice_shown() -> None:
    store = _settings_store()
    store.setValue("measurement_persistence_notice_shown", True)
    store.sync()


def interesting_dicom_tag_list(preferences: UserPreferences) -> list[str]:
    return [part.strip() for part in preferences.interesting_dicom_tags.split(",") if part.strip()]


def save_user_preferences(preferences: UserPreferences) -> None:
    """Save preferences using only the active profile's permitted history.

    Presenter builds do not persist folder-history/last-session paths. Keep
    old keys readable only by Full so opening a stick on another workstation
    cannot silently resume an old host path.
    """
    store = _settings_store()
    from echo_personal_tool.infrastructure.profile import capabilities_for

    capabilities = capabilities_for()
    values = dict(preferences.__dict__)
    if not capabilities.continue_last_session:
        for key in (
            "startup_mode",
            "last_opened_folder",
            "last_session_source",
            "last_session_date",
            "last_session_clip_count",
        ):
            values.pop(key, None)
    if not capabilities.tabs:
        values["tabs_enabled"] = False
    if not capabilities.measurement_storage:
        values["measurement_persistence_enabled"] = False
    for key, value in values.items():
        store.setValue(key, value)
    # Saving is an explicit choice: from here on the stored theme is the user's,
    # and the one-time move of the old default must not touch it again.
    store.setValue(_THEME_DEFAULT_MARKER, True)
    store.sync()
