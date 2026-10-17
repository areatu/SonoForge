"""Contract tests of the overlay nomenclature (TP-1 PR-1, rule D-11/A-12)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS, en_label_violations, ru_label_violations
from echo_personal_tool.domain.services.nomenclature import (
    OVERLAY_TO_CATALOG,
    catalog_label,
    length_decimals,
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


# ── D-12: linear sizes — mm 0 decimals, cm (ASE) 1 ──────────────────


@pytest.mark.parametrize(("unit", "expected"), [("mm", 0), ("cm", 1), ("px", 0)])
def test_length_decimals_rule(unit: str, expected: int) -> None:
    assert length_decimals(unit) == expected


def test_length_mm_reads_the_same_in_overlay_and_report() -> None:
    """52 mm reads «52 mm» in the on-image overlay and in the report text (mm)."""
    from echo_personal_tool.domain.models.linear_measurement import format_length_mm

    assert format_length_mm(52.0, "mm") == "52 mm"
    assert format_length_mm(52.0, "cm") == "5.2 cm"


def test_length_cm_reads_the_same_in_overlay_and_report() -> None:
    """length_display_unit=cm: 52 mm reads «5.2 cm» — same value everywhere."""
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.measurement_report_formatter import format_measurement_report
    from echo_personal_tool.domain.services.measurement_results_formatter import format_results_overlay

    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=52.0),),
    )
    overlay = format_results_overlay(snapshot, length_display_unit="cm")
    report = format_measurement_report(snapshot, length_display_unit="cm")
    assert "КДР ЛЖ: 5.2 cm" in overlay
    assert "КДР ЛЖ: 5.2 cm" in report
    assert "52" not in overlay.replace(" 5.2 cm", "")


def test_length_mm_in_report_keeps_zero_decimals() -> None:
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.measurement_report_formatter import format_measurement_report

    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=52.0),),
    )
    report = format_measurement_report(snapshot, length_display_unit="mm")
    assert "КДР ЛЖ: 52 mm" in report
