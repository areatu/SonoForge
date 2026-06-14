"""Application-layer viewer state coordinator."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.domain.models import (
    Contour,
    InstanceMetadata,
    LinearMeasurement,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.viewer_state import ViewerState


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
        )

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
        if emit:
            self._emit_state()

    def set_decode_in_progress(self, in_progress: bool) -> None:
        if self._decode_in_progress == in_progress:
            return
        self._decode_in_progress = in_progress
        self._emit_state()

    def set_total_frames(self, total_frames: int) -> None:
        if total_frames < 1:
            raise ValueError(f"total_frames must be >= 1, got {total_frames}")
        if self._total_frames == total_frames:
            return
        self._total_frames = total_frames
        if self._current_frame_index >= total_frames:
            self._current_frame_index = total_frames - 1
        self._emit_state()

    def set_frame(self, index: int) -> None:
        if self._instance is None or self._total_frames < 1:
            raise RuntimeError("Cannot set frame without a loaded instance")
        if index < 0 or index >= self._total_frames:
            raise IndexError(
                f"Frame index {index} out of range [0, {self._total_frames})"
            )
        if index == self._current_frame_index:
            return
        self._current_frame_index = index
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
        frame_index = (self._current_frame_index + delta) % self._total_frames
        if frame_index == self._current_frame_index:
            return
        self._current_frame_index = frame_index
        self._emit_state()

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

    def emit_state(self) -> None:
        """Publish the current snapshot to UI listeners."""
        self._emit_state()

    def set_manual_pixel_spacing(self, spacing: tuple[float, float] | None) -> None:
        self._manual_pixel_spacing = spacing
        self._emit_state()

    def clear_manual_pixel_spacing(self) -> None:
        self.set_manual_pixel_spacing(None)

    def reset_measurement_inputs(self) -> None:
        """Clear contours, linear measurements, Doppler input, and manual calibration."""
        self._contours = ()
        self._linear_measurements = ()
        self._doppler_measurement = None
        self._manual_pixel_spacing = None
        self._emit_state()

    def _emit_state(self) -> None:
        self.state_changed.emit(self.snapshot)
