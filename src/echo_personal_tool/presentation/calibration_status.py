"""Text for the calibration indicator shared by the chrome and properties.

The domain carries stable codes (``PixelSpacing``, ``assumed``, ``region``);
this module is the only place that turns them into words, so the badge of the
patient line and the properties panel cannot describe the same scale
differently (issue 555, 6.2).
"""

from __future__ import annotations

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.calibration import (
    CALIBRATION_AMBIGUOUS,
    CALIBRATION_CROSSES_REGION,
    CALIBRATION_FRAME_MISMATCH,
    CALIBRATION_NONE,
    CALIBRATION_REGION_REQUIRED,
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
)

SOURCE_KEYS: dict[str, str] = {
    "manual": "calibration.source.manual",
    "PixelSpacing": "calibration.source.pixel_spacing",
    "ImagerPixelSpacing": "calibration.source.imager_pixel_spacing",
    "NominalScannedPixelSpacing": "calibration.source.nominal_scanned_pixel_spacing",
    "SequenceOfUltrasoundRegions": "calibration.source.ultrasound_region",
    "SharedFunctionalGroupsSequence/PixelSpacing": "calibration.source.shared_functional_group",
    "PerFrameFunctionalGroupsSequence/PixelSpacing": "calibration.source.per_frame_functional_group",
    "saved_spacing": "calibration.source.saved_spacing",
}

CONFIDENCE_KEYS: dict[CalibrationConfidence, str] = {
    CalibrationConfidence.MEASURED: "calibration.confidence.measured",
    CalibrationConfidence.DERIVED: "calibration.confidence.derived",
    CalibrationConfidence.ASSUMED: "calibration.confidence.assumed",
    CalibrationConfidence.UNKNOWN: "calibration.confidence.unknown",
}

ASSUMPTION_KEYS: dict[str, str] = {
    "isotropic_manual": "calibration.assumption.isotropic",
    "imager_plane": "calibration.assumption.imager_plane",
    "nominal_scanned": "calibration.assumption.nominal_scanned",
    "seconds_as_length": "calibration.assumption.seconds_as_length",
}

REASON_KEYS: dict[str, str] = {
    CALIBRATION_NONE: "calibration.reason.missing",
    CALIBRATION_REGION_REQUIRED: "calibration.reason.region_required",
    CALIBRATION_CROSSES_REGION: "calibration.reason.crosses_region",
    CALIBRATION_AMBIGUOUS: "calibration.reason.ambiguous",
    CALIBRATION_FRAME_MISMATCH: "calibration.reason.frame_mismatch",
}


def source_name(source: str) -> str:
    """Localized source name; an unknown DICOM tag stays readable as itself."""
    key = SOURCE_KEYS.get(source)
    return tr(key) if key else source


def source_text(context: CalibrationContext) -> str:
    return source_name(context.source)


def confidence_text(confidence: CalibrationConfidence) -> str:
    return tr(CONFIDENCE_KEYS.get(confidence, "calibration.confidence.unknown"))


def scope_text(
    context: CalibrationContext,
    *,
    frame_index: int | None = None,
    region: CalibrationRegion | None = None,
) -> str:
    """Where the scale applies, in the terms the physician sees in the viewer."""
    if context.scope is CalibrationScope.FRAME:
        frame = context.frame_index if context.frame_index is not None else frame_index
        return tr("calibration.scope.frame", frame=0 if frame is None else frame + 1)
    if context.scope is CalibrationScope.REGION:
        bounds = context.region or region
        if bounds is None:
            return tr("calibration.scope.region")
        x0, x1, y0, y1 = bounds.as_tuple()
        return tr("calibration.scope.region_bounds", x0=x0, x1=x1, y0=y0, y1=y1)
    return tr("calibration.scope.instance")


def assumption_text(assumption: str | None) -> str:
    """Localized reason an ``ASSUMED`` scale is only an assumption.

    An unknown code stays readable as itself: the badge must never invent a
    meaning for a value the domain did not define.
    """
    if not assumption:
        return ""
    key = ASSUMPTION_KEYS.get(assumption)
    return tr(key) if key else assumption


def assumption_note(context: CalibrationContext) -> str:
    """Short visible suffix for an assumed scale, empty for a measured one.

    The badge tone is already amber, but colour alone is not a label: the
    persistent indicator says «предположение» in words as well (issue 555).
    """
    if not context.needs_assumption_note:
        return ""
    return tr("calibration.badge.assumed")


def summary(context: CalibrationContext) -> str:
    """One-line badge text: source, confidence, scope and an assumption tag."""
    return tr(
        "calibration.badge.available",
        source=source_text(context),
        confidence=confidence_text(context.confidence),
        scope=scope_text(context),
    ) + assumption_note(context)


def scale_line(context: CalibrationContext) -> str:
    """Badge text plus the concrete assumption reason, for a list of scales."""
    if context.assumption:
        return f"{summary(context)} · {assumption_text(context.assumption)}"
    if context.assumed_isotropic:
        return f"{summary(context)} · {tr('calibration.assumption.isotropic')}"
    return summary(context)


def details(context: CalibrationContext) -> str:
    """Hover text: the same facts plus revision and the isotropy assumption.

    The last paragraph explains what this line *is for* (2026-11-16 list,
    item 4): the physician kept asking why the orange «Масштаб: … —
    предполагаемая» line sits above the study and what it changes.
    """
    lines = [
        tr("calibration.detail.source", source=source_text(context)),
        tr("calibration.detail.confidence", confidence=confidence_text(context.confidence)),
        tr("calibration.detail.scope", scope=scope_text(context)),
        tr("calibration.detail.revision", revision=context.revision),
    ]
    if context.assumption:
        lines.append(tr("calibration.detail.assumption", assumption=assumption_text(context.assumption)))
    if context.assumed_isotropic:
        lines.append(tr("calibration.detail.assumed_isotropic"))
    if not context.is_calibrated:
        lines.append(tr("calibration.detail.unverified"))
    lines.append(tr("calibration.detail.role"))
    return "\n".join(lines)


def reason_text(reason: str) -> str:
    key = REASON_KEYS.get(reason)
    return tr(key) if key else reason


def unavailable_text(reason: str) -> str:
    """Badge text when no scale can be selected without measurement geometry."""
    if reason:
        return tr("calibration.badge.unavailable_reason", reason=reason_text(reason))
    return tr("calibration.badge.unavailable")


def indicator_text(context: CalibrationContext) -> str:
    """Compact patient-line badge: «Калибровка» with the state in words.

    The long «Масштаб: …» sentence ate the width of «Рост · Вес · ППТ» on the
    42 px patient row (2026-11-16 list, item 4 follow-up): the badge is now a
    narrow colour-coded strip.  Colour is still never the only label — the
    assumed scale keeps its «· предположение» suffix — and the full sentence
    (source, confidence, scope, revision) stays in the tooltip and the
    accessible name.
    """
    if context.needs_assumption_note:
        return tr("calibration.badge.short") + assumption_note(context)
    return tr("calibration.badge.short")


def indicator_unavailable_text() -> str:
    """Compact badge when no scale can be selected (tone: error)."""
    return tr("calibration.badge.short_unavailable")


def tone(context: CalibrationContext | None) -> str:
    """Semantic colour of a calibration: ok / warn / error.

    ``ASSUMED`` is deliberately amber, not green: a manual line or
    ``ImagerPixelSpacing`` is usable but is not a measured patient-plane
    calibration (issue 555).
    """
    if context is None:
        return "error"
    if context.confidence in (CalibrationConfidence.MEASURED, CalibrationConfidence.DERIVED):
        return "ok"
    if context.confidence is CalibrationConfidence.ASSUMED:
        return "warn"
    return "error"


def tone_key(context: CalibrationContext | None) -> str:
    return "calibration.tone." + tone(context)
