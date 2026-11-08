"""Prepared teaching contours are source-bound, frame-exact, and display-only."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from echo_personal_tool.application.prepared_anatomy import (
    AnnotationError,
    Shape,
    bind_to_source,
    create_annotation,
    load_annotation,
    parse_annotation,
    replace_shape,
    save_annotation,
)


def _manifest(data: bytes) -> dict:
    return {
        "version": 1,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "width": 32,
        "height": 24,
        "view": "A4C",
        "position": "left_lateral",
        "frames": {
            "0": [{"id": "lv", "points": [[0.1, 0.2], [0.8, 0.2], [0.5, 0.9]]}],
            "2": [{"id": "la", "points": [[0, 0], [1, 0], [0, 1]]}],
        },
    }


def test_binding_requires_exact_file_digest_and_display_size(tmp_path):
    clip = tmp_path / "synthetic.bin"
    clip.write_bytes(b"synthetic pixels only")
    annotation = parse_annotation(_manifest(clip.read_bytes()))
    identity = bind_to_source(annotation, clip, (24, 32))
    stat = clip.stat()
    assert identity == (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    with pytest.raises(AnnotationError, match="size"):
        bind_to_source(annotation, clip, (32, 24))
    clip.write_bytes(b"synthetic pixels changed")
    with pytest.raises(AnnotationError, match="content"):
        bind_to_source(annotation, clip, (24, 32))
    with pytest.raises(AnnotationError, match="size"):
        bind_to_source(annotation, clip, None)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(source_sha256="z" * 64),
        lambda raw: raw.update(patient="Do not allow PHI"),
        lambda raw: raw.update(view="unknown"),
        lambda raw: raw.update(width=True),
        lambda raw: raw.update(frames={"01": []}),
        lambda raw: raw.update(frames={"-1": []}),
        lambda raw: raw.update(frames={"0": [{"id": "lv", "points": [[0, 0], [1, 0], [float("nan"), 1]]}]}),
        lambda raw: raw.update(frames={"0": [{"id": "lv", "points": [[0, 0], [1, 0], [1.1, 1]]}]}),
        lambda raw: raw.update(frames={"0": [{"id": "lv", "points": [[0, 0], [1, 0], [1, 1]]}] * 2}),
    ],
)
def test_rejects_unsafe_or_ambiguous_metadata(mutate):
    raw = _manifest(b"synthetic")
    mutate(raw)
    with pytest.raises(AnnotationError):
        parse_annotation(raw)


def test_sidecar_is_bounded_and_not_interpolated(tmp_path):
    import json

    raw = _manifest(b"synthetic")
    sidecar = tmp_path / "synthetic.json"
    sidecar.write_text(json.dumps(raw), encoding="utf-8")
    annotation = load_annotation(sidecar)
    assert annotation.frames.get(1) is None
    assert annotation.frames[0][0].structure == "lv"
    assert annotation.frames[2][0].structure == "la"
    with pytest.raises(AnnotationError, match="size"):
        bind_to_source(replace(annotation, height=25), tmp_path / "missing", (24, 32))
    sidecar.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(AnnotationError, match="large"):
        load_annotation(sidecar)


def test_authoring_stays_separate_and_roundtrips_sidecar(tmp_path):
    clip = tmp_path / "synthetic.bin"
    clip.write_bytes(b"synthetic training clip")
    draft, identity = create_annotation(clip, (24, 32), "A4C", "left_lateral")
    assert identity[2] == clip.stat().st_size
    assert draft.frames == {}
    shape = Shape("lv", ((0.1, 0.1), (0.8, 0.1), (0.5, 0.8)))
    draft = replace_shape(draft, 0, shape, "lv")
    draft = replace_shape(draft, 2, Shape("la", shape.points), "la")
    assert 1 not in draft.frames
    draft = replace_shape(draft, 0, None, "lv")
    assert 0 not in draft.frames and draft.frames[2][0].structure == "la"
    sidecar = tmp_path / "separate.json"
    save_annotation(draft, sidecar)
    assert load_annotation(sidecar) == draft
    with pytest.raises(AnnotationError):
        replace_shape(draft, 3, shape, "ra")
    assert clip.read_bytes() == b"synthetic training clip"


@pytest.mark.gui
def test_freehand_tool_emits_visual_shape_without_measurement(qapp):
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

    from echo_personal_tool.presentation.prepared_anatomy_draw import PreparedDrawTool

    class Scene(QGraphicsScene):
        def mapSceneToView(self, position):
            return position

    viewer = QWidget()
    viewer._view = Scene(viewer)
    viewer._graphics = QGraphicsView(viewer)
    viewer.frame_shape = (24, 32)
    received = []
    tool = PreparedDrawTool(viewer, received.append)
    tool.arm("lv")
    for index, coords in enumerate(((4, 4), (24, 4), (14, 19))):
        event = SimpleNamespace(
            button=lambda: Qt.MouseButton.LeftButton,
            scenePos=lambda xy=coords: QPointF(*xy),
            isStart=lambda i=index: i == 0,
            isFinish=lambda i=index: i == 2,
            accept=lambda: None,
        )
        assert tool.drag(event)
    assert received == [Shape("lv", ((4 / 31, 4 / 23), (24 / 31, 4 / 23), (14 / 31, 19 / 23)))]
    assert tool.structure is None
    tool.dispose()
    tool.cancel()
    tool.dispose()
    viewer.close()


@pytest.mark.gui
def test_layer_draws_only_explicit_frames_and_clears(qapp):
    from PySide6.QtWidgets import QGraphicsScene, QWidget

    from echo_personal_tool.presentation.prepared_anatomy_layer import PreparedAnatomyLayer

    viewer = QWidget()
    viewer.resize(400, 400)
    viewer._view = QGraphicsScene(viewer)
    viewer._graphics = QWidget(viewer)
    layer = PreparedAnatomyLayer(viewer)
    layer.annotation = parse_annotation(_manifest(b"synthetic"))
    layer.render(0, (24, 32))
    assert len(viewer._view.items()) == 2  # path and label, no measurement object
    assert layer._badge.isVisibleTo(viewer)
    layer.render(1, (24, 32))
    assert not viewer._view.items()
    assert "2" in layer._badge.text()  # missing frame, 1-based badge
    layer.render(2, (24, 32))
    assert len(viewer._view.items()) == 2
    layer.enabled = False
    layer.render(2, (24, 32))
    assert not viewer._view.items()
    assert layer._badge.isHidden()
    layer.dispose()
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    layer.clear()
    layer.render(0, (24, 32))
    layer.dispose()  # idempotent even after the badge C++ object is gone
    viewer.close()
