"""Small, non-widget host and overlay for Doppler controller tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
from PySide6.QtCore import QObject, Signal

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.presentation.viewer.doppler_controller import DopplerController, DopplerViewerPort


class FakeSignals(QObject):
    markers_changed = Signal(object)
    vessel_changed = Signal(object)
    workflow_step_changed = Signal(str)
    workflow_completed = Signal()
    trace_prompt_changed = Signal(str)
    trace_committed = Signal(object)
    autovti_region_selected = Signal(float, float, str)


class FakeDopplerViewer:
    def __init__(self, frame: np.ndarray | None = None) -> None:
        self.frame = frame
        self.uid: str | None = "instance"
        self.frame_index: int | None = 3
        self.syncing = False
        self.active = False
        self.kind: str | None = None
        self.spatial_mode = False
        self.calls: list[str] = []
        self.messages: list[str] = []
        self.hints: list[str] = []
        self.answers: list[tuple[float, bool]] = []
        self.signals = FakeSignals()
        self.overlay = MagicMock()
        for name in (
            "markers_changed",
            "vessel_changed",
            "workflow_step_changed",
            "workflow_completed",
            "trace_prompt_changed",
            "trace_committed",
            "autovti_region_selected",
        ):
            setattr(self.overlay, name, getattr(self.signals, name))
        self.overlay.get_tool_mode.return_value = "none"
        self.overlay.axis_mapping.return_value = DopplerAxisMapping.from_frame_size(80, 60, time_span_ms=0.0)
        self.overlay.vessel_status.return_value = "none"
        self.overlay.workflow_prompt.return_value = None
        self.controller = DopplerController(self.port(), overlay=self.overlay)

    def clear_caliper(self) -> None:
        self.calls.append("clear_caliper")
        self.active = False
        self.kind = None
        self.controller.on_calibration_caliper_cleared()

    def arm(self, x: float, y: float | None) -> None:
        self.calls.append(f"arm:{x}:{y}")
        self.active = True
        self.kind = "doppler_velocity"

    def port(self) -> DopplerViewerPort:
        return DopplerViewerPort(
            frame=lambda: self.frame,
            instance_metadata=lambda: None,
            instance_uid=lambda: self.uid,
            frame_index=lambda: self.frame_index,
            contour_frame_index=lambda: self.frame_index,
            resolve_panels=lambda: None,
            dicom_doppler_panel=lambda: None,
            syncing=lambda: self.syncing,
            calibration_active=lambda: self.active,
            calibration_kind=lambda: self.kind,
            vessel_measurement_mode=lambda: self.spatial_mode,
            tick_snap_enabled=lambda: False,
            tick_snap_radius_px=lambda: 5.0,
            last_cursor_xy=lambda: None,
            create_overlay=lambda: self.overlay,
            map_event=lambda event: (event.x, event.y),
            cancel_tool=lambda: self.calls.append("cancel"),
            clear_calibration_caliper=self.clear_caliper,
            clear_active_contour=lambda: self.calls.append("clear_contour"),
            arm_velocity_calibration=self.arm,
            ensure_crosshair_graphics=lambda: self.calls.append("crosshair"),
            load_ecg_strip=lambda: self.calls.append("load_ecg"),
            show_message=lambda text, show: self.messages.append(text),
            set_hint=self.hints.append,
            ask_double=lambda *args: self.answers.pop(0),
            on_trace_committed=lambda trace: self.calls.append("trace"),
            parse_dicom_calibration=lambda *args, **kwargs: None,
            auto_detect_velocity=lambda *args, **kwargs: None,
            load_tick_calibration=lambda: None,
            read_ecg=lambda path: None,
        )
