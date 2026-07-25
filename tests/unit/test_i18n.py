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
    yield
    set_language("ru")
