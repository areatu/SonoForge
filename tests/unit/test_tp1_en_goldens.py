"""TP-1 acceptance: EN goldens — no mixed locales in overlay, report and PDF."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_FAKE_FONT = Path("/fake/font.ttf")
_MOCK_A4 = (595.27, 841.89)
_MOCK_MM = 2.8346


def _snapshot() -> MeasurementSnapshot:
    return MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=52.0),),
    )


def _measurement_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.search(r"(КДР ЛЖ|LVIDd)|5\.2|52", line)]


@pytest.fixture
def en_locale():
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language("en")
    yield
    set_language("ru")


def test_en_report_linear_golden(en_locale) -> None:
    from echo_personal_tool.domain.services.measurement_report_formatter import format_measurement_report

    text = format_measurement_report(_snapshot(), length_display_unit="cm")
    assert "LVIDd: 5.2 cm" in text
    assert not any(_CYRILLIC.search(line) for line in _measurement_lines(text))


def test_en_overlay_linear_golden(en_locale) -> None:
    from echo_personal_tool.domain.services.measurement_results_formatter import (
        format_results_overlay,
        format_results_overlay_html,
    )

    snapshot = _snapshot()
    overlay = format_results_overlay(snapshot, length_display_unit="cm")
    html = format_results_overlay_html(snapshot, length_display_unit="cm")
    assert "LVIDd: 5.2 cm" in overlay
    assert "LVIDd" in html and "5.2" in html
    assert not any(_CYRILLIC.search(line) for line in _measurement_lines(_plain(overlay) + _plain(html)))


def test_en_pdf_lines_match_report(en_locale, tmp_path: Path) -> None:
    from echo_personal_tool.infrastructure.i18n import tr
    from echo_personal_tool.infrastructure.measurement_report_pdf import export_measurement_report_pdf

    patches = {
        "canvas": patch("echo_personal_tool.infrastructure.measurement_report_pdf.canvas"),
        "pdfmetrics": patch("echo_personal_tool.infrastructure.measurement_report_pdf.pdfmetrics"),
        "TTFont": patch("echo_personal_tool.infrastructure.measurement_report_pdf.TTFont"),
        "A4": patch("echo_personal_tool.infrastructure.measurement_report_pdf.A4", _MOCK_A4),
        "mm": patch("echo_personal_tool.infrastructure.measurement_report_pdf.mm", _MOCK_MM),
        "font_path": patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf.report_cyrillic_font_path",
            return_value=_FAKE_FONT,
        ),
    }

    from echo_personal_tool.domain.services.measurement_report_formatter import format_measurement_report

    report = format_measurement_report(_snapshot(), length_display_unit="cm")
    mock_c = MagicMock()
    mocks = {key: value.start() for key, value in patches.items()}
    mocks["canvas"].Canvas.return_value = mock_c
    try:
        output = tmp_path / "report.pdf"
        export_measurement_report_pdf(report, output)
    finally:
        for value in patches.values():
            value.stop()

    assert mock_c.setTitle.called
    assert mock_c.setTitle.call_args.args == (tr("pdf.report_title"),)
    drawn = " ".join(str(call.args[2]) for call in mock_c.drawString.call_args_list)
    assert "LVIDd: 5.2 cm" in drawn
    assert not _CYRILLIC.search(drawn)


def _plain(html: str) -> str:
    import html as _html
    import re as _re

    return _re.sub(r"<[^>]+>", "", _html.unescape(html))
