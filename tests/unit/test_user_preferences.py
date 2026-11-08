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
    def test_always_returns_stored_window_level(self):
        prefs = UserPreferences(wl_window=100, wl_level=50, wl_dr=50)
        assert not hasattr(prefs, "wl_preset")
        assert resolve_wl_values(prefs) == (100, 50, 50)

    def test_stored_preset_does_not_override_window_level(self, isolated_prefs):
        store = QSettings("sonoforge-test", "prefs-test")
        store.setValue("wl_preset", "soft")
        store.setValue("wl_window", 111)
        store.setValue("wl_level", 22)
        store.setValue("wl_dr", 33)
        store.sync()
        loaded = load_user_preferences()
        assert not hasattr(loaded, "wl_preset")
        assert resolve_wl_values(loaded) == (111, 22, 33)
        assert store.value("wl_preset") == "soft"


class TestDefaultUserPreferences:
    def test_returns_user_preferences(self, isolated_prefs):
        prefs = default_user_preferences()
        assert isinstance(prefs, UserPreferences)
        assert prefs.ui_font_size == up_mod.DEFAULT_UI_FONT_SIZE
        assert prefs.playback_speed_multiplier == up_mod.DEFAULT_PLAYBACK_SPEED
        assert prefs.magnetic_snap_enabled is True
        assert prefs.language == "en"

        from echo_personal_tool.presentation.layout.presets import resolve_document

        for prefs in (default_user_preferences(), load_user_preferences()):
            layout = resolve_document(prefs.layout_state_v2_json, prefs.layout_state_json)
            assert (layout.preset, layout.tool_buttons) == ("classic", "auto")
            assert prefs.language == "en"
            assert prefs.lv_contour_input == "trace"
            assert prefs.atrial_contour_input == "trace"
            assert prefs.anonymize_frames is True

        prefs = UserPreferences(
            language="ru", lv_contour_input="landmarks", atrial_contour_input="landmarks", anonymize_frames=False
        )
        save_user_preferences(prefs)
        loaded = load_user_preferences()
        assert (loaded.language, loaded.lv_contour_input, loaded.atrial_contour_input, loaded.anonymize_frames) == (
            "ru",
            "landmarks",
            "landmarks",
            False,
        )


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
        from echo_personal_tool.application.user_preferences import (
            load_user_preferences as load_application_preferences,
        )
        from echo_personal_tool.application.user_preferences import (
            save_user_preferences as save_application_preferences,
        )

        prefs = UserPreferences(
            ui_font_size=14,
            playback_speed_multiplier=2.0,
            language="en",
            show_strain=True,
        )
        save_application_preferences(prefs)
        loaded = load_application_preferences()
        assert loaded.ui_font_size == 14
        assert loaded.playback_speed_multiplier == 2.0
        assert loaded.language == "en"
        assert loaded.show_strain is True

    def test_orthanc_cache_clear_on_exit_roundtrip(self, isolated_prefs):
        prefs = UserPreferences(orthanc_cache_clear_on_exit=False)
        save_user_preferences(prefs)
        loaded = load_user_preferences()
        assert loaded.orthanc_cache_clear_on_exit is False

    def test_tool_layout_v3_roundtrip(self, isolated_prefs):
        """TP-0 PR-2: the version-3 layout has its own key next to version 2."""
        prefs = UserPreferences(
            tool_panel_layout_json='{"version": 2, "sections": []}',
            tool_layout_v3_json='{"version": 3, "active_profile": "user-1", "profiles": []}',
        )
        save_user_preferences(prefs)
        loaded = load_user_preferences()
        assert loaded.tool_layout_v3_json == prefs.tool_layout_v3_json
        assert loaded.tool_panel_layout_json == prefs.tool_panel_layout_json

    def test_tool_layout_v3_defaults_to_empty(self, isolated_prefs):
        loaded = load_user_preferences()
        assert loaded.tool_layout_v3_json == ""

    def test_load_defaults_when_empty(self, isolated_prefs):
        loaded = load_user_preferences()
        assert loaded.ui_font_size == up_mod.DEFAULT_UI_FONT_SIZE
        assert loaded.language == "en"
        assert loaded.orthanc_cache_clear_on_exit is True

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
        assert loaded.language == "en"

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
        # Э4: UI fonts are logical pixels in both the stylesheet and the app font;
        # pt survives only in the PDF/print settings.
        assert up_mod.MAX_UI_FONT_SIZE >= 20
        assert up_mod.MAX_OVERLAY_FONT_SIZE >= 32

    def test_speed_bounds(self):
        assert up_mod.MIN_PLAYBACK_SPEED <= up_mod.DEFAULT_PLAYBACK_SPEED <= up_mod.MAX_PLAYBACK_SPEED

    def test_magnetic_bounds(self):
        assert up_mod.MIN_MAGNETIC_WEIGHT <= up_mod.DEFAULT_MAGNETIC_WEIGHT <= up_mod.MAX_MAGNETIC_WEIGHT
        assert up_mod.MIN_MAGNETIC_RADIUS <= up_mod.DEFAULT_MAGNETIC_RADIUS <= up_mod.MAX_MAGNETIC_RADIUS
        assert up_mod.MIN_MAGNETIC_RELEASE <= up_mod.DEFAULT_MAGNETIC_RELEASE <= up_mod.MAX_MAGNETIC_RELEASE


class TestUserPreferencesDataclass:
    def test_all_fields_have_defaults(self):
        prefs = UserPreferences()
        assert prefs.ui_font_size == up_mod.DEFAULT_UI_FONT_SIZE
        assert prefs.ui_scale_percent == 0  # 0 = Auto: follow the OS scale
        assert prefs.results_overlay_opacity == 0.70
        assert prefs.caliper_line_width == 2.0
        assert prefs.show_crosshair is True
        assert prefs.theme_mode == "graphite"
        assert prefs.startup_mode == "empty"
        assert prefs.reduce_motion is False
        assert prefs.gold_annotation_enabled is False
        assert prefs.show_doppler_calibration_roi is False


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


class TestLastSessionSource:
    """Q-05/D-27: where the last opened study came from."""

    def test_default_is_unknown(self) -> None:
        assert default_user_preferences().last_session_source == ""

    def test_round_trip(self, isolated_prefs: None) -> None:
        prefs = default_user_preferences()
        prefs.last_session_source = up_mod.SESSION_SOURCE_SERVER
        save_user_preferences(prefs)

        assert load_user_preferences().last_session_source == up_mod.SESSION_SOURCE_SERVER

    def test_folder_value_round_trips(self, isolated_prefs: None) -> None:
        prefs = default_user_preferences()
        prefs.last_session_source = up_mod.SESSION_SOURCE_FOLDER
        save_user_preferences(prefs)

        assert load_user_preferences().last_session_source == up_mod.SESSION_SOURCE_FOLDER

    def test_unknown_value_falls_back_to_empty(self, isolated_prefs: None) -> None:
        store = QSettings(up_mod._SETTINGS_ORG, up_mod._SETTINGS_APP)
        store.setValue("last_session_source", "cloud")
        store.sync()

        assert load_user_preferences().last_session_source == ""

    def test_missing_value_falls_back_to_empty(self, isolated_prefs: None) -> None:
        assert load_user_preferences().last_session_source == ""


class TestMeasurementPersistenceDefault:
    """W41-02 (2026-10-09): autosave default-on in the full profile, opt-in in
    Presenter, explicit user choice always wins, tests never inherit the
    default-on behaviour."""

    def test_default_is_off_under_pytest(self):
        # The host-profile guard: no test may start writing records to disk.
        assert up_mod.default_measurement_persistence_enabled() is False

    def test_full_profile_defaults_on(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("SONOFORGE_PROFILE", raising=False)
        assert up_mod.default_measurement_persistence_enabled() is True

    def test_presenter_profile_defaults_off(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("SONOFORGE_PROFILE", "presenter")
        assert up_mod.default_measurement_persistence_enabled() is False

    def test_unset_key_uses_profile_default(self, monkeypatch, isolated_prefs):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        assert load_user_preferences().measurement_persistence_enabled is True

    def test_presenter_unset_key_stays_off(self, monkeypatch, isolated_prefs):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("SONOFORGE_PROFILE", "presenter")
        assert load_user_preferences().measurement_persistence_enabled is False

    def test_explicitly_stored_choice_wins(self, monkeypatch, isolated_prefs):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        prefs = default_user_preferences()
        prefs.measurement_persistence_enabled = False
        save_user_preferences(prefs)
        assert load_user_preferences().measurement_persistence_enabled is False
        prefs.measurement_persistence_enabled = True
        save_user_preferences(prefs)
        assert load_user_preferences().measurement_persistence_enabled is True

    def test_notice_flag_roundtrip(self, isolated_prefs):
        assert up_mod.measurement_persistence_notice_shown() is False
        up_mod.mark_measurement_persistence_notice_shown()
        assert up_mod.measurement_persistence_notice_shown() is True


def test_tabs_enabled_defaults_true(isolated_qsettings) -> None:
    assert default_user_preferences().tabs_enabled
    assert load_user_preferences().tabs_enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_tabs_enabled_round_trip(isolated_qsettings, enabled) -> None:
    preferences = default_user_preferences()
    preferences.tabs_enabled = enabled
    save_user_preferences(preferences)
    assert load_user_preferences().tabs_enabled is enabled


def test_label_picker_enabled_defaults_true(isolated_qsettings) -> None:
    assert default_user_preferences().label_picker_enabled is True
    assert load_user_preferences().label_picker_enabled is True


@pytest.mark.parametrize("enabled", [True, False])
def test_label_picker_enabled_round_trip(isolated_qsettings, enabled) -> None:
    preferences = default_user_preferences()
    preferences.label_picker_enabled = enabled
    save_user_preferences(preferences)
    assert load_user_preferences().label_picker_enabled is enabled


def test_reference_norm_dots_defaults_off(isolated_qsettings) -> None:
    """UI-5 (UD-14, UA-15): the norm dots are opt-in — colour must never read
    as a diagnosis."""
    assert default_user_preferences().reference_norm_dots is False
    assert load_user_preferences().reference_norm_dots is False


@pytest.mark.parametrize("enabled", [True, False])
def test_reference_norm_dots_round_trip(isolated_qsettings, enabled) -> None:
    """UI-5 (UQ-03): the position of the «Нормы» switch is remembered."""
    preferences = default_user_preferences()
    preferences.reference_norm_dots = enabled
    save_user_preferences(preferences)
    assert load_user_preferences().reference_norm_dots is enabled


def test_native_window_frame_defaults_false(isolated_qsettings) -> None:
    assert default_user_preferences().native_window_frame is False
    assert load_user_preferences().native_window_frame is False


@pytest.mark.parametrize("enabled", [True, False])
def test_native_window_frame_round_trip(isolated_qsettings, enabled: bool) -> None:
    preferences = default_user_preferences()
    preferences.native_window_frame = enabled
    save_user_preferences(preferences)
    assert load_user_preferences().native_window_frame is enabled


# ── Theme default: the concept palette (ТЗ 2026-10-23, п. 4) ──────────


def test_the_default_theme_is_the_concept_palette(isolated_qsettings) -> None:
    """«Графит» is the palette of the approved design, so it is the default.

    The former default — ``vscode_dark`` — was a grey-blue editor palette that
    the interface never was designed in; it only happened to be pinned first.
    """
    from echo_personal_tool.infrastructure.user_preferences import DEFAULT_THEME_MODE

    assert DEFAULT_THEME_MODE == "graphite"
    assert default_user_preferences().theme_mode == "graphite"
    assert load_user_preferences().theme_mode == "graphite"


def test_the_previous_default_is_migrated_once(isolated_qsettings) -> None:
    """An installation that never chose a theme reaches the concept palette."""
    store = isolated_qsettings
    store.setValue("theme_mode", "vscode_dark")
    store.sync()

    assert load_user_preferences().theme_mode == "graphite"
    assert store.value("theme_mode") == "graphite"


def test_a_deliberate_choice_of_the_old_theme_sticks(isolated_qsettings) -> None:
    """After the one-time move, choosing VS Code Dark again is respected."""
    preferences = load_user_preferences()
    preferences.theme_mode = "vscode_dark"
    save_user_preferences(preferences)
    assert load_user_preferences().theme_mode == "vscode_dark"


@pytest.mark.parametrize("theme", ["dark", "light", "vscode_light", "system", "graphite"])
def test_other_known_themes_are_not_touched(isolated_qsettings, theme: str) -> None:
    store = isolated_qsettings
    store.setValue("theme_mode", theme)
    store.sync()
    assert load_user_preferences().theme_mode == theme


def test_accent_palette_round_trips_and_invalid_values_fall_back(isolated_prefs):
    for accent in ("theme", "blue", "teal", "violet", "amber"):
        prefs = default_user_preferences()
        prefs.accent_palette = accent
        save_user_preferences(prefs)
        assert load_user_preferences().accent_palette == accent
    store = up_mod._settings_store()
    store.setValue("accent_palette", "invalid")
    assert load_user_preferences().accent_palette == "theme"


def test_start_page_patient_data_is_opt_in_and_hotkeys_round_trip(isolated_prefs):
    from dataclasses import replace

    assert load_user_preferences().start_page_show_patient_data is False
    encoded = '{"caliper": ["F9"], "zoom_fit": []}'
    save_user_preferences(
        replace(default_user_preferences(), start_page_show_patient_data=True, shortcut_overrides_json=encoded)
    )
    saved = load_user_preferences()
    assert saved.start_page_show_patient_data is True
    assert saved.shortcut_overrides_json == encoded
    save_user_preferences(replace(saved, start_page_show_patient_data=False))
    assert load_user_preferences().start_page_show_patient_data is False


class TestStudyProfilePreference:
    """Item 11 of the 2026-11-06 list: the study type survives a restart."""

    def test_the_default_is_echocardiography(self) -> None:
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        assert UserPreferences().study_profile == "builtin.adult_echo"

    def test_the_choice_round_trips(self) -> None:
        from dataclasses import replace

        from echo_personal_tool.infrastructure.user_preferences import (
            UserPreferences,
            load_user_preferences,
            save_user_preferences,
        )

        save_user_preferences(replace(UserPreferences(), study_profile="builtin.thyroid"))
        assert load_user_preferences().study_profile == "builtin.thyroid"
        save_user_preferences(UserPreferences())
        assert load_user_preferences().study_profile == "builtin.adult_echo"

    def test_a_missing_value_reads_as_the_default(self, tmp_path, monkeypatch) -> None:
        """An old settings file has no such key: it must not break the startup."""
        from echo_personal_tool.infrastructure import user_preferences as module

        assert module._read_str(None, "builtin.adult_echo") == "builtin.adult_echo"
        assert module._read_str("", "builtin.adult_echo") == ""
        assert module._read_str(42, "builtin.adult_echo") == "builtin.adult_echo"


class TestReportTemplatePreference:
    """Item 12 of the 2026-11-06 list: the printable form survives a restart."""

    def test_the_default_is_the_full_standard_form(self) -> None:
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        assert UserPreferences().report_template_json == ""

    def test_a_saved_form_round_trips(self) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.services.report_template import (
            FIELD_PHYSICIAN,
            ReportTemplate,
            decode_template,
            encode_template,
        )
        from echo_personal_tool.infrastructure.user_preferences import (
            UserPreferences,
            load_user_preferences,
            save_user_preferences,
        )

        stored = encode_template(ReportTemplate(header_fields=(FIELD_PHYSICIAN,), show_notes=False))
        save_user_preferences(replace(UserPreferences(), report_template_json=stored))
        read = decode_template(load_user_preferences().report_template_json)
        assert read.header_fields == (FIELD_PHYSICIAN,)
        assert read.show_notes is False

        save_user_preferences(UserPreferences())
        assert load_user_preferences().report_template_json == ""

    def test_an_unreadable_setting_falls_back_to_the_standard_form(self) -> None:
        """A settings file damaged outside the app must not truncate a sheet."""
        from dataclasses import replace

        from echo_personal_tool.domain.services.report_template import decode_template, default_template
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        damaged = replace(UserPreferences(), report_template_json="{not json")
        assert decode_template(damaged.report_template_json) == default_template()
