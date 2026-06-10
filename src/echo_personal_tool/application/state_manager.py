"""Application-layer viewer state coordinator."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.domain.models import InstanceMetadata
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
        )

    def set_instance(
        self,
        metadata: InstanceMetadata,
        total_frames: int,
        frame_time_ms: float | None,
    ) -> None:
        self._instance = metadata
        self._total_frames = total_frames
        self._frame_time_ms = frame_time_ms
        self._current_frame_index = 0
        self._is_playing = False
        self._ed_frame_index = None
        self._es_frame_index = None
        self._emit_state()

    def set_frame(self, index: int) -> None:
        if index < 0 or (self._total_frames > 0 and index >= self._total_frames):
            raise IndexError(
                f"Frame index {index} out of range [0, {self._total_frames})"
            )
        self._current_frame_index = index
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

    def _emit_state(self) -> None:
        self.state_changed.emit(self.snapshot)
