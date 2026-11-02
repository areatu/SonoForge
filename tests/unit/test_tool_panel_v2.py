"""GUI tests of the measurement panel 2.0 (TP-2 PR-1)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from echo_personal_tool.application.tool_status import ToolState, ToolStatus
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.reference_card import HOVER_DELAY_MS, ReferenceCard, card_for_row
from echo_personal_tool.presentation.reference_grades import grade_colors
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
    assert panel.maximumWidth() == 560
    assert panel.preferred_width == 420
    assert panel._tabs.indexOf(panel.measure) >= 0


def test_default_width_shows_every_panel_grid_uncut(qtbot) -> None:
    """The shipped default width must be one where nothing is cut (2026-10-30).

    At the old 280/320 px the two-column quick, favourite and protocol grids
    needed more than the viewport of the scroll area, so the right tile of each
    pair hung outside the window.  The default is now the width of the Windows
    reference screenshot: two columns everywhere and no elided caption.
    """
    panel = _make_panel(qtbot)
    v2 = panel.measure
    panel.resize(panel.preferred_width, 900)
    QTest.qWait(20)
    assert v2._quick_columns == 2
    assert v2._favorite_columns == 2
    for chip in (*v2._quick_buttons, *v2._favorite_buttons):
        assert chip.text() == chip.label_text(), chip.label_text()


def test_narrow_panel_reflows_instead_of_clipping(qtbot) -> None:
    """Below the default the grids drop columns; no chip leaves the viewport."""
    from PySide6.QtWidgets import QWidget

    panel = _make_panel(qtbot)
    v2 = panel.measure
    panel.resize(280, 900)
    QTest.qWait(20)
    viewport = v2._scroll.viewport()
    page = v2._scroll.widget()
    assert v2._favorite_columns == 1
    assert v2._quick_columns in (1, 2)
    assert page.width() <= viewport.width()
    for child in page.findChildren(QWidget):
        if not child.isVisible():
            continue
        left = child.mapTo(page, child.rect().topLeft()).x()
        assert left + child.width() <= viewport.width() + 1, child.objectName()


def test_protocol_steps_stack_when_two_tiles_do_not_fit(qtbot) -> None:
    """Two step tiles per row while they fit, one when the panel is narrow."""
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.protocol_definitions import PROTOCOLS, SIMPSON_BIPLANE
    from echo_personal_tool.domain.protocols import progress
    from echo_personal_tool.domain.services.study_projection import build_study_projection

    panel = _make_panel(qtbot)
    v2 = panel.measure
    panel.set_protocols(PROTOCOLS)
    panel.set_protocol_progress(progress(SIMPSON_BIPLANE, build_study_projection(MeasurementSnapshot())))
    card = v2._protocol_card

    panel.resize(420, 900)
    QTest.qWait(20)
    assert card.step_columns() == 2

    # The columns follow the *measured* tile, not a font assumption: the suite
    # runs under whatever stylesheet the previous module left (a smaller theme
    # font makes two tiles fit at 280 px), so the expectation is derived here.
    panel.resize(280, 900)
    QTest.qWait(20)
    host = card._steps_host.width()
    natural = card._natural_tile_width()
    spacing = max(0, card._steps_layout.horizontalSpacing())
    margins = card._steps_layout.contentsMargins()
    available = host - margins.left() - margins.right()
    assert card.step_columns() == (2 if natural * 2 + spacing <= available else 1)
    for tile in card._tile_buttons:
        assert tile.width() <= host

    # A card too narrow for two natural tiles stacks them instead of cutting a
    # caption — that is the branch the fix was about.
    card.setFixedWidth(natural + 24 + margins.left() + margins.right())
    QTest.qWait(20)
    assert card.step_columns() == 1
    for tile in card._tile_buttons:
        assert tile.width() <= card._steps_host.width()


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


def test_search_favorites_and_hidden_toggle_reflow_at_narrow_width(qtbot) -> None:
    """Narrow panels keep search, all favourites and «Показать» reachable."""
    from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet
    from echo_personal_tool.resources.bundled_fonts import ui_font

    panel = _make_panel(qtbot)
    panel.resize(280, 360)
    v2 = panel.measure
    # Pin the metrics this reflow math depends on. The ambient application
    # stylesheet in an xdist worker is whatever earlier tests left behind
    # (the canonical-sheet fixture restores the FIRST sheet seen, whose
    # baked font size can be 11 px from a small-font preference test): at
    # 11 px the chips fit four per row and the column assertions below
    # flip with worker scheduling. The production sheet + bundled font
    # on the panel subtree make the test order-independent.
    panel.setStyleSheet(build_clinical_stylesheet(13))
    v2.setFont(ui_font(pixel_size=26))
    QTest.qWait(20)
    v2._reflow_panel_chips()

    assert v2._search.width() > 0
    assert v2._search_hint.width() == 18
    assert (
        max(
            v2._context_grid.getItemPosition(v2._context_grid.indexOf(button))[1]
            for button in v2._context_buttons.values()
        )
        < 3
    )
    # The grid is adaptive now: a 26 px font in a 280 px panel may leave only
    # one column, which is exactly what keeps every caption readable.
    assert (
        max(
            v2._favorites_grid.getItemPosition(v2._favorites_grid.indexOf(button))[1] for button in v2._favorite_buttons
        )
        < 3
    )
    assert len(v2._favorite_buttons) == 6
    assert all(button.width() > 0 for button in v2._favorite_buttons)
    assert all(button.accessibleName() and button.toolTip() for button in v2._favorite_buttons)

    v2._context_buttons["m"].click()
    QTest.qWait(20)
    assert v2._hidden_row.isVisible()
    assert v2._hidden_toggle.width() > 0
    assert v2._hidden_toggle.accessibleName() == v2._hidden_toggle.text()
    assert v2._scroll.verticalScrollBar().maximum() > 0
    assert v2._scroll.widget().layout() is not None


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


# ── UI-5 PR-4: the S2 card at the rows and the «Нормы» dots (§4.7) ──


def _measured(tool_id: str, key: str, value: float, unit: str = "mm") -> ToolStatus:
    return ToolStatus(
        tool_id=tool_id,
        key=key,
        value=value,
        text=f"{value:g}",
        unit=unit,
        state=ToolState.DONE,
        count=1,
    )


def test_norms_switch_is_off_by_default_and_its_position_moves(qtbot) -> None:
    """UA-15 / UQ-03: dots are opt-in, and the switch reports every move."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    assert v2.norms_visible() is False
    assert UserPreferences().reference_norm_dots is False

    seen: list[bool] = []
    v2.norms_toggled.connect(seen.append)
    v2._norms_check.setChecked(True)
    assert seen == [True]
    assert v2.norms_visible() is True

    # Adopting the remembered position is silent — the window is not a user.
    v2.set_norms_visible(False)
    assert seen == [True]
    assert v2.norms_visible() is False


def test_ua15_toggle_off_shows_no_dots_and_the_hover_card_still_works(qtbot) -> None:
    """UA-15: выключатель «Нормы» — выкл → в списке нет цветных точек,
    карточка по наведению работает."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_reference_sex_provider(lambda: "female")
    row = v2._rows["lv.lvesd"]
    v2.set_tool_statuses([_measured("lv.lvesd", "lv.lvesd", 31.0)])

    # The value has a gradation — but the switch is off, so no dot is shown.
    assert row.norm_grade
    assert row._dot.isHidden()

    row.enterEvent(None)
    qtbot.wait(HOVER_DELAY_MS + 100)
    card = v2.findChild(ReferenceCard, "referenceCard")
    assert card is not None and card.isVisible()
    assert card._model is not None
    assert card._model.value == 31.0
    assert card._model.param_id == "lvesd"
    row.leaveEvent(None)


def test_norm_dot_is_the_gradation_colour_and_vanishes_with_the_switch(qtbot) -> None:
    """UD-14: the dot is the handbook gradation colour and nothing else."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_reference_sex_provider(lambda: "female")
    row = v2._rows["lv.lvesd"]
    v2.set_tool_statuses([_measured("lv.lvesd", "lv.lvesd", 31.0)])

    expected = card_for_row("lv.lvesd", value=31.0, unit="mm", sex="female").grade
    assert expected is not None
    assert row.norm_grade == expected.name

    v2.set_norms_visible(True)
    assert not row._dot.isHidden()
    assert grade_colors(expected.name)[1] in row._dot.styleSheet()

    # The switch goes off — the dots leave the list (UA-15).
    v2._norms_check.setChecked(False)
    assert row._dot.isHidden()


def test_the_hover_delay_is_the_registered_four_hundred_ms(qtbot) -> None:
    """§4.7: the card is a hover card — 400 ms, never a plain mouse pass."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    row = v2._rows["lv.lvesd"]
    assert row._hover_timer.interval() == HOVER_DELAY_MS == 400

    row.enterEvent(None)
    assert v2.findChild(ReferenceCard, "referenceCard") is None
    qtbot.wait(HOVER_DELAY_MS + 100)
    assert v2.findChild(ReferenceCard, "referenceCard") is not None


def test_general_tools_do_not_show_an_empty_reference_card(qtbot) -> None:
    """General-purpose calipers and areas have no reference range to display."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    row = v2._rows["tool.area"]

    row.enterEvent(None)
    qtbot.wait(HOVER_DELAY_MS + 100)

    assert v2.findChild(ReferenceCard, "referenceCard") is None


def test_the_registry_key_opens_the_card_and_esc_closes_it(qtbot) -> None:
    """§4.7: the key on the focused row opens the card; Esc closes it first."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_reference_sex_provider(lambda: "female")
    row = v2._rows["lv.lvesd"]
    v2.set_tool_statuses([_measured("lv.lvesd", "lv.lvesd", 31.0)])
    row.setFocus()

    QTest.keyClick(row, Qt.Key.Key_N)
    card = v2.findChild(ReferenceCard, "referenceCard")
    assert card is not None and card.isVisible()

    # Esc is stage 0 (TP §6.2): the card closes, the event does not travel on.
    QTest.keyClick(row, Qt.Key.Key_Escape)
    assert not card.isVisible()


def test_the_card_hides_when_the_pointer_leaves_the_row(qtbot) -> None:
    """The row is the host: leaving it hides the card after the travel grace."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    row = v2._rows["lv.lvesd"]
    row.enterEvent(None)
    qtbot.wait(HOVER_DELAY_MS + 100)
    card = v2.findChild(ReferenceCard, "referenceCard")
    assert card is not None and card.isVisible()

    row.leaveEvent(None)
    qtbot.wait(400)  # the 250 ms grace expires with the pointer off the rows
    assert not card.isVisible()


def test_open_in_reference_hands_the_handbook_id_to_the_window(qtbot) -> None:
    """«Открыть в справочнике» — the card reports the handbook parameter."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_reference_sex_provider(lambda: "female")
    row = v2._rows["lv.lvesd"]
    v2.set_tool_statuses([_measured("lv.lvesd", "lv.lvesd", 31.0)])
    row.enterEvent(None)
    qtbot.wait(HOVER_DELAY_MS + 100)
    card = v2.findChild(ReferenceCard, "referenceCard")
    assert card is not None

    seen: list[str] = []
    panel.open_reference_requested.connect(seen.append)
    card._on_open_clicked()
    assert seen == ["lvesd"]


def test_values_norm_grades_and_dots_survive_a_panel_rebuild(qtbot) -> None:
    """A rebuild (theme, language) is not a new study: the statuses return."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_reference_sex_provider(lambda: "female")
    v2.set_norms_visible(True)
    v2.set_tool_statuses([_measured("lv.lvesd", "lv.lvesd", 31.0)])
    grade = v2._rows["lv.lvesd"].norm_grade
    assert grade

    v2.set_preferences(UserPreferences(tool_panel_v2=True))
    row = v2._rows["lv.lvesd"]
    assert row.measurement_value == 31.0
    assert row.norm_grade == grade
    assert not row._dot.isHidden()


def test_the_wrapper_forwards_the_s2_hooks_only_when_v2_is_on(qtbot) -> None:
    """ToolPanel keeps one contract for both Measures tabs (D-09)."""
    panel = _make_panel(qtbot)
    seen: list[bool] = []
    panel.norms_toggled.connect(seen.append)
    panel.set_norms_visible(True)
    panel.measure._norms_check.setChecked(False)
    assert seen == [False]
    panel.hide_reference_card()  # no card — and no error

    legacy = _make_panel(qtbot, v2=False)
    legacy.set_norms_visible(True)  # the legacy menu has no dots — no-op
    legacy.hide_reference_card()


def _editable_layout_json() -> str:
    from echo_personal_tool.domain import tool_settings
    from echo_personal_tool.domain.tool_layout_v3 import default_layout

    layout = tool_settings.duplicate_profile(default_layout(), new_id="user-test")
    return tool_settings.export_layout(layout)


def test_edit_pencil_opens_settings_for_the_read_only_builtin(qtbot) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    seen: list[str] = []
    v2.edit_requested.connect(seen.append)
    v2._edit_button.click()
    assert seen == ["2d"]
    assert v2.edit_mode() is False


def test_in_place_edit_star_and_eye_change_the_same_layout(qtbot) -> None:
    panel = _make_panel(qtbot, tool_layout_v3_json=_editable_layout_json())
    v2 = panel.measure
    seen: list[str] = []
    v2.layout_changed.connect(seen.append)
    v2.set_edit_mode(True)
    assert v2.edit_mode() is True
    assert v2._rows["tool.caliper"].edit_mode() is True

    favorites = {tool.id for tool in v2._view.favorites}
    tool_id = next(tool_id for tool_id in v2._rows if tool_id not in favorites)
    v2._rows[tool_id]._favorite_button.click()
    assert tool_id in {tool.id for tool in v2._view.favorites}
    assert seen

    v2._rows["tool.caliper"]._visibility_button.click()
    assert v2._tool_visible("tool.caliper") is False
    assert not v2._rows["tool.caliper"].is_visible()

    v2.set_edit_mode(False)
    assert v2.edit_mode() is False
    assert all(not row._visibility_button.isVisible() for row in v2._rows.values())


def test_the_row_tooltip_is_the_name_and_not_the_internal_requirement(qtbot) -> None:
    """«spatial_calibration» над строкой загораживал карточку норм (ТЗ п. 3).

    The requirement list is the internal name of a precondition: it means
    nothing to a sonographer, and both popups are anchored to the same row, so
    the tooltip painted over the very card whose norm it should help read.
    """
    panel = _make_panel(qtbot)
    v2 = panel.measure
    row = v2._rows["lv.lvesd"]

    assert "spatial_calibration" not in row.toolTip()
    assert "doppler_calibration" not in row.toolTip()
    from echo_personal_tool.infrastructure.i18n import get_language

    assert row.toolTip() == row.tool.label(get_language()).full


def test_the_row_tooltip_goes_silent_while_its_reference_card_is_up(qtbot) -> None:
    """Only the card speaks while it is visible; its title stays in the a11y name."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.set_reference_sex_provider(lambda: "female")
    row = v2._rows["lv.lvesd"]
    v2.set_tool_statuses([_measured("lv.lvesd", "lv.lvesd", 31.0)])
    assert row.toolTip()

    row.enterEvent(None)
    qtbot.wait(HOVER_DELAY_MS + 100)
    assert row.toolTip() == ""
    assert row.accessibleName()

    v2.hide_reference_card()
    assert row.toolTip()


def test_a_requirement_key_never_reaches_the_row_tooltip(qtbot) -> None:
    """Even a locked tool keeps «req:spatial_calibration» out of the tooltip.

    The key gated the tool; the row already shows the lock glyph, and the
    popup is what covered the reference card (ТЗ 2026-10-23, п. 3).
    """
    panel = _make_panel(qtbot)
    v2 = panel.measure
    row = v2._rows["lv.lvesd"]
    row.set_status("⊘", "req:spatial_calibration")
    assert "spatial_calibration" not in row.toolTip()

    # A human-readable warning still rides along.
    row.set_status("!", "Калибровка устарела")
    assert "Калибровка устарела" in row.toolTip()


def test_the_protocol_card_follows_a_theme_switch(qtbot) -> None:
    """The card's sheet is built from tokens, so the theme switch repaints it.

    The sheet is a plain string with the colours baked in, and nothing re-read
    the tokens after the build: switching «Светлая» → «Графит» left the card a
    white block inside a dark panel (item 4 of the 2026-10-23 list).
    """
    from echo_personal_tool.presentation.dark_theme import (
        apply_clinical_theme,
        get_theme_tokens,
    )

    panel = _make_panel(qtbot)
    v2 = panel.measure
    app = QApplication.instance()
    before = app.styleSheet()
    try:
        apply_clinical_theme(theme="light", font_size=13, animate=False)
        light_sheet = v2._protocol_card.styleSheet()
        assert f"background: {get_theme_tokens()['surface.2']};" in light_sheet

        apply_clinical_theme(theme="graphite", font_size=13, animate=False)
        graphite_sheet = v2._protocol_card.styleSheet()
        tokens = get_theme_tokens()
        assert graphite_sheet != light_sheet
        assert f"background: {tokens['surface.2']};" in graphite_sheet
        assert f"border-bottom: 1px solid {tokens['line.1']};" in graphite_sheet

        # The footer is a second sheet of the same kind.
        assert f"background: {tokens['surface.1']};" in v2._footer.styleSheet()
    finally:
        apply_clinical_theme(theme="dark", font_size=13, animate=False)
        if app.styleSheet() != before:  # pragma: no cover - test isolation
            app.setStyleSheet(before)


def test_a_theme_switch_does_not_restyle_forever(qtbot) -> None:
    """One re-interpolation per widget: re-applying the sheet provokes the event."""
    from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

    panel = _make_panel(qtbot)
    v2 = panel.measure
    app = QApplication.instance()
    before = app.styleSheet()
    calls: list[int] = []
    original = v2._protocol_card._apply_style

    def counted() -> None:
        calls.append(1)
        original()

    v2._protocol_card._apply_style = counted  # type: ignore[method-assign]
    try:
        apply_clinical_theme(theme="graphite", font_size=13, animate=False)
        app.processEvents()
        apply_clinical_theme(theme="graphite", font_size=13, animate=False)
        app.processEvents()
        assert len(calls) <= 2
    finally:
        v2._protocol_card._apply_style = original  # type: ignore[method-assign]
        apply_clinical_theme(theme="dark", font_size=13, animate=False)
        if app.styleSheet() != before:  # pragma: no cover - test isolation
            app.setStyleSheet(before)


def test_the_search_field_clear_button_fits_the_field(qtbot) -> None:
    """Qt's clear button is a QToolButton and used to inherit the button chrome.

    With the global «QPushButton, QToolButton» rule (6 px of padding, a 24 px
    floor, a border) it measured 22 × 38 inside a 28 px field, so the «×» was
    drawn half below the field and cut by its edge — the «смещённая кнопка
    удалить текст справа поля» of the 2026-10-23 list.
    """
    from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

    app = QApplication.instance()
    before = app.styleSheet()
    try:
        apply_clinical_theme(theme="dark", font_size=13, animate=False)
        panel = _make_panel(qtbot)
        field = panel.measure._search
        field.setText("кдр")
        QTest.qWait(10)
        side_buttons = field.findChildren(QToolButton)
        assert side_buttons, "the clear button of the field is gone"
        for button in side_buttons:
            assert button.height() <= field.height(), button.size()
            assert button.width() <= field.height(), button.size()
    finally:
        app.setStyleSheet(before)


def test_anatomy_tools_follow_the_adaptive_column_count(qtbot) -> None:
    """A narrow panel draws fewer, wider cells instead of wrapping captions."""
    panel = _make_panel(qtbot, v2=True)
    v2 = panel.measure
    QTest.qWait(20)
    for section in v2._section_widgets:
        grid = section._body.layout()
        columns = section.columns()
        assert 1 <= columns <= 3
        for index, row in enumerate(section.rows()):
            assert grid.getItemPosition(index)[:2] == (index // columns, index % columns)
            assert grid.itemAt(index).widget() is row


def test_patient_editors_can_move_to_top_bar_and_survive_panel_switch(qtbot) -> None:
    from dataclasses import replace

    from PySide6.QtWidgets import QHBoxLayout, QWidget

    panel = _make_panel(qtbot, v2=True)
    host = QWidget()
    qtbot.addWidget(host)
    QHBoxLayout(host)
    panel.set_patient_metrics_host(host)
    panel.set_patient_metrics(180, 80)
    assert panel.measure._footer.metrics_widget.parentWidget() is host
    assert panel.measure._footer._height_spin.value() == 180
    panel.rebuild_menu_with_preferences(replace(panel._preferences, tool_panel_v2=False))
    assert panel.measure._patient_metrics.parentWidget() is host
    panel.rebuild_menu_with_preferences(replace(panel._preferences, tool_panel_v2=True))
    assert panel.measure._footer.metrics_widget.parentWidget() is host
    assert panel.measure._footer._height_spin.value() == 180


def test_anatomy_board_has_four_columns_and_switches_exclusively(qtbot) -> None:
    from PySide6.QtWidgets import QPushButton

    panel = _make_panel(qtbot)
    v2 = panel.measure
    buttons = v2.findChildren(QPushButton, "panelAnatomyButton")
    assert len(buttons) == len(v2._section_widgets)
    board = v2._sections_layout.itemAt(1).widget().layout()
    columns = v2._anatomy_columns
    for index, (button, section) in enumerate(zip(buttons, v2._section_widgets)):
        assert board.getItemPosition(index)[:2] == (index // columns, index % columns)
        assert button.badge_text() == ""
        button.click()
        assert section.is_expanded() and button.isChecked()
        assert sum(item.is_expanded() for item in v2._section_widgets) == 1
        assert sum(item.isChecked() for item in buttons) == 1
        button.click()  # The current category cannot deselect itself.
        assert section.is_expanded() and button.isChecked()


def test_favorite_grid_keeps_its_badges_on_one_line(qtbot) -> None:
    """The number is a badge, no longer a second text line under the name."""
    panel = _make_panel(qtbot)
    v2 = panel.measure
    v2.resize(280, 640)
    v2._reflow_panel_chips()
    columns = v2._favorite_columns
    for index, button in enumerate(v2._favorite_buttons):
        assert v2._favorites_grid.getItemPosition(index)[:2] == (index // columns, index % columns)
        assert button.badge_text() == str(index + 1)
        assert "\n" not in button.text()
        assert button.label_text()
        assert not button.icon().isNull()


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
@pytest.mark.parametrize("font_size", [13, 19])
def test_anatomy_board_reserves_one_line_and_never_overlaps_tools(qtbot, style_name, font_size) -> None:
    """Short/high-DPI Windows-like layouts must scroll, not stack controls."""
    from PySide6.QtWidgets import QStyleFactory

    from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet
    from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2

    app = QApplication.instance()
    before_sheet, before_style = app.styleSheet(), app.style().objectName()
    panel = None
    try:
        app.setStyle(QStyleFactory.create(style_name))
        app.setStyleSheet(build_clinical_stylesheet(font_size, theme="graphite"))
        panel = ToolPanelV2(UserPreferences(ui_font_size=font_size))
        qtbot.addWidget(panel)
        panel.resize(280, 420)
        panel.show()
        for context in ("2d", "doppler", "m", "vessels", "auto"):
            panel._context_buttons[context].click()
            app.processEvents()
            board = panel._sections_layout.itemAt(1).widget()
            grid = board.layout()
            rectangles = []
            for index in range(grid.count()):
                button = grid.itemAt(index).widget()
                assert button.height() >= button.fontMetrics().height() + 10
                assert board.rect().contains(button.geometry())
                assert not any(button.geometry().intersects(rect) for rect in rectangles)
                rectangles.append(button.geometry())
            for section in panel._section_widgets:
                if section.is_expanded():
                    assert section.geometry().top() > board.geometry().bottom()
            for button in panel._favorite_buttons:
                assert button.height() >= button.fontMetrics().height() + 10
    finally:
        if panel is not None:
            panel.close()
        app.setStyle(QStyleFactory.create(before_style))
        app.setStyleSheet(before_sheet)


def test_context_rebuild_never_shows_a_transient_top_level_widget(qtbot) -> None:
    """Observe synchronous Show events: a final topLevelWidgets check misses the flash."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2

    app = QApplication.instance()
    host = QWidget()
    qtbot.addWidget(host)
    unexpected = []

    class WindowObserver(QObject):
        def eventFilter(self, watched, event):  # noqa: N802
            if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
                if watched.isWindow() and watched is not host:
                    unexpected.append((type(watched).__name__, watched.objectName()))
            return False

    observer = WindowObserver()
    app.installEventFilter(observer)
    try:
        panel = ToolPanelV2(UserPreferences(), parent=host)
        layout = QVBoxLayout(host)
        layout.addWidget(panel)
        host.resize(340, 500)
        host.show()
        for context in ("doppler", "m", "2d", "vessels", "auto", "doppler", "vessels", "2d"):
            panel._context_buttons[context].click()
            app.processEvents()
        panel._hidden_toggle.click()
        app.processEvents()
        assert unexpected == []
    finally:
        app.removeEventFilter(observer)


@pytest.mark.parametrize("acquisition", ["2d", "doppler", "m"])
def test_vessels_override_enables_only_spatial_stenosis_without_spectral_calibration(qtbot, acquisition) -> None:
    panel = _make_panel(qtbot)
    v2 = panel.measure
    contexts, actions = [], []
    panel.measurement_context_changed.connect(contexts.append)
    panel.action_requested.connect(lambda action, *_: actions.append(action))
    v2.set_view_context(acquisition, "PW")
    v2.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    v2._context_buttons["vessels"].click()
    assert v2.context() == "vessels"
    assert contexts[-1] == "vessels"
    assert not v2._mode_combo.isVisible()
    for tool_id in ("vessel.stenosis_d", "vessel.stenosis_area"):
        assert v2._rows[tool_id].isEnabled()
        # Both copies must stay active, not just the last dictionary entry.
        assert v2._quick_buttons[v2._quick_ids.index(tool_id)].isEnabled()
        assert v2._favorite_buttons[v2._favorite_ids.index(tool_id)].isEnabled()
        v2.activate_tool(tool_id)
    assert actions == [MeasurementAction.VESSEL_STENOSIS_DIAMETER, MeasurementAction.VESSEL_STENOSIS_AREA]
    assert not v2._tile_buttons["vessel.psv_edv"].isEnabled()
    v2.activate_tool("vessel.psv_edv")
    assert len(actions) == 2
    v2.set_doppler_tool_availability(time_ok=True, vessel_ok=True)
    assert v2._tile_buttons["vessel.psv_edv"].isEnabled()
    v2.set_view_context("doppler", "CW")  # A tag notification cannot override the user's choice.
    assert v2.context() == "vessels"
    assert contexts.count("vessels") == 1
    v2.reset_context_override()  # Existing per-clip override contract.
    assert v2.context() == "doppler"
    assert contexts[-1] == "doppler"
