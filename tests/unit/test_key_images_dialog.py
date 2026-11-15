"""The key-images dialog adds, refreshes and navigates by source identity (#561)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.key_images import KeyImageService, new_key_image
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.presentation.key_images import KeyImagesDialog

pytestmark = pytest.mark.gui


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


def _snapshot(instance: InstanceMetadata, frame: int = 2):
    return SimpleNamespace(instance=instance, current_frame_index=frame, contours=(), linear_measurements=())


def test_add_current_records_identity_and_source_stat(qtbot, tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    instance = _instance(clip)
    service = KeyImageService(tmp_path / "key-images")
    dialog = KeyImagesDialog(
        service=service,
        study_uid="1.2.3.4",
        instances={"1.2.3": instance},
        snapshot=_snapshot(instance),
        navigate=lambda _sop, _frame: None,
    )
    qtbot.addWidget(dialog)

    dialog.add_current()

    images = service.images("1.2.3.4")
    assert len(images) == 1
    assert images[0].sop_instance_uid == "1.2.3"
    assert images[0].frame_index == 2
    assert images[0].source_size == clip.stat().st_size
    assert dialog.status_text
    assert dialog.images == images


def test_open_navigates_by_sop_and_frame_not_list_position(qtbot, tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    instance = _instance(clip)
    service = KeyImageService(tmp_path / "key-images")
    image = new_key_image(
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        frame_index=7,
        frame_count=10,
        measurement_id="m-1",
        source_size=clip.stat().st_size,
        source_mtime_ns=clip.stat().st_mtime_ns,
    )
    service.add("1.2.3.4", image)
    opened: list[tuple[str, int]] = []
    dialog = KeyImagesDialog(
        service=service,
        study_uid="1.2.3.4",
        instances={"1.2.3": instance},
        snapshot=_snapshot(instance),
        navigate=lambda sop, frame: opened.append((sop, frame)),
    )
    qtbot.addWidget(dialog)

    dialog.open_selected()

    assert opened == [("1.2.3", 7)]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_changed_source_blocks_navigation_with_an_explicit_status(qtbot, tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    instance = _instance(clip)
    service = KeyImageService(tmp_path / "key-images")
    image = new_key_image(
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        frame_index=2,
        frame_count=10,
        measurement_id="",
        source_size=clip.stat().st_size,
        source_mtime_ns=clip.stat().st_mtime_ns,
    )
    service.add("1.2.3.4", image)
    clip.write_bytes(b"replaced-with-other-bytes-and-size")
    opened: list[tuple[str, int]] = []
    dialog = KeyImagesDialog(
        service=service,
        study_uid="1.2.3.4",
        instances={"1.2.3": instance},
        snapshot=_snapshot(instance),
        navigate=lambda sop, frame: opened.append((sop, frame)),
    )
    qtbot.addWidget(dialog)

    dialog.open_selected()

    assert opened == []
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog.status_text


def test_missing_source_is_explicit_and_does_not_navigate(qtbot, tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    instance = _instance(clip)
    service = KeyImageService(tmp_path / "key-images")
    image = new_key_image(
        sop_instance_uid="1.2.3",
        series_uid="1.2",
        frame_index=2,
        frame_count=10,
        measurement_id="",
        source_size=clip.stat().st_size,
        source_mtime_ns=clip.stat().st_mtime_ns,
    )
    service.add("1.2.3.4", image)
    clip.unlink()
    opened: list[tuple[str, int]] = []
    dialog = KeyImagesDialog(
        service=service,
        study_uid="1.2.3.4",
        instances={"1.2.3": instance},
        snapshot=_snapshot(instance),
        navigate=lambda sop, frame: opened.append((sop, frame)),
    )
    qtbot.addWidget(dialog)

    assert dialog.images
    dialog.open_selected()

    assert opened == []
    assert dialog.status_text


def test_delete_removes_only_the_selected_reference(qtbot, tmp_path) -> None:
    clip = tmp_path / "clip.dcm"
    clip.write_bytes(b"frames")
    instance = _instance(clip)
    service = KeyImageService(tmp_path / "key-images")
    for frame in (1, 2):
        service.add(
            "1.2.3.4",
            new_key_image(
                sop_instance_uid="1.2.3",
                series_uid="1.2",
                frame_index=frame,
                frame_count=10,
                measurement_id="",
                source_size=clip.stat().st_size,
                source_mtime_ns=clip.stat().st_mtime_ns,
            ),
        )
    dialog = KeyImagesDialog(
        service=service,
        study_uid="1.2.3.4",
        instances={"1.2.3": instance},
        snapshot=_snapshot(instance),
        navigate=lambda _sop, _frame: None,
    )
    qtbot.addWidget(dialog)

    dialog.delete_selected()

    assert len(service.images("1.2.3.4")) == 1
