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


def test_length_cm_reads_the_same_in_overlay_and_structured_report() -> None:
    """length_display_unit=cm: 52 mm reads «5.2 cm» in both active paths."""
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.measurement_results_formatter import format_results_overlay
    from echo_personal_tool.domain.services.nomenclature import caliper_label
    from echo_personal_tool.domain.services.report_builder import build_report_document

    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=52.0),),
    )
    label = caliper_label("LVEDD")
    overlay = format_results_overlay(snapshot, length_display_unit="cm")
    document = build_report_document(snapshot, length_display_unit="cm")
    rows = [value for group in document.groups for value in group.values]

    assert f"{label}: 5.2 cm" in overlay
    assert any((value.label, value.value, value.unit) == (label, "5.2", "cm") for value in rows)
    assert "52" not in overlay.replace(" 5.2 cm", "")


def test_html_overlay_converts_mm_to_cm_like_the_plain_overlay() -> None:
    """TP-1 PR-2 hotcheck: the HTML overlay reads 52mm as «5.2 cm», not «52 cm»."""
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.measurement_results_formatter import format_results_overlay_html

    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=52.0),),
    )
    html = _plain_html(format_results_overlay_html(snapshot, length_display_unit="cm"))
    assert "5.2" in html and " cm" in html
    assert "52" not in html

    plain_mm = format_results_overlay_html(snapshot, length_display_unit="mm").replace(" ", "")
    assert "52" in plain_mm and "mm" in plain_mm


def _plain_html(markup: str) -> str:
    import html as html_module
    import re

    return re.sub(r"<[^>]+>", "", html_module.unescape(markup))


def test_length_mm_in_structured_report_keeps_zero_decimals() -> None:
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.nomenclature import caliper_label
    from echo_personal_tool.domain.services.report_builder import build_report_document

    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=52.0),),
    )
    document = build_report_document(snapshot, length_display_unit="mm")
    rows = [value for group in document.groups for value in group.values]

    assert any((value.label, value.value, value.unit) == (caliper_label("LVEDD"), "52", "mm") for value in rows)
