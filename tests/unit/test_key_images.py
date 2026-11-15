"""Key-image references, persistence and source status (issue #561)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.key_images import (
    KeyImageService,
    key_image_status,
    measurement_id_at,
    new_key_image,
)
from echo_personal_tool.domain.models.key_image import (
    KEY_IMAGE_AVAILABLE,
    KEY_IMAGE_CHANGED,
    KEY_IMAGE_MISSING,
    KeyImage,
)
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.infrastructure.key_image_repository import (
    KeyImageRepository,
    KeyImageStorageError,
)
from echo_personal_tool.infrastructure.measurement_codec import study_key


def _image(path: Path, *, frame_index: int = 2, frame_count: int = 10, bookmark_id: str = "a" * 32) -> KeyImage:
    stat = path.stat()
    return KeyImage(
        bookmark_id=bookmark_id,
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        frame_index=frame_index,
        frame_count=frame_count,
        measurement_id="measurement-1",
        source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        created_at="2026-11-13T10:00:00+00:00",
    )


def _instance(path: Path, *, frames: int = 10) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=path,
    )


def test_repository_roundtrip_without_paths(tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    image = _image(clip)
    repository = KeyImageRepository(tmp_path / "key-images")

    repository.save("1.2.3.4", (image,))

    assert repository.load("1.2.3.4") == (image,)
    payload = next((tmp_path / "key-images").glob("*.json")).read_text(encoding="utf-8")
    assert str(clip) not in payload
    assert '"path"' not in payload


def test_repository_rejects_unknown_document_and_unsafe_frame(tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"x")
    repository = KeyImageRepository(tmp_path / "key-images")
    repository.save("1.2.3", (_image(clip),))
    record = next((tmp_path / "key-images").glob("*.json"))
    record.write_text('{"format": "other"}', encoding="utf-8")

    with pytest.raises(KeyImageStorageError):
        repository.load("1.2.3")
    with pytest.raises(KeyImageStorageError):
        repository.save("1.2.3", (_image_for_payload(frame_index=5, frame_count=5),))


def _image_for_payload(*, frame_index: int, frame_count: int) -> KeyImage:
    return KeyImage(
        bookmark_id="b" * 32,
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        frame_index=frame_index,
        frame_count=frame_count,
    )


def test_service_persists_deduplicates_and_removes(tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    service = KeyImageService(tmp_path / "key-images")
    first = _image(clip, bookmark_id="c" * 32)

    service.add("1.2.3.4", first)
    refreshed = KeyImageService(tmp_path / "key-images")
    assert refreshed.images("1.2.3.4") == (first,)

    replacement = _image(clip, bookmark_id="d" * 32)
    images = refreshed.add("1.2.3.4", replacement)
    assert len(images) == 1
    assert images[0].bookmark_id == first.bookmark_id, "same frame keeps the stable identity"

    assert refreshed.remove("1.2.3.4", first.bookmark_id) == ()
    assert KeyImageService(tmp_path / "key-images").images("1.2.3.4") == ()


def test_status_distinguishes_missing_changed_and_available(tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    image = _image(clip)
    instance = _instance(clip)

    assert key_image_status(image, {"1.2.3": instance}) == KEY_IMAGE_AVAILABLE
    assert key_image_status(image, {}) == KEY_IMAGE_MISSING
    assert key_image_status(image, {"1.2.3": _instance(clip, frames=11)}) == KEY_IMAGE_CHANGED

    stat = clip.stat()
    os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))
    assert key_image_status(image, {"1.2.3": instance}) == KEY_IMAGE_CHANGED

    clip.unlink()
    assert key_image_status(image, {"1.2.3": instance}) == KEY_IMAGE_MISSING


def test_measurement_id_is_recorded_only_when_unambiguous() -> None:
    one = SimpleNamespace(measurement_id="m-1", sop_instance_uid="1.2.3", frame_index=4)
    other = SimpleNamespace(measurement_id="m-2", sop_instance_uid="1.2.3", frame_index=4)
    snapshot = SimpleNamespace(contours=(one,), linear_measurements=(other,))

    assert measurement_id_at(snapshot, "1.2.3", 4) == ""

    snapshot = SimpleNamespace(contours=(one,), linear_measurements=())
    assert measurement_id_at(snapshot, "1.2.3", 4) == "m-1"
    assert measurement_id_at(snapshot, "1.2.3", 5) == ""


def test_new_key_image_has_a_stable_id_and_utc_timestamp(tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"x")
    image = new_key_image(
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        frame_index=1,
        frame_count=5,
        measurement_id="",
        source_size=clip.stat().st_size,
        source_mtime_ns=clip.stat().st_mtime_ns,
    )
    assert len(image.bookmark_id) == 32
    assert image.created_at.endswith("+00:00")


def test_repository_refuses_a_linked_root_or_record(tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"x")
    real = tmp_path / "real"
    real.mkdir()
    root = tmp_path / "key-images"
    root.symlink_to(real, target_is_directory=True)
    repository = KeyImageRepository(root)

    with pytest.raises(KeyImageStorageError, match="unsafe_path"):
        repository.save("1.2.3", (_image(clip),))

    record = tmp_path / "record.json"
    record.write_text("{}", encoding="utf-8")
    target = real / (study_key("1.2.3") + ".json")
    target.symlink_to(record)
    with pytest.raises(KeyImageStorageError, match="unsafe_path"):
        KeyImageRepository(real).load("1.2.3")


def test_repository_is_bounded(tmp_path) -> None:
    repository = KeyImageRepository(tmp_path / "key-images", max_bytes=10)
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"x")
    with pytest.raises(KeyImageStorageError):
        repository.save("1.2.3", (_image(clip),))
