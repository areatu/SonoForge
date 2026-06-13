"""Contour domain model and point handling tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from echo_personal_tool.domain.models import Contour, InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def test_resolve_contour_phase_defaults_to_ed_without_markers(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.set_state(
        ViewerState(
            instance=None,
            current_frame_index=3,
            total_frames=10,
            frame_time_ms=33.3,
            is_playing=False,
        )
    )
    assert viewer._resolve_contour_phase() == "ED"


def test_contour_drag_updates_numeric_overlay_on_current_frame(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(
        ViewerState(
            instance=_sample_instance(),
            current_frame_index=0,
            total_frames=10,
            frame_time_ms=33.3,
            is_playing=False,
        )
    )

    viewer.start_contour(phase="ED", view="A4C")
    viewer.handle_contour_click((10.0, 40.0))
    viewer.handle_contour_click((50.0, 40.0))
    viewer.handle_contour_click((30.0, 10.0))

    viewer._finalize_contour_point_drag(0, 16, 32.0, 8.0)

    overlay = "\n".join(viewer._frame_overlay_lines)
    assert "A4C ED" in overlay
    assert "Длина:" in overlay
    assert "Объём:" in overlay


def test_contour_dataclass_defaults() -> None:
    contour = Contour(phase="ED")

    assert contour.phase == "ED"
    assert contour.view == "A4C"
    assert contour.points == []
    assert contour.source == "manual"
    assert contour.num_nodes == 32


def test_contour_open_arc_helpers() -> None:
    annulus = ((0.0, 0.0), (10.0, 0.0))
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=[(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)],
    )
    assert contour.is_open_arc is True
    closed = contour.closed_polygon_points()
    assert closed[0] == (0.0, 0.0)
    assert closed[-1] == (0.0, 0.0)
    assert closed[-2] == (10.0, 0.0)
    assert len(closed) == 5


def test_model_contour_syncs_before_completed_signal(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    synced: list[list[Contour]] = []
    viewer.contours_changed.connect(synced.append)

    viewer.start_model_contour(phase="ED")
    viewer.handle_contour_click((10.0, 40.0))
    viewer.handle_contour_click((50.0, 40.0))
    viewer.handle_contour_click((30.0, 10.0))

    assert synced
    assert len(synced[-1]) == 1
    assert synced[-1][0].source == "model"
    assert not viewer.is_contour_mode_active


def test_viewer_widget_model_contour_finish(qtbot) -> None:
    from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    completed: list[Contour] = []
    viewer.contour_completed.connect(completed.append)

    viewer.start_model_contour()
    assert viewer.handle_contour_click((10.0, 40.0))
    assert viewer.handle_contour_click((50.0, 40.0))
    assert viewer.handle_contour_click((30.0, 10.0))

    assert not viewer.is_contour_mode_active
    contour = completed[0]
    assert contour.source == "model"
    assert contour.is_open_arc
    assert len(contour.points) == DEFAULT_NODE_COUNT
    assert viewer._contour_items[0].opts["pen"].color().name() == "#4caf50"


def test_contour_legacy_closed_polygon() -> None:
    contour = Contour(phase="ED", points=[(0, 0), (1, 0), (1, 1)])
    assert contour.is_open_arc is False
    assert contour.closed_polygon_points() == [(0, 0), (1, 0), (1, 1)]


def test_viewer_widget_open_arc_finish(qtbot) -> None:
    from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    completed: list[Contour] = []
    viewer.contour_completed.connect(completed.append)

    viewer.start_contour(phase="ED")
    viewer.handle_contour_click((10.0, 40.0))
    viewer.handle_contour_click((50.0, 40.0))
    assert viewer.handle_contour_click((30.0, 10.0))

    assert not viewer.is_contour_mode_active
    contour = completed[0]
    assert contour.is_open_arc
    assert contour.mitral_annulus is not None
    assert len(contour.points) == DEFAULT_NODE_COUNT
    assert viewer.contours()[-1] == contour


def test_viewer_widget_clears_contours_signal(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((32, 32), dtype=np.uint8))

    cleared: list[list[Contour]] = []
    viewer.contours_changed.connect(cleared.append)

    viewer.start_contour()
    viewer.handle_contour_click((1.0, 1.0))
    viewer.handle_contour_click((5.0, 1.0))
    viewer.handle_contour_click((3.0, 4.0))
    viewer.finish_contour()

    viewer.clear()

    assert cleared[-1] == []
