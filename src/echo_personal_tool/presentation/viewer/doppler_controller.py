"""Doppler tools, calibration, axis mapping, and mode controller for ``ViewerWidget`` (issue 420).

Before this slice ``ViewerWidget`` held all 19 Doppler attributes — the
``DopplerOverlayTools`` child widget, the calibration state and its instance /
frame ownership tags, the manual baseline/velocity wizard draft, the PW/CW/TDI
mode override, the grid snap hints, and the manual calibration banner state —
and mixed them with contours, M-mode, and playback.  ``DopplerController``
gives that entire cluster one single owner, matching ``MModeController``
(issue 479) and ``ReportCoordinator`` (issue 478).

Boundary:

* ``DopplerController`` owns the Doppler calibration state, the baseline-then-
  velocity calibration draft, the DICOM/override acquisition mode, the spectral
  auto-detection and tick-scale fallbacks, the manual calibration hint state,
  envelope / cardiac-cycle helpers, and the ``DopplerOverlayTools`` child
  widget.  It never imports ``ViewerWidget`` or ``MainWindow``; everything it
  needs from the host arrives through :class:`DopplerViewerPort`.
* ``ViewerWidget`` keeps the shared calibration caliper graphics, the vessel
  sensitivity overlay, the label-picker widget, and ``QInputDialog``; it wires
  them into :class:`DopplerViewerPort` and re-emits the controller's signals
  under the historical ``ViewerWidget`` signal names.
"""

from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.dicom_io import (
    load_samsung_tick_calibration,
    read_ecg_waveform,
    try_parse_dicom_doppler_calibration,
)
from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.calculations.doppler_metrics import compute as compute_doppler_metrics
from echo_personal_tool.domain.doppler_catalog import (
    HEART_RATE_INTERVAL_LABEL,
    flow_site_from_trace_label,
    format_velocity_measurement,
    normalize_doppler_mode,
    normalize_label,
)
from echo_personal_tool.domain.measurement_catalog import format_measurement as _fmt
from echo_personal_tool.domain.models import DopplerMeasurementDTO
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.frame_panels import FramePanelLayout, UltrasoundPanel
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.services.auto_doppler_velocity_calibration import (
    try_auto_doppler_velocity_calibration,
)
from echo_personal_tool.domain.services.cardiac_cycle_service import (
    CardiacCycle,
    CardiacCycleService,
)
from echo_personal_tool.domain.services.doppler_calibration import (
    build_axis_mapping,
    calibration_from_roi_and_baseline,
)
from echo_personal_tool.domain.services.doppler_envelope import extract_doppler_envelope
from echo_personal_tool.domain.services.doppler_grid_detector import detect_doppler_grid_lines
from echo_personal_tool.domain.services.nomenclature import flow_measurement_id
from echo_personal_tool.domain.services.roi_validator import validate_doppler_roi
from echo_personal_tool.domain.services.spectrogram_detector import detect_spectrogram_roi
from echo_personal_tool.domain.services.velocity_scale_detector import detect_velocity_scale_ticks
from echo_personal_tool.imaging.samsung_tick_detector import detect_samsung_doppler_scales
from echo_personal_tool.presentation.calibration_snap import snap_y_to_nearest_tick
from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools

logger = logging.getLogger(__name__)

DOPPLER_CAL_BASELINE_KEY = "viewer.doppler.cal_baseline"
DOPPLER_CAL_VELOCITY_KEY = "viewer.doppler.cal_velocity"
_GENERIC_DIST_LABEL_PREFIX = "Dist"

DopplerCalStep = Literal["baseline"]
DopplerToolMode = Literal["none", "peak", "interval", "trace", "autovti_region"]


@dataclass(frozen=True)
class DopplerViewerPort:
    """Narrow host boundary for :class:`DopplerController`.

    Kept as plain callables so standalone unit tests build it from attributes
    and lists without constructing a ``ViewerWidget`` or touching disk/dialogs.
    """

    frame: Callable[[], np.ndarray | None]
    instance_metadata: Callable[[], Any]
    instance_uid: Callable[[], str | None]
    frame_index: Callable[[], int | None]
    contour_frame_index: Callable[[], int | None]
    resolve_panels: Callable[[], FramePanelLayout | None]
    dicom_doppler_panel: Callable[[], UltrasoundPanel | None]
    syncing: Callable[[], bool]
    calibration_active: Callable[[], bool]
    calibration_kind: Callable[[], str | None]
    vessel_measurement_mode: Callable[[], bool]
    tick_snap_enabled: Callable[[], bool]
    tick_snap_radius_px: Callable[[], float]
    last_cursor_xy: Callable[[], tuple[float, float] | None]
    view: Callable[[], Any]
    overlay_parent: Callable[[], QWidget | None]
    map_event: Callable[[Any], tuple[float, float] | None]
    cancel_tool: Callable[[], None]
    clear_calibration_caliper: Callable[[], None]
    clear_active_contour: Callable[[], None]
    arm_velocity_calibration: Callable[[float, float | None], None]
    ensure_crosshair_graphics: Callable[[], None]
    load_ecg_strip: Callable[[], None]
    show_message: Callable[[str, bool], None]
    set_hint: Callable[[str], None]
    ask_double: Callable[[str, str, float, float, float, int], tuple[float, bool]]
    on_trace_committed: Callable[[object], None]
    parse_dicom_calibration: Callable[..., DopplerCalibrationState | None] = try_parse_dicom_doppler_calibration
    auto_detect_velocity: Callable[..., Any] = try_auto_doppler_velocity_calibration
    load_tick_calibration: Callable[[], Any] = load_samsung_tick_calibration
    read_ecg: Callable[[Path], Any] = read_ecg_waveform


class DopplerController(QObject):
    """Single owner of Doppler calibration, mode, auto-detection, and overlay tools."""

    markers_changed = Signal(object)
    calibration_changed = Signal(object)
    spectral_calibration_completed = Signal(object)
    frame_changing = Signal(int, object)
    frame_changed = Signal(int)
    vessel_changed = Signal(object)

    def __init__(
        self,
        port: DopplerViewerPort,
        *,
        overlay: Any = None,
        eager_overlay: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._overlay: Any = None
        self._overlay_connected = False

        self._axis_calibrated = False
        self._velocity_confirmed = False
        self._calibration_state: DopplerCalibrationState | None = None
        self._calibration_instance_uid: str | None = None
        self._calibration_frame_index: int | None = None
        self._cal_step: DopplerCalStep | None = None
        self._cal_kind: DopplerKind = DopplerKind.SPECTRAL
        self._dicom_mode: str = ""
        self._mode_override: str = ""
        self._roi_corner1: tuple[float, float] | None = None
        self._pending_roi: DopplerSpectrogramRoi | None = None
        self._pending_baseline_y: float | None = None
        self._pending_velocity_span: float | None = None
        self._pending_auto_velocity_span: float | None = None
        self._grid_line_positions: list[float] = []
        self._auto_calibration_enabled = True
        self._hint_in_strip = False
        self._hint_dismissed = False

        if overlay is not None:
            self._attach_overlay(overlay)
        elif eager_overlay:
            self._ensure_overlay()

    def _ensure_overlay(self) -> Any:
        if self._overlay is None:
            created = DopplerOverlayTools(self._port.view(), self._port.overlay_parent())
            self._attach_overlay(created)
        return self._overlay

    def _attach_overlay(self, overlay: Any) -> None:
        self._overlay = overlay
        if self._overlay_connected:
            return
        self._connect_signal(overlay, "markers_changed", self.markers_changed.emit)
        self._connect_signal(overlay, "vessel_changed", self.vessel_changed.emit)
        self._connect_signal(overlay, "workflow_step_changed", self._on_workflow_step_changed)
        self._connect_signal(overlay, "workflow_completed", self._on_workflow_completed)
        self._connect_signal(overlay, "trace_prompt_changed", self._on_trace_prompt_changed)
        self._connect_signal(overlay, "trace_committed", self._port.on_trace_committed)
        self._connect_signal(overlay, "autovti_region_selected", self._on_autovti_region_selected)
        self._overlay_connected = True

    @staticmethod
    def _connect_signal(source: Any, signal_name: str, slot: Callable[..., Any]) -> None:
        sig = getattr(source, signal_name, None)
        connect = getattr(sig, "connect", None)
        if callable(connect):
            connect(slot)

    # -- public state inspection & preferences -------------------------------

    @property
    def overlay(self) -> Any:
        """Underlying :class:`DopplerOverlayTools` (or test fake)."""
        return self._ensure_overlay()

    @property
    def calibration_state(self) -> DopplerCalibrationState | None:
        return self._calibration_state

    @calibration_state.setter
    def calibration_state(self, state: DopplerCalibrationState | None) -> None:
        self._calibration_state = state

    @property
    def axis_calibrated(self) -> bool:
        return self._axis_calibrated

    @axis_calibrated.setter
    def axis_calibrated(self, value: bool) -> None:
        self._axis_calibrated = bool(value)

    @property
    def velocity_confirmed(self) -> bool:
        return self._velocity_confirmed

    @velocity_confirmed.setter
    def velocity_confirmed(self, value: bool) -> None:
        self._velocity_confirmed = bool(value)

    @property
    def cal_step(self) -> DopplerCalStep | None:
        return self._cal_step

    @cal_step.setter
    def cal_step(self, step: DopplerCalStep | None) -> None:
        self._cal_step = step

    @property
    def cal_kind(self) -> DopplerKind:
        return self._cal_kind

    @property
    def pending_roi(self) -> DopplerSpectrogramRoi | None:
        return self._pending_roi

    @pending_roi.setter
    def pending_roi(self, roi: DopplerSpectrogramRoi | None) -> None:
        self._pending_roi = roi

    @property
    def pending_baseline_y(self) -> float | None:
        return self._pending_baseline_y

    @pending_baseline_y.setter
    def pending_baseline_y(self, value: float | None) -> None:
        self._pending_baseline_y = value

    @property
    def grid_line_positions(self) -> list[float]:
        return self._grid_line_positions

    @grid_line_positions.setter
    def grid_line_positions(self, values: Sequence[float]) -> None:
        self._grid_line_positions = list(values)

    @property
    def auto_calibration_enabled(self) -> bool:
        return self._auto_calibration_enabled

    @auto_calibration_enabled.setter
    def auto_calibration_enabled(self, enabled: bool) -> None:
        self._auto_calibration_enabled = bool(enabled)

    def set_auto_calibration_enabled(self, enabled: bool) -> None:
        self._auto_calibration_enabled = bool(enabled)

    def set_show_calibration_roi(self, show: bool) -> None:
        self.overlay.set_show_calibration_roi(bool(show))

    def reposition_manual_calibration_hint(self) -> None:
        self.overlay.reposition_manual_calibration_hint()

    def reload_text(self) -> None:
        self.overlay.reload_manual_calibration_hint_text()

    @property
    def calibration_in_progress(self) -> bool:
        if self._cal_step is not None:
            return True
        return bool(
            self._port.calibration_active() and self._port.calibration_kind() in {"spectral", "doppler_velocity"}
        )

    def dispose(self) -> None:
        """Idempotent teardown for QH-3 owner-scoped lifecycle checks."""
        if self._overlay is None or not self._overlay_connected:
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for sig_name, slot in (
                ("markers_changed", self.markers_changed.emit),
                ("vessel_changed", self.vessel_changed.emit),
                ("workflow_step_changed", self._on_workflow_step_changed),
                ("workflow_completed", self._on_workflow_completed),
                ("trace_prompt_changed", self._on_trace_prompt_changed),
                ("trace_committed", self._port.on_trace_committed),
                ("autovti_region_selected", self._on_autovti_region_selected),
            ):
                sig = getattr(self._overlay, sig_name, None)
                disconnect = getattr(sig, "disconnect", None)
                if callable(disconnect):
                    try:
                        disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        self._overlay_connected = False

    # -- instance / frame / cancel lifecycle hooks ---------------------------

    def on_instance_changed(self) -> None:
        """Reset clip-scoped calibration draft and per-clip hint dismissal."""
        if self._cal_step is not None:
            self._clear_wizard_draft()
        self.clear_calibration_display()
        self._hint_dismissed = False

    def on_frame_changed(self, previous_frame: int | None, new_frame: int) -> None:
        """Save outgoing frame's Doppler markers and clear incoming frame's state."""
        if previous_frame is not None and not self._port.syncing():
            self.frame_changing.emit(previous_frame, self.get_dto())
        self._port.clear_active_contour()
        self._calibration_state = None
        self._calibration_instance_uid = None
        self._calibration_frame_index = None
        self._velocity_confirmed = False
        self.overlay.clear_measurements(keep_calibration_graphics=False)
        if not self._port.syncing():
            self.frame_changed.emit(new_frame)

    def cancel_calibration_step(self) -> bool:
        """Cancel the baseline step on Escape; True when a step was armed."""
        if self._cal_step is None:
            return False
        self._clear_wizard_draft()
        self.sync_manual_calibration_hint()
        return True

    def cancel_active_tool(self) -> bool:
        return bool(self.overlay.cancel_active_tool())

    def on_calibration_caliper_cleared(self) -> None:
        """Clear Doppler velocity snap lines when the shared caliper disarms."""
        self._grid_line_positions = []
        self.sync_manual_calibration_hint()

    def _clear_wizard_draft(self) -> None:
        self._cal_step = None
        self._roi_corner1 = None
        self._pending_roi = None
        self._pending_baseline_y = None
        self._pending_velocity_span = None

    # -- acquisition mode (PW / CW / TDI) ------------------------------------

    def set_dicom_mode(self, mode: str | None) -> None:
        """Record the current clip's DICOM-derived acquisition mode."""
        normalized = normalize_doppler_mode(mode)
        if normalized == self._dicom_mode:
            return
        self._dicom_mode = normalized
        self.overlay.set_doppler_mode(self.resolved_mode())

    def set_mode_override(self, mode: str | None) -> None:
        """Set the explicit acquisition-mode override (``""`` = Auto)."""
        normalized = normalize_doppler_mode(mode)
        if normalized == self._mode_override:
            return
        self._mode_override = normalized
        self.overlay.set_doppler_mode(self.resolved_mode())

    def reset_mode_override(self) -> None:
        self.set_mode_override("")

    def mode_override(self) -> str:
        return self._mode_override

    def resolved_mode(self) -> str:
        """The mode the viewer actually uses: override wins over DICOM."""
        return self._mode_override or self._dicom_mode

    # -- calibration queries & manual hint -----------------------------------

    def start_scale_calibration(self) -> bool:
        return self.start_calibration(DopplerKind.SPECTRAL)

    def start_calibration(self, kind: DopplerKind = DopplerKind.SPECTRAL) -> bool:
        if self._port.frame() is None:
            return False
        self._port.cancel_tool()
        self._port.clear_calibration_caliper()
        self._cal_kind = kind
        self._cal_step = "baseline"
        self._roi_corner1 = None
        self._pending_roi = None
        self._pending_baseline_y = None
        self._pending_velocity_span = None
        self._pending_auto_velocity_span = None
        self._port.show_message(tr(DOPPLER_CAL_BASELINE_KEY), True)
        self.sync_manual_calibration_hint()
        return True

    @staticmethod
    def calibration_prompt() -> str:
        return tr("viewer.doppler_calibration_prompt")

    def calibration_matches_instance(self) -> bool:
        current_uid = self._port.instance_uid()
        if current_uid is None or self._calibration_instance_uid is None:
            return False
        if current_uid != self._calibration_instance_uid:
            return False
        frame_index = self._port.frame_index()
        if frame_index is None or self._calibration_frame_index is None:
            return False
        return frame_index == self._calibration_frame_index

    def clear_calibration_display(self, keep_time_scale: bool = False) -> None:
        """Clear calibration display, optionally preserving the time scale."""
        prior = self._calibration_state
        time_span_ms = 0.0
        time_origin_ms = 0.0
        time_from_dicom = False
        if keep_time_scale and prior is not None and prior.has_time_scale():
            time_span_ms = float(prior.time_span_ms or 0.0)
            time_origin_ms = float(prior.time_origin_ms or 0.0)
            time_from_dicom = bool(getattr(prior, "time_from_dicom_tags", False))
        self._calibration_state = None
        self._calibration_instance_uid = None
        self._calibration_frame_index = None
        self._axis_calibrated = False
        self._velocity_confirmed = False
        self.overlay.clear_measurements(keep_calibration_graphics=False)
        frame = self._port.frame()
        if frame is None:
            self.sync_manual_calibration_hint()
            return
        height, width = frame.shape[:2]
        if keep_time_scale and time_span_ms > 0.0:
            roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(width), height=max(1.0, float(height)))
            state = calibration_from_roi_and_baseline(
                roi,
                height / 2.0,
                velocity_span_cm_s=0.0,
                time_span_ms=time_span_ms,
                time_origin_ms=time_origin_ms,
                kind=self._cal_kind,
            )
            state = replace(state, time_from_dicom_tags=time_from_dicom)
            self._calibration_state = state
            self._calibration_instance_uid = self._port.instance_uid()
            self._calibration_frame_index = self._port.frame_index()
            self.overlay.set_axis_mapping(build_axis_mapping(state))
        else:
            self.overlay.set_axis_mapping(DopplerAxisMapping.from_frame_size(width, height, time_span_ms=0.0))
        self.sync_manual_calibration_hint()

    def is_axis_calibrated(self) -> bool:
        return self.is_velocity_calibrated() and self.is_time_calibrated()

    def is_velocity_calibrated(self) -> bool:
        state = self._calibration_state
        return state is not None and state.has_velocity_scale()

    def is_time_calibrated(self) -> bool:
        """True when a real horizontal time scale is known for this Doppler frame."""
        state = self._calibration_state
        return state is not None and state.has_time_scale()

    def _velocity_scale_is_set(self) -> bool:
        state = self._calibration_state
        if state is not None and state.has_velocity_scale():
            if state.has_velocity_scale_from_dicom() or (
                state.velocity_per_pixel_cm_s is not None and state.velocity_per_pixel_cm_s > 0.0
            ):
                return True
            return self._velocity_confirmed
        panel = self._port.dicom_doppler_panel()
        return panel is not None and panel.vertical_cm_s_per_pixel is not None

    def _hint_roi(self) -> DopplerSpectrogramRoi | None:
        state = self._calibration_state
        if state is not None and state.roi.width > 0.0 and state.roi.height > 0.0:
            return state.roi
        mapping: DopplerAxisMapping = self.overlay.axis_mapping()
        if mapping.roi is not None and mapping.roi.width > 0.0 and mapping.roi.height > 0.0:
            return mapping.roi
        panel = self._port.dicom_doppler_panel()
        if panel is not None and panel.bounds.width > 0.0 and panel.bounds.height > 0.0:
            return panel.bounds
        return None

    def sync_manual_calibration_hint(self) -> None:
        """Show the hint in the ROI center when a Doppler strip has no velocity scale."""
        active = self.calibration_in_progress
        roi = self._hint_roi()
        clip_open = self._port.frame() is not None and roi is not None
        wanted = (
            clip_open
            and not self._port.vessel_measurement_mode()
            and not self._hint_dismissed
            and not self._velocity_scale_is_set()
        )
        self.overlay.set_calibration_active(active)
        self.overlay.set_hint_roi(roi)
        self.overlay.set_manual_calibration_hint_visible(wanted)
        logger.debug(
            "[F6] doppler calibration hint wanted=%s roi=%s scale_set=%s active=%s",
            wanted,
            roi is not None,
            self._velocity_scale_is_set(),
            active,
        )
        if wanted:
            self._hint_in_strip = True
            self._port.set_hint(tr("viewer.doppler_vertical_scale_missing"))
        elif self._hint_in_strip:
            self._hint_in_strip = False
            self._port.set_hint("")

    def dismiss_manual_calibration_hint(self) -> None:
        """Hide the uncalibrated-Doppler prompt for the current clip."""
        if self._hint_dismissed:
            return
        self._hint_dismissed = True
        self.sync_manual_calibration_hint()

    def is_context(self) -> bool:
        """True when the viewer is in or showing a spectral Doppler context."""
        if self.overlay.get_tool_mode() != "none":
            return True
        if self._cal_step is not None:
            return True
        if self._port.calibration_kind() in {"spectral", "doppler_velocity"}:
            return True
        if self._calibration_state is not None:
            return True
        panels = self._port.resolve_panels()
        return panels is not None and panels.doppler is not None

    def apply_calibration_state(self, state: DopplerCalibrationState, *, persist: bool = True) -> None:
        frame = self._port.frame()
        if frame is not None:
            height, width = frame.shape[:2]
            roi = state.roi.normalized(float(width), float(height))
            baseline_y = max(0.0, min(float(state.baseline_y_px), float(height - 1)))
            state = DopplerCalibrationState(
                roi=roi,
                baseline_y_px=baseline_y,
                time_origin_ms=state.time_origin_ms,
                time_span_ms=state.time_span_ms,
                velocity_span_cm_s=state.velocity_span_cm_s,
                kind=state.kind,
                from_dicom_tags=state.from_dicom_tags,
                time_from_dicom_tags=getattr(state, "time_from_dicom_tags", False),
                velocity_from_dicom_tags=getattr(state, "velocity_from_dicom_tags", False),
                velocity_per_pixel_cm_s=getattr(state, "velocity_per_pixel_cm_s", None),
                velocity_sign=getattr(state, "velocity_sign", 1),
            )
        self._calibration_state = state
        self._calibration_instance_uid = self._port.instance_uid()
        self._calibration_frame_index = self._port.frame_index()
        self.overlay.set_axis_mapping(build_axis_mapping(state))
        self._axis_calibrated = state.has_velocity_scale()
        if state.has_velocity_scale_from_dicom() or (
            state.velocity_per_pixel_cm_s is not None and state.velocity_per_pixel_cm_s > 0.0
        ):
            self._velocity_confirmed = True
        self._port.load_ecg_strip()
        if persist and not self._port.syncing() and self.calibration_matches_instance():
            self.calibration_changed.emit(state)
        self.sync_manual_calibration_hint()

    def get_calibration_state(self) -> DopplerCalibrationState | None:
        return self._calibration_state

    def restore_state(
        self,
        calibration: DopplerCalibrationState | None,
        dto: object | None,
    ) -> None:
        """Restore calibration and measurements when switching instances."""
        if calibration is not None:
            self._velocity_confirmed = calibration.has_velocity_scale()
            self.apply_calibration_state(calibration, persist=False)
        elif not self.try_auto_detect_calibration():
            self.clear_calibration_display()
        if dto is not None:
            if isinstance(dto, DopplerMeasurementDTO):
                self.overlay.load_measurement_dto(dto)
        else:
            self.overlay.clear_measurements(keep_calibration_graphics=True)

    # -- auto-detection & frame axis configuration ---------------------------

    def try_auto_detect_calibration(self) -> bool:
        if not self._auto_calibration_enabled:
            return False
        frame = self._port.frame()
        if frame is None:
            return False
        instance = self._port.instance_metadata()
        if instance is None or getattr(instance, "media_format", None) != "dicom":
            return False
        path = getattr(instance, "path", None)
        if path is None:
            return False
        parsed = self._port.parse_dicom_calibration(
            path,
            kind=DopplerKind.SPECTRAL,
            frame=frame,
        )
        if parsed is None:
            return False
        logger.debug(
            "[ROI-TRACE] auto_detect: parsed roi=(%.0f,%.0f,%.0f,%.0f) size=(%.0fx%.0f) time=%s vel=%s",
            parsed.roi.x0,
            parsed.roi.y0,
            parsed.roi.x0 + parsed.roi.width,
            parsed.roi.y0 + parsed.roi.height,
            parsed.roi.width,
            parsed.roi.height,
            parsed.has_time_scale_from_dicom(),
            parsed.has_velocity_scale_from_dicom(),
        )
        if parsed.has_time_scale_from_dicom() or parsed.has_velocity_scale_from_dicom():
            if parsed.has_time_scale_from_dicom() and not parsed.velocity_from_dicom_tags:
                auto = self._port.auto_detect_velocity(
                    frame,
                    roi=parsed.roi,
                    baseline_y=parsed.baseline_y_px,
                    kind=parsed.kind,
                )
                if auto is not None and auto.confidence >= 0.6:
                    parsed = replace(
                        parsed,
                        velocity_span_cm_s=auto.velocity_span_cm_s,
                        velocity_from_dicom_tags=False,
                    )
                    self._velocity_confirmed = True
                else:
                    parsed = replace(parsed, velocity_span_cm_s=0.0)
            self.apply_calibration_state(parsed, persist=True)
            return True
        if parsed.has_velocity_scale() or parsed.roi.width > 0:
            self.apply_calibration_state(parsed, persist=True)
            self._pending_roi = parsed.roi
            self._pending_baseline_y = parsed.baseline_y_px
            auto = self._port.auto_detect_velocity(
                frame,
                roi=parsed.roi,
                baseline_y=parsed.baseline_y_px,
                kind=parsed.kind,
            )
            if auto is not None and auto.confidence >= 0.6:
                state = calibration_from_roi_and_baseline(
                    parsed.roi,
                    parsed.baseline_y_px,
                    velocity_span_cm_s=auto.velocity_span_cm_s,
                    time_span_ms=parsed.time_span_ms,
                    kind=parsed.kind,
                )
                self._velocity_confirmed = True
                self.apply_calibration_state(state, persist=True)
                self._pending_roi = None
                self._pending_baseline_y = None
                return True
            self.begin_velocity_calibration(start_y=self._pending_baseline_y)
            return True
        return False

    def configure_axis_for_frame(self) -> None:
        frame = self._port.frame()
        if frame is None:
            self.sync_manual_calibration_hint()
            return
        if self._calibration_state is not None and self.calibration_matches_instance():
            self.apply_calibration_state(self._calibration_state, persist=False)
            return
        if self._calibration_state is not None:
            self.clear_calibration_display()

        if self.try_auto_detect_calibration():
            return
        self._velocity_confirmed = False

        height, width = frame.shape[:2]
        scales = detect_samsung_doppler_scales(frame)
        if scales.time_scale.confidence < 0.3 or len(scales.time_scale.tick_positions) < 5:
            self.overlay.set_axis_mapping(DopplerAxisMapping.from_frame_size(width, height))
            self._axis_calibrated = False
            self.sync_manual_calibration_hint()
            return

        if scales.refined_roi is not None:
            if not self._apply_refined_scales_roi(frame, scales):
                return
        elif scales.bottom_velocity_scale is not None and scales.bottom_velocity_scale.confidence >= 0.3:
            self._apply_bottom_velocity_scale_roi(frame, scales)
        else:
            self._apply_dark_band_fallback(frame)

        self._axis_calibrated = False
        self.sync_manual_calibration_hint()

    def _time_span_from_spacing_px(self, spacing_px: float, roi_width: float) -> float:
        if spacing_px <= 0.0:
            return 0.0
        samsung_cal = self._port.load_tick_calibration()
        k_constant = samsung_cal.k_constant if samsung_cal is not None else 5.0
        frequency_hz = k_constant * spacing_px
        if frequency_hz <= 0.0:
            return 0.0
        return (1000.0 / frequency_hz) * roi_width

    def _apply_refined_scales_roi(self, frame: np.ndarray, scales: Any) -> bool:
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = scales.refined_roi
        roi = DopplerSpectrogramRoi(
            x0=x0,
            y0=y0,
            width=max(1.0, x1 - x0),
            height=max(1.0, y1 - y0),
        )
        vresult = validate_doppler_roi(roi, frame)
        if not vresult.valid:
            logger.debug("[ROI-TRACE] scales_refined: REJECTED — %s", vresult.reason)
            self.overlay.set_axis_mapping(DopplerAxisMapping.from_frame_size(width, height))
            self._axis_calibrated = False
            self.sync_manual_calibration_hint()
            return False
        baseline_y = roi.y0 + roi.height / 2.0
        time_span_ms = self._time_span_from_spacing_px(scales.time_scale.spacing_px, roi.width)
        velocity_span = 0.0
        auto_vel = self._port.auto_detect_velocity(
            frame,
            roi=roi,
            baseline_y=baseline_y,
            kind=DopplerKind.SPECTRAL,
        )
        if auto_vel is not None:
            velocity_span = auto_vel.velocity_span_cm_s
            self._velocity_confirmed = True
        state = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=velocity_span,
            time_span_ms=time_span_ms,
            kind=DopplerKind.SPECTRAL,
        )
        self.apply_calibration_state(state, persist=False)
        return True

    def _apply_bottom_velocity_scale_roi(self, frame: np.ndarray, scales: Any) -> None:
        height, width = frame.shape[:2]
        ts = scales.time_scale
        bs = scales.bottom_velocity_scale
        tick_x_min = min(ts.tick_positions)
        tick_x_max = max(ts.tick_positions)
        margin = max(ts.spacing_px * 2, 10.0)
        roi = DopplerSpectrogramRoi(
            x0=max(0.0, tick_x_min - margin),
            y0=max(0.0, bs.band_y - height * 0.45),
            width=max(1.0, (tick_x_max + margin) - max(0.0, tick_x_min - margin)),
            height=max(1.0, bs.band_y + 10.0 - max(0.0, bs.band_y - height * 0.45)),
        )
        vresult = validate_doppler_roi(roi, frame)
        if not vresult.valid:
            logger.debug("[ROI-TRACE] bottom_vel_scale: REJECTED — %s", vresult.reason)
            self.overlay.set_axis_mapping(DopplerAxisMapping.from_frame_size(width, height))
            self._axis_calibrated = False
            return
        baseline_y = roi.y0 + roi.height / 2.0
        time_span_ms = self._time_span_from_spacing_px(ts.spacing_px, roi.width)
        velocity_span = 0.0
        auto_vel = self._port.auto_detect_velocity(
            frame,
            roi=roi,
            baseline_y=baseline_y,
            kind=DopplerKind.SPECTRAL,
        )
        if auto_vel is not None:
            velocity_span = auto_vel.velocity_span_cm_s
            self._velocity_confirmed = True
        state = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=velocity_span,
            time_span_ms=time_span_ms,
            kind=DopplerKind.SPECTRAL,
        )
        self.apply_calibration_state(state, persist=False)

    def _apply_dark_band_fallback(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        spec_roi = detect_spectrogram_roi(frame)
        if spec_roi is None:
            self.overlay.set_axis_mapping(DopplerAxisMapping.from_frame_size(width, height))
            return
        x0, y0, x1, y1 = spec_roi
        roi = DopplerSpectrogramRoi(
            x0=x0,
            y0=y0,
            width=max(1.0, x1 - x0),
            height=max(1.0, y1 - y0),
        )
        vresult = validate_doppler_roi(roi, frame)
        if not vresult.valid:
            logger.debug("[ROI-TRACE] dark_band: REJECTED — %s", vresult.reason)
            self.overlay.set_axis_mapping(DopplerAxisMapping.from_frame_size(width, height))
            self._axis_calibrated = False
            return
        baseline_y = roi.y0 + roi.height / 2.0
        state = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=0.0,
            time_span_ms=0.0,
            kind=DopplerKind.SPECTRAL,
        )
        self.apply_calibration_state(state, persist=False)

    # -- manual baseline -> velocity calibration wizard ----------------------

    def handle_calibration_click(self, ev: Any) -> bool:
        frame = self._port.frame()
        if self._cal_step is None or frame is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        _, y = click

        if self._cal_step == "baseline":
            self._pending_baseline_y = y
            height, width = frame.shape[:2]
            roi = (
                self._pending_roi
                or (self._calibration_state.roi if self._calibration_state is not None else None)
                or DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(width), height=max(1.0, float(height)))
            )
            auto = None
            try:
                auto = self._port.auto_detect_velocity(
                    frame,
                    roi=roi,
                    baseline_y=y,
                    kind=self._cal_kind,
                )
            except Exception as exc:  # noqa: BLE001 - optional detector, manual wizard continues
                log_boundary_failure(logger, "calibration.auto", exc, code="blocked", level=logging.DEBUG)
            self._pending_auto_velocity_span = auto.velocity_span_cm_s if auto is not None else None
            prior_state = self._calibration_state
            partial = calibration_from_roi_and_baseline(
                roi,
                y,
                time_span_ms=float(getattr(prior_state, "time_span_ms", 0.0) or 0.0),
                time_origin_ms=float(getattr(prior_state, "time_origin_ms", 0.0) or 0.0),
                kind=self._cal_kind,
            )
            self.overlay.set_axis_mapping(build_axis_mapping(partial))
            self._pending_roi = roi
            self.begin_velocity_calibration(start_y=y)
            return True
        return False

    def begin_velocity_calibration(self, start_y: float | None = None) -> None:
        frame = self._port.frame()
        if frame is None:
            return
        width = int(frame.shape[1])
        self._cal_step = None
        roi = self._pending_roi
        if roi is not None and self._port.tick_snap_enabled():
            cal_x = min(roi.x1 - 4.0, float(width - 5))
            try:
                grid_lines = detect_doppler_grid_lines(
                    frame,
                    x0=int(roi.x0),
                    y0=int(roi.y0),
                    width=int(roi.width),
                    height=int(roi.height),
                )
                scale_ticks = detect_velocity_scale_ticks(frame, roi=roi)
                combined = sorted({round(g, 1) for g in grid_lines} | {round(t, 1) for t in scale_ticks})
            except Exception as exc:  # noqa: BLE001 - optional snap hints, manual span still works
                log_boundary_failure(logger, "calibration.grid", exc, code="blocked", level=logging.DEBUG)
                combined = []
            self._grid_line_positions = combined
        else:
            cal_x = min(float(width) * 0.96, float(width - 5))
            self._grid_line_positions = []
        if start_y is not None and self._grid_line_positions:
            start_y = snap_y_to_nearest_tick(
                start_y,
                self._grid_line_positions,
                radius_px=self._port.tick_snap_radius_px(),
            )
        self._port.arm_velocity_calibration(cal_x, start_y)
        self._port.show_message(tr(DOPPLER_CAL_VELOCITY_KEY), False)
        self.sync_manual_calibration_hint()

    def tick_time_span_ms(self, roi: DopplerSpectrogramRoi) -> float | None:
        """Time window of ``roi`` measured from the visible tick lattice."""
        frame = self._port.frame()
        if frame is None or roi.width <= 0.0:
            return None
        try:
            scales = detect_samsung_doppler_scales(frame)
        except Exception as exc:  # noqa: BLE001 - detector failure must not block calibration
            log_boundary_failure(logger, "doppler.tick_time", exc, code="blocked", level=logging.DEBUG)
            return None
        if scales.time_scale.confidence < 0.3 or scales.time_scale.spacing_px <= 0.0:
            return None
        span_ms = self._time_span_from_spacing_px(scales.time_scale.spacing_px, float(roi.width))
        return span_ms if span_ms > 0.0 else None

    def prompt_spectral_velocity_span(self, length_px: float) -> None:
        default_span = self._cal_kind.default_velocity_span_cm_s
        if self._pending_auto_velocity_span is not None:
            default_span = self._pending_auto_velocity_span
        elif self._calibration_state is not None and self._calibration_state.has_velocity_scale():
            default_span = self._calibration_state.velocity_span_cm_s
        default_span = min(max(float(default_span), 0.01), 1000000.0)

        span_cm_s, accepted = self._port.ask_double(
            tr("viewer.calibration_spectral_title"),
            tr("viewer.calibration_spectral_prompt"),
            default_span,
            0.01,
            1000000.0,
            2,
        )
        self._port.clear_calibration_caliper()
        frame = self._port.frame()
        if not accepted or frame is None or span_cm_s <= 0.0:
            return

        height, width = frame.shape[:2]
        roi = (
            self._pending_roi
            if self._pending_roi is not None
            else DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(width), height=max(1.0, float(height)))
        )
        baseline_y = self._pending_baseline_y if self._pending_baseline_y is not None else roi.y0 + roi.height / 2.0
        velocity_span = span_cm_s * (roi.height / length_px) if length_px > 1.0 else span_cm_s

        prior = self._calibration_state
        prior_time_span_ms = float(getattr(prior, "time_span_ms", 0.0) or 0.0)
        tick_time = self.tick_time_span_ms(roi)
        if prior_time_span_ms <= 0.0 and tick_time is not None:
            prior_time_span_ms = tick_time

        state = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=velocity_span,
            time_span_ms=prior_time_span_ms,
            kind=self._cal_kind,
        )
        if prior is not None:
            state = replace(
                state,
                time_origin_ms=prior.time_origin_ms,
                time_from_dicom_tags=prior.time_from_dicom_tags,
            )
        self._velocity_confirmed = True
        self.apply_calibration_state(state)
        self._pending_roi = None
        self._pending_baseline_y = None
        self._pending_velocity_span = None
        self._pending_auto_velocity_span = None
        self._port.show_message(tr("viewer.doppler_calibration_complete"), False)
        if not self._port.syncing():
            self.spectral_calibration_completed.emit(velocity_span)

    # -- tools, traces, workflows, envelope & cardiac cycles -----------------

    def start_mitral_inflow_workflow(self) -> bool:
        if self._port.frame() is None:
            return False
        self._port.cancel_tool()
        self.overlay.start_mitral_inflow_workflow()
        prompt = self.overlay.workflow_prompt()
        if prompt:
            self._port.show_message(prompt, False)
            self._port.set_hint(prompt)
        return True

    def workflow_active(self) -> bool:
        return self.overlay.workflow_prompt() is not None

    def _on_workflow_step_changed(self, prompt: str) -> None:
        self._port.show_message(prompt, False)
        self._port.set_hint(prompt)

    def _on_workflow_completed(self) -> None:
        done_text = tr("viewer.mitral_inflow_done")
        self._port.show_message(done_text, False)
        self._port.set_hint(done_text)

    def _on_trace_prompt_changed(self, prompt: str) -> None:
        self._port.show_message(prompt, False)
        self._port.set_hint(prompt)

    def _on_autovti_region_selected(self, t_start_ms: float, t_end_ms: float, direction: str) -> None:
        trace_label = self.overlay.trace_label()
        self.start_vti_auto_trace_with_region(t_start_ms, t_end_ms, direction, trace_label=trace_label)

    def restore_measurements(self, dto: object) -> None:
        if isinstance(dto, DopplerMeasurementDTO):
            self.overlay.load_measurement_dto(dto)

    def clear_measurements(self) -> None:
        self.overlay.clear_measurements(keep_calibration_graphics=False)

    def start_envelope_trace(
        self,
        plot_points: Sequence[tuple[float, float]],
        *,
        trace_label: str = "VTI",
    ) -> None:
        self.overlay.set_trace_label(trace_label)
        self.overlay.start_trace_from_plot_points(tuple(plot_points), label=trace_label)

    def set_tool_mode(
        self,
        mode: str,
        *,
        peak_label: str | None = None,
        interval_label: str | None = None,
        trace_label: str | None = None,
    ) -> None:
        self._port.cancel_tool()
        self.overlay.set_tool_mode(mode)
        if mode == "peak":
            self.overlay.set_peak_label(peak_label or "E", single_shot=True)
        elif mode == "interval":
            self.overlay.set_interval_label(interval_label or "DT", single_shot=True)
        elif interval_label is not None:
            self.overlay.set_interval_label(interval_label, single_shot=True)
        elif peak_label is not None:
            self.overlay.set_peak_label(peak_label, single_shot=True)
        if trace_label is not None:
            self.overlay.set_trace_label(trace_label)
        if mode != "none":
            prompt = self.overlay.workflow_prompt()
            if prompt:
                self._port.show_message(prompt, False)
            elif mode == "interval" and interval_label == HEART_RATE_INTERVAL_LABEL:
                self._port.show_message(tr("status.doppler_heart_rate_tool"), False)
            elif mode == "trace":
                prompt = self.overlay.trace_prompt()
                self._port.show_message(prompt or tr("viewer.doppler_trace_prompt"), False)
            elif mode == "autovti_region":
                prompt = self.overlay.autovti_region_prompt()
                self._port.show_message(prompt or tr("viewer.doppler_mode_click", mode=mode), False)
            else:
                self._port.show_message(tr("viewer.doppler_mode_click", mode=mode), False)
            self._port.ensure_crosshair_graphics()

    def get_tool_mode(self) -> str:
        return str(self.overlay.get_tool_mode())

    def finish_trace(self) -> bool:
        finished = bool(self.overlay.finish_trace())
        if finished:
            label = str(self.overlay.last_committed_trace_label())
            metrics = self.last_committed_metrics()
            self._port.show_message(self.trace_summary(metrics, label), False)
        else:
            self._port.show_message(tr("viewer.doppler_trace_finish"), False)
        return finished

    @staticmethod
    def trace_summary(metrics: Any, trace_label: str) -> str:
        """Format the transient result overlay with a specific flow label."""
        site = flow_site_from_trace_label(trace_label) or "AV"
        display_site = "xV" if normalize_label(trace_label) in {"vti", "vti_trace"} else site
        flow = metrics.flow(site)
        if flow is None:
            return trace_label
        parts: list[str] = []
        if flow.vti_cm is not None:
            vti_id = "doppler.vti" if display_site == "xV" else flow_measurement_id(site, "VTI")
            parts.append(f"{display_site} VTI: {_fmt(vti_id, flow.vti_cm, 'cm')} cm")
        for name, velocity_cm_s in (("Vmax", flow.vmax_cm_s), ("Vmean", flow.vmean_cm_s)):
            if velocity_cm_s is not None:
                vel_id = "doppler.vmax" if display_site == "xV" else flow_measurement_id(site, name)
                vel_str, unit = format_velocity_measurement(vel_id, velocity_cm_s, flow.mode)
                parts.append(f"{display_site} {name}: {vel_str} {unit}")
        if flow.pgmax_mmhg is not None:
            parts.append(f"{display_site} PGmax: {_fmt('doppler.pg_peak', flow.pgmax_mmhg, 'mmHg')} mmHg")
        if flow.pgmean_mmhg is not None:
            parts.append(f"{display_site} PGmean: {_fmt('doppler.pg_mean', flow.pgmean_mmhg, 'mmHg')} mmHg")
        return " | ".join(parts) or trace_label

    def last_committed_metrics(self) -> Any:
        return compute_doppler_metrics(self.overlay.get_measurement_dto())

    def get_dto(self) -> DopplerMeasurementDTO:
        dto: DopplerMeasurementDTO = self.overlay.get_measurement_dto()
        return dto

    def show_vessel_measurement(self, measurement: Any) -> None:
        self.overlay.show_vessel_measurement(measurement)

    def cardiac_cycles(
        self,
        envelope: tuple[tuple[float, float], ...],
    ) -> tuple[CardiacCycle, ...]:
        """Build cardiac cycles aligned to the envelope's local time axis."""
        instance = self._port.instance_metadata()
        path = getattr(instance, "path", None) if instance is not None else None
        if instance is None or path is None:
            return ()

        try:
            ecg = self._port.read_ecg(path)
        except Exception as exc:  # noqa: BLE001 - missing/unreadable waveform degrades without ECG
            log_boundary_failure(logger, "dicom.waveform", exc, code="invalid", level=logging.DEBUG)
            ecg = None

        mapping: DopplerAxisMapping = self.overlay.axis_mapping()
        times_ms = np.array([mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
        velocities = np.array([mapping.velocity_cm_s_from_y(p[1]) for p in envelope], dtype=np.float64)
        return tuple(
            CardiacCycleService().get_cycles(
                ecg=ecg,
                spectrogram_time_axis_ms=times_ms,
                fallback_signal=velocities,
            )
        )

    def extract_envelope(
        self,
        preset: str = "normal",
        *,
        force_direction: str | None = None,
        time_range_px: tuple[float, float] | None = None,
    ) -> tuple[tuple[float, float], ...]:
        """Extract the spectral envelope from the current Doppler frame."""
        frame = self._port.frame()
        if frame is None:
            return ()
        state = self.get_calibration_state()
        if state is None:
            return ()
        return extract_doppler_envelope(
            frame,
            state.roi,
            state.baseline_y_px,
            preset=preset,
            force_direction=force_direction,
            time_range_px=time_range_px,
        )

    def start_vti_auto_trace(self, trace_label: str = "VTI") -> bool:
        """Commit a cycle-clipped auto-envelope as an editable VTI trace."""
        if self._port.frame() is None:
            return False
        envelope = self.extract_envelope()
        if not envelope or len(envelope) < 2:
            self._port.show_message(tr("viewer.vessel_auto_trace_failed"), True)
            return False
        cycles = self.cardiac_cycles(envelope)
        if not self.overlay.apply_auto_vti_trace(envelope, cycles=cycles, trace_label=trace_label):
            self._port.show_message(tr("viewer.vessel_auto_trace_failed"), True)
            return False
        metrics = self.last_committed_metrics()
        self._port.show_message(self.trace_summary(metrics, trace_label), True)
        return True

    def start_vti_auto_trace_with_region(
        self,
        t_start_ms: float,
        t_end_ms: float,
        direction: str,
        trace_label: str = "VTI",
    ) -> bool:
        """Auto-extract VTI envelope within a user-defined time range."""
        if self._port.frame() is None:
            return False
        mapping: DopplerAxisMapping = self.overlay.axis_mapping()
        envelope = self.extract_envelope(
            force_direction=direction,
            time_range_px=(mapping.x_from_time_ms(t_start_ms), mapping.x_from_time_ms(t_end_ms)),
        )
        if not envelope or len(envelope) < 2:
            self._port.show_message(tr("viewer.vessel_auto_trace_failed"), True)
            return False
        if not self.overlay.apply_auto_vti_trace(
            envelope,
            cycles=(),
            trace_label=trace_label,
            time_range_ms=(t_start_ms, t_end_ms),
        ):
            self._port.show_message(tr("viewer.vessel_auto_trace_failed"), True)
            return False
        metrics = self.last_committed_metrics()
        self._port.show_message(self.trace_summary(metrics, trace_label), True)
        return True

    # -- mouse, cursor & caliper-zone hooks ----------------------------------

    def update_interval_preview(self, x: float) -> None:
        if self.overlay.get_tool_mode() == "interval" and self.overlay.has_pending_interval_start():
            self.overlay.update_interval_preview_position(x)

    def handle_mouse_click(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        if self.overlay.get_tool_mode() == "none" and self.overlay.vessel_status() != "none":
            handled = bool(self.overlay.handle_vessel_click(click[0], click[1]))
            if handled and self.overlay.vessel_status() == "done":
                self._port.show_message(tr("viewer.vessel_done_prompt"), True)
            return handled
        if self.overlay.get_tool_mode() == "none":
            return False
        if self.overlay.get_tool_mode() == "trace" and self.overlay.consume_trace_click_suppression():
            return True
        double = hasattr(ev, "double") and bool(ev.double())
        return bool(self.overlay.handle_click(click[0], click[1], double=double))

    def handle_peak_press(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        return click is not None and bool(self.overlay.begin_peak_drag(*click))

    def handle_peak_drag(self, ev: Any) -> bool:
        left_pressed = ev.button() == Qt.MouseButton.LeftButton or bool(ev.buttons() & Qt.MouseButton.LeftButton)
        if not left_pressed or not self.overlay.has_peak_drag():
            return False
        click = self._port.map_event(ev)
        return click is not None and bool(self.overlay.move_peak_drag(*click))

    def handle_peak_release(self, ev: Any) -> bool:
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        return bool(self.overlay.finish_peak_drag())

    def handle_trace_press(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if self.overlay.get_tool_mode() != "trace":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None or not self.overlay.has_trace_onset():
            return False
        return bool(self.overlay.begin_trace_stroke(click[0], click[1]))

    def handle_trace_drag(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if self.overlay.get_tool_mode() != "trace":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        return bool(self.overlay.extend_trace_stroke(click[0], click[1]))

    def handle_trace_release(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if self.overlay.get_tool_mode() != "trace":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        return bool(self.overlay.end_trace_stroke(click[0], click[1]))

    def handle_vessel_press(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if self.overlay.get_tool_mode() != "none" or self.overlay.vessel_status() != "done":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        return bool(self.overlay.begin_vessel_drag(click[0], click[1]))

    def handle_vessel_drag(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if self.overlay.get_tool_mode() != "none" or self.overlay.vessel_status() != "done":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        self.overlay.move_vessel_caliper(click[0], click[1])
        return True

    def handle_vessel_release(self, ev: Any) -> bool:
        if self._cal_step is not None or self._port.calibration_active():
            return False
        if self.overlay.get_tool_mode() != "none" or self.overlay.vessel_status() != "done":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        self.overlay.finish_vessel_drag()
        return True

    def remove_measurement_at_cursor(self) -> bool:
        """Delete the Doppler measurement under the last cursor position."""
        cursor = self._port.last_cursor_xy()
        if cursor is None:
            return False
        return bool(self.overlay.remove_measurement_near(cursor[0], cursor[1]))

    def caliper_zone(self) -> DopplerSpectrogramRoi | None:
        """Region where the generic caliper measures time/velocity, not distance."""
        state = self._calibration_state
        if (
            state is not None
            and self.calibration_matches_instance()
            and (state.has_time_scale() or state.has_velocity_scale())
        ):
            return state.roi
        panels = self._port.resolve_panels()
        if panels is not None and panels.doppler is not None:
            panel = panels.doppler
            if panel.horizontal_ms_per_pixel is not None or panel.vertical_cm_s_per_pixel is not None:
                return panel.bounds
        return None

    def caliper_measurement(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        label: str,
    ) -> LinearMeasurement | None:
        """Time/velocity caliper when both points lie inside the Doppler ROI."""
        if not label.startswith(_GENERIC_DIST_LABEL_PREFIX):
            return None
        time_ms: float | None = None
        velocity_cm_s: float | None = None
        state = self._calibration_state
        if (
            state is not None
            and self.calibration_matches_instance()
            and (state.has_time_scale() or state.has_velocity_scale())
            and state.roi.contains(start[0], start[1])
            and state.roi.contains(end[0], end[1])
        ):
            mapping = build_axis_mapping(state)
            if state.has_time_scale():
                time_ms = abs(mapping.time_ms_from_x(end[0]) - mapping.time_ms_from_x(start[0]))
            if state.velocity_span_cm_s > 0.0:
                velocity_cm_s = abs(mapping.velocity_cm_s_from_y(end[1]) - mapping.velocity_cm_s_from_y(start[1]))
            elif state.velocity_per_pixel_cm_s:
                velocity_cm_s = abs(end[1] - start[1]) * abs(state.velocity_per_pixel_cm_s)
        else:
            panels = self._port.resolve_panels()
            panel = panels.doppler if panels is not None else None
            if (
                panel is not None
                and panel.contains(start[0], start[1])
                and panel.contains(end[0], end[1])
                and (panel.horizontal_ms_per_pixel is not None or panel.vertical_cm_s_per_pixel is not None)
            ):
                if panel.horizontal_ms_per_pixel is not None:
                    time_ms = abs(end[0] - start[0]) * panel.horizontal_ms_per_pixel
                if panel.vertical_cm_s_per_pixel is not None:
                    velocity_cm_s = abs(end[1] - start[1]) * panel.vertical_cm_s_per_pixel
        if time_ms is None and velocity_cm_s is None:
            return None
        instance_uid = self._port.instance_uid() or ""
        return LinearMeasurement(
            label=label,
            pixel_length=math.hypot(end[0] - start[0], end[1] - start[1]),
            millimeter_length=None,
            frame_index=self._port.contour_frame_index(),
            start=start,
            end=end,
            sop_instance_uid=instance_uid,
            time_ms=time_ms,
            velocity_cm_s=velocity_cm_s,
            doppler=True,
            doppler_mode=self.resolved_mode(),
        )
