"""Regression coverage for context swaps, unified report editing and cine controls."""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from echo_personal_tool.domain.services.report_builder import PatientInfo
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.report_mode.patient import ReportPatientEditor
from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2, _clear_layout


def test_removed_widgets_never_become_top_level_windows(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    child = QWidget()
    layout.addWidget(child)
    host.show()
    _clear_layout(layout)
    assert child.parentWidget() is host
    assert child.isHidden()
    assert not child.isWindow()


def test_viewer_context_bursts_coalesce_and_preserve_update_state(qtbot, monkeypatch):
    panel = ToolPanelV2(UserPreferences())
    qtbot.addWidget(panel)
    rebuilt = []
    original = panel._rebuild_content

    def rebuild():
        rebuilt.append(panel.context())
        original()

    monkeypatch.setattr(panel, "_rebuild_content", rebuild)
    panel.set_view_context("doppler", "cw", defer=True)
    panel.set_view_context("m", defer=True)
    panel.set_view_context("2d", defer=True)
    assert not rebuilt
    qtbot.waitUntil(lambda: bool(rebuilt))
    assert rebuilt == ["2d"]
    assert panel.updatesEnabled()
    panel.setUpdatesEnabled(False)
    panel._rebuild()
    assert not panel.updatesEnabled()


def test_doppler_submode_is_only_shown_in_doppler(qtbot):
    panel = ToolPanelV2(UserPreferences())
    qtbot.addWidget(panel)
    assert panel._mode_combo.isHidden()
    panel.set_view_context("doppler", "pw")
    assert not panel._mode_combo.isHidden()
    assert panel._mode_combo.isEnabled()
    assert [panel._mode_combo.itemData(index) for index in range(4)] == ["", "PW", "CW", "TDI"]
    assert panel._footer._report_button.isHidden()


def test_report_patient_editor_does_not_emit_when_loading_another_tab(qtbot):
    editor = ReportPatientEditor()
    qtbot.addWidget(editor)
    edits = []
    editor.field_changed.connect(lambda *args: edits.append(args))
    editor.set_patient(PatientInfo(name="A", institution="Hospital", sex="F"))
    assert not edits
    editor._fields["name"].textEdited.emit("Edited")
    assert edits == [("name", "Edited")]
    editor.set_patient(PatientInfo(name="B"))
    assert editor._fields["institution"].text() == ""
    assert editor._sex.currentData() == ""


def test_cine_transport_has_stable_round_play_button_and_endpoint_navigation(qtbot):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer._timeline_slider.setRange(0, 9)
    viewer._timeline_slider.setValue(4)
    frames = []
    viewer.frame_selected.connect(frames.append)
    viewer._first_frame_button.click()
    viewer._last_frame_button.click()
    assert frames == [0, 9]
    viewer._sync_play_button(False)
    size = viewer._play_button.size()
    assert viewer._play_button.text() == ""
    assert not viewer._play_button.icon().isNull()
    viewer._sync_play_button(True)
    assert viewer._play_button.size() == size
    assert viewer._play_button.property("cinePlaying") is True
