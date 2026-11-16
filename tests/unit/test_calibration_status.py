"""Calibration wording and tone (#555, 6.2)."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.localization import get_language, set_language, tr
from echo_personal_tool.domain.models.calibration import (
    ASSUMPTION_IMAGER_PLANE,
    ASSUMPTION_SECONDS_AS_LENGTH,
    CALIBRATION_CROSSES_REGION,
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
)
from echo_personal_tool.presentation import calibration_status


def _context(confidence: CalibrationConfidence, **kwargs) -> CalibrationContext:
    return CalibrationContext(
        spacing=(0.1, 0.1),
        source="PixelSpacing",
        confidence=confidence,
        **kwargs,
    )


def test_a_measured_scale_is_green_and_an_assumption_is_never_green() -> None:
    measured = _context(CalibrationConfidence.MEASURED)
    assumed = _context(CalibrationConfidence.ASSUMED)

    assert calibration_status.tone(measured) == "ok"
    assert calibration_status.tone(assumed) == "warn"
    assert calibration_status.tone(None) == "error"


def test_status_summary_names_source_confidence_and_scope() -> None:
    frame = _context(CalibrationConfidence.DERIVED, scope=CalibrationScope.FRAME, frame_index=1)
    text = calibration_status.summary(frame)

    assert calibration_status.source_name("PixelSpacing") in text
    assert calibration_status.confidence_text(CalibrationConfidence.DERIVED) in text
    assert "2" in text, "frames are shown one-based, as the viewer numbers them"


def test_region_scope_prints_its_bounds() -> None:
    region = CalibrationRegion(x0=1, x1=20, y0=3, y1=40)
    context = _context(CalibrationConfidence.DERIVED, scope=CalibrationScope.REGION, region=region)
    text = calibration_status.scope_text(context)

    assert "1" in text and "20" in text and "3" in text and "40" in text


def test_details_explain_the_isotropy_assumption_and_an_unverified_scale() -> None:
    context = _context(CalibrationConfidence.ASSUMED, assumed_isotropic=True)
    lines = calibration_status.details(context).splitlines()

    assert len(lines) == 6
    assert any("изотроп" in line.lower() or "isotrop" in line.lower() for line in lines)


def test_details_explain_what_the_calibration_line_is_for() -> None:
    """2026-11-16 list, item 4: the orange «Масштаб: …» line, explained.

    The tooltip must say what the line is, what «предположение» means and what
    the scale affects — the physician's question cannot be left to colour.
    """
    context = _context(CalibrationConfidence.ASSUMED)
    detail = calibration_status.details(context)
    role = tr("calibration.detail.role")

    assert detail.endswith(role)
    assert "калипер" in role or "caliper" in role
    assert "предположение" in role.lower() or "assumption" in role.lower()


def test_unavailable_badge_names_the_reason() -> None:
    text = calibration_status.unavailable_text(CALIBRATION_CROSSES_REGION)

    assert calibration_status.reason_text(CALIBRATION_CROSSES_REGION) in text


def test_an_assumption_code_is_named_in_the_badge_and_in_details() -> None:
    """Colour is not a label: the assumption is spelled out (#555)."""
    context = CalibrationContext(
        spacing=(0.3, 0.3),
        source="SequenceOfUltrasoundRegions",
        confidence=CalibrationConfidence.ASSUMED,
        assumption=ASSUMPTION_SECONDS_AS_LENGTH,
    )

    badge = calibration_status.summary(context)
    detail = calibration_status.details(context)

    code = calibration_status.assumption_text(ASSUMPTION_SECONDS_AS_LENGTH)
    assert calibration_status.assumption_note(context) in badge
    assert code not in badge, "the badge stays short; the code belongs to the list/tooltip"
    assert code in detail
    assert code in calibration_status.scale_line(context)
    assert calibration_status.tone(context) == "warn"


def test_an_unknown_assumption_code_stays_readable_as_itself() -> None:
    context = CalibrationContext(
        spacing=(0.1, 0.1),
        source="ImagerPixelSpacing",
        confidence=CalibrationConfidence.ASSUMED,
        assumption=ASSUMPTION_IMAGER_PLANE,
    )

    assert calibration_status.assumption_text("future_code") == "future_code"
    assert calibration_status.assumption_text(ASSUMPTION_IMAGER_PLANE)
    assert "future_code" not in calibration_status.details(context)


@pytest.fixture
def _restore_language():
    previous = get_language()
    yield
    set_language(previous)


@pytest.mark.parametrize(
    ("language", "confidence", "scope"),
    [("ru", "измеренная", "весь клип"), ("en", "measured", "whole clip")],
)
def test_the_badge_names_source_confidence_and_scope_in_both_languages(
    _restore_language, language: str, confidence: str, scope: str
) -> None:
    """#555: the same calibration reads as a sentence in RU and EN."""
    set_language(language)
    context = _context(CalibrationConfidence.MEASURED)

    badge = calibration_status.summary(context)

    assert calibration_status.source_name("PixelSpacing") in badge
    assert confidence in badge
    assert scope in badge
    assert calibration_status.tone(context) == "ok"


@pytest.mark.parametrize(
    ("language", "assumed"),
    [("ru", "предположение"), ("en", "assumption")],
)
def test_an_assumed_scale_is_named_in_words_in_both_languages(_restore_language, language: str, assumed: str) -> None:
    set_language(language)
    context = _context(CalibrationConfidence.ASSUMED, assumed_isotropic=True)

    badge = calibration_status.summary(context)

    assert assumed in badge.lower()
    assert calibration_status.tone(context) == "warn"


def test_the_patient_line_badge_is_a_narrow_strip() -> None:
    """2026-11-16, п.4: «Калибровка» вместо длинного «Масштаб: …».

    The long sentence overwrote «Рост · Вес · ППТ» on the patient row.  The
    strip stays narrow, keeps the state in words (colour is never the only
    label), and never says «Масштаб».
    """
    measured = _context(CalibrationConfidence.MEASURED)
    assumed = _context(CalibrationConfidence.ASSUMED)

    strip = calibration_status.indicator_text(measured)
    assert strip == tr("calibration.badge.short")
    assert len(strip) < 20

    assumed_strip = calibration_status.indicator_text(assumed)
    assert assumed_strip.endswith(tr("calibration.badge.assumed"))
    assert len(assumed_strip) < 40
    assert len(assumed_strip) < len(calibration_status.summary(assumed))
    assert "Масштаб" not in assumed_strip and "Scale" not in assumed_strip

    unavailable = calibration_status.indicator_unavailable_text()
    assert len(unavailable) < 30
    assert "Масштаб" not in unavailable and "Scale" not in unavailable
