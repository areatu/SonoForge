"""TP-1 acceptance: EN goldens — no mixed locales in overlay, report and PDF."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _snapshot() -> MeasurementSnapshot:
    return MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=52.0),),
    )


@pytest.fixture
def en_locale():
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language("en")
    yield
    set_language("ru")


def test_en_structured_report_linear_golden(en_locale) -> None:
    from echo_personal_tool.domain.services.report_builder import build_report_document

    document = build_report_document(_snapshot(), length_display_unit="cm")
    rows = [value for group in document.groups for value in group.values]

    assert any((value.label, value.value, value.unit) == ("LVIDd", "5.2", "cm") for value in rows)
    assert not _CYRILLIC.search(" ".join(value.label for value in rows))


def test_en_overlay_linear_golden(en_locale) -> None:
    from echo_personal_tool.domain.services.measurement_results_formatter import (
        format_results_overlay,
        format_results_overlay_html,
    )

    snapshot = _snapshot()
    overlay = format_results_overlay(snapshot, length_display_unit="cm")
    html_overlay = format_results_overlay_html(snapshot, length_display_unit="cm")
    assert "LVIDd: 5.2 cm" in overlay
    assert "LVIDd" in html_overlay and "5.2" in html_overlay
    assert not _CYRILLIC.search(overlay)
    assert not _CYRILLIC.search(_plain(html_overlay))


def test_en_structured_pdf_contains_the_report_rows(en_locale, tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    from echo_personal_tool.domain.services.report_builder import build_report_document
    from echo_personal_tool.infrastructure.measurement_report_pdf import export_report_document_pdf

    document = build_report_document(_snapshot(), length_display_unit="cm")
    output = export_report_document_pdf(document, tmp_path / "report.pdf")
    with pymupdf.open(output) as pdf:
        text = "\n".join(page.get_text() for page in pdf)

    assert "LVIDd" in text
    assert "5.2 cm" in text
    assert not _CYRILLIC.search(text)


def _plain(markup: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(markup))
