"""Unit tests for infrastructure/user_preferences.py — covers all helper functions and save/load."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtCore import QSettings

from echo_personal_tool.infrastructure import user_preferences as up_mod
from echo_personal_tool.infrastructure.user_preferences import (
    UserPreferences,
    default_user_preferences,
    interesting_dicom_tag_list,
    load_user_preferences,
    resolve_wl_values,
    save_user_preferences,
)


@pytest.fixture
def isolated_prefs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    org = "sonoforge-test"
    app = "prefs-test"
    monkeypatch.setattr(up_mod, "_SETTINGS_ORG", org)
    monkeypatch.setattr(up_mod, "_SETTINGS_APP", app)
    store = QSettings(org, app)
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


class TestClampInt:
    def test_valid_value(self):
        assert up_mod._clamp_int(12, 10, 9, 18) == 12

    def test_below_min(self):
        assert up_mod._clamp_int(5, 10, 9, 18) == 9

    def test_above_max(self):
        assert up_mod._clamp_int(25, 10, 9, 18) == 18

    def test_none_returns_default(self):
        assert up_mod._clamp_int(None, 10, 9, 18) == 10

    def test_string_number(self):
        assert up_mod._clamp_int("15", 10, 9, 18) == 15

    def test_invalid_string_returns_default(self):
        assert up_mod._clamp_int("abc", 10, 9, 18) == 10


class TestClampFloat:
    def test_valid_value(self):
        assert up_mod._clamp_float(0.5, 0.7, 0.1, 1.0) == 0.5

    def test_below_min(self):
        assert up_mod._clamp_float(-1.0, 0.7, 0.1, 1.0) == 0.1

    def test_above_max(self):
        assert up_mod._clamp_float(5.0, 0.7, 0.1, 1.0) == 1.0

    def test_none_returns_default(self):
        assert up_mod._clamp_float(None, 0.7, 0.1, 1.0) == 0.7

    def test_invalid_string_returns_default(self):
        assert up_mod._clamp_float("xyz", 0.7, 0.1, 1.0) == 0.7


class TestReadBool:
    def test_none_returns_default(self):
        assert up_mod._read_bool(None, True) is True
        assert up_mod._read_bool(None, False) is False

    def test_bool_passthrough(self):
        assert up_mod._read_bool(True, False) is True
        assert up_mod._read_bool(False, True) is False

    def test_string_true(self):
        assert up_mod._read_bool("true", False) is True
        assert up_mod._read_bool("True", False) is True
        assert up_mod._read_bool("1", False) is True
        assert up_mod._read_bool("yes", False) is True

    def test_string_false(self):
        assert up_mod._read_bool("false", True) is False
        assert up_mod._read_bool("0", True) is False
        assert up_mod._read_bool("no", True) is False

    def test_other_type(self):
        assert up_mod._read_bool(42, False) is True
        assert up_mod._read_bool(0, True) is False


class TestReadChoice:
    def test_valid_choice(self):
        assert up_mod._read_choice("dark", "light", {"dark", "light"}) == "dark"

    def test_invalid_choice(self):
        assert up_mod._read_choice("invalid", "light", {"dark", "light"}) == "light"

    def test_non_string(self):
        assert up_mod._read_choice(42, "default", {"42"}) == "default"


class TestResolveWlValues:
    def test_soft_preset(self):
        prefs = UserPreferences(wl_preset="soft")
        assert resolve_wl_values(prefs) == (70, 40, 35)

    def test_contrast_preset(self):
        prefs = UserPreferences(wl_preset="contrast")
        assert resolve_wl_values(prefs) == (140, 55, 65)

    def test_last_used(self):
        prefs = UserPreferences(wl_preset="last_used", wl_window=100, wl_level=50, wl_dr=50)
        assert resolve_wl_values(prefs) == (100, 50, 50)


class TestDefaultUserPreferences:
    def test_returns_user_preferences(self):
        prefs = default_user_preferences()
        assert isinstance(prefs, UserPreferences)
        assert prefs.ui_font_size == up_mod.DEFAULT_UI_FONT_SIZE
        assert prefs.playback_speed_multiplier == up_mod.DEFAULT_PLAYBACK_SPEED
        assert prefs.magnetic_snap_enabled is True
        assert prefs.language == "ru"


class TestInterestingDicomTagList:
    def test_default_tags(self):
        prefs = default_user_preferences()
        tags = interesting_dicom_tag_list(prefs)
        assert "StudyDate" in tags
        assert "SeriesDescription" in tags

    def test_empty_string(self):
        prefs = UserPreferences(interesting_dicom_tags="")
        tags = interesting_dicom_tag_list(prefs)
        assert tags == []

    def test_with_spaces(self):
        prefs = UserPreferences(interesting_dicom_tags=" Tag1 , Tag2 , Tag3 ")
        tags = interesting_dicom_tag_list(prefs)
        assert tags == ["Tag1", "Tag2", "Tag3"]


class TestSaveAndLoadPreferences:
    def test_roundtrip(self, isolated_prefs):
        prefs = UserPreferences(
            ui_font_size=14,
            playback_speed_multiplier=2.0,
            language="en",
            show_strain=True,
        )
        save_user_preferences(prefs)
        loaded = load_user_preferences()
        assert loaded.ui_font_size == 14
        assert loaded.playback_speed_multiplier == 2.0
        assert loaded.language == "en"
        assert loaded.show_strain is True

    def test_load_defaults_when_empty(self, isolated_prefs):
        loaded = load_user_preferences()
        assert loaded.ui_font_size == up_mod.DEFAULT_UI_FONT_SIZE
        assert loaded.language == "ru"

    def test_clamping_on_load(self, isolated_prefs):
        store = QSettings("sonoforge-test", "prefs-test")
        store.setValue("ui_font_size", 100)
        store.sync()
        loaded = load_user_preferences()
        assert loaded.ui_font_size == up_mod.MAX_UI_FONT_SIZE

    def test_clamping_negative(self, isolated_prefs):
        store = QSettings("sonoforge-test", "prefs-test")
        store.setValue("ui_font_size", -5)
        store.sync()
        loaded = load_user_preferences()
        assert loaded.ui_font_size == up_mod.MIN_UI_FONT_SIZE

    def test_invalid_choice_uses_default(self, isolated_prefs):
        store = QSettings("sonoforge-test", "prefs-test")
        store.setValue("language", "de")
        store.sync()
        loaded = load_user_preferences()
        assert loaded.language == "ru"

    def test_overlay_custom_position(self, isolated_prefs):
        store = QSettings("sonoforge-test", "prefs-test")
        store.setValue("results_overlay_custom_position", True)
        store.setValue("results_overlay_x_ratio", 0.10)
        store.sync()
        loaded = load_user_preferences()
        assert loaded.results_overlay_custom_position is False  # x_ratio < 0.15 → disabled

    def test_overlay_custom_position_valid(self, isolated_prefs):
        store = QSettings("sonoforge-test", "prefs-test")
        store.setValue("results_overlay_custom_position", True)
        store.setValue("results_overlay_x_ratio", 0.50)
        store.sync()
        loaded = load_user_preferences()
        assert loaded.results_overlay_custom_position is True


class TestConstants:
    def test_font_size_bounds(self):
        assert up_mod.MIN_UI_FONT_SIZE <= up_mod.DEFAULT_UI_FONT_SIZE <= up_mod.MAX_UI_FONT_SIZE
        assert up_mod.MIN_OVERLAY_FONT_SIZE <= up_mod.DEFAULT_RESULTS_OVERLAY_FONT_SIZE <= up_mod.MAX_OVERLAY_FONT_SIZE

    def test_speed_bounds(self):
        assert up_mod.MIN_PLAYBACK_SPEED <= up_mod.DEFAULT_PLAYBACK_SPEED <= up_mod.MAX_PLAYBACK_SPEED

    def test_magnetic_bounds(self):
        assert up_mod.MIN_MAGNETIC_WEIGHT <= up_mod.DEFAULT_MAGNETIC_WEIGHT <= up_mod.MAX_MAGNETIC_WEIGHT
        assert up_mod.MIN_MAGNETIC_RADIUS <= up_mod.DEFAULT_MAGNETIC_RADIUS <= up_mod.MAX_MAGNETIC_RADIUS
        assert up_mod.MIN_MAGNETIC_RELEASE <= up_mod.DEFAULT_MAGNETIC_RELEASE <= up_mod.MAX_MAGNETIC_RELEASE


class TestUserPreferencesDataclass:
    def test_all_fields_have_defaults(self):
        prefs = UserPreferences()
        assert prefs.ui_font_size == 12
        assert prefs.results_overlay_opacity == 0.70
        assert prefs.caliper_line_width == 2.0
        assert prefs.show_crosshair is True
        assert prefs.theme_mode == "dark"
        assert prefs.startup_mode == "empty"
        assert prefs.reduce_motion is False
        assert prefs.gold_annotation_enabled is False


class TestAreaToolMode:
    def test_default_is_click(self) -> None:
        prefs = default_user_preferences()
        assert prefs.area_tool_mode == "click"

    def test_click_valid(self) -> None:
        prefs = UserPreferences(area_tool_mode="click")
        assert prefs.area_tool_mode == "click"

    def test_freehand_valid(self) -> None:
        prefs = UserPreferences(area_tool_mode="freehand")
        assert prefs.area_tool_mode == "freehand"
