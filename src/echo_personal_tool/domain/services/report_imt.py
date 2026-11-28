"""Explicitly accepted structured IMT results, never synthetic linear calipers."""

from __future__ import annotations

from echo_personal_tool.domain.models.imt import ImtDraft
from echo_personal_tool.domain.models.value_origin import measurement_origin
from echo_personal_tool.domain.services.report_document import ReportValue
from echo_personal_tool.domain.services.report_groups import GROUP_PRECEREBRAL
from echo_personal_tool.domain.translation import tr


def imt_report_values(drafts: tuple[ImtDraft, ...]) -> tuple[ReportValue, ...]:
    """Keep each accepted acquisition and its own scale/provenance in mm.

    The live viewer's scale is irrelevant to a historical accepted record.
    Research labels and absence of an automatic normal/abnormal verdict are
    intentional. Repeats are not silently averaged or replaced by a maximum.
    """
    rows: list[ReportValue] = []
    for draft in drafts:
        if not draft.confirmed:
            continue
        source = draft.source
        origin = measurement_origin(
            draft.method,
            measurement_id=f"imt:{source.instance_uid}:{source.frame_index}:{source.side}",
            revision=draft.revision,
            sop_instance_uid=source.instance_uid,
            frame_index=source.frame_index,
        )
        for statistic, value in (("mean", draft.mean_mm), ("minimum", draft.min_mm), ("maximum", draft.max_mm)):
            rows.append(
                ReportValue(
                    label=tr(
                        "imt.report_label",
                        side=source.side,
                        statistic=tr(f"imt.{statistic}"),
                        frame=source.frame_index + 1,
                    ),
                    value=f"{value:.3f}",
                    unit="mm",
                    group=GROUP_PRECEREBRAL,
                    parameter_id=source.measurement_key
                    if statistic == "mean"
                    else f"{source.measurement_key}.{statistic}",
                    origin=origin,
                )
            )
    return tuple(rows)
