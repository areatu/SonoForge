"""Extended unit tests for main_window (layout document, pure helpers, key methods)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.layout.presets import (
    PRESET_CLASSIC,
    PRESET_FILMSTRIP,
    PRESET_MIRRORED,
    LayoutConfigV2,
)
from echo_personal_tool.presentation.main_window import (
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


# ── MainWindow._load_layout_document ───────────────────────────────


class TestLoadLayoutDocument:
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
        assert window._load_layout_document() == LayoutConfigV2()

    def test_valid_json(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"swap_places": True}))
        assert window._load_layout_document() == LayoutConfigV2(preset=PRESET_MIRRORED)

    def test_swap_and_gallery_migrate_to_the_filmstrip(self, qtbot) -> None:
        """Spec §8.1: presets are exclusive; the filmstrip wins over the mirror."""
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"swap_places": True, "gallery_horizontal": True}))
        assert window._load_layout_document().preset == PRESET_FILMSTRIP

    def test_invalid_json_returns_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, "not json")
        assert window._load_layout_document() == LayoutConfigV2()

    def test_unknown_field_returns_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"unknown_field": True}))
        assert window._load_layout_document() == LayoutConfigV2()

    def test_multiview_is_never_restored(self, qtbot) -> None:
        window = self._make_window(qtbot)
        self._set_v1(window, json.dumps({"swap_places": True, "multiview": True}))
        assert window._load_layout_document() == LayoutConfigV2(preset=PRESET_MIRRORED)
        assert window._multiview_mode is False


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


# ── MainWindow preset / tool-buttons selection ───────────────────────


class TestLayoutSelection:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    def test_select_preset(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert window._layout_document.preset == PRESET_CLASSIC
        window._on_layout_preset_selected(PRESET_MIRRORED)
        assert window._layout_document.preset == PRESET_MIRRORED

    def test_select_tool_buttons(self, qtbot) -> None:
        window = self._make_window(qtbot)
        window._on_layout_tool_buttons_selected("rail")
        assert window._layout_document.tool_buttons == "rail"

    def test_unknown_values_are_ignored(self, qtbot) -> None:
        window = self._make_window(qtbot)
        window._on_layout_preset_selected("sideways")
        window._on_layout_tool_buttons_selected("floating")
        assert window._layout_document == LayoutConfigV2()


# ── MainWindow slot assembly (UI-2 PR-1: the table replaces _decide_left/_right) ──


class TestSlotAssembly:
    def _make_window(self, qtbot) -> MainWindow:
        prefs = UserPreferences(layout_state_json="")
        window = MainWindow(controller=AppController(), user_preferences=prefs)
        qtbot.addWidget(window)
        return window

    @staticmethod
    def _sides(window: MainWindow, document: LayoutConfigV2, *, multiview: bool = False) -> tuple[object, object]:
        from echo_personal_tool.presentation.layout.presets import slot_plan

        plan = slot_plan(document, multiview=multiview)
        return window._slot_widget(plan.left), window._slot_widget(plan.right)

    def test_default_left_is_gallery(self, qtbot) -> None:
        window = self._make_window(qtbot)
        left, right = self._sides(window, LayoutConfigV2())
        assert left is window._gallery
        # Default layout: tool panel sits in the splitter, not in a side slot
        assert right is None

    def test_mirrored_preset(self, qtbot) -> None:
        window = self._make_window(qtbot)
        left, right = self._sides(window, LayoutConfigV2(preset=PRESET_MIRRORED))
        assert left is window._tool_panel
        assert right is window._gallery

    def test_filmstrip_preset_has_no_left_slot(self, qtbot) -> None:
        window = self._make_window(qtbot)
        left, right = self._sides(window, LayoutConfigV2(preset=PRESET_FILMSTRIP))
        assert left is None
        assert right is window._tool_panel

    def test_multiview_puts_the_tool_panel_on_the_right(self, qtbot) -> None:
        window = self._make_window(qtbot)
        _left, right = self._sides(window, LayoutConfigV2(), multiview=True)
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
        with (
            patch.object(window, "_show_status") as show_status,
            patch.object(window._viewer, "append_frame_overlay") as overlay,
        ):
            # ES phase should not trigger prompt
            window._maybe_prompt_es_auto("A4C", "ES", mode="manual")

        show_status.assert_not_called()
        overlay.assert_not_called()

    def test_ed_triggers(self, qtbot) -> None:
        window = self._make_window(qtbot)
        with (
            patch.object(window, "_show_status") as show_status,
            patch.object(window._viewer, "append_frame_overlay") as overlay,
        ):
            window._maybe_prompt_es_auto("A4C", "ED", mode="mbs")

        show_status.assert_called_once()
        message = show_status.call_args.args[0]
        assert message.startswith(tr("status.lv_go_systole", es_name="ESV Auto", view_label="4C"))
        overlay.assert_called_once_with(message)


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

    def test_layout_document_default(self, qtbot) -> None:
        window = self._make_window(qtbot)
        assert window._layout_document == LayoutConfigV2()
        assert window._multiview_mode is False
