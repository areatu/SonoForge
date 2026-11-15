"""Calibration wording and tone (#555, 6.2)."""

from __future__ import annotations

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

    assert len(lines) == 5
    assert any("изотроп" in line.lower() or "isotrop" in line.lower() for line in lines)


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
