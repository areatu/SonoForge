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
    """Caches the active instance context, frame position, and ED/ES markers."""

    state_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._instance: InstanceMetadata | None = None
        self._current_frame_index = 0
        self._total_frames = 0
        self._frame_time_ms: float | None = None
        self._is_playing = False
        self._ed_frame_index: int | None = None
        self._es_frame_index: int | None = None
        self._doppler_measurement: DopplerMeasurementDTO | None = None
        self._contours: tuple[Contour, ...] = ()
        self._linear_measurements: tuple[LinearMeasurement, ...] = ()
        self._measurement_snapshot: MeasurementSnapshot | None = None
        self._decode_in_progress = False

    @property
    def snapshot(self) -> ViewerState:
        return ViewerState(
            instance=self._instance,
            current_frame_index=self._current_frame_index,
            total_frames=self._total_frames,
            frame_time_ms=self._frame_time_ms,
            is_playing=self._is_playing,
            ed_frame_index=self._ed_frame_index,
            es_frame_index=self._es_frame_index,
            doppler_measurement=self._doppler_measurement,
            contours=self._contours,
            linear_measurements=self._linear_measurements,
            measurement_snapshot=self._measurement_snapshot,
            decode_in_progress=self._decode_in_progress,
        )

    def set_instance(
        self,
        metadata: InstanceMetadata,
        total_frames: int,
        frame_time_ms: float | None,
    ) -> None:
        if total_frames < 1:
            raise ValueError(f"total_frames must be >= 1, got {total_frames}")
        self._instance = metadata
        self._total_frames = total_frames
        self._frame_time_ms = frame_time_ms if frame_time_ms and frame_time_ms > 0 else 33.3
        self._current_frame_index = 0
        self._is_playing = False
        self._ed_frame_index = None
        self._es_frame_index = None
        self._doppler_measurement = None
        self._contours = ()
        self._linear_measurements = ()
        self._measurement_snapshot = None
        self._decode_in_progress = False
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

    def mark_ed(self) -> None:
        self._ed_frame_index = self._current_frame_index
        self._emit_state()

    def mark_es(self) -> None:
        self._es_frame_index = self._current_frame_index
        self._emit_state()

    def clear_phase_markers(self) -> None:
        self._ed_frame_index = None
        self._es_frame_index = None
        self._emit_state()

    def set_doppler_measurement(self, dto: DopplerMeasurementDTO) -> None:
        self._doppler_measurement = dto
        self._emit_state()

    def set_contours(self, contours: tuple[Contour, ...]) -> None:
        self._contours = contours
        self._emit_state()

    def set_linear_measurements(self, measurements: tuple[LinearMeasurement, ...]) -> None:
        self._linear_measurements = measurements
        self._emit_state()

    def set_measurement_snapshot(self, snapshot: MeasurementSnapshot | None) -> None:
        self._measurement_snapshot = snapshot
        self._emit_state()

    def _emit_state(self) -> None:
        self.state_changed.emit(self.snapshot)
