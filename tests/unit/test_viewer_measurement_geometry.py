"""Measurements survive zoom, pan, flip and rotation (#555).

A caliper is committed in document coordinates, never in screen pixels.  The
view transform may move the image under the pointer, but the stored endpoints
and the physical length must not change.  These tests drive the real viewport
with Qt mouse clicks, apply each display transform through the public viewer
contract, and measure the same two image points.

Flip and rotation are not separate tools of the viewer (only zoom and pan are
exposed to the user); the tests exercise them as view transforms to prove the
screen-to-image mapping is the only thing they change.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF, Qt

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

#: Row spacing is 2.5x the column spacing: the two axes must not be averaged.
SPACING = (0.5, 0.2)
START = (70.0, 50.0)
END = (130.0, 110.0)
#: 60 px along each axis at SPACING: hypot(60 * 0.2, 60 * 0.5).
EXPECTED_MM = 32.31098884280702
EXPECTED_PX = 84.8528137423857


def _state() -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=1,
        pixel_spacing=SPACING,
        frame_time_ms=33.3,
        series_description="Geometry",
        path=Path("/tmp/geometry-acceptance.dcm"),
    )
    return ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=1,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _make_viewer(qtbot) -> ViewerWidget:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(700, 600)
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer.show_frame(np.zeros((160, 200), dtype=np.uint8))
    viewer.set_state(_state())
    return viewer


def _screen_point(viewer: ViewerWidget, point: tuple[float, float]):
    scene = viewer.contract.view.mapViewToScene(QPointF(*point))
    return viewer.contract.graphics.mapFromScene(scene)


def _identity(viewer: ViewerWidget) -> None:
    del viewer


def _zoom(viewer: ViewerWidget) -> None:
    # A 2x zoom around the centre of the 200x160 frame.
    viewer.contract.view.setRange(xRange=(50, 150), yRange=(30, 130), padding=0)


def _pan(viewer: ViewerWidget) -> None:
    # The same 2x scale, shifted by 20 px in both axes.
    viewer.contract.view.setRange(xRange=(30, 230), yRange=(20, 180), padding=0)


def _flip_vertical(viewer: ViewerWidget) -> None:
    # The image is drawn upside down: screen Y moves, document Y does not.
    viewer.contract.view.invertY(False)


def _rotate_quarter_turn(viewer: ViewerWidget) -> None:
    viewer.contract.graphics.rotate(90)


@pytest.mark.parametrize(
    "transform",
    [
        pytest.param(_identity, id="identity"),
        pytest.param(_zoom, id="zoom"),
        pytest.param(_pan, id="pan"),
        pytest.param(_flip_vertical, id="flip-vertical"),
        pytest.param(_rotate_quarter_turn, id="rotate-90"),
    ],
)
def test_a_caliper_keeps_its_document_endpoints_under_every_view_transform(
    qtbot, transform: Callable[[ViewerWidget], None]
) -> None:
    viewer = _make_viewer(qtbot)
    before = _screen_point(viewer, START)

    transform(viewer)
    qtbot.wait(10)
    after = _screen_point(viewer, START)
    if transform is not _identity:
        assert (after.x(), after.y()) != (before.x(), before.y()), "the transform really moved the screen image"

    viewport = viewer.contract.graphics.viewport()
    assert 0 <= after.x() < viewport.width()
    assert 0 <= after.y() < viewport.height()

    assert viewer.start_linear_caliper_for("LVEDD") is True
    for point in (START, END):
        scene = viewer.contract.view.mapViewToScene(QPointF(*point))
        qtbot.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=viewer.contract.graphics.mapFromScene(scene))

    stored = [
        measurement
        for measurement in viewer.contract.stored_linear_measurements.values()
        if measurement.label == "LVEDD"
    ]
    assert len(stored) == 1
    measurement = stored[0]
    assert measurement.start == pytest.approx(START, abs=0.3)
    assert measurement.end == pytest.approx(END, abs=0.3)
    assert measurement.pixel_length == pytest.approx(EXPECTED_PX, abs=0.4)
    assert measurement.millimeter_length == pytest.approx(EXPECTED_MM, abs=0.3)


def test_a_rotated_view_still_maps_the_pointer_back_to_image_coordinates(qtbot) -> None:
    viewer = _make_viewer(qtbot)
    viewer.contract.graphics.rotate(90)
    qtbot.wait(10)

    for point in (START, END):
        scene = viewer.contract.view.mapViewToScene(QPointF(*point))
        back = viewer.contract.view.mapSceneToView(scene)
        assert (back.x(), back.y()) == pytest.approx(point, abs=1e-6)


def test_a_flipped_view_still_maps_the_pointer_back_to_image_coordinates(qtbot) -> None:
    viewer = _make_viewer(qtbot)
    viewer.contract.view.invertY(False)
    qtbot.wait(10)

    for point in (START, END):
        scene = viewer.contract.view.mapViewToScene(QPointF(*point))
        back = viewer.contract.view.mapSceneToView(scene)
        assert (back.x(), back.y()) == pytest.approx(point, abs=1e-6)


def test_zoom_and_pan_change_the_viewport_not_the_frame(qtbot) -> None:
    viewer = _make_viewer(qtbot)
    frame_before = viewer.contract.current_frame
    before = viewer.contract.view.viewRange()

    _zoom(viewer)
    qtbot.wait(10)
    _pan(viewer)
    qtbot.wait(10)

    after = viewer.contract.view.viewRange()
    assert after != before
    assert viewer.contract.current_frame is frame_before
