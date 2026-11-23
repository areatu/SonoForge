"""Stress-echo report rows (plan А.11, issue #649) — the protocol projection.

Kept out of ``report_builder`` (which sits at the module-size limit): these
rows are honest no-norm values — WMSI carries no reference range, the verdict
is the domain's own code — so the projection builds :class:`ReportValue`
directly from the assessment instead of routing through the norm-aware
helpers.
"""

from __future__ import annotations

from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.domain.models.stress_echo import StressEchoAssessment
from echo_personal_tool.domain.services.report_document import ReportValue
from echo_personal_tool.domain.translation import tr


def stress_echo_report_values(assessment: StressEchoAssessment, *, group: str) -> tuple[ReportValue, ...]:
    """The protocol rows of one assessment, labels already translated.

    Numeric rows only for the stages that have scored segments (WMSI rest /
    stress and ΔWMSI); the worsened-segment count and the verdict are text
    rows and always appear once anything was scored — a half comparison
    reports «недостаточно данных», never a fabricated conclusion.
    """
    if assessment.is_empty():
        return ()
    values: list[ReportValue] = []
    for label_key, measurement_id, value in (
        ("stress_echo.wmsi_rest_row", "lv.wmsi_rest", assessment.wmsi_rest()),
        ("stress_echo.wmsi_stress_row", "lv.wmsi_stress", assessment.wmsi_stress()),
        ("stress_echo.wmsi_delta_row", "lv.wmsi_delta", assessment.wmsi_delta()),
    ):
        if value is None:
            continue
        values.append(
            ReportValue(
                label=tr(label_key),
                value=format_measurement(measurement_id, value, ""),
                parameter_id=measurement_id,
                unit="",
                norm="",
                pathological=False,
                norm_grade="",
                group=group,
            )
        )
    values.append(
        ReportValue(
            label=tr("stress_echo.worsened_row"),
            value=str(len(assessment.worsened_segments())),
            parameter_id="lv.wmsi",
            unit="",
            norm="",
            pathological=False,
            norm_grade="",
            group=group,
        )
    )
    values.append(
        ReportValue(
            label=tr("stress_echo.verdict_row"),
            value=tr(f"stress_echo.verdict_{assessment.verdict_code()}"),
            parameter_id="lv.wmsi",
            unit="",
            norm="",
            pathological=False,
            norm_grade="",
            group=group,
        )
    )
    return tuple(values)
