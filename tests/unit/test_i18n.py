"""Tests for i18n locale loading and key parity."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo_personal_tool.domain.models import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.measurement_results_formatter import format_results_overlay
from echo_personal_tool.infrastructure import i18n as i18n_mod
from echo_personal_tool.infrastructure.i18n import (
    get_language,
    register_ui_reload,
    set_language,
    tr,
    tr_plural,
    unregister_ui_reload,
)

_LOCALES_DIR = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"


def _load_locale(lang: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{lang}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_locale_key_parity() -> None:
    ru = _load_locale("ru")
    en = _load_locale("en")
    assert set(ru) == set(en)
    assert len(ru) > 0


def test_tr_substitution() -> None:
    set_language("en")
    text = tr("status.loading", name="study.dcm")
    assert "study.dcm" in text


def test_plural_forms_for_english_and_russian() -> None:
    set_language("en")
    assert tr_plural("status.studies_loaded", 1) == "Loaded 1 study"
    assert tr_plural("status.studies_loaded", 2) == "Loaded 2 studies"

    set_language("ru")
    assert tr_plural("status.studies_loaded", 1) == "Загружено 1 исследование"
    assert tr_plural("status.studies_loaded", 2) == "Загружено 2 исследования"
    assert tr_plural("status.studies_loaded", 5) == "Загружено 5 исследований"
    assert tr_plural("status.studies_loaded", 21) == "Загружено 21 исследование"


def test_plural_falls_back_for_unknown_category() -> None:
    set_language("en")
    assert tr_plural("status.studies_loaded", 1.5) == "Loaded 1.5 studies"


def test_gallery_group_clip_count_pluralization() -> None:
    set_language("en")
    assert tr_plural("gallery.group.clips", 1) == "1 clip"
    assert tr_plural("gallery.group.clips", 2) == "2 clips"

    set_language("ru")
    assert tr_plural("gallery.group.clips", 1) == "1 клип"
    assert tr_plural("gallery.group.clips", 3) == "3 клипа"
    assert tr_plural("gallery.group.clips", 5) == "5 клипов"


def test_plural_forms_for_count_sensitive_strings() -> None:
    """The strings a user sees with small counts must not read "1 записей"."""
    set_language("ru")
    assert tr_plural("persistence.stats", 1, size="0.1").startswith("1 запись ·")
    assert tr_plural("persistence.stats", 2, size="0.2").startswith("2 записи ·")
    assert tr_plural("persistence.stats", 5, size="0.5").startswith("5 записей ·")
    assert tr_plural("constructor.param.delete_selected_confirm", 1) == "Удалить 1 параметр?"
    assert tr_plural("constructor.param.delete_selected_confirm", 3) == "Удалить 3 параметра?"
    assert tr_plural("constructor.param.delete_selected_confirm", 7) == "Удалить 7 параметров?"
    assert tr_plural("constructor.pathology.delete_confirm", 1, names="A").startswith("Удалить 1 патологию?")
    assert tr_plural("constructor.pathology.delete_confirm", 2, names="A, B").startswith("Удалить 2 патологии?")
    assert tr_plural("viewer.vessel_average_done", 1, psv=1.0, edv=0.5).endswith("(среднее по 1 циклу)")
    assert tr_plural("viewer.vessel_average_done", 4, psv=1.0, edv=0.5).endswith("(среднее по 4 циклам)")

    set_language("en")
    assert tr_plural("persistence.stats", 1, size="0.1").startswith("1 record ·")
    assert tr_plural("persistence.stats", 2, size="0.2").startswith("2 records ·")
    assert tr_plural("constructor.param.delete_selected_confirm", 1) == "Delete 1 parameter?"
    assert tr_plural("viewer.vessel_average_done", 1, psv=1.0, edv=0.5).endswith("(avg 1 cycle)")


def test_set_language_switches_linear_measurement_label() -> None:
    measurement = LinearMeasurement("IVSd", 10.0, 5.0)
    set_language("ru")
    assert "МЖП" in measurement.display_text()
    set_language("en")
    assert "IVSd" in measurement.display_text()


def test_overlay_rwt_respects_language() -> None:
    set_language("ru")
    ru_text = format_results_overlay(MeasurementSnapshot(rwt=0.42))
    set_language("en")
    en_text = format_results_overlay(MeasurementSnapshot(rwt=0.42))
    assert "ОТС" in ru_text
    assert "RWT" in en_text


# ── Additional tests for coverage ──


def test_get_language_default() -> None:
    set_language("ru")
    assert get_language() == "ru"


def test_set_language_unknown_falls_back_to_en() -> None:
    set_language("xx")
    assert get_language() == "en"


def test_set_language_valid_ru() -> None:
    set_language("ru")
    assert get_language() == "ru"


def test_set_language_valid_en() -> None:
    set_language("en")
    assert get_language() == "en"


def test_tr_fallback_to_en() -> None:
    """If key not in current lang, falls back to en."""
    # Inject a key only in en
    i18n_mod._translations["en"]["test_only_en"] = "English only"
    set_language("ru")
    text = tr("test_only_en")
    assert text == "English only"
    del i18n_mod._translations["en"]["test_only_en"]


def test_tr_returns_key_if_not_found() -> None:
    result = tr("nonexistent_key_xyz_123")
    assert result == "nonexistent_key_xyz_123"


def test_tr_no_kwargs() -> None:
    set_language("en")
    text = tr("status.loading", name="test.dcm")
    assert "test.dcm" in text


def test_tr_with_kwargs_key_error_returns_raw_text() -> None:
    """If format kwargs don't match placeholders, return raw text."""
    set_language("en")
    text = tr("status.loading", wrong_key="val")
    # Should not crash, returns the raw translated text or key
    assert isinstance(text, str)


def test_register_and_unregister_ui_reload() -> None:
    cb = MagicMock()
    register_ui_reload(cb)
    set_language("en")  # should trigger callback
    cb.assert_called_once()
    unregister_ui_reload(cb)


def test_unregister_nonexistent_callback() -> None:
    cb = MagicMock()
    # Should not raise
    unregister_ui_reload(cb)


def test_ui_reload_exception_swallowed() -> None:
    bad_cb = MagicMock(side_effect=RuntimeError("crash"))
    register_ui_reload(bad_cb)
    set_language("en")  # should not raise despite bad callback
    unregister_ui_reload(bad_cb)


def test_load_locales_skips_internal_keys() -> None:
    """Keys starting with _ should be skipped."""
    # Reload to verify internal keys are excluded
    i18n_mod._load_locales()
    for lang_dict in i18n_mod._translations.values():
        for key in lang_dict:
            assert not key.startswith("_"), f"Internal key '{key}' should be filtered"


def test_load_locales_handles_corrupt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrupt JSON should be handled gracefully."""
    corrupt_dir = tmp_path / "locales"
    corrupt_dir.mkdir()
    (corrupt_dir / "en.json").write_text("NOT JSON {{{")
    (corrupt_dir / "ru.json").write_text('{"key": "val"}')
    monkeypatch.setattr(i18n_mod, "_LOCALES_DIR", corrupt_dir)
    i18n_mod._load_locales()
    assert i18n_mod._translations.get("en") == {}
    assert i18n_mod._translations.get("ru") == {"key": "val"}


def test_load_locales_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Missing locale file should be handled gracefully."""
    empty_dir = tmp_path / "locales"
    empty_dir.mkdir()
    monkeypatch.setattr(i18n_mod, "_LOCALES_DIR", empty_dir)
    i18n_mod._load_locales()
    assert i18n_mod._translations == {}


@pytest.fixture(autouse=True)
def restore_russian() -> None:
    locales_dir = i18n_mod._LOCALES_DIR
    yield
    # Another autouse fixture requests monkeypatch, so pytest may run this
    # teardown while a test's temporary locale directory is still active.
    # Restore the real path before reloading to avoid leaking an empty catalog
    # into tests collected after this module.
    i18n_mod._LOCALES_DIR = locales_dir
    i18n_mod._load_locales()
    set_language("ru")
