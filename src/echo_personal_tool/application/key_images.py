"""Study key images: durable references and their current source status (#561).

The UI asks one question — is this reference still usable?  The answer is
derived from the open study and the file's stat identity, never from the order
of the thumbnail gallery.  Persistence is a tiny per-study JSON document in
``infrastructure.key_image_repository``; pixels stay in the frame cache and
the source file.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.key_image import (
    KEY_IMAGE_AVAILABLE,
    KEY_IMAGE_CHANGED,
    KEY_IMAGE_MISSING,
    KeyImage,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.infrastructure.key_image_repository import KeyImageRepository

_UTC = timezone.utc  # noqa: UP017 - datetime.UTC migration deferred (ruff target py310)


def new_key_image(
    *,
    sop_instance_uid: str,
    series_uid: str,
    frame_index: int,
    frame_count: int,
    measurement_id: str,
    source_size: int,
    source_mtime_ns: int,
) -> KeyImage:
    """Build an entry with a stable id and UTC creation time."""
    return KeyImage(
        bookmark_id=uuid.uuid4().hex,
        sop_instance_uid=sop_instance_uid,
        series_uid=series_uid,
        frame_index=int(frame_index),
        frame_count=int(frame_count),
        measurement_id=measurement_id,
        source_size=int(source_size),
        source_mtime_ns=int(source_mtime_ns),
        created_at=datetime.now(_UTC).isoformat(timespec="seconds"),
    )


def measurement_id_at(snapshot: ViewerState, sop_instance_uid: str, frame_index: int) -> str:
    """The measurement of this clip/frame, when exactly one is unambiguous.

    A bookmark can name a measurement only if the frame carries one candidate;
    with two calipers on one still the entry stays frame-scoped rather than
    silently choosing one of them.
    """
    items: tuple[Contour | LinearMeasurement, ...] = (*snapshot.contours, *snapshot.linear_measurements)
    ids = {
        item.measurement_id
        for item in items
        if item.measurement_id and item.sop_instance_uid == sop_instance_uid and item.frame_index == frame_index
    }
    return next(iter(ids)) if len(ids) == 1 else ""


def key_image_status(image: KeyImage, instances: Mapping[str, InstanceMetadata]) -> str:
    """``available`` / ``missing`` / ``changed`` for the open study.

    A copied study at another path stays available because the identity is the
    SOP plus the recorded file stat, not a persisted path.  A replaced file of
    a different size or mtime, a shorter clip or a stale SOP is not followed.
    """
    instance = instances.get(image.sop_instance_uid)
    if instance is None or instance.path is None:
        return KEY_IMAGE_MISSING
    if instance.number_of_frames != image.frame_count:
        return KEY_IMAGE_CHANGED
    try:
        stat = instance.path.stat()
    except OSError:
        return KEY_IMAGE_MISSING
    if (stat.st_size, stat.st_mtime_ns) != (image.source_size, image.source_mtime_ns):
        return KEY_IMAGE_CHANGED
    return KEY_IMAGE_AVAILABLE


class KeyImageService:
    """Per-study key images; every mutation is flushed before it returns."""

    def __init__(self, root: Path) -> None:
        self._repository = KeyImageRepository(root)

    def images(self, study_uid: str) -> tuple[KeyImage, ...]:
        return self._repository.load(study_uid)

    def add(self, study_uid: str, image: KeyImage) -> tuple[KeyImage, ...]:
        """Add an entry, replacing the same clip/frame instead of duplicating it."""
        previous = self.images(study_uid)
        same = next(
            (
                item
                for item in previous
                if item.sop_instance_uid == image.sop_instance_uid and item.frame_index == image.frame_index
            ),
            None,
        )
        if same is not None:
            image = KeyImage(
                bookmark_id=same.bookmark_id,
                sop_instance_uid=image.sop_instance_uid,
                series_uid=image.series_uid,
                frame_index=image.frame_index,
                frame_count=image.frame_count,
                measurement_id=image.measurement_id,
                source_size=image.source_size,
                source_mtime_ns=image.source_mtime_ns,
                created_at=same.created_at,
            )
        images = tuple(item for item in previous if item is not same) + (image,)
        self._repository.save(study_uid, images)
        return images

    def remove(self, study_uid: str, bookmark_id: str) -> tuple[KeyImage, ...]:
        images = tuple(item for item in self.images(study_uid) if item.bookmark_id != bookmark_id)
        self._repository.save(study_uid, images)
        return images
