"""Doppler peak/interval/trace overlays on a 2D viewer plot (pixel coordinates)."""

from __future__ import annotations

import statistics

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.calculations.vessel_metrics import (
    VesselMetrics,
    compute_vessel_metrics,
)
from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.cardiac_cycle_service import (
    CardiacCycle,
    derive_psv_edv_indices_per_cycle,
    derive_psv_edv_indices_with_cycles,
)
from echo_personal_tool.domain.services.doppler_trace_points import (
    filter_velocity_spikes,
    finalize_vti_trace_points,
)

_BASELINE_CLICK_TOLERANCE_PX = 8.0
_TRACE_MIN_SAMPLE_PX = 4.0


class _PeakScatterItem(pg.ScatterPlotItem):
    """Scatter item that owns Vpeak drag events instead of the ViewBox."""

    def __init__(self, owner) -> None:
        super().__init__(
            size=10,
            pen=pg.mkPen("#ff6f00", width=2),
            brush=pg.mkBrush("#ffb74d"),
            symbol="o",
        )
        self._owner = owner
        # Let the ViewBox own the press/drag sequence. ScatterPlotItem can
        # consume the initial press without forwarding a drag event.
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        view = self.getViewBox()
        point = view.mapSceneToView(ev.scenePos()) if view is not None else None
        if point is None or not self._owner.begin_peak_drag(float(point.x()), float(point.y())):
            ev.ignore()
            return
        ev.accept()

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        view = self.getViewBox()
        point = view.mapSceneToView(ev.scenePos()) if view is not None else None
        if point is None or not self._owner.move_peak_drag(float(point.x()), float(point.y())):
            ev.ignore()
            return
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.LeftButton and self._owner.finish_peak_drag():
            ev.accept()
            return
        ev.ignore()


_PEAK_LABELS = ("E", "A", "e_sept", "e_lat", "a_sept", "s_sept", "s_lat", "Vmax", "TR Vmax", "s_prime_rv")
_INTERVAL_LABELS = ("DT", "IVRT", "AT")
_MITRAL_INFLOW_WORKFLOW: tuple[tuple[str, str], ...] = (
    ("peak", "E"),
    ("interval", "DT"),
    ("peak", "A"),
)
_TRACE_LABELS = (
    "VTI",
    "VTI MV",
    "VTI MR",
    "VTI AV",
    "VTI AR",
    "VTI TR",
    "VTI PR",
)


class DopplerOverlayTools(QWidget):
    """Place Doppler markers on the same PyQtGraph view as the 2D frame."""

    markers_changed = Signal(object)
    workflow_step_changed = Signal(str)
    workflow_completed = Signal()
    trace_prompt_changed = Signal(str)
    vessel_changed = Signal(object)
    autovti_region_selected = Signal(float, float, str)

    def __init__(self, plot: pg.PlotWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = plot
        self._axis_mapping = DopplerAxisMapping.poc_default()

        self._roi_item = pg.PlotDataItem(pen=pg.mkPen("#90caf9", width=1))
        self._roi_item.setZValue(5)
        self._plot.addItem(self._roi_item)

        self._baseline_item = pg.PlotDataItem(pen=pg.mkPen("#78909c", width=1, style=Qt.PenStyle.DashLine))
        self._baseline_item.setZValue(6)
        self._plot.addItem(self._baseline_item)

        self._peak_scatter = _PeakScatterItem(self)
        self._peak_scatter.setZValue(20)
        self._plot.addItem(self._peak_scatter)

        self._interval_items: list[pg.PlotDataItem] = []
        self._interval_preview_item: pg.PlotDataItem | None = None

        self._trace_item = pg.PlotDataItem(
            pen=pg.mkPen("#1565c0", width=2),
            brush=pg.mkBrush(21, 101, 192, 70),
        )
        self._trace_item.setZValue(15)
        self._plot.addItem(self._trace_item)
        self._trace_items: list[pg.PlotDataItem] = []

        self._tool_mode = "none"
        self._active_partial_points: list[tuple[float, float]] = []
        self._active_interval_start: float | None = None
        self._peak_label_index = 0
        self._interval_label_index = 0
        self._trace_label = "VTI"
        self._peak_markers: list[DopplerPeakMarker] = []
        self._peak_drag_index: int | None = None
        self._interval_markers: list[DopplerIntervalMarker] = []
        self._traces: list[DopplerTrace] = []
        self._single_shot_peak = True
        self._single_shot_interval = True
        self._workflow: tuple[tuple[str, str], ...] | None = None
        self._workflow_index = 0
        self._trace_stroke_active = False
        self._trace_suppress_click = False
        self._trace_last_plot_xy: tuple[float, float] | None = None

        self._vessel_mode: str = "none"  # "none" | "psv" | "edv" | "done"
        self._vessel_psv_px: tuple[float, float] | None = None
        self._vessel_edv_px: tuple[float, float] | None = None
        self._vessel_drag_target: str | None = None
        self._vessel_cycle_source: str | None = None
        self._vessel_averaged_cycles: int = 1
        self._vessel_cycles: tuple[CardiacCycle, ...] = ()
        self._vessel_cycle_psv_candidates: tuple[tuple[float, float], ...] = ()
        self._vessel_cycle_index: int = 0
        self._vessel_cycle_selection: bool = False
        self._vessel_points: pg.ScatterPlotItem | None = None
        self._vessel_text_item: pg.TextItem | None = None
        self._auto_envelope_item: pg.PlotDataItem | None = None
        self._auto_peak_guide_item: pg.PlotDataItem | None = None
        self._vessel_cycle_band: pg.PlotDataItem | None = None
        self._vessel_cycle_text: pg.TextItem | None = None

        self._autovti_start_ms: float | None = None
        self._autovti_direction: str | None = None
        self._autovti_region_item: pg.PlotCurveItem | None = None
        self._autovti_band_item: pg.PlotDataItem | None = None

    def set_axis_mapping(self, mapping: DopplerAxisMapping) -> None:
        self._axis_mapping = mapping
        self._refresh_calibration_graphics()
        self._refresh_peak_scatter()
        self._redraw_intervals()
        self._redraw_traces()
        self._redraw_vessel_graphics()

    def axis_mapping(self) -> DopplerAxisMapping:
        return self._axis_mapping

    def set_tool_mode(self, mode: str) -> None:
        mode_name = mode.strip().lower()
        if mode_name not in {"none", "peak", "interval", "trace", "autovti_region"}:
            raise ValueError(f"Unsupported Doppler tool mode: {mode}")
        if mode_name != self._tool_mode:
            self._clear_partial_state()
        self._tool_mode = mode_name
        if mode_name == "trace":
            self._emit_trace_prompt()
        elif mode_name == "autovti_region":
            self._emit_autovti_prompt()

    def has_trace_onset(self) -> bool:
        return bool(self._active_partial_points)

    def trace_prompt(self) -> str | None:
        if self._tool_mode != "trace":
            return None
        from echo_personal_tool.infrastructure.i18n import tr

        if not self._active_partial_points:
            return f"{self._trace_label}: {tr('doppler.trace_click_baseline')}"
        if self._trace_stroke_active:
            return f"{self._trace_label}: {tr('doppler.trace_draw_envelope')}"
        if len(self._active_partial_points) < 3:
            return f"{self._trace_label}: {tr('doppler.trace_trace_spectrum')}"
        return f"{self._trace_label}: {tr('doppler.trace_click_end')}"

    def consume_trace_click_suppression(self) -> bool:
        if not self._trace_suppress_click:
            return False
        self._trace_suppress_click = False
        return True

    def begin_trace_stroke(self, x_px: float, y_px: float) -> bool:
        if self._tool_mode != "trace" or not self._active_partial_points:
            return False
        self._trace_stroke_active = True
        if not (self._is_near_baseline(y_px) and len(self._active_partial_points) >= 2):
            self._extend_trace_sample(x_px, y_px)
        self._emit_trace_prompt()
        return True

    def extend_trace_stroke(self, x_px: float, y_px: float) -> bool:
        if self._tool_mode != "trace" or not self._trace_stroke_active:
            return False
        self._extend_trace_sample(x_px, y_px)
        return True

    def end_trace_stroke(self, x_px: float, y_px: float) -> bool:
        if self._tool_mode != "trace" or not self._trace_stroke_active:
            return False
        self._trace_stroke_active = False
        self._trace_suppress_click = True
        self._extend_trace_sample(x_px, y_px)
        if self._is_near_baseline(y_px) and len(self._active_partial_points) >= 2:
            self._close_trace_at(self._axis_mapping.time_ms_from_x(x_px))
            finished = self.finish_trace()
            self._emit_trace_prompt()
            return finished
        self._emit_trace_prompt()
        return True

    def get_tool_mode(self) -> str:
        return self._tool_mode

    def set_trace_label(self, label: str) -> None:
        normalized = label.strip() or "VTI"
        if normalized not in _TRACE_LABELS:
            self._trace_label = normalized
            return
        self._trace_label = normalized

    def last_committed_trace_label(self) -> str:
        if not self._traces:
            return self._trace_label
        return self._traces[-1].label

    def trace_label(self) -> str:
        return self._trace_label

    def cancel_active_tool(self) -> bool:
        had_active_state = (
            self._tool_mode != "none"
            or bool(self._active_partial_points)
            or self._active_interval_start is not None
            or self._autovti_start_ms is not None
            or self._autovti_band_item is not None
        )
        self._tool_mode = "none"
        self._workflow = None
        self._workflow_index = 0
        self._clear_partial_state()
        return had_active_state

    def set_peak_label(self, label: str, *, single_shot: bool = True) -> None:
        self._peak_label_index = self._resolve_label_index(label, _PEAK_LABELS)
        self._single_shot_peak = single_shot

    def set_interval_label(self, label: str, *, single_shot: bool = True) -> None:
        self._interval_label_index = self._resolve_label_index(label, _INTERVAL_LABELS)
        self._single_shot_interval = single_shot

    def prefill_interval_start(self, time_ms: float) -> None:
        self._active_interval_start = float(time_ms)
        self._refresh_interval_preview()

    def start_mitral_inflow_workflow(self) -> None:
        self._workflow = _MITRAL_INFLOW_WORKFLOW
        self._workflow_index = 0
        self._activate_workflow_step()

    def workflow_prompt(self) -> str | None:
        if self._workflow is None:
            return None
        if self._workflow_index >= len(self._workflow):
            return None
        from echo_personal_tool.infrastructure.i18n import tr

        mode, label = self._workflow[self._workflow_index]
        if mode == "peak":
            return f"Mitral inflow: {tr('doppler.peak', label=label)}"
        if mode == "interval":
            if self._active_interval_start is not None:
                return f"Mitral inflow: {label} — {tr('doppler.interval_click_end')}"
            return f"Mitral inflow: {label} — {tr('doppler.interval_click_start')}"
        return None

    def finish_trace(self) -> bool:
        if len(self._active_partial_points) < 3:
            return False
        if not self._trace_last_point_on_baseline():
            return False

        finalized = finalize_vti_trace_points(self._active_partial_points)
        if len(finalized) < 3:
            return False

        self._append_trace(DopplerTrace(label=self._trace_label, points=finalized))
        self._clear_partial_state()
        self._tool_mode = "none"
        self.markers_changed.emit(self._build_measurement_dto())
        return True

    def _append_trace(self, trace: DopplerTrace) -> None:
        """Append a committed trace and draw its filled envelope."""
        self._traces.append(trace)

        completed_item = pg.PlotDataItem(
            pen=pg.mkPen("#1565c0", width=2),
            brush=pg.mkBrush(21, 101, 192, 70),
        )
        completed_item.setZValue(15)
        xs = [self._axis_mapping.x_from_time_ms(point[0]) for point in trace.points]
        ys = [self._axis_mapping.y_from_velocity_cm_s(point[1]) for point in trace.points]
        completed_item.setFillLevel(self._baseline_plot_y_px())
        completed_item.setData(xs, ys)
        self._plot.addItem(completed_item)
        self._trace_items.append(completed_item)

    def start_trace_from_plot_points(
        self,
        plot_points: tuple[tuple[float, float], ...],
        *,
        label: str | None = None,
    ) -> None:
        """Load semi-auto envelope as editable trace (plot x/y pixels)."""
        if len(plot_points) < 2:
            return
        if label is not None:
            self._trace_label = label
        mapped = []
        for x_px, y_px in plot_points:
            mapped.append(
                (
                    self._axis_mapping.time_ms_from_x(x_px),
                    self._axis_mapping.velocity_cm_s_from_y(y_px),
                )
            )
        self._active_partial_points = mapped
        x_values = [point[0] for point in plot_points]
        y_values = [point[1] for point in plot_points]
        self._trace_item.setData(x_values, y_values)
        self._tool_mode = "trace"

    def get_measurement_dto(self) -> DopplerMeasurementDTO:
        return self._build_measurement_dto()

    def load_measurement_dto(self, dto: DopplerMeasurementDTO) -> None:
        self.clear_measurements(keep_calibration_graphics=True)
        self._peak_markers = list(dto.peaks)
        self._interval_markers = list(dto.intervals)
        self._traces = list(dto.traces)
        self._refresh_peak_scatter()
        self._redraw_intervals()
        self._redraw_traces()

    def clear_measurements(self, *, keep_calibration_graphics: bool = False) -> None:
        self._peak_markers.clear()
        self._peak_drag_index = None
        self._interval_markers.clear()
        self._traces.clear()
        self._peak_scatter.setData([], [])

        for item in self._interval_items:
            self._plot.removeItem(item)
        self._interval_items.clear()
        self._clear_interval_preview()

        for item in self._trace_items:
            self._plot.removeItem(item)
        self._trace_items.clear()

        self._clear_partial_state()
        self._tool_mode = "none"
        self._workflow = None
        self._workflow_index = 0
        self.clear_vessel()
        if not keep_calibration_graphics:
            self._roi_item.setData([], [])
            self._baseline_item.setData([], [])

    def handle_click(self, x_px: float, y_px: float, *, double: bool = False) -> bool:
        if self._tool_mode == "none":
            return False
        if self._tool_mode == "trace":
            if self.consume_trace_click_suppression():
                return True
            if double and self._is_near_baseline(y_px):
                time_ms = self._axis_mapping.time_ms_from_x(x_px)
                return self._handle_trace_click(time_ms, 0.0, y_px=y_px)
            if double:
                return self.finish_trace()
            time_ms = self._axis_mapping.time_ms_from_x(x_px)
            velocity_cm_s = self._axis_mapping.velocity_cm_s_from_y(y_px)
            return self._handle_trace_click(time_ms, velocity_cm_s, y_px=y_px)
        if self._tool_mode == "autovti_region":
            return self._handle_autovti_click(x_px, y_px)

        time_ms = self._axis_mapping.time_ms_from_x(x_px)
        velocity_cm_s = self._axis_mapping.velocity_cm_s_from_y(y_px)
        return self._handle_mapped_click(time_ms, velocity_cm_s, x_px=x_px, y_px=y_px)

    def begin_peak_drag(self, x_px: float, y_px: float) -> bool:
        """Start moving the nearest existing peak marker."""
        if self._tool_mode != "none":
            return False
        for index in reversed(range(len(self._peak_markers))):
            marker = self._peak_markers[index]
            marker_xy = (
                self._axis_mapping.x_from_time_ms(marker.time_ms),
                self._axis_mapping.y_from_velocity_cm_s(marker.velocity_cm_s),
            )
            if _near_point(x_px, y_px, marker_xy):
                self._peak_drag_index = index
                return True
        return False

    def move_peak_drag(self, x_px: float, y_px: float) -> bool:
        """Move the active peak and emit updated physical measurements."""
        if self._peak_drag_index is None:
            return False
        index = self._peak_drag_index
        self._peak_markers[index] = DopplerPeakMarker(
            label=self._peak_markers[index].label,
            time_ms=self._axis_mapping.time_ms_from_x(float(x_px)),
            velocity_cm_s=self._axis_mapping.velocity_cm_s_from_y(float(y_px)),
        )
        self._refresh_peak_scatter()
        self._emit_markers_changed()
        return True

    def finish_peak_drag(self) -> bool:
        if self._peak_drag_index is None:
            return False
        self._peak_drag_index = None
        return True

    def has_peak_drag(self) -> bool:
        return self._peak_drag_index is not None

    def set_vessel_mode(self) -> None:
        self.set_tool_mode("none")
        self._vessel_mode = "psv"

    def vessel_status(self) -> str:
        return self._vessel_mode

    def get_vessel_values(self) -> tuple[float, float] | None:
        if self._vessel_psv_px is None or self._vessel_edv_px is None:
            return None
        psv = self._axis_mapping.velocity_cm_s_from_y(self._vessel_psv_px[1])
        edv = self._axis_mapping.velocity_cm_s_from_y(self._vessel_edv_px[1])
        return psv, edv

    def get_vessel_metrics(self) -> VesselMetrics | None:
        values = self.get_vessel_values()
        if values is None:
            return None
        psv, edv = values
        return compute_vessel_metrics(psv, edv)

    def handle_vessel_click(self, x_px: float, y_px: float) -> bool:
        if self._vessel_mode not in {"psv", "edv"}:
            return False
        if self._vessel_mode == "psv":
            self._vessel_psv_px = (float(x_px), float(y_px))
            self._vessel_mode = "edv"
        else:
            self._vessel_edv_px = (float(x_px), float(y_px))
            self._vessel_mode = "done"
        self._redraw_vessel_graphics()
        self._emit_vessel_changed()
        return True

    def move_vessel_caliper(self, x_px: float, y_px: float) -> None:
        if self._vessel_drag_target is None:
            return
        if self._vessel_drag_target == "psv" and self._vessel_psv_px is not None:
            self._vessel_psv_px = (float(x_px), float(y_px))
        elif self._vessel_drag_target == "edv" and self._vessel_edv_px is not None:
            self._vessel_edv_px = (float(x_px), float(y_px))
        self._redraw_vessel_graphics()
        self._emit_vessel_changed()

    def finish_vessel_drag(self) -> None:
        self._vessel_drag_target = None

    def begin_vessel_drag(self, x_px: float, y_px: float) -> bool:
        if self._vessel_mode != "done":
            return False
        if self._vessel_psv_px is not None and _near_point(x_px, y_px, self._vessel_psv_px):
            self._vessel_drag_target = "psv"
            return True
        if self._vessel_edv_px is not None and _near_point(x_px, y_px, self._vessel_edv_px):
            self._vessel_drag_target = "edv"
            return True
        return False

    def clear_vessel(self) -> None:
        self._reset_vessel_cycle_selection()
        self._vessel_mode = "none"
        self._vessel_psv_px = None
        self._vessel_edv_px = None
        self._vessel_drag_target = None
        self._vessel_cycle_source = None
        self._vessel_averaged_cycles = 1
        self._clear_auto_envelope()
        self._redraw_vessel_graphics()

    def _clear_auto_envelope(self) -> None:
        if self._auto_envelope_item is not None:
            try:
                self._plot.removeItem(self._auto_envelope_item)
            except Exception:  # noqa: BLE001
                pass
            self._auto_envelope_item = None
        if self._auto_peak_guide_item is not None:
            try:
                self._plot.removeItem(self._auto_peak_guide_item)
            except Exception:  # noqa: BLE001
                pass
            self._auto_peak_guide_item = None

    def _show_auto_peak_guide(self, envelope: tuple[tuple[float, float], ...]) -> None:
        if not envelope:
            return
        baseline_y = self._baseline_plot_y_px()
        if self._envelope_below_baseline(envelope):
            peak_index = max(range(len(envelope)), key=lambda index: envelope[index][1])
        else:
            peak_index = min(range(len(envelope)), key=lambda index: envelope[index][1])
        peak_x, peak_y = envelope[peak_index]
        item = pg.PlotDataItem(
            [peak_x, peak_x],
            [baseline_y, peak_y],
            pen=pg.mkPen("#ff9800", width=2, style=Qt.PenStyle.DashLine),
        )
        item.setZValue(26)
        self._plot.addItem(item)
        self._auto_peak_guide_item = item

    def apply_auto_trace(
        self,
        envelope: tuple[tuple[float, float], ...],
        *,
        cycles: tuple[CardiacCycle, ...] = (),
    ) -> tuple[float, float] | None:
        """Render an auto-traced envelope and derive PSV/EDV markers.

        PSV is taken at the highest-velocity envelope point (minimum plot y),
        EDV at the diastolic minimum after the peak. When *cycles* (from the
        ECG cardiac-cycle service) are given, PSV/EDV are snapped inside the
        ECG cycle containing the systolic peak; otherwise the whole-envelope
        heuristic is used. Returns (psv, edv) in cm/s or None.
        """
        self._reset_vessel_cycle_selection()
        self._clear_auto_envelope()
        if not envelope or len(envelope) < 2:
            return None
        xs = [p[0] for p in envelope]
        ys = [p[1] for p in envelope]
        item = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#00e5ff", width=2))
        item.setZValue(24)
        self._plot.addItem(item)
        self._auto_envelope_item = item

        cycle_snapped = None
        below_baseline = self._envelope_below_baseline(envelope)
        if cycles:
            cycle_snapped = derive_psv_edv_indices_with_cycles(
                envelope,
                cycles,
                self._axis_mapping,
                below_baseline=below_baseline,
            )
        if cycle_snapped is not None:
            psv_idx, edv_idx, edv_value = cycle_snapped
            self._vessel_cycle_source = cycles[0].source
        else:
            psv_idx, edv_idx = derive_psv_edv_indices(
                envelope,
                below_baseline=below_baseline,
            )
            self._vessel_cycle_source = "image"
            edv_value = envelope[edv_idx][1]
        psv_x, psv_y = envelope[psv_idx]
        edv_x = envelope[edv_idx][0]
        psv = self._axis_mapping.velocity_cm_s_from_y(psv_y)
        edv = self._axis_mapping.velocity_cm_s_from_y(edv_value)

        self._vessel_mode = "done"
        self._vessel_psv_px = (psv_x, psv_y)
        self._vessel_edv_px = (edv_x, edv_value)
        self._redraw_vessel_graphics()
        return psv, edv

    def apply_auto_vti_trace(
        self,
        envelope: tuple[tuple[float, float], ...],
        *,
        cycles: tuple[CardiacCycle, ...] = (),
        trace_label: str = "VTI",
        time_range_ms: tuple[float, float] | None = None,
    ) -> bool:
        """Commit a clipped auto-envelope as an editable VTI trace.

        When *time_range_ms* is given, the envelope is clipped to the user-
        selected time span. When ECG *cycles* are given (and no time range),
        the envelope is clipped to the cycle containing the highest-velocity
        sample. Otherwise the whole envelope is used. Returns ``True`` when a
        trace was committed.
        """
        self._clear_auto_envelope()
        if not envelope or len(envelope) < 2:
            return False
        ys = [p[1] for p in envelope]
        clipped = envelope
        if time_range_ms is not None:
            t_start, t_end = time_range_ms
            clipped = tuple(p for p in envelope if t_start <= self._axis_mapping.time_ms_from_x(p[0]) <= t_end)
            if len(clipped) < 3:
                return False
        elif cycles:
            peak_time = self._axis_mapping.time_ms_from_x(envelope[int(np.argmin(ys))][0])
            cycle = next((c for c in cycles if c.start_ms <= peak_time <= c.end_ms), None)
            if cycle is not None:
                clipped = tuple(
                    p for p in envelope if cycle.start_ms <= self._axis_mapping.time_ms_from_x(p[0]) <= cycle.end_ms
                )
                if len(clipped) < 3:
                    return False

        xs = [p[0] for p in clipped]
        ys = [p[1] for p in clipped]
        item = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#00e5ff", width=2))
        item.setZValue(24)
        self._plot.addItem(item)
        self._auto_envelope_item = item

        mapped = [
            (
                self._axis_mapping.time_ms_from_x(point[0]),
                self._axis_mapping.velocity_cm_s_from_y(point[1]),
            )
            for point in clipped
        ]
        roi = self._axis_mapping.roi
        max_velocity = self._axis_mapping.velocity_span_cm_s
        if roi is not None:
            max_velocity = max(
                max_velocity,
                abs(self._axis_mapping.velocity_cm_s_from_y(roi.y0)),
                abs(self._axis_mapping.velocity_cm_s_from_y(roi.y1)),
            )
        filtered = filter_velocity_spikes(mapped, max_velocity_cm_s=max_velocity)
        finalized = finalize_vti_trace_points(filtered)
        if len(finalized) < 3:
            return False
        self._append_trace(DopplerTrace(label=trace_label, points=finalized))
        if trace_label.strip().upper() in {
            "VTI MV",
            "VTI MR",
            "VTI AV",
            "VTI AR",
            "VTI TV",
            "VTI PV",
            "VTI TR",
            "VTI PR",
        }:
            guide_points = tuple(
                (
                    self._axis_mapping.x_from_time_ms(time_ms),
                    self._axis_mapping.y_from_velocity_cm_s(velocity_cm_s),
                )
                for time_ms, velocity_cm_s in finalized
            )
            self._show_auto_peak_guide(guide_points)
        self._tool_mode = "none"
        self.markers_changed.emit(self._build_measurement_dto())
        return True

    def apply_averaged_vessel(
        self,
        envelope: tuple[tuple[float, float], ...],
        *,
        cycles: tuple[CardiacCycle, ...] = (),
        max_beats: int = 3,
    ) -> tuple[float, float] | None:
        """Average PSV/EDV across up to *max_beats* cardiac cycles.

        Per-cycle PSV/EDV are derived inside each cycle's own diastolic window;
        the PSV and EDV are the MEDIANS across the contributing cycles, which
        makes the result robust to one corrupted (artifact) beat. Markers are
        placed at the median velocities on the first beat's times. Stores the
        contributing cycles and per-cycle PSV candidates and activates the
        manual cycle-selection correction mode. Returns ``(psv, edv)`` in cm/s
        or ``None`` when no cycle yields a valid snapshot.
        """
        self._reset_vessel_cycle_selection()
        self._clear_auto_envelope()
        if not envelope or len(envelope) < 2 or not cycles:
            return None
        xs = [p[0] for p in envelope]
        ys = [p[1] for p in envelope]
        item = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#00e5ff", width=2))
        item.setZValue(24)
        self._plot.addItem(item)
        self._auto_envelope_item = item

        per_cycle = derive_psv_edv_indices_per_cycle(
            envelope,
            cycles,
            self._axis_mapping,
            below_baseline=self._envelope_below_baseline(envelope),
            max_cycles=max_beats,
        )
        if not per_cycle:
            return None
        psv_entries = [
            (
                self._axis_mapping.time_ms_from_x(envelope[psv_idx][0]),
                self._axis_mapping.velocity_cm_s_from_y(envelope[psv_idx][1]),
            )
            for psv_idx, _, _, _ in per_cycle
        ]
        edv_values = [self._axis_mapping.velocity_cm_s_from_y(edv_value) for _, _, edv_value, _ in per_cycle]
        psv_median = statistics.median(entry[1] for entry in psv_entries)
        edv_median = statistics.median(edv_values)
        psv_time = envelope[per_cycle[0][0]][0]
        edv_time = envelope[per_cycle[0][1]][0]

        self._vessel_mode = "done"
        self._vessel_psv_px = (psv_time, self._axis_mapping.y_from_velocity_cm_s(psv_median))
        self._vessel_edv_px = (edv_time, self._axis_mapping.y_from_velocity_cm_s(edv_median))
        self._vessel_cycle_source = cycles[0].source
        self._vessel_averaged_cycles = len(per_cycle)
        self._vessel_cycles = tuple(cycles[idx] for _, _, _, idx in per_cycle)
        self._vessel_cycle_psv_candidates = tuple(psv_entries)
        self._vessel_cycle_index = 0
        self._vessel_cycle_selection = True
        self._redraw_vessel_graphics()
        self._redraw_vessel_cycle_graphics()
        return psv_median, edv_median

    def vessel_cycle_source(self) -> str | None:
        return self._vessel_cycle_source

    def vessel_averaged_cycles(self) -> int:
        return self._vessel_averaged_cycles

    def vessel_cycle_selection_active(self) -> bool:
        return self._vessel_cycle_selection and bool(self._vessel_cycle_psv_candidates)

    def vessel_cycle_count(self) -> int:
        return len(self._vessel_cycles)

    def vessel_cycle_index(self) -> int:
        return self._vessel_cycle_index

    def vessel_cycle_candidate(self) -> float | None:
        if not self._vessel_cycle_psv_candidates:
            return None
        if self._vessel_cycle_index < 0 or self._vessel_cycle_index >= len(self._vessel_cycle_psv_candidates):
            return None
        return self._vessel_cycle_psv_candidates[self._vessel_cycle_index][1]

    def move_vessel_cycle(self, delta: int) -> bool:
        if not self._vessel_cycle_selection or not self._vessel_cycles:
            return False
        count = len(self._vessel_cycles)
        self._vessel_cycle_index = (self._vessel_cycle_index + delta) % count
        self._redraw_vessel_cycle_graphics()
        self._emit_vessel_changed()
        return True

    def assign_vessel_cycle_psv(self) -> bool:
        if not self._vessel_cycle_selection or not self._vessel_cycle_psv_candidates:
            return False
        if self._vessel_cycle_index < 0 or self._vessel_cycle_index >= len(self._vessel_cycle_psv_candidates):
            return False
        time_ms, velocity_cm_s = self._vessel_cycle_psv_candidates[self._vessel_cycle_index]
        self._vessel_psv_px = (
            self._axis_mapping.x_from_time_ms(time_ms),
            self._axis_mapping.y_from_velocity_cm_s(velocity_cm_s),
        )
        self._vessel_cycle_selection = False
        self._redraw_vessel_graphics()
        self._emit_vessel_changed()
        return True

    def cancel_vessel_cycle_selection(self) -> bool:
        if not self._vessel_cycle_selection:
            return False
        self._vessel_cycle_selection = False
        self._redraw_vessel_graphics()
        return True

    def _clear_vessel_cycle_graphics(self) -> None:
        if self._vessel_cycle_band is not None:
            try:
                self._plot.removeItem(self._vessel_cycle_band)
            except Exception:  # noqa: BLE001
                pass
            self._vessel_cycle_band = None
        if self._vessel_cycle_text is not None:
            try:
                self._plot.removeItem(self._vessel_cycle_text)
            except Exception:  # noqa: BLE001
                pass
            self._vessel_cycle_text = None

    def _reset_vessel_cycle_selection(self) -> None:
        self._clear_vessel_cycle_graphics()
        self._vessel_cycle_selection = False
        self._vessel_cycles = ()
        self._vessel_cycle_psv_candidates = ()
        self._vessel_cycle_index = 0

    def _redraw_vessel_cycle_graphics(self) -> None:
        self._clear_vessel_cycle_graphics()
        if not self._vessel_cycle_selection or not self._vessel_cycles:
            return
        index = min(max(self._vessel_cycle_index, 0), len(self._vessel_cycles) - 1)
        cycle = self._vessel_cycles[index]
        x_start = self._axis_mapping.x_from_time_ms(cycle.start_ms)
        x_end = self._axis_mapping.x_from_time_ms(cycle.end_ms)
        top = -1.0
        bottom = self._axis_mapping.plot_height + 1.0
        band = pg.PlotDataItem(
            [x_start, x_end],
            [top, top],
            pen=pg.mkPen(255, 235, 59, 40),
            brush=pg.mkBrush(255, 235, 59, 40),
        )
        band.setZValue(23)
        band.setFillLevel(bottom)
        self._plot.addItem(band)
        self._vessel_cycle_band = band
        candidate = self.vessel_cycle_candidate()
        if candidate is not None:
            label = pg.TextItem(f"PSV кандидат: {candidate:.1f} cm/s", anchor=(0.0, 0.0), fill=(0, 0, 0, 200))
            label.setZValue(30)
            label.setPos(x_start, top + 2)
            self._plot.addItem(label)
            self._vessel_cycle_text = label

    def show_vessel_measurement(self, measurement: VesselMeasurement) -> None:
        self._vessel_mode = "done"
        self._vessel_cycle_source = getattr(measurement, "cycle_source", "manual")
        self._vessel_averaged_cycles = getattr(measurement, "averaged_cycles", 1)
        psv_y = self._axis_mapping.y_from_velocity_cm_s(measurement.psv_cm_s)
        edv_y = self._axis_mapping.y_from_velocity_cm_s(measurement.edv_cm_s)
        self._vessel_psv_px = (0.0, psv_y)
        self._vessel_edv_px = (0.0, edv_y)
        self._redraw_vessel_graphics()

    def _redraw_vessel_graphics(self) -> None:
        if self._vessel_points is not None:
            self._plot.removeItem(self._vessel_points)
            self._vessel_points = None
        if self._vessel_text_item is not None:
            self._plot.removeItem(self._vessel_text_item)
            self._vessel_text_item = None

        spots = []
        if self._vessel_psv_px is not None:
            spots.append({"pos": self._vessel_psv_px, "data": "PSV"})
        if self._vessel_edv_px is not None:
            spots.append({"pos": self._vessel_edv_px, "data": "EDV"})
        if spots:
            self._vessel_points = pg.ScatterPlotItem(size=10, pen=pg.mkPen("#ffffff", width=1))
            self._vessel_points.setZValue(25)
            self._vessel_points.setData(spots)
            self._plot.addItem(self._vessel_points)

        values = self.get_vessel_values()
        metrics = self.get_vessel_metrics()
        if values is not None and metrics is not None:
            psv, edv = values
            self._vessel_text_item = _build_vessel_text(psv, edv, metrics)
            roi = self._axis_mapping.roi
            if roi is not None:
                self._vessel_text_item.setPos(roi.x1, roi.y0)
            else:
                self._vessel_text_item.setPos(self._axis_mapping.plot_width, 0.0)
            self._plot.addItem(self._vessel_text_item)

        self._redraw_vessel_cycle_graphics()

    def _emit_vessel_changed(self) -> None:
        self.vessel_changed.emit(self.get_vessel_metrics())

    def _build_measurement_dto(self) -> DopplerMeasurementDTO:
        return DopplerMeasurementDTO(
            peaks=tuple(self._peak_markers),
            intervals=tuple(self._interval_markers),
            traces=tuple(self._traces),
        )

    def _clear_partial_state(self) -> None:
        self._active_partial_points = []
        self._active_interval_start = None
        self._trace_stroke_active = False
        self._trace_suppress_click = False
        self._trace_last_plot_xy = None
        self._peak_drag_index = None
        self._trace_item.setData([], [])
        self._clear_interval_preview()
        self._clear_autovti_region()

    def _clear_interval_preview(self) -> None:
        if self._interval_preview_item is not None:
            self._interval_preview_item.setData([], [])
            if self._interval_preview_item.scene() is not None:
                self._plot.removeItem(self._interval_preview_item)

    def _resolve_label_index(self, label: str, labels: tuple[str, ...]) -> int:
        normalized = label.strip()
        if normalized not in labels:
            raise ValueError(f"Unsupported label: {label}")
        return labels.index(normalized)

    def _current_peak_label(self) -> str:
        return _PEAK_LABELS[self._peak_label_index]

    def _current_interval_label(self) -> str:
        return _INTERVAL_LABELS[self._interval_label_index]

    def _advance_peak_label(self) -> None:
        if self._single_shot_peak:
            return
        self._peak_label_index = (self._peak_label_index + 1) % len(_PEAK_LABELS)

    def _advance_interval_label(self) -> None:
        if self._single_shot_interval:
            return
        self._interval_label_index = (self._interval_label_index + 1) % len(_INTERVAL_LABELS)

    def _find_peak_time(self, label: str) -> float | None:
        for marker in reversed(self._peak_markers):
            if marker.label == label:
                return marker.time_ms
        return None

    def _activate_workflow_step(self) -> None:
        if self._workflow is None or self._workflow_index >= len(self._workflow):
            self._workflow = None
            self._tool_mode = "none"
            self.workflow_completed.emit()
            return
        mode, label = self._workflow[self._workflow_index]
        self._tool_mode = mode
        if mode == "peak":
            self.set_peak_label(label, single_shot=True)
        elif mode == "interval":
            self.set_interval_label(label, single_shot=True)
            self._active_interval_start = None
            if label == "DT":
                e_time = self._find_peak_time("E")
                if e_time is not None:
                    self.prefill_interval_start(e_time)
        prompt = self.workflow_prompt()
        if prompt:
            self.workflow_step_changed.emit(prompt)

    def _complete_workflow_step(self) -> None:
        if self._workflow is None:
            return
        self._workflow_index += 1
        self._activate_workflow_step()

    def _emit_markers_changed(self) -> None:
        self.markers_changed.emit(self._build_measurement_dto())

    def _refresh_calibration_graphics(self) -> None:
        mapping = self._axis_mapping
        roi = mapping.roi
        if roi is not None:
            xs = [roi.x0, roi.x1, roi.x1, roi.x0, roi.x0]
            ys = [roi.y0, roi.y0, roi.y1, roi.y1, roi.y0]
            self._roi_item.setData(xs, ys)
        else:
            self._roi_item.setData([], [])

        if not mapping.has_roi_calibration:
            self._baseline_item.setData([], [])
            return

        baseline_y = mapping.baseline_plot_y()
        if baseline_y is not None and roi is not None:
            self._baseline_item.setData([roi.x0, roi.x1], [baseline_y, baseline_y])
        else:
            self._baseline_item.setData([], [])

    def _refresh_peak_scatter(self) -> None:
        spots = [
            {
                "pos": (
                    self._axis_mapping.x_from_time_ms(marker.time_ms),
                    self._axis_mapping.y_from_velocity_cm_s(marker.velocity_cm_s),
                ),
                "data": marker.label,
            }
            for marker in self._peak_markers
        ]
        self._peak_scatter.setData(spots)

    def _baseline_y_for_interval(self) -> float:
        baseline = self._axis_mapping.baseline_plot_y()
        if baseline is not None:
            return baseline
        return self._axis_mapping.plot_height * 0.5

    def _ensure_interval_preview_item(self) -> pg.PlotDataItem:
        if self._interval_preview_item is None:
            self._interval_preview_item = pg.PlotDataItem(
                pen=pg.mkPen("#00897b", width=3, style=Qt.PenStyle.DashLine),
                symbol="t",
                symbolSize=10,
                symbolBrush=pg.mkBrush("#00897b"),
            )
            self._interval_preview_item.setZValue(19)
            self._plot.addItem(self._interval_preview_item)
        return self._interval_preview_item

    def _refresh_interval_preview(self, *, end_x_px: float | None = None) -> None:
        if self._active_interval_start is None:
            self._clear_interval_preview()
            return
        x_start = self._axis_mapping.x_from_time_ms(self._active_interval_start)
        y_base = self._baseline_y_for_interval()
        preview = self._ensure_interval_preview_item()
        if end_x_px is None:
            tick_half = 6.0
            preview.setData(
                [x_start, x_start],
                [y_base - tick_half, y_base + tick_half],
            )
            return
        x_end = float(end_x_px)
        tick_half = 6.0
        xs: list[float] = [x_start, x_end]
        ys: list[float] = [y_base, y_base]
        for x_tick in (x_start, x_end):
            xs.extend([x_tick, x_tick])
            ys.extend([y_base - tick_half, y_base + tick_half])
        preview.setData(xs, ys)

    def update_interval_preview_position(self, x_px: float) -> None:
        if self._tool_mode != "interval" or self._active_interval_start is None:
            return
        self._refresh_interval_preview(end_x_px=x_px)

    def has_pending_interval_start(self) -> bool:
        return self._active_interval_start is not None

    def _add_interval_item(self, marker: DopplerIntervalMarker) -> None:
        x_start = self._axis_mapping.x_from_time_ms(marker.start_time_ms)
        x_end = self._axis_mapping.x_from_time_ms(marker.end_time_ms)
        y_base = self._baseline_y_for_interval()
        interval_pen = pg.mkPen("#00897b", width=3)
        interval_item = pg.PlotDataItem(
            [x_start, x_end],
            [y_base, y_base],
            pen=interval_pen,
        )
        interval_item.setZValue(18)
        self._plot.addItem(interval_item)
        self._interval_items.append(interval_item)
        tick_half = 6.0
        for x_tick in (x_start, x_end):
            tick_item = pg.PlotDataItem(
                [x_tick, x_tick],
                [y_base - tick_half, y_base + tick_half],
                pen=interval_pen,
            )
            tick_item.setZValue(19)
            self._plot.addItem(tick_item)
            self._interval_items.append(tick_item)

    def _redraw_intervals(self) -> None:
        for item in self._interval_items:
            self._plot.removeItem(item)
        self._interval_items.clear()
        for marker in self._interval_markers:
            self._add_interval_item(marker)

    def _redraw_traces(self) -> None:
        for item in self._trace_items:
            self._plot.removeItem(item)
        self._trace_items.clear()
        for trace in self._traces:
            if len(trace.points) < 2:
                continue
            xs = [self._axis_mapping.x_from_time_ms(point[0]) for point in trace.points]
            ys = [self._axis_mapping.y_from_velocity_cm_s(point[1]) for point in trace.points]
            item = pg.PlotDataItem(
                pen=pg.mkPen("#1565c0", width=2),
                brush=pg.mkBrush(21, 101, 192, 70),
            )
            item.setZValue(15)
            item.setFillLevel(self._baseline_plot_y_px())
            item.setData(xs, ys)
            self._plot.addItem(item)
            self._trace_items.append(item)

    def _add_peak_marker(self, time_ms: float, velocity_cm_s: float) -> None:
        marker = DopplerPeakMarker(
            label=self._current_peak_label(),
            time_ms=float(time_ms),
            velocity_cm_s=float(velocity_cm_s),
        )
        self._peak_markers.append(marker)
        self._refresh_peak_scatter()
        self._advance_peak_label()
        self._emit_markers_changed()
        if self._workflow is not None:
            self._complete_workflow_step()
        elif self._single_shot_peak:
            self._tool_mode = "none"

    def _add_interval_marker(self, end_time_ms: float) -> None:
        start_time_ms = (
            float(self._active_interval_start) if self._active_interval_start is not None else float(end_time_ms)
        )
        marker = DopplerIntervalMarker(
            label=self._current_interval_label(),
            start_time_ms=start_time_ms,
            end_time_ms=float(end_time_ms),
        )
        self._interval_markers.append(marker)
        self._add_interval_item(marker)
        self._active_interval_start = None
        self._clear_interval_preview()
        self._advance_interval_label()
        self._emit_markers_changed()
        if self._workflow is not None:
            self._complete_workflow_step()
        elif self._single_shot_interval:
            self._tool_mode = "none"

    def _add_trace_point(self, time_ms: float, velocity_cm_s: float) -> None:
        self._active_partial_points.append((float(time_ms), float(velocity_cm_s)))
        self._refresh_active_trace_graphics()

    def _refresh_active_trace_graphics(self) -> None:
        x_values = [self._axis_mapping.x_from_time_ms(point[0]) for point in self._active_partial_points]
        y_values = [self._axis_mapping.y_from_velocity_cm_s(point[1]) for point in self._active_partial_points]
        self._trace_item.setFillLevel(self._baseline_plot_y_px())
        self._trace_item.setData(x_values, y_values)

    def _extend_trace_sample(self, x_px: float, y_px: float) -> None:
        if self._trace_last_plot_xy is not None:
            last_x, last_y = self._trace_last_plot_xy
            if ((x_px - last_x) ** 2 + (y_px - last_y) ** 2) ** 0.5 < _TRACE_MIN_SAMPLE_PX:
                return
        time_ms = self._axis_mapping.time_ms_from_x(x_px)
        if self._active_partial_points and self._trace_stroke_active:
            last_time = self._active_partial_points[-1][0]
            if time_ms < last_time - 0.5:
                return
        velocity_cm_s = self._axis_mapping.velocity_cm_s_from_y(y_px)
        self._add_trace_point(time_ms, velocity_cm_s)
        self._trace_last_plot_xy = (float(x_px), float(y_px))

    def _close_trace_at(self, time_ms: float) -> None:
        baseline_velocity = self._baseline_velocity_cm_s()
        if self._active_partial_points:
            last_time, last_velocity = self._active_partial_points[-1]
            if abs(last_time - time_ms) < 0.5 and abs(last_velocity - baseline_velocity) < 1.0:
                return
        self._add_trace_point(time_ms, baseline_velocity)

    def _emit_trace_prompt(self) -> None:
        prompt = self.trace_prompt()
        if prompt:
            self.trace_prompt_changed.emit(prompt)

    def autovti_region_prompt(self) -> str | None:
        if self._tool_mode != "autovti_region":
            return None
        from echo_personal_tool.infrastructure.i18n import tr

        label = self._trace_label
        if self._autovti_start_ms is None:
            return f"{label}: {tr('doppler.autovti_click_start')}"
        return f"{label}: {tr('doppler.autovti_click_end')}"

    def _emit_autovti_prompt(self) -> None:
        prompt = self.autovti_region_prompt()
        if prompt:
            self.trace_prompt_changed.emit(prompt)

    def _baseline_plot_y_px(self) -> float:
        baseline = self._axis_mapping.baseline_plot_y()
        if baseline is not None:
            return float(baseline)
        return self._axis_mapping.plot_height * 0.5

    def _envelope_below_baseline(self, envelope: tuple[tuple[float, float], ...]) -> bool:
        """True when the auto-traced envelope sits below the baseline."""
        if not envelope:
            return False
        median_y = float(np.median([point[1] for point in envelope]))
        return median_y > self._baseline_plot_y_px()

    def _baseline_velocity_cm_s(self) -> float:
        return self._axis_mapping.velocity_cm_s_from_y(self._baseline_plot_y_px())

    def _is_near_baseline(self, y_px: float) -> bool:
        return abs(y_px - self._baseline_plot_y_px()) <= _BASELINE_CLICK_TOLERANCE_PX

    def _trace_last_point_on_baseline(self) -> bool:
        if not self._active_partial_points:
            return False
        span = self._axis_mapping.velocity_span_cm_s
        tolerance = max(1.0, span * 0.025)
        return abs(self._active_partial_points[-1][1]) < tolerance

    def _handle_trace_click(self, time_ms: float, velocity_cm_s: float, *, y_px: float) -> bool:
        if not self._active_partial_points:
            if not self._is_near_baseline(y_px):
                return False
            self._add_trace_point(time_ms, self._baseline_velocity_cm_s())
            self._trace_last_plot_xy = (float(self._axis_mapping.x_from_time_ms(time_ms)), y_px)
            self._trace_suppress_click = True
            self._emit_trace_prompt()
            return True
        if self._is_near_baseline(y_px) and len(self._active_partial_points) >= 2:
            self._close_trace_at(time_ms)
            finished = self.finish_trace()
            self._emit_trace_prompt()
            return finished
        self._extend_trace_sample(
            self._axis_mapping.x_from_time_ms(time_ms),
            self._axis_mapping.y_from_velocity_cm_s(velocity_cm_s),
        )
        self._emit_trace_prompt()
        return True

    def _handle_autovti_click(self, x_px: float, y_px: float) -> bool:
        """Two-click region selection for Auto VTI: start/end time + direction.

        The lateralization of the clicks (above/below baseline) determines the
        auto-tracing direction. Direction is derived from
        ``velocity_cm_s_from_y`` so it is consistent with the axis mapping's
        coordinate convention (the same conversion used by trace and peak
        modes), rather than a raw Y comparison that may be in a different
        coordinate space.
        """
        if self._autovti_start_ms is None:
            start_ms = self._axis_mapping.time_ms_from_x(x_px)
            self._autovti_start_ms = start_ms
            velocity = self._axis_mapping.velocity_cm_s_from_y(y_px)
            self._autovti_direction = "up" if velocity >= 0 else "down"
            self._show_autovti_region_start(x_px)
            self._emit_autovti_prompt()
            return True
        start_ms = self._autovti_start_ms
        end_ms = self._axis_mapping.time_ms_from_x(x_px)
        if end_ms < start_ms:
            start_ms, end_ms = end_ms, start_ms
        direction = self._autovti_direction

        self._show_autovti_region_band(start_ms, end_ms)

        QTimer.singleShot(0, self._clear_autovti_region)
        self._tool_mode = "none"
        self.autovti_region_selected.emit(start_ms, end_ms, direction)
        return True

    def _show_autovti_region_start(self, x_px: float) -> None:
        if self._autovti_region_item is not None:
            try:
                self._plot.removeItem(self._autovti_region_item)
            except Exception:
                pass
        x_plot = float(x_px)
        y_min = self._axis_mapping.plot_origin_y
        y_max = y_min + self._axis_mapping.plot_height
        item = pg.PlotCurveItem(
            [x_plot, x_plot],
            [y_min, y_max],
            pen=pg.mkPen("#ffaa00", width=1, style=Qt.PenStyle.DotLine),
        )
        item.setZValue(22)
        self._plot.addItem(item)
        self._autovti_region_item = item

    def _show_autovti_region_band(self, start_ms: float, end_ms: float) -> None:
        if self._autovti_band_item is not None:
            try:
                self._plot.removeItem(self._autovti_band_item)
            except Exception:
                pass
        x_start = self._axis_mapping.x_from_time_ms(start_ms)
        x_end = self._axis_mapping.x_from_time_ms(end_ms)
        y_min = self._axis_mapping.plot_origin_y
        y_max = y_min + self._axis_mapping.plot_height
        item = pg.PlotDataItem(
            [x_start, x_end, x_end, x_start, x_start],
            [y_min, y_min, y_max, y_max, y_min],
            pen=QPen(Qt.PenStyle.NoPen),
            brush=pg.mkBrush(255, 170, 0, 40),
        )
        item.setZValue(21)
        self._plot.addItem(item)
        self._autovti_band_item = item

    def _clear_autovti_region(self) -> None:
        if self._autovti_region_item is not None:
            try:
                self._plot.removeItem(self._autovti_region_item)
            except Exception:
                pass
            self._autovti_region_item = None
        if self._autovti_band_item is not None:
            try:
                self._plot.removeItem(self._autovti_band_item)
            except Exception:
                pass
            self._autovti_band_item = None
        self._autovti_start_ms = None
        self._autovti_direction = None

    def _handle_mapped_click(
        self,
        time_ms: float,
        velocity_cm_s: float,
        *,
        x_px: float | None = None,
        y_px: float | None = None,
    ) -> bool:
        del x_px, y_px
        if self._tool_mode == "peak":
            self._add_peak_marker(time_ms, velocity_cm_s)
            return True
        if self._tool_mode == "interval":
            if self._active_interval_start is None:
                self._active_interval_start = float(time_ms)
                self._refresh_interval_preview()
                return True
            self._add_interval_marker(time_ms)
            return True
        return False


def _near_point(px: float, py: float, target: tuple[float, float], tol: float = 15.0) -> bool:
    return abs(px - target[0]) <= tol and abs(py - target[1]) <= tol


def derive_psv_edv_indices(
    envelope: tuple[tuple[float, float], ...],
    *,
    below_baseline: bool = False,
) -> tuple[int, int]:
    """Return indices of the PSV and EDV points of an auto-traced envelope.

    Envelope points are plot coordinates ``(x_px, y_px)`` with velocity
    increasing upward, so PSV (max velocity) is the minimum y and EDV
    (diastolic minimum velocity) is the maximum y inside the search window.
    EDV falls back to the last envelope point when the post-PSV segment is
    too short or the found minimum is too close to the cycle end (unreliable).
    When *below_baseline* is set the y axis is reflected first so a negative
    (below-baseline) envelope is handled symmetrically.
    """
    ys = np.asarray([point[1] for point in envelope])
    if below_baseline:
        ys = -ys
    if len(ys) < 5:
        return int(np.argmin(ys)), len(ys) - 1

    psv_idx = int(np.argmin(ys))
    diastolic = ys[psv_idx:]
    if len(diastolic) < 3:
        return psv_idx, len(ys) - 1

    search_start = int(len(diastolic) * 0.6)
    local_idx = int(np.argmax(diastolic[search_start:])) + search_start
    edv_idx = psv_idx + local_idx

    psv_y = float(ys[psv_idx])
    last_y = float(ys[-1])
    edv_y = float(ys[edv_idx])
    fall_px = last_y - psv_y
    if fall_px > 0 and (edv_y - last_y) < 0.05 * fall_px:
        edv_idx = len(ys) - 1

    return psv_idx, edv_idx


def _build_vessel_text(psv_cm_s: float, edv_cm_s: float, metrics: VesselMetrics) -> pg.TextItem:
    lines = [
        f"PSV: {psv_cm_s:.1f} cm/s",
        f"EDV: {edv_cm_s:.1f} cm/s",
        f"RI: {metrics.ri:.2f}" if metrics.ri is not None else "RI: —",
        f"S/D: {metrics.sd:.2f}" if metrics.sd is not None else "S/D: —",
        f"MV≈: {metrics.mv_approx:.1f} cm/s" if metrics.mv_approx is not None else "MV≈: —",
    ]
    if not metrics.valid:
        lines.append("Проверьте точки")
    text = "\n".join(lines)
    item = pg.TextItem(text, anchor=(1.0, 0.0), fill=(0, 0, 0, 200))
    item.setZValue(30)
    return item
