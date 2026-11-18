"""Scale resolution for a single contour or point set (#547).

The active viewer has one effective pixel spacing, but a study may contain
clips, frames and panels with different scales.  Consumers must ask for the
scale *under the measurement* instead of borrowing the active clip's value;
an ambiguous scoped scale is a refusal, never a fallback.

This module stays free of Qt and of ``AppController`` state: callers pass the
viewer snapshot, the session and a lookup for instance metadata.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from typing import Any

from echo_personal_tool.domain.models import Contour, InstanceMetadata, ViewerState
from echo_personal_tool.domain.models.calibration import (
    CALIBRATION_AMBIGUOUS,
    CALIBRATION_CROSSES_REGION,
    CALIBRATION_FRAME_MISMATCH,
    CALIBRATION_MIXED,
    CALIBRATION_REGION_REQUIRED,
    select_calibration_for_points,
)

Spacing = tuple[float, float]

#: A selection with one of these reasons is a refusal, not a missing scale:
#: borrowing the active/instance scale would silently measure another panel.
_AMBIGUOUS_REASONS = frozenset(
    {
        CALIBRATION_AMBIGUOUS,
        CALIBRATION_CROSSES_REGION,
        CALIBRATION_FRAME_MISMATCH,
        CALIBRATION_MIXED,
        CALIBRATION_REGION_REQUIRED,
    }
)


def spacing_for_points(state: ViewerState | None, points: Any) -> tuple[Spacing | None, bool]:
    """Panel scale under *points*, or ``(None, False)`` when unavailable.

    ``ViewerState.calibration_for_points`` also refuses a geometry that spans
    panels, returning ``(None, True)`` semantics through a missing context; the
    second element here is ``True`` only for a usable calibrated scale.
    """
    if state is None:
        return (1.0, 1.0), False
    selection = state.calibration_for_points(points)
    context = selection.context
    if context is not None and context.spacing is not None:
        row, col = context.spacing
        if math.isfinite(row) and math.isfinite(col) and row > 0.0 and col > 0.0:
            return context.spacing, True
    if selection.reason in _AMBIGUOUS_REASONS:
        return None, True
    # The legacy uncalibrated path: geometry still runs on pixel coordinates
    # and the formatter prints px/px²/px³.
    return (1.0, 1.0), False


def resolve_contour_spacing(
    contour: Contour,
    *,
    state: ViewerState,
    session: Any | None,
    instance_for: Callable[[str], InstanceMetadata | None],
    sources: Mapping[str, Mapping[str, Any]],
) -> tuple[Spacing | None, bool]:
    """Scale under *contour*, or ``(None, True)`` when it is ambiguous.

    Resolution uses the contour's own instance, frame and bbox.  ``(None, True)``
    means "would be physical, but the scoped scale is ambiguous" — callers must
    skip the contour instead of measuring it with a neighbouring scale.
    """
    uid = contour.sop_instance_uid or (state.instance.sop_instance_uid if state.instance is not None else "")
    if session is not None and uid:
        manual = dict(session.calibration_by_instance).get(uid)
        if manual is not None:
            return manual.spacing, manual.spacing is not None
    instance = instance_for(uid) if uid else state.instance
    contexts = instance.calibrations if instance is not None else ()
    if contexts:
        selection = select_calibration_for_points(
            contexts,
            contour.points,
            frame_index=contour.frame_index if contour.frame_index is not None else state.current_frame_index,
        )
        if selection.context is not None:
            return selection.context.spacing, selection.context.spacing is not None
        if selection.reason in _AMBIGUOUS_REASONS:
            return None, True
        # ``calibration_missing``: the geometry is outside every panel, so the
        # instance-level fallback below is safe.
    if instance is not None:
        if instance.calibration is not None:
            return instance.calibration.spacing, instance.calibration.spacing is not None
        if instance.pixel_spacing is not None:
            return instance.pixel_spacing, True
    descriptor = sources.get(uid, {})
    spacing = descriptor.get("spacing")
    if spacing:
        return (float(spacing[0]), float(spacing[1])), True
    return None, False


def contour_spacing_resolver(
    state: ViewerState,
    session: Any | None,
    instance_for: Callable[[str], InstanceMetadata | None],
    sources: Mapping[str, Mapping[str, Any]],
) -> Callable[[Contour], tuple[Spacing | None, bool]]:
    """Bind the resolution context once for a batch of contours."""
    return partial(
        resolve_contour_spacing,
        state=state,
        session=session,
        instance_for=instance_for,
        sources=sources,
    )


def express_contours_on_grid(
    items: Sequence[Contour],
    pixel_spacing: Spacing | None,
    spacing_for_contour: Callable[[Contour], tuple[Spacing | None, bool]],
) -> tuple[Contour, ...]:
    """Express every contour on the active pixel grid, never on a borrowed scale.

    A contour may come from another clip of the study, and that clip may have
    per-frame/per-panel calibrations.  Its own scale is resolved by frame and
    geometry; when that is ambiguous the contour is dropped from the physical
    calculation instead of being measured with the active clip's scale (#547).
    """
    output: list[Contour] = []
    for contour in items:
        source_spacing, source_calibrated = spacing_for_contour(contour)
        if source_calibrated and source_spacing is None:
            continue
        if source_spacing is None or pixel_spacing is None:
            # Legacy contour with no scale at all: keep it in its pixel space.
            # A scoped-but-ambiguous contour was already dropped above.
            output.append(contour)
            continue
        row, col = source_spacing[0] / pixel_spacing[0], source_spacing[1] / pixel_spacing[1]
        output.append(_rescale_contour(contour, row, col))
    return tuple(output)


def _rescale_contour(contour: Contour, row: float, col: float) -> Contour:
    # An open Simpson contour includes its annulus chord and apex. Scaling
    # only the arc measures a different cavity when choosing a different clip.
    def point(p: tuple[float, float]) -> tuple[float, float]:
        return p[0] * col, p[1] * row

    annulus = contour.mitral_annulus
    return replace(
        contour,
        points=[point(p) for p in contour.points],
        mitral_annulus=(point(annulus[0]), point(annulus[1])) if annulus is not None else None,
        apex_landmark=point(contour.apex_landmark) if contour.apex_landmark is not None else None,
    )
