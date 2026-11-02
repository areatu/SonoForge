"""Pure grouping helpers for the clip gallery (no Qt dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.services.instance_sort import sort_instances_by

MODE_GROUP_ORDER = ("2d", "doppler", "m_mode")


@dataclass(frozen=True)
class ThumbnailModeGroup:
    """Clips for one imaging mode, with their ordered study-group indexes."""

    mode: str
    instances: tuple[tuple[InstanceMetadata, int], ...]


def canonical_clip_mode(mode: str | None) -> str:
    """Return a supported clip-group key; unknown modes safely fall back to 2D."""
    normalized = str(mode or "2d").strip().casefold()
    return normalized if normalized in MODE_GROUP_ORDER else "2d"


def group_thumbnail_instances(
    studies: list[StudyMetadata],
    sort_mode: str = "created",
) -> tuple[ThumbnailModeGroup, ...]:
    """Group clips by imaging mode while retaining study and within-study order.

    Studies are ordered newest first, as in the former gallery. Each mode group
    then keeps those studies contiguous and applies the selected clip sort mode
    within each study. The returned study index is stable for letter markers.
    """
    grouped_studies: list[tuple[StudyMetadata, list[InstanceMetadata]]] = []
    for study in studies:
        instances = [instance for series in study.series for instance in series.instances]
        if instances:
            grouped_studies.append((study, instances))
    grouped_studies.sort(key=lambda item: item[0].study_datetime or datetime.min, reverse=True)

    grouped_instances: dict[str, list[tuple[InstanceMetadata, int]]] = {mode: [] for mode in MODE_GROUP_ORDER}
    for study_index, (_study, study_instances) in enumerate(grouped_studies):
        for instance in sort_instances_by(study_instances, sort_mode):
            mode = canonical_clip_mode(instance.clip_mode)
            grouped_instances[mode].append((instance, study_index))

    return tuple(
        ThumbnailModeGroup(mode, tuple(grouped_instances[mode])) for mode in MODE_GROUP_ORDER if grouped_instances[mode]
    )


def ordered_thumbnail_instances(
    studies: list[StudyMetadata],
    sort_mode: str = "created",
) -> tuple[tuple[InstanceMetadata, int], ...]:
    """Newest studies first, clips chronological across all imaging modes.

    Study indexes keep the gallery's letter/colour markers stable. In contrast
    to mode buckets, changing a mode filter never changes relative clip order.
    """
    ordered_studies = sorted(studies, key=lambda study: study.study_datetime or datetime.min, reverse=True)
    result: list[tuple[InstanceMetadata, int]] = []
    study_index = 0
    for study in ordered_studies:
        instances = [instance for series in study.series for instance in series.instances]
        if not instances:
            continue
        result.extend((instance, study_index) for instance in sort_instances_by(instances, sort_mode))
        study_index += 1
    return tuple(result)
