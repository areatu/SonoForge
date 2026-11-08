"""Report phrases: the starter set, search, insertion and the document format.

UI-4 PR-3 (spec §4.6, UQ-08).  The module under test is pure: the column
renders its groups, the store persists its documents, and the insertion
helpers decide where a sentence lands in the conclusion.
"""

from __future__ import annotations

import json

import pytest

from echo_personal_tool.domain.measurement_catalog import SECTIONS
from echo_personal_tool.domain.services.report_phrases import (
    KIND_NORM,
    KIND_PATHOLOGY,
    MAX_PHRASE_TEXT,
    PHRASES,
    PhraseDocumentError,
    conclusion_insertion,
    dumped_document,
    filter_phrases,
    inserted_phrase_ids,
    insertion_segment,
    make_user_phrase,
    parse_phrase_document,
    phrase_groups,
    phrase_id,
    phrase_is_inserted,
    phrases_match,
)


class TestStarterSet:
    def test_the_set_is_small_bilingual_and_belongs_to_catalog_sections(self) -> None:
        # The echo starter set plus the conclusion templates of the organ
        # protocols; the owner keeps the library lean on purpose.
        assert 0 < len(PHRASES) <= 60
        for phrase in PHRASES:
            assert phrase.builtin is True
            assert phrase.ru.strip() and phrase.en.strip()
            assert phrase.ru == phrase.ru.strip()
            assert phrase.en == phrase.en.strip()
            assert phrase.section in SECTIONS

    def test_ids_are_unique_and_built_in(self) -> None:
        assert len({phrase.id for phrase in PHRASES}) == len(PHRASES)
        assert all(phrase.id.startswith("builtin.") for phrase in PHRASES)

    def test_groups_follow_norm_first_then_the_catalog_order(self) -> None:
        groups = phrase_groups(PHRASES, "ru")
        # The conclusion templates lead: «Норма» first, «Патология» after.
        assert [group.section for group in groups[:2]] == [KIND_NORM, KIND_PATHOLOGY]
        sections = [group.section for group in groups[2:]]
        expected = [
            section for section in SECTIONS if section in {phrase.section for phrase in PHRASES if not phrase.kind}
        ]
        assert sections == expected
        assert groups[2].title == SECTIONS["general"].label("ru").short
        english = phrase_groups(PHRASES, "en")
        assert [english[0].title, english[1].title] == ["Norm", "Pathology"]
        assert english[2].title == SECTIONS["general"].label("en").short

    def test_text_follows_the_language_and_unknown_reads_english(self) -> None:
        phrase = PHRASES[0]
        assert phrase.text("ru") == phrase.ru
        assert phrase.text("en") == phrase.en
        assert phrase.text("de") == phrase.en


class TestConclusionTemplates:
    def test_norm_comes_before_pathology(self) -> None:
        groups = phrase_groups(PHRASES, "ru", profile_id="kidney")
        assert [group.section for group in groups[:2]] == [KIND_NORM, KIND_PATHOLOGY]
        assert [group.title for group in groups[:2]] == ["Норма", "Патология"]

    def test_an_organ_protocol_only_offers_its_own_templates(self) -> None:
        kidney = {phrase.id for group in phrase_groups(PHRASES, "ru", profile_id="kidney") for phrase in group.phrases}
        assert "builtin.kidney.stones" in kidney
        assert "builtin.thyroid.nodules" not in kidney
        assert "builtin.vascular.stenosis" not in kidney
        # The echo starter set is scoped to the echocardiography protocol.
        assert "builtin.general.standard" not in kidney

    def test_the_norm_template_is_shared_by_every_protocol(self) -> None:
        for profile_id in ("echo", "vascular", "abdomen", "kidney", "thyroid", "ultrasound_generic"):
            groups = phrase_groups(PHRASES, "ru", profile_id=profile_id)
            norm = next(group for group in groups if group.section == KIND_NORM)
            assert {phrase.id for phrase in norm.phrases} == {"builtin.norm.no_pathology"}

    def test_the_pathology_lists_cover_the_owners_examples(self) -> None:
        thyroid = {
            phrase.text("ru")
            for group in phrase_groups(PHRASES, "ru", profile_id="thyroid")
            for phrase in group.phrases
        }
        assert "Диффузные изменения по типу аутоиммунного тиреоидита" in thyroid
        assert "Очаговые изменения" in thyroid
        kidney = {
            phrase.text("ru") for group in phrase_groups(PHRASES, "ru", profile_id="kidney") for phrase in group.phrases
        }
        assert {"Конкременты", "Кисты", "Изменения паренхимы"} <= kidney


class TestSearch:
    def test_search_matches_either_language(self) -> None:
        english = filter_phrases(PHRASES, "ru", "left ventricular cavity")
        russian = filter_phrases(PHRASES, "ru", "полость левого желудочка")
        assert english
        assert {phrase.section for phrase in english} <= {"lv", "rv"}
        assert english == russian

    def test_search_matches_the_section_title(self) -> None:
        # «МК/АК» names the MV/AV section but appears in none of its phrases.
        found = filter_phrases(PHRASES, "ru", "мк/ак")
        assert len(found) == len([phrase for phrase in PHRASES if phrase.section == "mv_av"])
        assert {phrase.section for phrase in found} == {"mv_av"}

    def test_search_is_case_and_space_insensitive(self) -> None:
        assert filter_phrases(PHRASES, "ru", "  ПОЛОСТЬ   ЛЖ ") == filter_phrases(PHRASES, "ru", "полость лж")

    def test_no_match_yields_no_groups(self) -> None:
        assert phrase_groups(PHRASES, "ru", "zzz-no-such-phrase") == ()


class TestInsertion:
    def test_a_phrase_ends_the_sentence_and_the_next_one_starts_cleanly(self) -> None:
        text, position = conclusion_insertion("Полость ЛЖ не расширена", "Толщина стенок ЛЖ в норме")
        assert text == "Полость ЛЖ не расширена. Толщина стенок ЛЖ в норме."
        assert position == len(text)

    def test_after_punctuation_a_single_space_is_enough(self) -> None:
        text, position = conclusion_insertion("Заключение:", "Текст", 11)
        assert text == "Заключение: Текст."
        assert position == len(text)

    def test_an_empty_conclusion_gets_the_sentence_only(self) -> None:
        text, position = conclusion_insertion("", "Первая фраза")
        assert text == "Первая фраза."
        assert position == len(text)

    def test_a_phrase_with_final_punctuation_is_not_doubled(self) -> None:
        assert insertion_segment("", "", "Давление 26 мм рт. ст.") == "Давление 26 мм рт. ст."
        assert insertion_segment("", "", "Вариант:") == "Вариант:"

    def test_the_cursor_lands_after_the_inserted_text(self) -> None:
        text, position = conclusion_insertion("abc", "def", 3)
        assert text == "abc. def."
        assert position == len(text)

    def test_insertion_inside_a_sentence_keeps_the_tail_readable(self) -> None:
        text, _position = conclusion_insertion("Начало конец", "Вставка", 6)
        assert text == "Начало. Вставка. конец"


class TestInsertedMarks:
    def test_detection_ignores_case_and_whitespace(self) -> None:
        assert phrase_is_inserted(
            "Итог: полость   ЛЕВОГО желудочка не расширена.",
            "Полость левого желудочка не расширена",
        )

    def test_detection_requires_whole_words(self) -> None:
        assert not phrase_is_inserted("Полость ЛЖ не расширеная", "Полость ЛЖ не расширена")

    def test_inserted_ids_follow_the_text_and_the_language(self) -> None:
        phrase = PHRASES[0]
        assert phrase.id in inserted_phrase_ids(PHRASES, phrase.text("ru"), "ru")
        assert phrase.id in inserted_phrase_ids(PHRASES, phrase.text("en"), "en")
        assert inserted_phrase_ids(PHRASES, "", "ru") == frozenset()


class TestUserPhrase:
    def test_whitespace_is_collapsed_and_the_missing_language_falls_back(self) -> None:
        phrase = make_user_phrase("lv", "  Моя \n фраза  ", "   ")
        assert phrase is not None
        assert (phrase.ru, phrase.en) == ("Моя фраза", "Моя фраза")
        assert phrase.builtin is False
        assert phrase.section == "lv"

    def test_at_least_one_language_is_required(self) -> None:
        assert make_user_phrase("lv", "  ", None) is None
        assert make_user_phrase("lv", 42, {}) is None

    def test_a_paragraph_is_not_a_phrase(self) -> None:
        assert make_user_phrase("lv", "x" * (MAX_PHRASE_TEXT + 1), "") is None
        assert make_user_phrase("lv", "x" * MAX_PHRASE_TEXT, "") is not None

    def test_an_unknown_section_falls_back_to_general(self) -> None:
        phrase = make_user_phrase("no-such-section", "Фраза", "")
        assert phrase is not None and phrase.section == "general"

    def test_identity_is_content_derived(self) -> None:
        first = make_user_phrase("lv", "Фраза", "Phrase")
        second = make_user_phrase("lv", " Фраза ", "Phrase")
        assert first is not None and second is not None
        assert first.id == second.id == phrase_id("lv", "Фраза", "Phrase")
        assert first.id.startswith("user.")

    def test_matching_compares_both_languages(self) -> None:
        first = make_user_phrase("lv", "Фраза", "Phrase")
        same = make_user_phrase("rv", "ФРАЗА", "phrase")
        other = make_user_phrase("lv", "Фраза", "Another phrase")
        assert first is not None and same is not None and other is not None
        assert phrases_match(first, same)
        assert not phrases_match(first, other)


class TestDocument:
    def test_round_trip_keeps_the_library(self) -> None:
        phrases = (
            make_user_phrase("lv", "Первая", "First"),
            make_user_phrase("aorta", "Вторая", "Second"),
        )
        assert all(phrase is not None for phrase in phrases)
        document = parse_phrase_document(dumped_document(phrases))
        assert document.phrases == phrases
        assert document.skipped == 0

    def test_the_document_carries_the_format_and_version(self) -> None:
        payload = json.loads(dumped_document(()))
        assert payload["format"] == "sonoforge.report-phrases"
        assert payload["version"] == 1
        assert payload["phrases"] == []

    def test_broken_items_are_skipped_and_counted(self) -> None:
        payload = json.dumps(
            {
                "phrases": [
                    {"section": "lv", "ru": "Фраза", "en": "Phrase"},
                    {"section": "lv", "ru": "Фраза", "en": "Phrase"},
                    {"section": "lv"},
                    "not-an-object",
                    {"section": "lv", "ru": "x" * (MAX_PHRASE_TEXT + 1), "en": ""},
                ]
            },
            ensure_ascii=False,
        )
        document = parse_phrase_document(payload)
        assert len(document.phrases) == 1
        assert document.skipped == 4

    def test_only_the_document_shape_makes_the_import_fail(self) -> None:
        with pytest.raises(PhraseDocumentError):
            parse_phrase_document("not json")
        with pytest.raises(PhraseDocumentError):
            parse_phrase_document("[]")
        with pytest.raises(PhraseDocumentError):
            parse_phrase_document("{}")
        with pytest.raises(PhraseDocumentError):
            parse_phrase_document('{"phrases": "nope"}')
