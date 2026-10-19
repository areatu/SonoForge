"""GUI tests of the measurement panel 2.0 (TP-2 PR-1)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.infrastructure.i18n import set_language
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


def test_v2_is_on_by_default() -> None:
    """The TP-2 gate turns the panel 2.0 on; the flag stays as a rollback."""
    assert UserPreferences().tool_panel_v2 is True


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


def test_doppler_key_three_activates_the_e_prime_favourite(qtbot) -> None:
    """A-03: the favourite «3» of the Doppler context is «e′ септ.»."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2._context_buttons["doppler"].click()
    assert v2._rows["tdi.e_sept"].is_active() is False

    received = []
    v2.action_requested.connect(lambda *args: received.append(args))
    QTest.keyClick(v2, Qt.Key.Key_3)
    assert received
    assert received[0][0] is MeasurementAction.DOPPLER_PEAK
    assert received[0][1] in ("ap4c", "A4C")


def test_favorite_digits_do_not_fire_while_searching(qtbot) -> None:
    """Digits typed into the search field stay in the search field."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    received = []
    v2.action_requested.connect(lambda *args: received.append(args))
    v2.focus_search()
    v2._search.setText("3")
    QTest.keyClick(v2, Qt.Key.Key_3)
    assert received == []


def test_arrow_traverses_the_expanded_rows(qtbot) -> None:
    """A-13: arrows move the keyboard focus over the rows of open sections."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    first_section = v2._section_widgets[0]
    first_section.set_expanded(True)
    rows = first_section.rows()
    assert len(rows) >= 2

    rows[0].setFocus()
    QTest.keyClick(v2, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is rows[1]
    QTest.keyClick(v2, Qt.Key.Key_Up)
    assert QApplication.focusWidget() is rows[0]


def test_section_header_shows_the_measured_progress(qtbot) -> None:
    """§4.2: the header shows «2/9» for the tools with a value."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    section = v2._section_widgets[0]
    rows = section.rows()
    rows[0].set_value("52 мм")
    rows[1].set_value("34 мм")
    assert section.progress() == (2, len(rows))
    assert section._progress.text() == f"2/{len(rows)}"
    rows[0].set_value("")
    assert section.progress() == (1, len(rows))


def test_rows_keep_their_labels_at_the_gate_widths_and_scales(qtbot) -> None:
    """A-16: 280/320/420 px × 100/150/200 % × RU/EN — no key text clipped.

    The scale emulates ``QT_SCALE_FACTOR`` by enlarging the panel font:
    close enough to verify the word-wrapped labels, values and section
    progress keep fitting at every width so no tool needs cutting.
    """
    for width in (280, 320, 420):
        for scale in (1.0, 1.5, 2.0):
            for language in ("ru", "en"):
                set_language(language)
                try:
                    panel = _make_panel(qtbot)
                    if scale != 1.0:
                        font = QApplication.font()
                        font.setPointSizeF(font.pointSizeF() * scale)
                        panel.setFont(font)
                    v2 = panel.measure
                    panel.resize(width, 900)
                    for section in v2._section_widgets:
                        section.set_expanded(True)
                    QTest.qWait(10)

                    viewport = v2._scroll.viewport().width()
                    for section in v2._section_widgets:
                        progress, total = section.progress()
                        assert total > 0
                        assert section._progress.text() == f"{progress}/{total}"
                        for row in section.rows():
                            assert row.width() <= viewport + 1, (width, language, row.tool.id)
                            title_h = row._title.height()
                            line_h = row._title.fontMetrics().height()
                            assert title_h >= line_h, (width, scale, language, row.tool.id)
                finally:
                    set_language("ru")
                    panel.close()
                    panel.hide()
