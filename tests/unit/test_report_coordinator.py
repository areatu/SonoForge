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
    activated_tools: list[str] = field(default_factory=list)

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
            activate_tool=self.activated_tools.append,
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


def test_conclusion_adjudication_is_per_tab_and_revalidated(coordinator, controller, window, monkeypatch) -> None:
    from echo_personal_tool.domain.calculators.models import CalculationsSnapshot, CalculatorResult, OutputValue
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.presentation.report_mode.conclusion_decision import ConclusionDecisionDialog

    def snapshot(eroa: float) -> MeasurementSnapshot:
        outputs = tuple(
            OutputValue(id=name, label=name, value=value, unit="", decimals=2, formula="")
            for name, value in (("eroa_mr", eroa), ("rvol_mr", 40), ("rf_mr", 60))
        )
        return MeasurementSnapshot(
            calculations=CalculationsSnapshot(results=(CalculatorResult(calculator_id="pisa_mr", outputs=outputs),))
        )

    controller.compute_study_snapshot.return_value = snapshot(0.45)
    current_values = []

    def ask(parent, finding, *, current=None):
        current_values.append(current)
        return next(key for key in finding.candidates if key.endswith("moderate"))

    monkeypatch.setattr(ConclusionDecisionDialog, "ask", ask)
    first_tab = window.tab
    first = coordinator.provide_conclusion()
    assert "mv.regurgitation" in first_tab.report_conclusion_choices
    assert first.changed
    coordinator.provide_conclusion()
    assert current_values[-1] is not None
    window.tab = _tab()
    coordinator.provide_conclusion()
    assert current_values[-1] is None
    window.tab = first_tab
    controller.compute_study_snapshot.return_value = snapshot(0.46)
    coordinator.provide_conclusion()
    assert current_values[-1] is None
    monkeypatch.setattr(ConclusionDecisionDialog, "ask", lambda *args, **kwargs: None)
    canceled = coordinator.provide_conclusion()
    assert not window.tab.report_conclusion_choices
    assert "Physician selection:" not in canceled.text


def test_conclusion_choice_dialog_defaults_to_review(qtbot) -> None:
    from PySide6.QtWidgets import QComboBox

    from echo_personal_tool.domain.services.report_conclusion import ConclusionFinding
    from echo_personal_tool.presentation.report_mode.conclusion_decision import ConclusionDecisionDialog

    finding = ConclusionFinding(
        "mv.regurgitation",
        "report.conclusion.finding.mr.review",
        0,
        (),
        (),
        ("report.conclusion.finding.mr.moderate", "report.conclusion.finding.mr.severe"),
        (0.4, 40, 60),
    )
    dialog = ConclusionDecisionDialog(finding)
    qtbot.addWidget(dialog)
    combo = dialog.findChild(QComboBox, "conclusionDecisionChoice")
    assert combo.currentData() == ""
    assert combo.count() == 3
    dialog2 = ConclusionDecisionDialog(finding, current=finding.candidates[1])
    qtbot.addWidget(dialog2)
    assert dialog2.findChild(QComboBox, "conclusionDecisionChoice").currentData() == finding.candidates[1]


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

    def test_measure_tool_opens_the_organ_measurement(self, coordinator, window) -> None:
        coordinator.set_mode(True)

        coordinator.measure_tool("cca.imt")

        assert window.tab.report_mode is False
        assert window.activated_tools == ["cca.imt"]

    def test_measure_without_a_protocol_or_tool_does_nothing(self, coordinator, window) -> None:
        coordinator.set_mode(True)

        coordinator.measure_step("", 0)
        coordinator.measure_tool("")

        assert window.tab.report_mode is True
        assert window.activated_tools == []

    def test_measure_arms_the_protocol_step_on_the_images(self, coordinator, window) -> None:
        window.protocol.active_protocol_id = "other"
        coordinator.set_mode(True)

        coordinator.measure_step("lv_linear", 2)

        assert window.tab.report_mode is False
        window.protocol.start.assert_called_once_with("lv_linear")
        window.protocol.arm.assert_called_once_with(2)


class TestCompleteness:
    """Issue 560: the pre-export checklist reaches the sheet and the PDF."""

    def test_an_incomplete_checklist_is_printed_as_a_notice(self, coordinator) -> None:
        from echo_personal_tool.application.localization import tr

        coordinator.set_mode(True)
        document = coordinator.current_document()

        assert tr("report.notice.checklist_incomplete", missing=22, stale=0) in document.notices

    def test_a_stale_value_is_counted_apart_from_missing(self, coordinator, controller) -> None:
        from echo_personal_tool.domain.protocols import ProjectionValue
        from echo_personal_tool.domain.translation import tr

        controller.study_projection.return_value = StudyProjection(
            values={"lv.ivsd": ProjectionValue(value=1.0, stale=True)}
        )
        coordinator.set_mode(True)
        document = coordinator.current_document()

        assert tr("report.notice.checklist_incomplete", missing=21, stale=1) in document.notices
        assert coordinator.page.checklist_summary().stale == 1

    def test_unreviewed_contours_are_reported_next_to_missing_values(self, coordinator, controller) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

        controller.compute_study_snapshot.return_value = MeasurementSnapshot(unreviewed_contours=3)
        coordinator.set_mode(True)
        coordinator.current_document()

        assert coordinator.page.checklist_summary().unreviewed == 3

    def test_the_checklist_follows_the_study_type(self, coordinator, window) -> None:
        window.preferences.study_profile = "builtin.vascular"

        coordinator.set_mode(True)

        assert [section.id for section in coordinator.page.sections.sections] == ["precerebral"]
        assert coordinator.page.checklist_summary().missing == 2

    def test_a_decision_prints_on_the_sheet_with_its_reason(self, coordinator) -> None:
        from echo_personal_tool.application.localization import tr
        from echo_personal_tool.domain.services.report_sections import CHECK_NOT_APPLICABLE

        coordinator.set_mode(True)
        page = coordinator.page
        item = page.sections.sections[0].items[0]
        page.sections.set_decision(item.key, CHECK_NOT_APPLICABLE, "не входит в протокол")

        document = coordinator.current_document()
        rows = [value for group in document.groups for value in group.values if value.label == item.label]

        assert len(rows) == 1
        assert tr("report.checklist.not_applicable") in rows[0].value
        assert "не входит в протокол" in rows[0].value
        assert page.checklist_summary().not_applicable == 1


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

    def test_the_echo_study_profile_defaults_to_the_echo_format(self, coordinator, window) -> None:
        """2026-11-16, п.6: «Эхокардиография» opens the sheet as «ЭхоКГ».

        The old DICOM-header classification asked the vendor tags for cardiac
        keywords first and buried the echo sheet under «УЗИ» whenever a Samsung
        cine carried none of them.
        """
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        window.preferences.study_profile = "builtin.adult_echo"
        window.tab.report_profile = ""
        assert coordinator.profile_id() == PROFILE_ECHO

    def test_another_study_profile_keeps_its_own_default_format(self, coordinator, window) -> None:
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        window.preferences.study_profile = "builtin.vascular"
        window.tab.report_profile = ""
        chosen = coordinator.profile_id()
        assert chosen != PROFILE_ECHO
        assert chosen in coordinator.allowed_profiles()

    def test_apply_preferences_mirrors_the_saved_template(self, coordinator, window) -> None:
        """2026-11-16, п.6: «колонки измерений — две» reaches the sheet at once."""
        import json

        from echo_personal_tool.domain.services.report_template import COLUMNS_TWO, ReportTemplate

        coordinator.set_mode(True)
        window.preferences.report_template_json = json.dumps(ReportTemplate(columns=COLUMNS_TWO).as_dict())

        coordinator.apply_preferences(window.preferences)

        template = coordinator.page.preview.template
        assert template is not None
        assert template.normalized_columns == COLUMNS_TWO


@pytest.fixture
def repeated_rows(controller):
    from echo_personal_tool.domain.models import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_selection import select_report_sources

    raw = tuple(
        LinearMeasurement(label, mm, mm, frame, sop_instance_uid="1.2.9")
        for label, mm, frame in [("Alpha", 61, 8), ("Beta", 34, 10), ("Gamma", 45, 3), ("Alpha", 53, 2)]
    )

    def snapshot(*, report_choices=None):
        selected, repeats = select_report_sources(raw, report_choices or {})
        return MeasurementSnapshot(linear_measurements=selected, report_repeats=repeats, spacing_calibrated=True)

    controller.compute_study_snapshot.side_effect = snapshot
    controller.studies = _studies(_instance("1.2.9", "scan.dcm"))


@pytest.mark.gui
def test_row_dialog_persists_layout_but_only_pins_the_sample_in_its_tab(
    coordinator, repeated_rows, window, monkeypatch, tmp_path
):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QPushButton, QTreeWidget

    from echo_personal_tool.application.localization import tr
    from echo_personal_tool.presentation.report_values_dialog import ReportValuesDialog

    window.preferences.report_value_order = ("thyroid:absent:0",)
    window.preferences.report_value_excluded = ("kidney:absent:0",)
    coordinator.set_mode(True)
    page = coordinator.page
    rows = {v.label: v for g in page.document.groups for v in g.values}
    assert list(rows) == ["Beta", "Gamma", "Alpha"]
    assert float(rows["Alpha"].value) == 53

    def edit(dialog):
        tree = dialog.findChild(QTreeWidget, "reportValuesTree")
        assert tree.currentItem().text(0) == "Alpha"  # entered from the repeated row
        source = dialog.findChild(QComboBox, "reportMeasurementSource")
        assert source.count() == 3 and source.currentData() == ""
        assert "61" in source.itemText(1) and tr(
            "report.origin.clip_frame", name="scan.dcm", frame=9
        ) in source.itemText(1)
        source.setCurrentIndex(1)
        group = tree.currentItem().parent()
        group.child(1).setCheckState(0, Qt.CheckState.Unchecked)
        up = next(b for b in dialog.findChildren(QPushButton) if b.text() == tr("report.values.up"))
        up.click()
        up.click()
        assert not up.isEnabled()
        return ReportValuesDialog.DialogCode.Accepted

    monkeypatch.setattr(ReportValuesDialog, "exec", edit)
    # Item 1 of the 2026-11-18 list: the row dialog is no longer behind the
    # context menu — the menu is only «скрыть», the choice moved to the card.
    menu = page.preview._build_value_menu(rows["Alpha"])
    assert [action.text() for action in menu.actions()] == [tr("report.hide_value")]
    coordinator.edit_values(rows["Alpha"].key)
    doc_rows = [v for g in page.document.groups for v in g.values]
    assert [v.label for v in doc_rows] == ["Alpha", "Beta"]
    assert float(doc_rows[0].value) == 61 and doc_rows[0].origin.clips[0].frame_index == 8
    assert window.preferences.report_value_excluded == tuple(sorted((rows["Gamma"].key, "kidney:absent:0")))
    assert window.preferences.report_value_order == (
        "thyroid:absent:0",
        rows["Alpha"].key,
        rows["Beta"].key,
        rows["Gamma"].key,
    )
    assert [key for key, _ in page.sections.hidden_values] == [rows["Gamma"].key]
    _check_exports(coordinator, window, monkeypatch, tmp_path)

    first = window.tab
    frozen = page.preview.version()
    coordinator.set_finished(True)
    window.tab = _tab()
    window.tab.tab_id = "another"
    window.tab.report_mode = True
    coordinator.mode_page()  # switch through the real tab-surface hook
    assert [(v.label, float(v.value)) for g in page.document.groups for v in g.values] == [("Alpha", 53), ("Beta", 34)]
    coordinator.set_value_hidden(rows["Gamma"].key, False)
    assert rows["Gamma"].key not in window.preferences.report_value_excluded
    assert page.document.groups[0].values[-1].label == "Gamma"
    window.tab = first
    coordinator.mode_page()
    assert page.preview.version() == frozen and coordinator.current_document() == frozen.document
    assert not page.sections.hidden_values
    assert page.preview._build_value_menu(rows["Alpha"]) is None


@pytest.mark.gui
def test_all_measurements_mode_edits_rows_the_study_never_measured(qapp):
    """2026-11-18 list, item 3: the layout of future reports is editable here."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeWidget

    from echo_personal_tool.presentation.report_values_dialog import ReportValuesDialog

    dialog = ReportValuesDialog((), (), clip_label=lambda uid: "")
    assert dialog.findChild(QTreeWidget, "reportValuesTree").topLevelItemCount() == 0
    dialog._mode.setCurrentIndex(1)
    tree = dialog.findChild(QTreeWidget, "reportValuesTree")
    rows = {}
    for i in range(tree.topLevelItemCount()):
        section = tree.topLevelItem(i)
        for j in range(section.childCount()):
            row = section.child(j)
            rows[row.data(0, Qt.ItemDataRole.UserRole)] = row
    assert "av:linear.ao.sinus:0" in rows and "ra:ra.ravi:0" in rows
    assert rows["av:linear.ao.sinus:0"].text(0) == "Ao Sinus"

    rows["av:linear.ao.sinus:0"].setCheckState(0, Qt.CheckState.Unchecked)
    edits = dialog.edits()
    assert "av:linear.ao.sinus:0" in edits.excluded
    # The choice is remembered when the mode toggles back and forth.
    dialog._mode.setCurrentIndex(0)
    assert dialog._mode.currentData() == "study"
    edits = dialog.edits()
    assert "av:linear.ao.sinus:0" in edits.excluded
    dialog.deleteLater()


def _check_exports(coordinator, window, monkeypatch, tmp_path):
    import csv
    import json

    import pymupdf

    from echo_personal_tool.presentation.coordinators import report_coordinator as module

    # Exercise the actual PDF worker/export, not just the builder. Printing
    # rasterises the preview PDF: intercept the bytes handed to the printer.
    preview = coordinator.page.pdf_bytes
    window.save_path = str(tmp_path / "report.pdf")
    coordinator.export_pdf()
    for contents in (preview, Path(window.save_path).read_bytes()):
        with pymupdf.open(stream=contents, filetype="pdf") as pdf:
            text = "\n".join(sheet.get_text() for sheet in pdf)
            assert "Gamma" not in text and text.index("Alpha") < text.index("Beta")
            assert "61" in text[text.index("Alpha") : text.index("Beta")]
    print_job = MagicMock(return_value=True)
    monkeypatch.setattr(module, "print_report_pdf", print_job)
    window.printer = object()
    coordinator.print_sheet()
    print_job.assert_called_once_with(preview, window.printer)
    window.save_path = str(tmp_path / "report.json")
    coordinator.export_json()
    exported = json.loads(Path(window.save_path).read_text(encoding="utf-8"))["groups"][0]["values"]
    assert [(row["label"], float(row["value"])) for row in exported] == [("Alpha", 61), ("Beta", 34)]
    window.save_path = str(tmp_path / "report.csv")
    coordinator.export_csv()
    with Path(window.save_path).open(encoding="utf-8") as f:
        assert [(r["label"], float(r["value"])) for r in csv.DictReader(f)] == [("Alpha", 61), ("Beta", 34)]


@pytest.mark.gui
def test_automatic_choice_cancel_and_quick_hide_do_not_leak_between_tabs(
    coordinator, window, repeated_rows, monkeypatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QToolButton, QTreeWidget

    from echo_personal_tool.presentation.report_values_dialog import ReportValuesDialog

    coordinator.set_mode(True)
    page = coordinator.page
    rows = {v.label: v for g in page.document.groups for v in g.values}
    alpha, beta = rows["Alpha"].key, rows["Beta"].key
    coordinator.set_value_hidden(beta, True)

    def select(dialog, index):
        dialog.findChild(QComboBox, "reportMeasurementSource").setCurrentIndex(index)
        return ReportValuesDialog.DialogCode.Accepted

    monkeypatch.setattr(ReportValuesDialog, "exec", lambda dialog: select(dialog, 1))
    coordinator.edit_values(alpha)
    assert window.tab.report_value_choices and beta in window.tab.report_hidden_values
    assert beta not in window.preferences.report_value_excluded and not window.saved_preferences
    monkeypatch.setattr(ReportValuesDialog, "exec", lambda dialog: select(dialog, 0))
    coordinator.edit_values(alpha)
    assert window.tab.report_value_choices == {}
    assert [float(v.value) for g in page.document.groups for v in g.values if v.key == alpha] == [53]

    def cancel(dialog):
        tree = dialog.findChild(QTreeWidget)
        tree.currentItem().setCheckState(0, Qt.CheckState.Unchecked)
        dialog.findChild(QComboBox, "reportMeasurementSource").setCurrentIndex(1)
        return ReportValuesDialog.DialogCode.Rejected

    before = page.document
    monkeypatch.setattr(ReportValuesDialog, "exec", cancel)
    button = page.preview.findChild(QToolButton, "reportEditValues")
    button.click()
    assert page.document == before and not window.tab.report_value_choices and not window.saved_preferences
    coordinator.set_finished(True)
    assert not button.isEnabled() and page.preview._build_value_menu(rows["Alpha"]) is None
    coordinator.edit_values(rows["Alpha"].key)
    assert page.document == before and not window.tab.report_value_choices


@pytest.mark.gui
def test_last_hidden_row_can_be_restored_from_an_empty_section(coordinator, repeated_rows, window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeWidget

    from echo_personal_tool.presentation.report_values_dialog import ReportValuesDialog

    coordinator.set_mode(True)
    page = coordinator.page
    before = page.document.groups

    def check_rows(dialog, state):
        tree = dialog.findChild(QTreeWidget)
        section = tree.topLevelItem(0)
        for i in range(section.childCount()):
            section.child(i).setCheckState(0, state)
        return ReportValuesDialog.DialogCode.Accepted

    monkeypatch.setattr(ReportValuesDialog, "exec", lambda dialog: check_rows(dialog, Qt.CheckState.Unchecked))
    coordinator.edit_values()
    assert not page.document.groups and len(page.sections.hidden_values) == 3
    monkeypatch.setattr(ReportValuesDialog, "exec", lambda dialog: check_rows(dialog, Qt.CheckState.Checked))
    coordinator.edit_values()
    assert page.document.groups == before and not page.sections.hidden_values
