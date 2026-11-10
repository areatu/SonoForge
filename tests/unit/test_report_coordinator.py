"""ReportCoordinator without a window (#478).

The coordinator receives an application facade and a port of callables; these
tests build both from plain functions and a ``MagicMock`` controller. The only
Qt object is the stack that parents the report page — no ``QMainWindow``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from echo_personal_tool.application.tab_session import TabSession
from echo_personal_tool.application.user_preferences import UserPreferences, default_user_preferences
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.services.report_profiles import DEFAULT_PROFILE_ID
from echo_personal_tool.domain.services.study_projection import StudyProjection
from echo_personal_tool.presentation.coordinators.report_coordinator import (
    ReportCoordinator,
    ReportWindowPort,
    instance_label,
    study_profile_id,
)


@dataclass
class FakeWindow:
    """Records what the coordinator asks of the window."""

    stack: Any
    tab: TabSession | None
    preferences: UserPreferences = field(default_factory=default_user_preferences)
    statuses: list[str] = field(default_factory=list)
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    saved_preferences: list[UserPreferences] = field(default_factory=list)
    rename_result: bool = True
    save_path: str = ""
    printer: object | None = None
    protocol: MagicMock = field(default_factory=MagicMock)

    def port(self) -> ReportWindowPort:
        def store(preferences: UserPreferences) -> None:
            self.preferences = preferences
            self.saved_preferences.append(preferences)

        def rename(measurement_id: str, label: str) -> bool:
            self.calls.append(("rename", measurement_id, label))
            return self.rename_result

        return ReportWindowPort(
            active_tab=lambda: self.tab,
            preferences=lambda: self.preferences,
            store_preferences=store,
            page_stack=lambda: self.stack,
            dialog_parent=lambda: self.stack,
            show_status=self.statuses.append,
            show_active_surface=lambda: self.calls.append(("surface",)),
            focus_images=lambda: self.calls.append(("focus_images",)),
            focus_viewer=lambda: self.calls.append(("focus_viewer",)),
            open_instance=lambda instance: self.calls.append(("open", instance.sop_instance_uid)),
            protocol_session=lambda: self.protocol,
            rename_contour=rename,
            mirror_report_mode=lambda report: self.calls.append(("mirror", report)),
            ask_save_path=lambda title, name, file_filter: self.calls.append(("ask_save", name)) or self.save_path,
            warn=lambda title, text: self.calls.append(("warn", title, text)),
            ask_printer=lambda: self.printer,
        )


def _tab() -> TabSession:
    return TabSession(tab_id="t1", origin="folder", root="/tmp", cache_session_id="", studies=[])


def _instance(uid: str, name: str | None = None) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="8",
        modality="US",
        number_of_frames=30,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=Path(f"/data/{name}") if name else None,
    )


def _studies(*instances: InstanceMetadata) -> list[SimpleNamespace]:
    """The open studies as the coordinator walks them: study → series → instances."""
    return [SimpleNamespace(series=[SimpleNamespace(instances=list(instances))])]


@pytest.fixture
def controller() -> MagicMock:
    controller = MagicMock()
    controller.compute_study_snapshot.return_value = None
    controller.patient_metric_sources.return_value = ("unset", "unset")
    controller.study_projection.return_value = StudyProjection()
    controller.state_manager.snapshot.instance = None
    controller.state_manager.snapshot.total_frames = 0
    controller.studies = []
    return controller


@pytest.fixture
def window(qapp) -> FakeWindow:
    from PySide6.QtWidgets import QStackedWidget

    stack = QStackedWidget()
    yield FakeWindow(stack=stack, tab=_tab())
    stack.deleteLater()


@pytest.fixture
def coordinator(controller: MagicMock, window: FakeWindow) -> ReportCoordinator:
    return ReportCoordinator(controller, window.port())


class TestMode:
    def test_the_page_is_built_on_first_entry_and_reused(self, coordinator, window) -> None:
        assert coordinator.page is None

        coordinator.set_mode(True)
        page = coordinator.page
        coordinator.set_mode(False)
        coordinator.set_mode(True)

        assert page is not None
        assert coordinator.page is page
        assert window.stack.indexOf(page) >= 0
        assert window.tab.report_mode is True

    def test_leaving_the_mode_gives_the_keys_back_to_the_images(self, coordinator, window) -> None:
        coordinator.set_mode(True)
        window.calls.clear()

        coordinator.set_mode(False)

        assert window.calls == [("surface",), ("focus_images",)]
        assert coordinator.mode_active() is False

    def test_toggle_and_the_tool_panel_entry(self, coordinator) -> None:
        coordinator.toggle_mode()
        assert coordinator.mode_active() is True
        coordinator.toggle_mode()
        assert coordinator.mode_active() is False
        coordinator.show_results()
        assert coordinator.mode_active() is True

    def test_without_a_tab_nothing_happens(self, coordinator, window) -> None:
        window.tab = None

        coordinator.set_mode(True)

        assert coordinator.page is None
        assert window.calls == []
        assert coordinator.mode_page() is None

    def test_mode_page_mirrors_the_switch_and_builds_nothing_for_the_images(self, coordinator, window) -> None:
        assert coordinator.mode_page() is None
        assert window.calls == [("mirror", False)]
        assert coordinator.page is None

        window.tab.report_mode = True
        page = coordinator.mode_page()

        assert page is coordinator.page is not None
        assert window.calls[-1] == ("mirror", True)


class TestTabEdits:
    def test_the_conclusion_lives_in_the_tab(self, coordinator, window) -> None:
        coordinator.set_conclusion("Норма")
        assert window.tab.report_conclusion == "Норма"

    def test_a_finished_version_refuses_edits(self, coordinator, window) -> None:
        window.tab.report_conclusion = "Подписано"
        window.tab.report_finished = True

        coordinator.set_conclusion("Правка")
        coordinator.set_value_hidden("lvef", True)
        coordinator.set_patient_field("name", "Иванов")
        coordinator.remember_generated_conclusion("блок")
        coordinator.rename_value("m-1", "Почка")

        assert window.tab.report_conclusion == "Подписано"
        assert window.tab.report_hidden_values == set()
        assert window.tab.report_patient_fields == {}
        assert window.tab.report_generated_conclusion == ""
        assert window.calls == []

    def test_hiding_and_restoring_a_row(self, coordinator, window) -> None:
        coordinator.set_value_hidden("lvef", True)
        assert coordinator.hidden_value_keys() == {"lvef"}
        # A key without a row in the current document is still listed, so it can be restored.
        assert coordinator.hidden_value_labels() == (("lvef", "lvef"),)

        coordinator.set_value_hidden("lvef", False)
        assert coordinator.hidden_value_keys() == set()

    def test_patient_fields_override_the_header(self, coordinator, window) -> None:
        coordinator.set_patient_field("name", "Петров")
        coordinator.set_patient_field("not_a_field", "x")

        assert window.tab.report_patient_fields == {"name": "Петров"}
        assert coordinator.patient_info(None).name == "Петров"

    def test_the_inputs_footnote_is_a_saved_preference(self, coordinator, window) -> None:
        coordinator.set_inputs_visible(True)

        assert len(window.saved_preferences) == 1
        assert window.preferences.report_show_inputs is True

    def test_measure_arms_the_protocol_step_on_the_images(self, coordinator, window) -> None:
        window.protocol.active_protocol_id = "other"
        coordinator.set_mode(True)

        coordinator.measure_step("lv_linear", 2)

        assert window.tab.report_mode is False
        window.protocol.start.assert_called_once_with("lv_linear")
        window.protocol.arm.assert_called_once_with(2)


class TestRename:
    def test_the_label_is_stripped_and_sent_to_the_viewer(self, coordinator, window) -> None:
        coordinator.rename_value("m-10", "  Почка ")
        assert window.calls == [("rename", "m-10", "Почка")]

    def test_a_contour_of_another_clip_is_reported(self, coordinator, window) -> None:
        window.rename_result = False
        coordinator.rename_value("ghost", "Почка")
        assert len(window.statuses) == 1

    def test_a_blank_name_is_not_an_edit(self, coordinator, window) -> None:
        coordinator.rename_value("m-10", "   ")
        coordinator.rename_value("", "Почка")
        assert window.calls == []


class TestOpenFrames:
    def test_another_clip_is_opened_and_the_frame_waits_for_it(self, coordinator, controller, window) -> None:
        target = _instance("1.2.3", "clip.dcm")
        controller.studies = _studies(target)

        coordinator.open_frames("1.2.3", 7)

        assert ("open", "1.2.3") in window.calls
        assert window.calls[-1] == ("focus_viewer",)
        assert coordinator.pending_frame == 7
        controller.state_manager.set_frame.assert_not_called()

        controller.state_manager.snapshot.total_frames = 30
        coordinator.resume_pending_frame()

        controller.set_playing.assert_called_once_with(False)
        controller.state_manager.set_frame.assert_called_once_with(7)
        assert coordinator.pending_frame is None

    def test_the_clip_on_screen_jumps_at_once(self, coordinator, controller) -> None:
        target = _instance("1.2.3")
        controller.studies = _studies(target)
        controller.state_manager.snapshot.instance = target
        controller.state_manager.snapshot.total_frames = 10

        coordinator.open_frames("1.2.3", 4)

        controller.state_manager.set_frame.assert_called_once_with(4)
        assert coordinator.pending_frame is None

    def test_a_missing_clip_and_an_out_of_range_frame(self, coordinator, controller, window) -> None:
        coordinator.open_frames("nope", 1)
        assert len(window.statuses) == 1

        controller.state_manager.snapshot.total_frames = 5
        coordinator.jump_to_frame(5)
        coordinator.jump_to_frame(-1)
        controller.state_manager.set_frame.assert_not_called()

    def test_clip_labels_follow_the_gallery(self, coordinator, controller) -> None:
        named, unnamed = _instance("1", "a.dcm"), _instance("2")
        controller.studies = _studies(named, unnamed)

        assert coordinator.clip_label("1") == "a.dcm"
        assert coordinator.clip_label("2") == "2"
        assert coordinator.clip_label("3") == ""
        assert instance_label(named) == "a.dcm"


class TestExport:
    def test_csv_is_written_where_the_dialog_points(self, coordinator, window, tmp_path) -> None:
        coordinator.set_mode(True)
        window.save_path = str(tmp_path / "out.csv")

        coordinator.export_csv()

        assert (tmp_path / "out.csv").read_text(encoding="utf-8").startswith("group")
        assert ("ask_save", "echo_report.csv") in window.calls

    def test_a_cancelled_dialog_writes_nothing(self, coordinator, window, tmp_path) -> None:
        coordinator.set_mode(True)
        window.save_path = ""

        coordinator.export_json()

        assert list(tmp_path.iterdir()) == []

    def test_a_write_error_is_shown_without_its_text(self, coordinator, window, tmp_path) -> None:
        coordinator.set_mode(True)
        window.save_path = str(tmp_path / "missing_dir" / "out.json")

        coordinator.export_json()

        warnings = [call for call in window.calls if call[0] == "warn"]
        assert len(warnings) == 1
        assert str(tmp_path) not in warnings[0][2]

    def test_nothing_to_export_before_the_page_exists(self, coordinator, window) -> None:
        coordinator.export_pdf()
        coordinator.export_csv()
        coordinator.print_sheet()
        assert window.calls == []

    def test_print_goes_to_the_chosen_printer_only(self, coordinator, window, monkeypatch) -> None:
        from echo_personal_tool.presentation.coordinators import report_coordinator as module

        printed: list[object] = []
        monkeypatch.setattr(module, "print_report_pdf", lambda data, printer: printed.append(printer) or True)
        coordinator.set_mode(True)
        page = coordinator.page
        monkeypatch.setattr(type(page), "pdf_bytes", property(lambda self: b"%PDF-1.4"))

        window.printer = None
        coordinator.print_sheet()
        assert printed == []

        window.printer = printer = object()
        coordinator.print_sheet()
        assert printed == [printer]


class TestFormatAndFinish:
    def test_without_a_tab_the_format_is_the_default(self, coordinator, window) -> None:
        window.tab = None
        assert coordinator.profile_id() == DEFAULT_PROFILE_ID

    def test_an_explicit_choice_belongs_to_the_tab(self, coordinator, window) -> None:
        allowed = coordinator.allowed_profiles()
        coordinator.choose_profile(allowed[-1])
        assert window.tab.report_profile == allowed[-1]
        assert coordinator.profile_id() == allowed[-1]

    def test_a_format_the_study_profile_does_not_print_falls_back(self, coordinator, window) -> None:
        window.tab.report_profile = "no-such-format"
        assert coordinator.profile_id() in coordinator.allowed_profiles()

    def test_finishing_without_a_rendered_sheet_is_refused(self, coordinator, window) -> None:
        coordinator.set_finished(True)
        assert window.tab.report_finished is False

    def test_a_new_draft_drops_the_frozen_version(self, coordinator, window) -> None:
        window.tab.report_finished = True
        window.tab.report_frozen_sheet = object()

        coordinator.set_finished(False)

        assert window.tab.report_finished is False
        assert window.tab.report_frozen_sheet is None

    def test_the_study_profile_comes_from_the_preferences(self, window) -> None:
        assert study_profile_id(window.preferences)
