"""Sex button, report edits and norm hovers share the active tab's context."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.tab_session import TabSession
from echo_personal_tool.presentation.study_header_controls import PatientSexController, reference_sex
from echo_personal_tool.presentation.system_bar import SystemBar
from tests.unit.test_report_coordinator import controller as controller
from tests.unit.test_report_coordinator import coordinator as coordinator
from tests.unit.test_report_coordinator import window as window

pytestmark = pytest.mark.gui


@pytest.fixture
def header(qtbot, window, controller, coordinator):
    host = QWidget()
    qtbot.addWidget(host)
    host._system_bar = SystemBar(host)
    host._controller = controller
    host._tabs = SimpleNamespace(active=window.tab)
    host.report_coordinator = coordinator
    binding = PatientSexController(host)
    return host, binding


def test_square_sex_button_updates_report_and_hover_without_stale_cache(header, window, coordinator, qtbot):
    host, _ = header
    button = host.findChild(QWidget, "patientSexButton")
    assert button.width() == button.height()
    assert button.text() == "М" and button.isChecked()
    assert "sex" not in window.tab.report_patient_fields  # unknown DICOM is not fabricated
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert button.text() == "Ж" and not button.isChecked()
    assert coordinator.patient_info(None).sex == "F"
    assert reference_sex(host) == "female"
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert coordinator.patient_info(None).sex == "M" and reference_sex(host) == "male"


def test_report_edit_and_tab_switch_restore_the_correct_sex(header, window, coordinator):
    host, _ = header
    coordinator.set_patient_field("sex", "F")
    assert host._system_bar.patient_sex() == "F"
    first = window.tab
    second = TabSession(tab_id="second", origin="folder", root="/second", cache_session_id="", studies=[])
    second.report_patient_fields["sex"] = "M"
    window.tab = host._tabs.active = second
    coordinator.mode_page()
    assert host._system_bar.patient_sex() == "M"
    window.tab = host._tabs.active = first
    coordinator.mode_page()
    assert host._system_bar.patient_sex() == "F"
    assert reference_sex(host) == "female"


def test_finished_report_sex_cannot_be_changed_from_header(header, window, coordinator, qtbot):
    host, binding = header
    coordinator.set_patient_field("sex", "F")
    window.tab.report_finished = True
    binding.sync()
    button = host.findChild(QWidget, "patientSexButton")
    assert not button.isEnabled()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert coordinator.patient_info(None).sex == "F"


def test_sex_button_retranslates_without_changing_sex(header):
    from echo_personal_tool.application.localization import set_language

    host, _ = header
    host.report_coordinator.set_patient_field("sex", "F")
    set_language("en")
    host._system_bar.reload_text()
    assert host.findChild(QWidget, "patientSexButton").text() == "W"
    assert host._system_bar.patient_sex() == "F"


def test_norm_card_uses_new_sex_immediately_after_click(header, qtbot):
    from echo_personal_tool.presentation.reference_card import card_for_row

    host, _ = header
    male = card_for_row("lv.lvedd", value=54.0, unit="мм", sex=reference_sex(host), language="ru")
    qtbot.mouseClick(host.findChild(QWidget, "patientSexButton"), Qt.MouseButton.LeftButton)
    female = card_for_row("lv.lvedd", value=54.0, unit="мм", sex=reference_sex(host), language="ru")
    assert (male.norm.low, male.norm.high) == (42.0, 59.0)
    assert (female.norm.low, female.norm.high) == (36.0, 51.0)
    assert male.grade.name == "Норма" and female.grade.name != "Норма"
