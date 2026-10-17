"""Contract tests of the overlay nomenclature (TP-1 PR-1, rule D-11/A-12)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS, en_label_violations, ru_label_violations
from echo_personal_tool.domain.services.nomenclature import (
    OVERLAY_TO_CATALOG,
    catalog_label,
    overlay_label,
    view_label,
)
from echo_personal_tool.infrastructure.i18n import set_language, tr


@pytest.fixture()
def language():
    def _set(lang: str) -> None:
        set_language(lang)

    yield _set
    set_language("en")


@pytest.mark.parametrize("key", sorted(OVERLAY_TO_CATALOG))
def test_mapped_keys_resolve_to_catalog(key: str) -> None:
    measurement_id = OVERLAY_TO_CATALOG[key]
    assert measurement_id in MEASUREMENTS
    for lang in ("ru", "en"):
        assert catalog_label(measurement_id, lang)


@pytest.mark.parametrize("key", sorted(OVERLAY_TO_CATALOG))
def test_mapped_labels_fully_ru_xor_en(key: str) -> None:
    measurement_id = OVERLAY_TO_CATALOG[key]
    spec = MEASUREMENTS[measurement_id]
    assert ru_label_violations(spec.label("ru").short) == []
    assert en_label_violations(spec.label("en").short) == []


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_overlay_label_follows_language(lang: str, language) -> None:
    language(lang)
    assert overlay_label("result.mv_e") == catalog_label("mv.e", lang)
    assert overlay_label("result.mv_e") == MEASUREMENTS["mv.e"].label(lang).short


def test_unknown_key_falls_back_to_locale_key() -> None:
    assert overlay_label("result.at") == tr("result.at")


@pytest.mark.parametrize(
    ("kind", "view", "measurement_id"),
    [
        ("kdo", "4C", "lv.edv_a4c"),
        ("kdo", "2C", "lv.edv_a2c"),
        ("kso", "4C", "lv.esv_a4c"),
        ("kso", "2C", "lv.esv_a2c"),
    ],
)
def test_view_labels_hit_the_catalog(kind: str, view: str, measurement_id: str) -> None:
    assert view_label(kind, view) == catalog_label(measurement_id)


@pytest.mark.parametrize("kind", ["kdo", "kso"])
def test_unknown_view_falls_back(kind: str) -> None:
    assert view_label(kind, "5C") == tr(f"panel.{kind}_lv", view="5C")
