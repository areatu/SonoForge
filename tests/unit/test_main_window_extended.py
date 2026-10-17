"""Extended unit tests for main_window (LayoutConfig, pure helpers, key methods)."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import (
    LayoutConfig,
    MainWindow,
    _loaded_file_label,
)

# ── _loaded_file_label ─────────────────────────────────────────────


class TestLoadedFileLabel:
    def test_with_path(self) -> None:
        inst = InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2.4",
            modality="US",
            number_of_frames=1,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="x",
            path=Path("/data/patient/scan.dcm"),
        )
        assert _loaded_file_label(inst) == "scan.dcm"

    def test_without_path(self) -> None:
        inst = InstanceMetadata(
            sop_instance_uid="1.2.3.4.5",
            series_uid="1.2.4",
            modality="US",
            number_of_frames=1,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="x",
        )
        assert _loaded_file_label(inst) == "1.2.3.4.5"


# ── LayoutConfig ───────────────────────────────────────────────────


class TestLayoutConfig:
    def test_defaults(self) -> None:
        cfg = LayoutConfig()
        assert cfg.swap_places is False
        assert cfg.gallery_horizontal is False
        assert cfg.activity_bar is False
        assert cfg.status_bar_visible is True
        assert cfg.multiview is False

    def test_all_true(self) -> None:
        cfg = LayoutConfig(
            swap_places=True,
            gallery_horizontal=True,
            activity_bar=True,
            status_bar_visible=True,
            multiview=True,
        )
        assert cfg.swap_places is True
        assert cfg.multiview is True

    def test_from_dict(self) -> None:
        data = {"swap_places": True, "gallery_horizontal": True}
        cfg = LayoutConfig(**data)
        assert cfg.swap_places is True
        assert cfg.gallery_horizontal is True
        assert cfg.activity_bar is False  # default

    def test_roundtrip_json(self) -> None:
        cfg = LayoutConfig(swap_places=True, multiview=True)
        raw = json.dumps(asdict(cfg))
        restored = LayoutConfig(**json.loads(raw))
        assert restored == cfg

    def test_replace(self) -> None:
        cfg = LayoutConfig()
        new = replace(cfg, swap_places=True, activity_bar=True)
        assert new.swap_places is True
        assert new.activity_bar is True
        assert cfg.swap_places is False  # original unchanged


# ── MainWindow._format_speckle_preset_name ─────────────────────────


class TestFormatSpecklePresetName:
    def test_standard(self) -> None:
        assert MainWindow._format_speckle_preset_name("standard") == "Standard"

    def test_research(self) -> None:
        assert MainWindow._format_speckle_preset_name("research") == "Research"

    def test_debug(self) -> None:
        assert MainWindow._format_speckle_preset_name("debug") == "Debug"

    def test_unknown(self) -> None:
        assert MainWindow._format_speckle_preset_name("custom_v2") == "custom_v2"


# ── MainWindow._load_layout_state ──────────────────────────────────


class TestLoadLayoutState:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    @staticmethod
    def _set_v1(window: MainWindow, raw: str) -> None:
        """Only the version-1 key: the window saves a version-2 document on every rebuild."""
        window._user_preferences.layout_state_v2_json = ""
        window._user_preferences.layout_state_json = raw

    def test_empty_json_returns_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, "")
        cfg = window._load_layout_state()
        assert cfg == LayoutConfig()

    def test_valid_json(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"swap_places": True}))
        cfg = window._load_layout_state()
        assert cfg.swap_places is True
        assert cfg.gallery_horizontal is False

    def test_swap_and_gallery_migrate_to_the_filmstrip(self, qtbot) -> None:
        """Spec §8.1: presets are exclusive; the filmstrip wins over the mirror."""
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"swap_places": True, "gallery_horizontal": True}))
        cfg = window._load_layout_state()
        assert cfg.gallery_horizontal is True
        assert cfg.swap_places is False

    def test_invalid_json_returns_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, "not json")
        cfg = window._load_layout_state()
        assert cfg == LayoutConfig()

    def test_unknown_field_returns_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"unknown_field": True}))
        cfg = window._load_layout_state()
        assert cfg == LayoutConfig()

    def test_multiview_is_never_restored(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"swap_places": True, "multiview": True}))
        cfg = window._load_layout_state()
        assert cfg.swap_places is True
        assert cfg.multiview is False


# ── MainWindow._has_chamber_contour ────────────────────────────────


class TestHasChamberContour:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    def test_no_contours(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert window._has_chamber_contour("LV", "A4C", "ED") is False

    def test_matching_contour(self, qtbot) -> None:
        window = self._make_window(qtbot)
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 20)])
        window._controller.state_manager.set_contours([contour])
        assert window._has_chamber_contour("LV", "A4C", "ED") is True

    def test_case_insensitive(self, qtbot) -> None:
        window = self._make_window(qtbot)
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 20)])
        window._controller.state_manager.set_contours([contour])
        assert window._has_chamber_contour("lv", "a4c", "ed") is True

    def test_wrong_chamber(self, qtbot) -> None:
        window = self._make_window(qtbot)
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 20)])
        window._controller.state_manager.set_contours([contour])
        assert window._has_chamber_contour("RA", "A4C", "ED") is False

    def test_wrong_phase(self, qtbot) -> None:
        window = self._make_window(qtbot)
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 20)])
        window._controller.state_manager.set_contours([contour])
        assert window._has_chamber_contour("LV", "A4C", "ES") is False


# ── MainWindow._on_layout_toggle ───────────────────────────────────


class TestOnLayoutToggle:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    def test_toggle_swap_places(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert window._layout_config.swap_places is False
        window._on_layout_toggle("swap_places", True)
        assert window._layout_config.swap_places is True

    def test_toggle_multiview(self, qtbot) -> None:
        window = self._make_window(qtbot)
        window._on_layout_toggle("multiview", True)
        assert window._layout_config.multiview is True

    def test_toggle_back(self, qtbot) -> None:
        window = self._make_window(qtbot)
        window._on_layout_toggle("swap_places", True)
        window._on_layout_toggle("swap_places", False)
        assert window._layout_config.swap_places is False


# ── MainWindow slot assembly (UI-2 PR-1: the table replaces _decide_left/_right) ──


class TestSlotAssembly:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    @staticmethod
    def _sides(window: MainWindow, cfg: LayoutConfig) -> tuple[object, object]:
        from echo_personal_tool.presentation.layout.presets import slot_plan

        plan = slot_plan(cfg.to_v2(), multiview=cfg.multiview)
        return window._slot_widget(plan.left), window._slot_widget(plan.right)

    def test_default_left_is_gallery(self, qtbot) -> None:
        window = self._make_window(qtbot)
        left, right = self._sides(window, LayoutConfig())
        assert left is window._gallery
        # Default layout: tool panel sits in the splitter, not in a side slot
        assert right is None

    def test_swapped_places(self, qtbot) -> None:
        window = self._make_window(qtbot)
        left, right = self._sides(window, LayoutConfig(swap_places=True))
        assert left is window._tool_panel
        assert right is window._gallery

    def test_gallery_horizontal_has_no_left_slot(self, qtbot) -> None:
        window = self._make_window(qtbot)
        left, right = self._sides(window, LayoutConfig(gallery_horizontal=True))
        assert left is None
        assert right is window._tool_panel

    def test_multiview_puts_the_tool_panel_on_the_right(self, qtbot) -> None:
        window = self._make_window(qtbot)
        _left, right = self._sides(window, LayoutConfig(multiview=True))
        assert right is window._tool_panel


# ── MainWindow._maybe_prompt_es_auto ───────────────────────────────


class TestMaybePromptEsAuto:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    def test_only_for_ed(self, qtbot) -> None:
        window = self._make_window(qtbot)
        # ES phase should not trigger prompt
        window._maybe_prompt_es_auto("A4C", "ES", mode="manual")
        # No crash = pass

    def test_ed_triggers(self, qtbot) -> None:
        window = self._make_window(qtbot)
        window._maybe_prompt_es_auto("A4C", "ED", mode="mbs")
        # No crash = pass


# ── MainWindow._format_speckle_preset_name (static) ───────────────


class TestMainWindowProperties:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    def test_browser_alias(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert window._browser is window._gallery

    def test_has_controller(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert isinstance(window._controller, AppController)

    def test_has_orthanc_cache(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert window._orthanc_cache is not None

    def test_layout_config_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert isinstance(window._layout_config, LayoutConfig)
