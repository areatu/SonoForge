"""Tests for persistent user preferences."""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.user_preferences import (
    DEFAULT_UI_FONT_SIZE,
    UserPreferences,
    default_user_preferences,
    load_user_preferences,
    resolve_wl_values,
    save_user_preferences,
)

pytestmark = pytest.mark.gui


def test_default_user_preferences() -> None:
    defaults = default_user_preferences()
    assert defaults.ui_font_size == DEFAULT_UI_FONT_SIZE
    assert defaults.playback_speed_multiplier == 1.0
    assert defaults.results_overlay_custom_position is False


def test_user_preferences_round_trip(qtbot) -> None:
    preferences = UserPreferences(
        ui_font_size=14,
        results_overlay_x_ratio=0.42,
        results_overlay_y_ratio=0.33,
        results_overlay_custom_position=True,
        results_overlay_font_size=18,
        results_overlay_opacity=0.7,
        caliper_line_width=3.5,
        contour_pen_manual_width=2.5,
        contour_pen_ai_width=3.0,
        contour_pen_simpson_width=1.5,
        magnetic_snap_enabled=False,
        playback_speed_multiplier=1.5,
        wl_preset="soft",
        show_crosshair=False,
        thumbnail_scale="large",
        doppler_auto_calibration_enabled=False,
        length_display_unit="cm",
        confirm_reset=False,
        pdf_font_size=12,
        startup_mode="last_folder",
        last_opened_folder="/tmp/study",
    )
    save_user_preferences(preferences)
    loaded = load_user_preferences()
    assert loaded.ui_font_size == 14
    assert loaded.results_overlay_custom_position is True
    assert loaded.results_overlay_opacity == 0.7
    assert loaded.playback_speed_multiplier == 1.5
    assert loaded.wl_preset == "soft"
    assert loaded.length_display_unit == "cm"
    assert loaded.startup_mode == "last_folder"
    assert loaded.last_opened_folder == "/tmp/study"

    save_user_preferences(UserPreferences())
    defaults = load_user_preferences()
    assert defaults.ui_font_size == DEFAULT_UI_FONT_SIZE
    assert defaults.magnetic_snap_enabled is True


def test_resolve_wl_values() -> None:
    soft = UserPreferences(wl_preset="soft")
    assert resolve_wl_values(soft) == (70, 40, 35)
    custom = UserPreferences(wl_preset="last_used", wl_window=88, wl_level=44, wl_dr=33)
    assert resolve_wl_values(custom) == (88, 44, 33)
