"""UI-5 PR-2 — the reference window S1 (spec UI §4.7, §8.5; UD-06, UD-15).

The gate of UI-5 says: «в карточке нет изображений; «Открыть в справочнике»
открывает S1 на параметре».  The picture lives here, in the window, and the
tests keep it here: the card still has none, the window shows the scheme of the
pathology and the numbered «Как измерять» above the source.

The rest is the contract of the mockup: the eighteen themes on the left, the
sex switch that changes the norm column, the table whose first column and
gradation columns say what the handbook says, the patient's value with the
colour of its grade, and the search across the whole handbook.
"""

from __future__ import annotations

import re

import pytest
from PySide6.QtCore import QObject, Qt, Signal

pytestmark = pytest.mark.gui

_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture()
def apply_theme(monkeypatch):
    from echo_personal_tool.presentation import dark_theme

    def _apply(theme: str) -> dict[str, str]:
        monkeypatch.setattr(dark_theme, "_current_theme_mode", theme)
        return dark_theme.get_theme_tokens()

    return _apply


@pytest.fixture()
def window(qtbot, apply_theme):
    from echo_personal_tool.infrastructure.i18n import set_language
    from echo_personal_tool.presentation import reference_window as module

    set_language("ru")
    apply_theme("graphite")
    module.reset_reference_window()
    window = module.ReferenceWindow()
    qtbot.addWidget(window)
    yield window
    module.reset_reference_window()


class TestWindowShape:
    def test_every_topic_of_the_handbook_is_in_the_navigation(self, window):
        assert len(window.topic_slugs()) == 18
        assert window.selected_topic_slug == "left_ventricle"

    def test_the_first_topic_is_open_on_start(self, window):
        assert window.selected_param_id() == "lvedd"

    def test_the_table_has_the_columns_of_the_mockup(self, window):
        assert window.headers() == ("ПАРАМЕТР", "ЕД.", "НОРМА · М / Ж", "Норма", "Лёгкое", "Умеренное", "Тяжёлое")

    def test_the_window_is_not_modal(self, window):
        assert window.isModal() is False
        assert window.windowModality() == Qt.WindowModality.NonModal

    def test_chips_name_the_pathologies_of_the_topic(self, window):
        texts = [button.text() for button in window._chip_group.buttons()]
        assert texts[0] == "Размеры" and "Фракция выброса" in texts

    def test_the_sex_switch_starts_on_both(self, window):
        assert window.sex == ""
        assert window._sex_buttons[""].isChecked()


class TestSexSwitch:
    def test_women_change_the_norm_column(self, window):
        window.set_sex("female")
        row = next(row for row in window.rows_on_screen() if row.param_id == "lvedd")
        assert row.norm_text == "36–51"
        assert window.headers()[2] == "НОРМА"

    def test_men_get_their_own_range(self, window):
        window.set_sex("male")
        row = next(row for row in window.rows_on_screen() if row.param_id == "lvedd")
        assert row.norm_text == "42–59"

    def test_both_says_which_sex_comes_first(self, window):
        window.set_sex("female")
        window.set_sex("")
        row = next(row for row in window.rows_on_screen() if row.param_id == "lvedd")
        assert row.norm_text == "42–59 / 36–51"
        assert "М / Ж" in window.headers()[2]


class TestOpenAtParameter:
    def test_card_request_lands_on_the_row(self, window):
        assert window.open_at("lvedd") is True
        assert window.selected_topic_slug == "left_ventricle"
        assert window.selected_param_id() == "lvedd"

    def test_another_topic_is_opened_too(self, window):
        assert window.open_at("mr_eroa_primary") is True
        assert window.selected_topic_slug == "mitral_valve"
        assert window.selected_param_id() == "mr_eroa_primary"

    def test_unknown_parameter_is_refused(self, window):
        before = window.selected_topic_slug
        assert window.open_at("no_such_parameter") is False
        assert window.selected_topic_slug == before

    def test_open_at_carries_the_sex_of_the_card(self, window):
        window.open_at("lvedd", sex="female")
        assert window.sex == "female"


class TestPatientValues:
    def test_the_value_column_appears_with_the_study_values(self, window):
        assert "ПАЦИЕНТА" not in window.headers()
        window.set_patient(sex="female", age=59, values={"lvedd": 48.0})
        assert window.headers()[-1] == "ПАЦИЕНТА"
        row = next(row for row in window.rows_on_screen() if row.param_id == "lvedd")
        assert row.value_text == "48 мм" and row.grade == "Норма"

    def test_the_value_cell_carries_the_grade_colour(self, window):
        from echo_personal_tool.presentation.reference_grades import grade_colors

        window.set_patient(sex="female", age=59, values={"lvedd": 48.0})
        table = window._table
        column = window.headers().index("ПАЦИЕНТА")
        item = table.item(0, column)
        assert item.text() == "48 мм"
        fill, text = grade_colors("Норма")
        color = item.background().color()
        assert color.alpha() == int(fill[1:3], 16)
        assert color.name().lower() == "#" + fill[3:].lower()
        assert item.foreground().color().name().lower() == text.lower()

    def test_without_values_the_column_is_hidden(self, window):
        window.set_patient(sex="female", age=59, values={"lvedd": 48.0})
        window.set_values({})
        assert "ПАЦИЕНТА" not in window.headers()
        assert window._values_toggle.isEnabled() is False

    def test_projection_keys_are_translated(self, window):
        window.set_projection({"lv.lvedd": 48.0, "lv.edv_bp": 120.0})
        assert window.patient_values() == {"lvedd": 48.0}
        assert "ПАЦИЕНТА" in window.headers()

    def test_age_is_shown_next_to_the_switch(self, window):
        window.set_patient(sex="female", age=59, values={})
        assert "59" in window._patient_label.text()


class TestSearch:
    def test_search_reaches_every_topic(self, window):
        window.set_search("КДР")
        assert "ТЕМА" in window.headers()
        assert window.selected_param_id() == "lvedd"
        assert window.rows_on_screen()[0].topic_name == "Левый желудочек"

    def test_nothing_found_says_so(self, window):
        window.set_search("нет-такого-параметра")
        assert window.rows_on_screen() == ()
        assert window._empty_label.isVisible() is False or window._table.isVisible() is False

    def test_clearing_the_query_returns_to_the_topic(self, window):
        window.set_search("КДР")
        window.set_search("")
        assert window.selected_topic_slug == "left_ventricle"
        assert "ТЕМА" not in window.headers()


class TestIllustration:
    def test_the_topic_shows_its_picture(self, window):
        window.open_at("lvedd")
        assert window._image_paths
        assert window._image_counter.text().startswith("1 /")

    def test_a_parameter_without_a_picture_says_so(self, window):
        window.open_at("lvedd")
        window._image_paths = ()
        window._show_current_image()
        assert window._image_label.text() == "Нет изображения"

    def test_how_to_has_a_placeholder_until_the_handbook_fills_it(self, window):
        window.open_at("lvedd")
        row = window.selected_row()
        labels = [window._how_to_layout.itemAt(i).widget().text() for i in range(window._how_to_layout.count())]
        if row.how_to:
            assert labels and labels[0].startswith("1. ")
        else:
            assert labels == ["Инструкции пока нет"]

    def test_source_is_shown_next_to_the_picture(self, window):
        window.open_at("lvedd")
        assert window._source_label.text()
        assert "ASE" in window._source_label.text()


class TestTheme:
    def test_the_window_paints_itself_from_tokens(self, window, monkeypatch):
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        sheet = window.styleSheet() + window._table.styleSheet()
        assert tokens["surface.0"] in sheet and tokens["surface.1"] in sheet
        assert tokens["line.1"] in sheet and tokens["accent.tab"] in sheet
        # Every colour written into a stylesheet of the window is a role value;
        # a literal of its own would not be in the token set.
        allowed = {value.lower() for value in tokens.values() if isinstance(value, str)}
        literals = {match.lower() for match in _COLOUR_LITERAL.findall(sheet)}
        assert literals <= allowed

    def test_a_theme_change_repaints_the_table(self, window, apply_theme):
        apply_theme("graphite")
        window.apply_theme()
        graphite_sheet = window._table.styleSheet()
        apply_theme("light")
        window.apply_theme()
        assert window._table.styleSheet() != graphite_sheet


class TestCachedWindow:
    def test_one_window_per_session(self, qtbot):
        from echo_personal_tool.presentation import reference_window as module

        module.reset_reference_window()
        first = module.show_reference_window()
        second = module.show_reference_window(param_id="lvedd")
        try:
            assert first is second
            assert second.selected_param_id() == "lvedd"
        finally:
            module.reset_reference_window()

    def test_escape_closes_the_window(self, window, qtbot):
        window.show()
        qtbot.keyClick(window, Qt.Key.Key_Escape)
        assert window.isVisible() is False

    def test_constructor_and_sources_are_host_actions(self, window):
        seen = []
        window.constructor_requested.connect(lambda: seen.append("constructor"))
        window.sources_requested.connect(lambda: seen.append("sources"))
        window._btn_constructor.click()
        window._btn_sources.click()
        assert seen == ["constructor", "sources"]


class TestMainWindowEntryPoints:
    """The overlay, the card and the palette all land in the same window."""

    def test_parameter_request_opens_the_window(self, qtbot, monkeypatch):
        from echo_personal_tool.presentation import reference_window as module
        from echo_personal_tool.presentation.main_window import MainWindow

        calls: list[dict] = []

        class _StubWindow(QObject):
            constructor_requested = Signal()
            sources_requested = Signal()

        def fake_show(parent=None, **kwargs):
            calls.append(kwargs)
            return _StubWindow()

        monkeypatch.setattr(module, "show_reference_window", fake_show)
        window = MainWindow()
        qtbot.addWidget(window)
        try:
            window._open_reference_dialog(param_id="lvedd")
            assert calls and calls[-1]["param_id"] == "lvedd"
            assert "values" in calls[-1] and "sex" in calls[-1]
        finally:
            window.close()

    def test_documents_keep_their_own_viewer(self, monkeypatch):
        from echo_personal_tool.presentation import ase_reference_dialog
        from echo_personal_tool.presentation.main_window import MainWindow

        calls: list[dict] = []
        monkeypatch.setattr(
            ase_reference_dialog, "show_ase_reference_dialog", lambda parent, **kwargs: calls.append(kwargs)
        )
        window = MainWindow()
        try:
            window._open_reference_dialog(open_document=True)
            assert calls and calls[-1]["open_document"] is True
        finally:
            window.close()
