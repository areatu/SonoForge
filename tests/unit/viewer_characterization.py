"""QH-0 observable-contract harness for :class:`ViewerWidget` (issue #516).

The harness deliberately knows only two seams:

* the public ``ViewerWidget`` API (signals included);
* the reviewed ``ViewerContract`` adapter for widgets, because Qt objects are
  not part of the widget's public Python surface.

Nothing here reaches into private attributes of the widget or its mixins. That
is the point: a clustering refactor may move code between modules as long as a
cluster keeps its observable behaviour, so the evidence must be collected from
the same surface the application and the tests are allowed to use.

What is recorded:

* ``SignalRecorder`` — every public signal in emission order, so a refactor
  cannot quietly reorder or add emissions;
* ``viewer_surface`` — a plain snapshot of the user-visible surface (transport,
  frame counter, FPS, zoom, display levels, overlay position, tool flags);
* ``instance_snapshot`` / ``contour_snapshot`` — the payload a frame switch or a
  finished contour must preserve.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtGui import QWheelEvent

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

#: Public signals that make up the frame/transport and tool clusters.
TRANSPORT_SIGNALS = (
    "frame_selected",
    "scroll_frame_selected",
    "play_pause_requested",
    "loop_in_requested",
    "loop_out_requested",
    "loop_toggle_requested",
    "loop_bound_changed",
    "fps_override_requested",
)

MEASUREMENT_SIGNALS = (
    "contour_completed",
    "contours_changed",
    "linear_measurements_changed",
    "calibration_completed",
)

TOOL_SIGNALS = (
    "results_overlay_position_changed",
    "results_overlay_parameter_clicked",
    "doppler_frame_changing",
    "doppler_frame_changed",
    "mmode_column_ready",
    "mmode_line_completed",
    "mmode_calibration_changed",
)


class SignalRecorder:
    """Connects every public ``ViewerWidget`` signal and keeps emission order."""

    def __init__(self, viewer: ViewerWidget) -> None:
        self._events: list[tuple[str, tuple[Any, ...]]] = []
        names = sorted(
            name
            for name in vars(type(viewer))
            if not name.startswith("_") and isinstance(getattr(viewer, name, None), SignalInstance)
        )
        for name in sorted(names):
            getattr(viewer, name).connect(self._make_slot(name))

    def _make_slot(self, name: str):
        def slot(*args: Any) -> None:
            self._events.append((name, args))

        return slot

    def clear(self) -> None:
        self._events.clear()

    def events(self) -> list[tuple[str, tuple[Any, ...]]]:
        return list(self._events)

    def names(self) -> list[str]:
        return [name for name, _ in self._events]

    def args_of(self, name: str) -> list[tuple[Any, ...]]:
        return [args for emitted, args in self._events if emitted == name]

    def only(self, allowed: Iterable[str]) -> list[str]:
        """Return emissions outside ``allowed`` (helper for precise assertions)."""
        expected = set(allowed)
        return [name for name in self.names() if name not in expected]


def make_viewer(qtbot) -> ViewerWidget:
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    return widget


def make_frame(value: int = 128, shape: tuple[int, int] = (64, 64)) -> np.ndarray:
    """A deterministic greyscale frame with enough contrast for levels maths."""
    height, width = shape
    gradient = np.arange(height * width, dtype=np.uint32).reshape(height, width)
    frame = ((gradient + value) % 251).astype(np.uint8)
    return frame


def make_instance(
    sop_instance_uid: str = "1.2.3.qh0",
    *,
    frame_time_ms: float = 1000.0 / 30.0,
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=sop_instance_uid,
        series_uid="1.2.3.qh0.series",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=frame_time_ms,
        series_description="QH-0 characterization",
    )


def make_state(
    *,
    frame: int = 0,
    total: int = 1,
    fps: float = 30.0,
    playing: bool = False,
    instance: InstanceMetadata | None = None,
    contours: Any = (),
    linear_measurements: Any = (),
) -> ViewerState:
    return ViewerState(
        instance=instance or make_instance(frame_time_ms=1000.0 / fps),
        current_frame_index=frame,
        total_frames=total,
        frame_time_ms=1000.0 / fps,
        is_playing=playing,
        contours=contours,
        linear_measurements=linear_measurements,
    )


def image_pixels(item: Any) -> tuple[int, ...] | None:
    """Corner pixels of the rendered image — levels show up here, not in getLevels()."""
    image = getattr(item, "image", None)
    if image is None or getattr(image, "size", 0) == 0:
        return None
    return (
        int(image[0, 0]),
        int(image[0, -1]),
        int(image[-1, 0]),
        int(image[-1, -1]),
    )


def viewer_surface(viewer: ViewerWidget) -> dict[str, Any]:
    """Snapshot the observable surface; floats rounded so snapshots compare."""
    contract = viewer.contract
    return {
        "timeline": (
            contract.timeline_slider.minimum(),
            contract.timeline_slider.maximum(),
            contract.timeline_slider.value(),
        ),
        "play_caption": contract.play_button.accessibleName(),
        "play_enabled": contract.play_button.isEnabled(),
        "frame_label": contract.source_label.text(),
        "fps_label": contract.fps_label.text(),
        "hint": contract.hint_bar.text(),
        "zoom_mode": viewer.zoom_mode,
        "zoom_factor": round(float(viewer.zoom_factor), 4),
        "pixels": image_pixels(contract.image_item),
        "sliders": (
            contract.window_slider.value(),
            contract.level_slider.value(),
            contract.dr_slider.value(),
        ),
        "calibration": viewer.is_calibration_active,
        "linear_caliper": viewer.is_linear_caliper_active,
        "contour_mode": viewer.is_contour_mode_active,
        "label_picker": viewer.is_label_picker_visible(),
        "overlay": tuple(round(float(value), 4) for value in viewer.results_overlay_position()),
        "overlay_custom": viewer.results_overlay_custom_position(),
        "instance": viewer.current_instance_uid(),
        "has_frame": viewer.has_frame,
        "contours": len(viewer.contours()),
    }


def instance_snapshot(viewer: ViewerWidget) -> dict[str, Any]:
    """Fields a frame/instance switch must not disturb (Perf-01, S-02)."""
    contract = viewer.contract
    return {
        "instance": viewer.current_instance_uid(),
        "pixels": image_pixels(contract.image_item),
        "sliders": (
            contract.window_slider.value(),
            contract.level_slider.value(),
            contract.dr_slider.value(),
        ),
        "zoom_mode": viewer.zoom_mode,
        "zoom_factor": round(float(viewer.zoom_factor), 4),
        "overlay": tuple(round(float(value), 4) for value in viewer.results_overlay_position()),
        "overlay_custom": viewer.results_overlay_custom_position(),
    }


def contour_snapshot(contour: Any) -> dict[str, Any]:
    """Payload of ``contour_completed`` that must survive the owner extraction."""
    return {
        "chamber": contour.chamber,
        "phase": contour.phase,
        "view": contour.view,
        "frame_index": contour.frame_index,
        "points": len(contour.points),
    }


def ctrl_wheel_event(delta_y: int, position: Any = None, modifiers: Any = None) -> QWheelEvent:
    """A ``QWheelEvent`` with Ctrl pressed, used through ``contract.handle_wheel``."""
    from PySide6.QtCore import QPoint, QPointF

    point = position if position is not None else QPointF(10.0, 10.0)
    return QWheelEvent(
        point,
        point,
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        modifiers if modifiers is not None else Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
