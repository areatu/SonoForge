"""The local report-phrase library: persistence, limits, import and export.

UI-4 PR-3 (UQ-08): user phrases live in one JSON document that doubles as the
import/export format.  A broken or missing file must degrade to an empty
library, while a failed write is the caller's problem (the column reports it).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.report_phrases import (
    PhraseDocumentError,
    make_user_phrase,
    parse_phrase_document,
)
from echo_personal_tool.infrastructure import report_phrase_store as store_module
from echo_personal_tool.infrastructure.report_phrase_store import PhraseStore


def _store(tmp_path: Path) -> PhraseStore:
    return PhraseStore(tmp_path / "phrases.json")


def test_a_missing_file_is_an_empty_library(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.phrases() == ()
    assert store.path == tmp_path / "phrases.json"


def test_add_persists_and_another_store_reads_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    added = store.add("lv", "  Моя   фраза  ", "My phrase")
    assert added is not None
    assert store.phrases() == (added,)
    assert _store(tmp_path).phrases() == (added,)


def test_add_is_idempotent_for_the_same_text(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.add("lv", "Фраза", "Phrase") is not None
    assert store.add("lv", " Фраза ", "Phrase") is None
    assert len(store.phrases()) == 1


def test_add_rejects_empty_text(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.add("lv", "   ", "") is None
    assert store.phrases() == ()


def test_the_library_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "MAX_USER_PHRASES", 2)
    store = _store(tmp_path)
    assert store.add("lv", "Первая", "First") is not None
    assert store.add("lv", "Вторая", "Second") is not None
    assert store.add("lv", "Третья", "Third") is None
    assert len(store.phrases()) == 2


def test_remove_deletes_only_the_given_phrase(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.add("lv", "Первая", "First")
    second = store.add("lv", "Вторая", "Second")
    assert first is not None and second is not None
    assert store.remove(first.id) is True
    assert store.phrases() == (second,)
    assert store.remove("user.unknown") is False


def test_a_corrupt_file_degrades_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "phrases.json"
    path.write_text("{not json", encoding="utf-8")
    assert _store(tmp_path).phrases() == ()


def test_a_corrupt_file_is_not_overwritten_by_add(tmp_path: Path) -> None:
    path = tmp_path / "phrases.json"
    path.write_text("{not json", encoding="utf-8")
    store = _store(tmp_path)
    assert store.add("lv", "Фраза", "Phrase") is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["phrases"]) == 1


def test_import_merges_skips_duplicates_and_counts_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    existing = store.add("lv", "Уже есть", "Already here")
    assert existing is not None
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "phrases": [
                    {"section": "lv", "ru": "Уже есть", "en": "Already here"},
                    {"section": "la", "ru": "Новая", "en": "New"},
                    {"section": "la", "ru": "", "en": ""},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = store.import_file(source)

    assert (result.added, result.duplicates, result.skipped) == (1, 1, 1)
    assert {phrase.ru for phrase in store.phrases()} == {"Уже есть", "Новая"}


def test_import_rejects_a_non_phrase_document(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("<xml/>", encoding="utf-8")
    with pytest.raises(PhraseDocumentError):
        _store(tmp_path).import_file(source)


def test_import_respects_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "MAX_USER_PHRASES", 1)
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "phrases": [
                    {"section": "lv", "ru": "Первая", "en": "First"},
                    {"section": "lv", "ru": "Вторая", "en": "Second"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = _store(tmp_path)
    result = store.import_file(source)
    assert (result.added, result.skipped) == (1, 1)


def test_export_writes_the_document_the_store_reads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    added = store.add("aorta", "Аорта не расширена", "The aorta is not dilated")
    assert added is not None
    exported = tmp_path / "export.json"
    assert store.export_file(exported) == 1

    document = parse_phrase_document(exported.read_text(encoding="utf-8"))
    assert document.phrases == (added,)

    # Another workstation imports that file as-is.
    other = PhraseStore(tmp_path / "other.json")
    result = other.import_file(exported)
    assert result.added == 1
    assert other.phrases() == (added,)


def test_the_default_path_is_the_user_data_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "profile" / "report_phrases.json"
    monkeypatch.setattr(store_module, "report_phrases_file", lambda: target)
    assert PhraseStore().path == target


def test_the_written_document_is_human_readable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    phrase = make_user_phrase("lv", "Фраза", "Phrase")
    assert phrase is not None
    store.add("lv", phrase.ru, phrase.en)
    text = store.path.read_text(encoding="utf-8")
    assert "Фраза" in text  # ensure_ascii=False: the file stays editable
    assert text.endswith("\n")
