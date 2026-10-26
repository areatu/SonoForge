"""Regression coverage for context swaps, unified report editing and cine controls."""

import pytest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from echo_personal_tool.domain.services.report_builder import PatientInfo
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.report_mode.patient import ReportPatientEditor
from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2, _clear_layout

pytestmark = pytest.mark.gui


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
    from echo_personal_tool.infrastructure.i18n import tr

    editor = ReportPatientEditor(tr)
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


def test_patient_metric_editors_are_compact_instead_of_stretched(qtbot):
    panel = ToolPanelV2(UserPreferences())
    qtbot.addWidget(panel)
    for spin in (panel._footer._height_spin, panel._footer._weight_spin):
        assert 70 <= spin.width() <= 120
        assert spin.minimumWidth() == spin.maximumWidth()


def test_long_continue_caption_wraps_without_truncating_the_action(qtbot, tmp_path):
    from echo_personal_tool.presentation.start_page import StartPage

    folder = tmp_path / ("Long study name " * 8)
    folder.mkdir()
    page = StartPage(profile_name="full")
    qtbot.addWidget(page)
    page.resize(1000, 700)
    page.set_continue_target("folder", str(folder), date="2026-10-26", clip_count=123)
    page.show()
    qtbot.wait(20)
    button = page.continue_button
    assert folder.name in button.text()
    assert button.accessibleName() == button.text()
    assert button.height() >= 44
    assert button._caption.wordWrap()
    assert button._caption.width() < page._sidebar.width()


def test_labelled_toolbar_allocates_space_for_both_icon_and_full_caption(qtbot):
    from echo_personal_tool.presentation.tool_buttons.row import ToolButtonRow

    row = ToolButtonRow()
    qtbot.addWidget(row)
    row.update_geometry()
    for spec in row.specs():
        button = row.button(spec.id)
        if button is not None:
            expected = button.fontMetrics().horizontalAdvance(button.text()) + 16
            if not button.icon().isNull():
                expected += button.iconSize().width() + 6
            assert button.width() >= expected, spec.id
