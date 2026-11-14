"""Application-layer viewer state coordinator."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.domain.models import (
    CalibrationContext,
    Contour,
    InstanceMetadata,
    LinearMeasurement,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.pixel_spacing_resolver import manual_calibration_context
from echo_personal_tool.infrastructure.profiler import profiled as _prof


class StateManager(QObject):
    """Caches the active instance context and frame position."""

    state_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._instance: InstanceMetadata | None = None
        self._current_frame_index = 0
        self._total_frames = 0
        self._frame_time_ms: float | None = None
        self._is_playing = False
        self._doppler_measurement: DopplerMeasurementDTO | None = None
        self._contours: tuple[Contour, ...] = ()
        self._linear_measurements: tuple[LinearMeasurement, ...] = ()
        self._measurement_snapshot: MeasurementSnapshot | None = None
        self._decode_in_progress = False
        self._manual_pixel_spacing: tuple[float, float] | None = None
        self._manual_calibration: CalibrationContext | None = None
        self._scroll_navigation = False
        # Manually placed A→B loop of the cine (issue 7). Session-scoped, like
        # the markers of the phase strip; reset on every clip swap.
        self._loop_in: int | None = None
        self._loop_out: int | None = None
        self._loop_armed = False

    @property
    def snapshot(self) -> ViewerState:
        return ViewerState(
            instance=self._instance,
            current_frame_index=self._current_frame_index,
            total_frames=self._total_frames,
            frame_time_ms=self._frame_time_ms,
            is_playing=self._is_playing,
            doppler_measurement=self._doppler_measurement,
            contours=self._contours,
            linear_measurements=self._linear_measurements,
            measurement_snapshot=self._measurement_snapshot,
            decode_in_progress=self._decode_in_progress,
            manual_pixel_spacing=self._manual_pixel_spacing,
            manual_calibration=self._manual_calibration,
        )

    def clear_instance(self, *, emit: bool = True) -> None:
        """Reset the active viewer identity when committing a different study set."""
        self._instance = None
        self._current_frame_index = 0
        self._total_frames = 0
        self._frame_time_ms = None
        self._is_playing = False
        self._doppler_measurement = None
        self._contours = ()
        self._linear_measurements = ()
        self._measurement_snapshot = None
        self._decode_in_progress = False
        self._manual_pixel_spacing = None
        self._manual_calibration = None
        self._scroll_navigation = False
        self._reset_loop()
        if emit:
            self._emit_state()

    def set_instance(
        self,
        metadata: InstanceMetadata,
        total_frames: int,
        frame_time_ms: float | None,
        *,
        emit: bool = True,
    ) -> None:
        if total_frames < 1:
            raise ValueError(f"total_frames must be >= 1, got {total_frames}")
        self._instance = metadata
        self._total_frames = total_frames
        self._frame_time_ms = frame_time_ms if frame_time_ms and frame_time_ms > 0 else 33.3
        self._current_frame_index = 0
        self._is_playing = False
        self._doppler_measurement = None
        self._contours = ()
        self._linear_measurements = ()
        self._measurement_snapshot = None
        self._decode_in_progress = False
        self._manual_pixel_spacing = None
        self._manual_calibration = None
        self._reset_loop()
        if emit:
            self._emit_state()

    def set_frame_time(
        self,
        frame_time_ms: float | None,
        metadata: InstanceMetadata | None = None,
        *,
        emit: bool = True,
    ) -> None:
        """Retiming only (the transport's FPS override): playhead, contours,
        measurements and the decode state all stay — unlike ``set_instance``."""
        self._frame_time_ms = frame_time_ms if frame_time_ms and frame_time_ms > 0 else 33.3
        if metadata is not None:
            self._instance = metadata
        if emit:
            self._emit_state()

    @_prof
    def set_decode_in_progress(self, in_progress: bool, *, emit: bool = True) -> None:
        if self._decode_in_progress == in_progress:
            return
        self._decode_in_progress = in_progress
        if emit:
            self._emit_state()

    @_prof
    def set_total_frames(self, total_frames: int) -> None:
        if total_frames < 1:
            raise ValueError(f"total_frames must be >= 1, got {total_frames}")
        if self._total_frames == total_frames:
            return
        self._total_frames = total_frames
        if self._current_frame_index >= total_frames:
            self._current_frame_index = total_frames - 1
        if self._loop_in is not None and self._loop_out is not None:
            self.set_loop_bounds(self._loop_in, self._loop_out)
        self._emit_state()

    @_prof
    def set_frame(self, index: int, *, scroll: bool = False) -> None:
        if self._instance is None or self._total_frames < 1:
            raise RuntimeError("Cannot set frame without a loaded instance")
        if index < 0 or index >= self._total_frames:
            raise IndexError(f"Frame index {index} out of range [0, {self._total_frames})")
        if index == self._current_frame_index:
            return
        self._current_frame_index = index
        self._scroll_navigation = scroll
        self._emit_state()

    def set_playing(self, is_playing: bool) -> None:
        if self._is_playing == is_playing:
            return
        self._is_playing = is_playing
        self._emit_state()

    def toggle_playback(self) -> None:
        self.set_playing(not self._is_playing)

    def step_frame(self, delta: int) -> None:
        if self._instance is None or self._total_frames < 1 or delta == 0:
            return
        frame_index = self.loop_next_frame(self._current_frame_index, delta)
        if frame_index == self._current_frame_index:
            return
        self._current_frame_index = frame_index
        self._emit_state()

    # ── loop region (A→B repeat of the cine) ────────────────────────────
    def _reset_loop(self) -> None:
        self._loop_in = None
        self._loop_out = None
        self._loop_armed = False

    def loop_bounds(self) -> tuple[int, int] | None:
        if self._loop_in is None or self._loop_out is None:
            return None
        return (self._loop_in, self._loop_out)

    def loop_armed(self) -> bool:
        return self._loop_armed and self.loop_bounds() is not None

    def loop_state(self) -> tuple[int | None, int | None, bool]:
        bounds = self.loop_bounds()
        if bounds is None:
            return (None, None, False)
        return (bounds[0], bounds[1], self._loop_armed)

    def set_loop_bounds(self, loop_in: int, loop_out: int) -> tuple[int, int]:
        """Clamp and order the A/B pair; a collapsed pair disarms the loop."""
        total = max(1, self._total_frames)
        a = max(0, min(int(loop_in), total - 1))
        b = max(0, min(int(loop_out), total - 1))
        if a > b:
            a, b = b, a
        self._loop_in, self._loop_out = a, b
        if a == b:
            self._loop_armed = False
        return (a, b)

    def set_loop_bound(self, which: str, frame: int) -> tuple[int, int]:
        current = self.loop_bounds() or (self._current_frame_index, self._current_frame_index)
        a, b = (frame, current[1]) if which == "a" else (current[0], frame)
        return self.set_loop_bounds(a, b)

    def set_loop_armed(self, armed: bool) -> bool:
        bounds = self.loop_bounds()
        if armed and (bounds is None or bounds[0] >= bounds[1]):
            self._loop_armed = False
            return False
        self._loop_armed = bool(armed)
        return self._loop_armed

    def toggle_loop(self) -> bool:
        return self.set_loop_armed(not self._loop_armed)

    def clear_loop_bounds(self) -> None:
        self._reset_loop()

    def loop_next_frame(self, current: int, delta: int = 1) -> int:
        """Frame to show after ``current`` when stepping by ``delta``.

        Plain modulo without an armed loop; the A→B window with it. A
        playhead parked outside the region snaps back into it.
        """
        total = self._total_frames
        if total < 1:
            return 0
        if self.loop_armed():
            assert self._loop_in is not None and self._loop_out is not None
            loop_in, loop_out = self._loop_in, self._loop_out
            if current < loop_in or current > loop_out:
                return loop_in if delta >= 0 else loop_out
            span = loop_out - loop_in + 1
            return loop_in + (current - loop_in + delta) % span
        return (current + delta) % total

    def set_doppler_measurement(
        self,
        dto: DopplerMeasurementDTO,
        *,
        emit: bool = True,
    ) -> None:
        self._doppler_measurement = dto
        if emit:
            self._emit_state()

    def set_contours(
        self,
        contours: tuple[Contour, ...],
        *,
        emit: bool = True,
    ) -> None:
        self._contours = contours
        if emit:
            self._emit_state()

    def set_linear_measurements(
        self,
        measurements: tuple[LinearMeasurement, ...],
        *,
        emit: bool = True,
    ) -> None:
        self._linear_measurements = measurements
        if emit:
            self._emit_state()

    def set_measurement_snapshot(
        self,
        snapshot: MeasurementSnapshot | None,
        *,
        emit: bool = True,
    ) -> None:
        self._measurement_snapshot = snapshot
        if emit:
            self._emit_state()

    @_prof
    def emit_state(self) -> None:
        """Publish the current snapshot to UI listeners."""
        self._emit_state()

    def set_manual_pixel_spacing(self, spacing: tuple[float, float] | None, *, emit: bool = True) -> None:
        previous = self._manual_calibration
        self._manual_pixel_spacing = spacing
        if spacing is None:
            self._manual_calibration = None
        else:
            revision = (previous.revision if previous is not None else 0) + 1
            self._manual_calibration = manual_calibration_context(spacing, revision=revision)
        if emit:
            self._emit_state()

    def set_manual_calibration(self, calibration: CalibrationContext | None, *, emit: bool = True) -> None:
        self._manual_calibration = calibration
        self._manual_pixel_spacing = calibration.spacing if calibration is not None else None
        if emit:
            self._emit_state()

    def clear_manual_pixel_spacing(self) -> None:
        self.set_manual_pixel_spacing(None)

    @_prof
    def reset_measurement_inputs(self) -> None:
        """Clear contours, linear measurements, Doppler input, and manual calibration."""
        self._contours = ()
        self._linear_measurements = ()
        self._doppler_measurement = None
        self._manual_pixel_spacing = None
        self._manual_calibration = None
        self._emit_state()

    def _emit_state(self) -> None:
        scroll = self._scroll_navigation
        self._scroll_navigation = False
        state = ViewerState(
            instance=self._instance,
            current_frame_index=self._current_frame_index,
            total_frames=self._total_frames,
            frame_time_ms=self._frame_time_ms,
            is_playing=self._is_playing,
            doppler_measurement=self._doppler_measurement,
            contours=self._contours,
            linear_measurements=self._linear_measurements,
            measurement_snapshot=self._measurement_snapshot,
            decode_in_progress=self._decode_in_progress,
            manual_pixel_spacing=self._manual_pixel_spacing,
            manual_calibration=self._manual_calibration,
            scroll_navigation=scroll,
        )
        self.state_changed.emit(state)
