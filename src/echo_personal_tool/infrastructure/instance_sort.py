"""Natural sort keys for instances/series in study browser and thumbnails."""

from __future__ import annotations

import re

from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata

_NATURAL_SPLIT = re.compile(r"(\d+)")


def natural_sort_key(text: str) -> tuple:
    """Sort ``001``, ``002``, ``010`` in numeric order (not lexicographic)."""
    parts: list[tuple[int, int | str]] = []
    for piece in _NATURAL_SPLIT.split(text):
        if not piece:
            continue
        if piece.isdigit():
            parts.append((0, int(piece)))
        else:
            parts.append((1, piece.casefold()))
    return tuple(parts)


def instance_filename_sort_key(instance: InstanceMetadata) -> tuple:
    """Primary thumbnail/browser order: filename, then SOP UID."""
    if instance.path is not None:
        return (0, natural_sort_key(instance.path.name))
    return (1, instance.sop_instance_uid)


def series_filename_sort_key(series: SeriesMetadata) -> tuple:
    """Order series by first instance filename (flat export folders)."""
    if series.instances:
        return instance_filename_sort_key(series.instances[0])
    return (2, series.modality, series.description or series.series_uid)


def sort_instances(instances: list[InstanceMetadata]) -> tuple[InstanceMetadata, ...]:
    return tuple(sorted(instances, key=instance_filename_sort_key))


def sort_series_list(series_list: list[SeriesMetadata]) -> list[SeriesMetadata]:
    for index, series in enumerate(series_list):
        sorted_instances = sort_instances(list(series.instances))
        if sorted_instances != series.instances:
            series_list[index] = SeriesMetadata(
                series_uid=series.series_uid,
                study_uid=series.study_uid,
                modality=series.modality,
                description=series.description,
                instances=sorted_instances,
            )
    series_list.sort(key=series_filename_sort_key)
    return series_list
