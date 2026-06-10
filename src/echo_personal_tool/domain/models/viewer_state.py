"""Pure domain snapshot of viewer playback and phase-marker state."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.metadata import InstanceMetadata


@dataclass(frozen=True)
class ViewerState:
    instance: InstanceMetadata | None
    current_frame_index: int
    total_frames: int
    frame_time_ms: float | None
    is_playing: bool
    ed_frame_index: int | None
    es_frame_index: int | None

    @property
    def fps(self) -> float:
        if self.frame_time_ms is None or self.frame_time_ms <= 0:
            return 0.0
        return 1000.0 / self.frame_time_ms
