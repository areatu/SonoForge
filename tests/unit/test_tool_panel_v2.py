"""GUI tests of the measurement panel 2.0 (TP-2 PR-1)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.tool_panel import ToolPanel

pytestmark = pytest.mark.gui


def _make_panel(qtbot, *, v2: bool = True, **preferences) -> ToolPanel:
    preferences.setdefault("tool_panel_v2", v2)
    panel = ToolPanel(UserPreferences(**preferences))
    qtbot.addWidget(panel)
    panel.resize(320, 640)
    panel.show()
    QTest.qWait(10)
    return panel


def test_legacy_menu_is_the_default(qtbot) -> None:
    panel = _make_panel(qtbot, v2=False)
    assert panel.is_v2 is False
    assert type(panel.measure).__name__ == "MeasureTab"
    assert panel.maximumWidth() > 420
    assert panel.preferred_width == 280


def test_v2_panel_is_the_measures_tab_when_the_flag_is_on(qtbot) -> None:
    panel = _make_panel(qtbot)
    assert panel.is_v2 is True
    assert type(panel.measure).__name__ == "ToolPanelV2"
    assert panel.measure.context() == "2d"
    assert panel.measure.is_v2 is True
    assert panel.minimumWidth() == 280
    assert panel.maximumWidth() == 420
    assert panel.preferred_width == 320
    assert panel._tabs.indexOf(panel.measure) >= 0


def test_flag_switch_replaces_the_measures_tab_in_place(qtbot) -> None:
    panel = _make_panel(qtbot, v2=False)
    controls_index = panel._tabs.indexOf(panel.controls)
    panel.rebuild_menu_with_preferences(UserPreferences(tool_panel_v2=True))
    assert panel.is_v2 is True
    assert type(panel.measure).__name__ == "ToolPanelV2"
    assert panel._tabs.indexOf(panel.measure) >= 0
    assert panel._tabs.indexOf(panel.controls) == controls_index
    panel.rebuild_menu_with_preferences(UserPreferences(tool_panel_v2=False))
    assert panel.is_v2 is False
    assert type(panel.measure).__name__ == "MeasureTab"


def test_search_focus_and_enter_activate_the_first_result(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.focus_search()
    assert v2.has_search_focus()

    v2._search.setText("кдр")
    assert v2._results.count() == 1
    assert v2._results.item(0).text() == "КДР ЛЖ"

    received = []
    v2.action_requested.connect(lambda *args: received.append(args))
    QTest.keyClick(v2._search, Qt.Key.Key_Return)
    assert received
    assert received[0][0] is MeasurementAction.LV2D_ALL_DIASTOLE
    assert v2._search.text() == ""


def test_search_finds_pasp_in_the_doppler_context(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_view_context("doppler", "cw")
    v2._search.setText("сдла")
    assert v2._results.item(0).text() == "Сист. ДЛА"
    v2._activate_first_match()
    assert v2._search.text() == ""


def test_search_that_matches_nothing_says_so(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2._search.setText("сдла")
    assert v2._results.item(0).text() == "Ничего не найдено"
    assert v2._results.item(0).data(Qt.ItemDataRole.UserRole) is None


def test_context_segments_switch_quick_tiles(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    assert [tool.id for tool in v2._view.quick] == [
        "tool.caliper",
        "tool.area",
        "lv.linear_ed",
        "lv.edv_a4c",
    ]

    v2._context_buttons["doppler"].click()
    assert v2.effective_context() == "doppler"
    assert v2._context_buttons["doppler"].isChecked()
    assert [tool.id for tool in v2._view.quick] == ["mv.e", "mv.dt", "av.vti", "av.vti.auto"]

    v2.reset_context_override()
    assert v2._context_buttons["auto"].isChecked()


def test_show_hidden_line_reveals_other_contexts(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2._context_buttons["m"].click()
    assert v2._hidden_row.isVisible() or v2._hidden_row.isHidden() is False
    hidden_before = v2._view.hidden_count
    assert hidden_before > 0
    v2._hidden_toggle.click()
    assert v2.show_hidden_tools() is True
    assert v2._view.hidden_count == hidden_before


def test_doppler_availability_disables_time_only_tools(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_view_context("doppler", "cw")
    v2.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    assert not v2._rows["av.vti"].is_available()
    assert v2._rows["av.vmax"].is_available()
    v2.set_doppler_tool_availability(time_ok=True, vessel_ok=True)
    assert v2._rows["av.vti"].is_available()


def test_highlight_uses_a_static_marker(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.highlight_action(MeasurementAction.LV2D_ES)
    assert v2._rows["lv.lvesd"].is_active()
    v2.clear_action_highlight()
    assert not v2._rows["lv.lvesd"].is_active()


def test_footer_shows_patient_metrics_and_report_count(qtbot) -> None:
    panel = _make_panel(qtbot, auto_play=True)
    v2 = panel.measure
    v2.set_patient_metrics(178.0, 74.0, None)
    assert v2._footer._height_spin.value() == 178
    assert v2._footer._weight_spin.value() == 74
    assert "ППТ" in v2._footer._bsa_label.text()
    assert "m²" in v2._footer._bsa_label.text()
    v2.set_measurement_count(3)
    assert "3" in v2._footer._report_button.text()
    assert v2.auto_play() is True


def test_reload_text_keeps_the_panel_usable(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.reload_text()
    assert v2._context_buttons["auto"].text()
    assert v2._search.placeholderText()


def test_slash_focuses_the_panel_search(qtbot, isolated_qsettings, monkeypatch) -> None:
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.presentation.main_window import MainWindow

    window = MainWindow(
        controller=AppController(),
        user_preferences=UserPreferences(tool_panel_v2=True),
    )
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitActive(window)
    assert window._tool_panel.is_v2

    # The offscreen platform does not activate windows, so assert the routing
    # (the panel's own focus behavior is covered above with a shown panel).
    called: list[bool] = []
    monkeypatch.setattr(window._tool_panel, "focus_search", lambda: called.append(True))
    window._viewer.setFocus()
    QTest.keyClick(window._viewer, Qt.Key.Key_Slash)
    assert called
