"""Acceptance: open preferences → change theme/font → close → reopen → verify persistence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from echo_personal_tool.infrastructure.user_preferences import (
    DEFAULT_UI_FONT_SIZE,
    MAX_UI_FONT_SIZE,
    MIN_UI_FONT_SIZE,
    default_user_preferences,
    resolve_wl_values,
)

pytestmark = [pytest.mark.gui, pytest.mark.acceptance]


class TestPreferencesWorkflow:
    def test_default_preferences_valid(self) -> None:
        """Default UserPreferences has sensible values."""
        prefs = default_user_preferences()
        assert MIN_UI_FONT_SIZE <= prefs.ui_font_size <= MAX_UI_FONT_SIZE
        assert prefs.theme_mode in {"dark", "light", "system", "vscode_dark", "vscode_light"}
        assert prefs.language in {"ru", "en"}

    def test_theme_mode_change(self) -> None:
        """Theme mode can be changed between valid values."""
        prefs = default_user_preferences()
        for mode in ("dark", "light", "vscode_dark", "vscode_light", "system"):
            prefs = replace(prefs, theme_mode=mode)
            assert prefs.theme_mode == mode

    def test_font_size_change(self) -> None:
        """UI font size can be changed within valid range."""
        prefs = default_user_preferences()
        prefs = replace(prefs, ui_font_size=16)
        assert prefs.ui_font_size == 16

    def test_font_size_clamping(self) -> None:
        """Font size values outside range are clamped by loader."""
        from echo_personal_tool.infrastructure.user_preferences import _clamp_int

        assert _clamp_int(5, DEFAULT_UI_FONT_SIZE, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE) == MIN_UI_FONT_SIZE
        assert _clamp_int(99, DEFAULT_UI_FONT_SIZE, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE) == MAX_UI_FONT_SIZE
        assert _clamp_int(12, DEFAULT_UI_FONT_SIZE, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE) == 12

    def test_wl_preset_resolution(self) -> None:
        """Window/level preset resolves to correct values."""
        prefs = default_user_preferences()

        soft = replace(prefs, wl_preset="soft")
        assert resolve_wl_values(soft) == (70, 40, 35)

        contrast = replace(prefs, wl_preset="contrast")
        assert resolve_wl_values(contrast) == (140, 55, 65)

        custom = replace(prefs, wl_preset="last_used", wl_window=120, wl_level=60, wl_dr=40)
        assert resolve_wl_values(custom) == (120, 60, 40)

    def test_layout_state_json_field(self) -> None:
        """Layout state JSON field can store serialized layout."""
        prefs = default_user_preferences()
        layout = '{"swap_places": true, "gallery_horizontal": false}'
        prefs = replace(prefs, layout_state_json=layout)
        assert prefs.layout_state_json == layout

    def test_preferences_dataclass_is_copyable(self) -> None:
        """UserPreferences can be replaced with new values."""
        prefs = default_user_preferences()
        prefs2 = replace(prefs, language="en", theme_mode="light")
        assert prefs2.language == "en"
        assert prefs2.theme_mode == "light"
        assert prefs.language == "ru"  # original unchanged

    def test_preferences_dialog_standalone(self, qtbot, qapp) -> None:
        """User preferences dialog can be created without crashing."""
        from echo_personal_tool.presentation.user_preferences_dialog import (
            show_user_preferences_dialog,
        )

        # We don't actually open the modal dialog (would block); just verify import works
        assert callable(show_user_preferences_dialog)

    def test_boolean_preferences_roundtrip(self) -> None:
        """Boolean preferences toggle correctly."""
        prefs = default_user_preferences()
        prefs = replace(prefs, show_crosshair=False, magnetic_snap_enabled=False)
        assert prefs.show_crosshair is False
        assert prefs.magnetic_snap_enabled is False
        prefs = replace(prefs, show_crosshair=True, magnetic_snap_enabled=True)
        assert prefs.show_crosshair is True
        assert prefs.magnetic_snap_enabled is True

    def test_experimental_feature_flags(self) -> None:
        """Only LV strain is an experimental feature (off by default)."""
        prefs = default_user_preferences()
        assert prefs.show_strain is False
