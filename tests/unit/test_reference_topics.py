"""UI-5 PR-2 — the S1 view model (spec UI §4.7, §8.5; UD-14, UD-15).

The window of the handbook shows a whole topic; the model answers what each row
of its table says.  These tests pin the answers the acceptance scenario needs:
the norm follows the sex of the patient, the gradation columns carry the bounds
of the handbook, and the value of the open study appears only where the units of
the projection and of the handbook agree.

Nothing here imports Qt: the model is a domain module, and the window is only
one of its readers (the report and the card S2 read the same handbook).
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.domain.services.reference_topics import (
    PROJECTION_TO_HANDBOOK,
    SEX_BOTH,
    SEX_FEMALE,
    SEX_MALE,
    build_topic_view,
    chip_label,
    format_cut,
    gradation_key,
    gradation_rank,
    reference_values,
    search_view,
    topic_entries,
)


@pytest.fixture(scope="module")
def ru_store() -> ReferenceDataStore:
    return ReferenceDataStore(language="ru").load()


@pytest.fixture(scope="module")
def en_store() -> ReferenceDataStore:
    return ReferenceDataStore(language="en").load()


class TestTopicEntries:
    def test_every_topic_of_the_handbook_is_listed(self, ru_store):
        entries = topic_entries(ru_store)
        assert len(entries) == len(ru_store.get_topics()) == 18
        assert [entry.slug for entry in entries][:3] == ["left_ventricle", "left_atrium", "right_ventricle"]

    def test_counts_are_parameters_not_pathologies(self, ru_store):
        entry = next(entry for entry in topic_entries(ru_store) if entry.slug == "left_ventricle")
        view = build_topic_view(ru_store, "left_ventricle")
        assert entry.parameter_count == len(view.rows) > entry.pathology_count
        assert entry.pathology_count == len(ru_store.get_topic("left_ventricle").pathologies)
        # A pathology may hold no parameter of its own (the segments of the LV
        # are a picture), so the chips are the pathologies that reach the table.
        assert set(view.pathology_names) <= {p.name for p in ru_store.get_topic("left_ventricle").pathologies}


class TestTopicView:
    def test_rows_are_unique_and_keep_the_handbook_order(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle")
        ids = [row.param_id for row in view.rows]
        assert len(ids) == len(set(ids))
        assert ids[:4] == ["lvedd", "lvesd", "lvedvi", "lvesvi"]

    def test_unknown_topic_is_empty_not_an_error(self, ru_store):
        view = build_topic_view(ru_store, "no_such_topic")
        assert view.rows == () and view.columns == ()

    def test_pathology_filter_is_the_chips(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle")
        assert view.pathology_names[0] == "Размеры левого желудочка"
        rows = [row for row in view.rows if row.pathology_name == view.pathology_names[0]]
        assert {row.param_id for row in rows} == {"lvedd", "lvesd", "lvedvi", "lvesvi", "lvpwd", "ivsd"}


class TestSex:
    def test_norm_follows_the_patient_sex(self, ru_store):
        female = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE)
        male = build_topic_view(ru_store, "left_ventricle", sex=SEX_MALE)
        female_lvedd = next(row for row in female.rows if row.param_id == "lvedd")
        male_lvedd = next(row for row in male.rows if row.param_id == "lvedd")
        assert female_lvedd.norm_text == "36–51"
        assert male_lvedd.norm_text == "42–59"

    def test_both_shows_one_range_when_the_sexes_agree(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_BOTH)
        rwt = next(row for row in view.rows if row.param_id == "rwt_hyp")
        assert rwt.norm_text == "0.32–0.42"

    def test_both_names_the_order_when_the_sexes_differ(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_BOTH)
        lvedd = next(row for row in view.rows if row.param_id == "lvedd")
        first, second = lvedd.norm_text.split(" / ")
        assert (first, second) == ("42–59", "36–51")

    def test_unknown_sex_id_falls_back_to_both(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex="unknown")
        lvedd = next(row for row in view.rows if row.param_id == "lvedd")
        assert "/" in lvedd.norm_text


class TestGradations:
    def test_four_columns_for_the_left_ventricle(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE)
        assert view.columns == ("Норма", "Лёгкое", "Умеренное", "Тяжёлое")

    def test_columns_merge_the_gender_of_the_handbook_word(self, ru_store):
        view = build_topic_view(ru_store, "mitral_valve", sex=SEX_MALE, language="ru")
        assert [gradation_key(column) for column in view.columns] == ["normal", "mild", "moderate", "severe"]

    def test_cells_align_with_the_columns(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE)
        lvedd = next(row for row in view.rows if row.param_id == "lvedd")
        assert len(lvedd.gradation_texts) == len(view.columns)
        assert lvedd.gradation_texts == ("36–51", "52–56", "57–61", "≥ 62")

    def test_missing_gradation_is_an_empty_cell(self, ru_store):
        view = build_topic_view(ru_store, "mitral_valve", sex=SEX_MALE, language="ru")
        row = view.rows[0]
        normal_cell = row.gradation_texts[view.columns.index(next(c for c in view.columns if "Норм" in c))]
        assert normal_cell == ""

    def test_open_bounds_are_written_with_a_sign(self):
        from echo_personal_tool.domain.services.reference_card import GradeCut

        assert format_cut(GradeCut("Норма", 36.0, 51.0)) == "36–51"
        assert format_cut(GradeCut("Тяжёлое", 62.0, None)) == "≥ 62"
        assert format_cut(GradeCut("Ниже", None, 35.0)) == "≤ 35"
        assert format_cut(GradeCut("Пусто", None, None)) == ""

    def test_rank_orders_the_four_meanings(self):
        assert [gradation_rank(name) for name in ("Норма", "Лёгкое", "Умеренное", "Тяжёлое")] == [0, 1, 2, 3]
        assert gradation_rank("Лёгкая") == gradation_rank("Mild") == 1
        assert gradation_rank("Нечто") == 4


class TestPatientValues:
    def test_value_and_grade_come_from_the_card_model(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE, values={"lvedd": 48.0})
        lvedd = next(row for row in view.rows if row.param_id == "lvedd")
        assert lvedd.value == 48.0
        assert lvedd.value_text == "48 мм"
        assert lvedd.grade == "Норма"

    def test_row_without_a_value_keeps_an_empty_value_text(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE, values={"lvedd": 48.0})
        lvesd = next(row for row in view.rows if row.param_id == "lvesd")
        assert lvesd.value is None and lvesd.value_text == ""

    def test_projection_translation_covers_the_lv_family(self):
        projection = {
            "lv.lvedd": 48.0,
            "lv.lvesd": 31.0,
            "lv.ivsd": 10.0,
            "lv.lvpwd": 9.0,
            "lv.mass": 162.0,
            "lv.mass_i": 95.0,
            "lv.rwt": 0.42,
            "lv.ef_bp": 59.0,
        }
        assert reference_values(projection) == {
            "lvedd": 48.0,
            "lvesd": 31.0,
            "ivsd": 10.0,
            "lvpwd": 9.0,
            "lvm": 162.0,
            "lvmi_hyp": 95.0,
            "rwt_hyp": 0.42,
            "lvef": 59.0,
        }

    def test_volumes_and_doppler_are_not_guessed(self):
        dropped = {"lv.edv_bp": 120.0, "lv.esv_bp": 50.0, "tr.vmax": 280.0, "av.vmax": 200.0}
        assert reference_values(dropped) == {}

    def test_translation_table_only_names_known_projection_keys(self):
        for key in PROJECTION_TO_HANDBOOK:
            assert key.split(".")[0] in {"lv"}

    def test_none_projection_is_an_empty_map(self):
        assert reference_values(None) == {}


class TestSearchView:
    def test_search_keeps_topic_and_pathology(self, ru_store):
        view = search_view(ru_store, "КДР", sex=SEX_FEMALE)
        assert view.is_topic is False
        assert view.rows
        assert all("кдр" in row.name.lower() for row in view.rows)
        assert all(row.topic_name and row.pathology_name for row in view.rows)

    def test_search_is_deduplicated_by_parameter(self, ru_store):
        view = search_view(ru_store, "лж", sex=SEX_BOTH, language="ru")
        ids = [row.param_id for row in view.rows]
        assert len(ids) == len(set(ids))

    def test_search_matches_the_english_handbook_too(self, en_store):
        view = search_view(en_store, "LVEDD", sex=SEX_FEMALE, language="en")
        assert [row.param_id for row in view.rows] == ["lvedd"]

    def test_empty_query_gives_an_empty_view(self, ru_store):
        view = search_view(ru_store, "   ", sex=SEX_BOTH)
        assert view.rows == () and view.is_topic is False

    def test_nothing_found_is_an_empty_view(self, ru_store):
        assert search_view(ru_store, "нет-такого-параметра", sex=SEX_BOTH).rows == ()


class TestRowContent:
    def test_how_to_is_shown_when_the_handbook_has_it(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE)
        assert any(row.how_to for row in view.rows) or all(row.how_to == () for row in view.rows)

    def test_source_and_method_travel_with_the_row(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle", sex=SEX_FEMALE)
        lvm = next(row for row in view.rows if row.param_id == "lvm")
        assert lvm.source
        assert lvm.method

    def test_images_come_from_the_pathology(self, ru_store):
        view = build_topic_view(ru_store, "left_ventricle")
        lvedd = next(row for row in view.rows if row.param_id == "lvedd")
        assert "01-LV.png" in lvedd.image_paths

    def test_chip_label_drops_the_topic_from_the_pathology_name(self):
        assert chip_label("Размеры левого желудочка", "Левый желудочек") == "Размеры"
        assert chip_label("Фракция выброса левого желудочка", "Левый желудочек") == "Фракция выброса"
        assert chip_label("Митральный стеноз", "Митральный клапан") == "Митральный стеноз"
        assert chip_label("Почки", "Почки") == "Почки"


class TestPaletteEntries:
    """«Справочник: КДР» of Ctrl+K (spec §4.7) — the catalogue side."""

    def test_query_finds_the_parameter_of_the_handbook(self):
        from echo_personal_tool.presentation.command_catalog import reference_commands

        commands = reference_commands("КДР", language="ru")
        assert commands
        assert commands[0].action == "reference_param:lvedd"
        assert commands[0].label_text.startswith("Справочник: ")
        assert commands[0].id == "reference.lvedd"

    def test_one_letter_is_not_a_query(self):
        from echo_personal_tool.presentation.command_catalog import reference_commands

        assert reference_commands("к", language="ru") == ()

    def test_limit_keeps_the_palette_a_palette(self):
        from echo_personal_tool.presentation.command_catalog import reference_commands

        commands = reference_commands("лж", language="ru", limit=3)
        assert len(commands) == 3

    def test_english_handbook_names_are_matched_too(self):
        from echo_personal_tool.presentation.command_catalog import reference_commands

        commands = reference_commands("LVEDD", language="en")
        assert [command.action for command in commands] == ["reference_param:lvedd"]

    def test_parameter_matches_are_unique(self):
        from echo_personal_tool.domain.services.reference_topics import parameter_matches

        ids = [param.id for param in parameter_matches("ллж", language="ru")]
        assert len(ids) == len(set(ids))
