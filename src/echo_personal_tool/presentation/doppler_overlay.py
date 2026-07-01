"""Doppler peak/interval/trace overlays on a 2D viewer plot (pixel coordinates)."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.services.doppler_trace_points import finalize_vti_trace_points

_BASELINE_CLICK_TOLERANCE_PX = 8.0
_TRACE_MIN_SAMPLE_PX = 4.0

_PEAK_LABELS = ("E", "A", "e_sept", "e_lat", "a_sept", "s_sept", "Vmax", "TR Vmax")
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

        self._peak_scatter = pg.ScatterPlotItem(
            size=10,
            pen=pg.mkPen("#ff6f00", width=2),
            brush=pg.mkBrush("#ffb74d"),
            symbol="o",
        )
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
        self._interval_markers: list[DopplerIntervalMarker] = []
        self._traces: list[DopplerTrace] = []
        self._single_shot_peak = True
        self._single_shot_interval = True
        self._workflow: tuple[tuple[str, str], ...] | None = None
        self._workflow_index = 0
        self._trace_stroke_active = False
        self._trace_suppress_click = False
        self._trace_last_plot_xy: tuple[float, float] | None = None

    def set_axis_mapping(self, mapping: DopplerAxisMapping) -> None:
        self._axis_mapping = mapping
        self._refresh_calibration_graphics()
        self._refresh_peak_scatter()
        self._redraw_intervals()
        self._redraw_traces()

    def axis_mapping(self) -> DopplerAxisMapping:
        return self._axis_mapping

    def set_tool_mode(self, mode: str) -> None:
        mode_name = mode.strip().lower()
        if mode_name not in {"none", "peak", "interval", "trace"}:
            raise ValueError(f"Unsupported Doppler tool mode: {mode}")
        if mode_name != self._tool_mode:
            self._clear_partial_state()
        self._tool_mode = mode_name
        if mode_name == "trace":
            self._emit_trace_prompt()

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

    def cancel_active_tool(self) -> bool:
        had_active_state = (
            self._tool_mode != "none"
            or bool(self._active_partial_points)
            or self._active_interval_start is not None
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

        trace = DopplerTrace(label=self._trace_label, points=finalized)
        self._traces.append(trace)

        completed_item = pg.PlotDataItem(
            pen=pg.mkPen("#1565c0", width=2),
            brush=pg.mkBrush(21, 101, 192, 70),
        )
        completed_item.setZValue(15)
        xs = [self._axis_mapping.x_from_time_ms(point[0]) for point in finalized]
        ys = [self._axis_mapping.y_from_velocity_cm_s(point[1]) for point in finalized]
        completed_item.setFillLevel(self._baseline_plot_y_px())
        completed_item.setData(xs, ys)
        self._plot.addItem(completed_item)
        self._trace_items.append(completed_item)

        self._clear_partial_state()
        self._tool_mode = "none"
        self.markers_changed.emit(self._build_measurement_dto())
        return True

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

        time_ms = self._axis_mapping.time_ms_from_x(x_px)
        velocity_cm_s = self._axis_mapping.velocity_cm_s_from_y(y_px)
        return self._handle_mapped_click(time_ms, velocity_cm_s, x_px=x_px, y_px=y_px)

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
        self._trace_item.setData([], [])
        self._clear_interval_preview()

    def _clear_interval_preview(self) -> None:
        if self._interval_preview_item is not None:
            self._interval_preview_item.setData([], [])

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
                pen=pg.mkPen("#00897b", width=2, style=Qt.PenStyle.DashLine),
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
        interval_pen = pg.mkPen("#00897b", width=2)
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
            float(self._active_interval_start)
            if self._active_interval_start is not None
            else float(end_time_ms)
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
        x_values = [
            self._axis_mapping.x_from_time_ms(point[0]) for point in self._active_partial_points
        ]
        y_values = [
            self._axis_mapping.y_from_velocity_cm_s(point[1])
            for point in self._active_partial_points
        ]
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
            if (
                abs(last_time - time_ms) < 0.5
                and abs(last_velocity - baseline_velocity) < 1.0
            ):
                return
        self._add_trace_point(time_ms, baseline_velocity)

    def _emit_trace_prompt(self) -> None:
        prompt = self.trace_prompt()
        if prompt:
            self.trace_prompt_changed.emit(prompt)

    def _baseline_plot_y_px(self) -> float:
        baseline = self._axis_mapping.baseline_plot_y()
        if baseline is not None:
            return float(baseline)
        return self._axis_mapping.plot_height * 0.5

    def _baseline_velocity_cm_s(self) -> float:
        return self._axis_mapping.velocity_cm_s_from_y(self._baseline_plot_y_px())

    def _is_near_baseline(self, y_px: float) -> bool:
        return abs(y_px - self._baseline_plot_y_px()) <= _BASELINE_CLICK_TOLERANCE_PX

    def _trace_last_point_on_baseline(self) -> bool:
        if not self._active_partial_points:
            return False
        return abs(self._active_partial_points[-1][1]) < 1.0

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
