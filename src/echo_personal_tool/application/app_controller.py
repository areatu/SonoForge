"""Application use-case orchestration."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker
from echo_personal_tool.application.workers.scan_worker import ScanWorker
from echo_personal_tool.application.workers.thumbnail_loader_worker import ThumbnailLoaderWorker
from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.infrastructure.video_reader import VideoReader


class AppController(QObject):
    """Coordinates scanning and frame loading between UI and infrastructure."""

    studies_loaded = Signal(list)
    scan_failed = Signal(str)
    frame_loaded = Signal(np.ndarray)
    frame_load_failed = Signal(str)
    thumbnail_loaded = Signal(str, QImage)
    status_message = Signal(str)

    def __init__(self, thread_pool: QThreadPool | None = None) -> None:
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._state_manager = StateManager()
        self._timer = QTimer(self)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._advance_playback)
        self._studies: list[StudyMetadata] = []
        self._current_instance: InstanceMetadata | None = None
        self._current_source_kind: str | None = None
        self._loaded_source_path: Path | None = None
        self._loaded_frame_index: int | None = None
        self._pending_source_path: Path | None = None
        self._pending_frame_index: int | None = None
        self._load_request_id = 0
        self._pending_load_id = 0
        self._pending_thumbnails: set[str] = set()
        self._state_manager.state_changed.connect(self._on_state_changed)

    @property
    def studies(self) -> list[StudyMetadata]:
        return self._studies

    @property
    def state_manager(self) -> StateManager:
        return self._state_manager

    def open_folder(self, root: Path, error_log_path: Path | None = None) -> None:
        self.status_message.emit(f"Scanning {root}…")
        worker = ScanWorker(root, error_log_path=error_log_path)
        worker.signals.finished.connect(self._on_studies_scanned)
        worker.signals.failed.connect(self._on_scan_failed)
        self._thread_pool.start(worker)

    def _on_studies_scanned(self, studies: object) -> None:
        self._studies = list(studies)  # type: ignore[arg-type]
        count = len(self._studies)
        self.status_message.emit(f"Loaded {count} studies")
        self.studies_loaded.emit(self._studies)

    def _on_scan_failed(self, message: str) -> None:
        self.status_message.emit(f"Scan failed: {message}")
        self.scan_failed.emit(message)

    def load_instance(self, instance: InstanceMetadata, frame_index: int = 0) -> None:
        if instance.path is None:
            self.frame_load_failed.emit("Instance has no file path")
            return
        self._current_instance = instance
        self._current_source_kind = "mp4" if instance.path.suffix.lower() == ".mp4" else "dicom"
        self.status_message.emit(f"Loading {instance.path.name}…")
        try:
            if self._current_source_kind == "mp4":
                with VideoReader() as reader:
                    reader.open(instance.path)
                    total_frames = reader.frame_count
                    fps = reader.fps
                frame_time_ms = 1000.0 / fps if fps > 0 else 33.3
            else:
                total_frames = instance.number_of_frames
                frame_time_ms = instance.frame_time_ms or 33.3
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.frame_load_failed.emit(str(exc))
            return

        self._loaded_source_path = None
        self._loaded_frame_index = None
        self._pending_source_path = None
        self._pending_frame_index = None
        self._state_manager.set_instance(
            instance,
            total_frames=total_frames,
            frame_time_ms=frame_time_ms,
        )
        if frame_index != 0:
            self._state_manager.set_frame(frame_index)

    def load_thumbnail(self, instance: InstanceMetadata) -> None:
        if instance.path is None:
            return
        if instance.path.suffix.lower() == ".mp4":
            return
        uid = instance.sop_instance_uid
        if uid in self._pending_thumbnails:
            return

        self._pending_thumbnails.add(uid)
        worker = ThumbnailLoaderWorker(
            instance.path,
            uid,
            number_of_frames=instance.number_of_frames,
        )
        worker.signals.finished.connect(self._on_thumbnail_loaded)
        worker.signals.failed.connect(self._on_thumbnail_failed)
        self._thread_pool.start(worker)

    def _on_thumbnail_loaded(self, sop_instance_uid: str, image: QImage) -> None:
        self._pending_thumbnails.discard(sop_instance_uid)
        self.thumbnail_loaded.emit(sop_instance_uid, image)

    def _on_thumbnail_failed(self, sop_instance_uid: str, _message: str) -> None:
        self._pending_thumbnails.discard(sop_instance_uid)

    def load_first_instance_of_series(self, study: StudyMetadata, series_uid: str) -> None:
        for series in study.series:
            if series.series_uid != series_uid:
                continue
            if not series.instances:
                self.frame_load_failed.emit("Series has no instances")
                return
            self.load_instance(series.instances[0])
            return
        self.frame_load_failed.emit("Series not found in study")

    def set_playing(self, is_playing: bool) -> None:
        self._state_manager.set_playing(is_playing)

    def toggle_playback(self) -> None:
        self._state_manager.toggle_playback()

    def step_frame(self, delta: int) -> None:
        self._state_manager.step_frame(delta)

    def mark_ed(self) -> None:
        self._state_manager.mark_ed()
        frame = self._state_manager.snapshot.ed_frame_index
        if frame is not None:
            self.status_message.emit(f"ED marked at frame {frame + 1}")

    def mark_es(self) -> None:
        self._state_manager.mark_es()
        frame = self._state_manager.snapshot.es_frame_index
        if frame is not None:
            self.status_message.emit(f"ES marked at frame {frame + 1}")

    def _on_state_changed(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        interval = max(1, int(round(state.frame_time_ms or 33.3)))
        self._timer.setInterval(interval)
        if state.is_playing and not self._timer.isActive():
            self._timer.start()
        elif not state.is_playing and self._timer.isActive():
            self._timer.stop()
        self._request_frame_if_needed(state)

    def _request_frame_if_needed(self, state: ViewerState) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        if (
            self._loaded_source_path == self._current_instance.path
            and self._loaded_frame_index == state.current_frame_index
            and self._pending_load_id == 0
        ):
            return
        if (
            self._pending_load_id != 0
            and self._pending_source_path == self._current_instance.path
            and self._pending_frame_index == state.current_frame_index
        ):
            return

        self._load_request_id += 1
        request_id = self._load_request_id
        self._pending_load_id = request_id
        self._pending_source_path = self._current_instance.path
        self._pending_frame_index = state.current_frame_index

        source_kind = self._current_source_kind or "dicom"
        worker = FrameLoaderWorker(
            self._current_instance.path,
            frame_index=state.current_frame_index,
            source_kind=source_kind,
        )
        worker.signals.finished.connect(
            partial(
                self._on_frame_loaded,
                request_id,
                self._current_instance.path,
                state.current_frame_index,
            )
        )
        worker.signals.failed.connect(partial(self._on_frame_load_failed, request_id))
        self._thread_pool.start(worker)

    def _advance_playback(self) -> None:
        self.step_frame(1)

    def _on_frame_loaded(
        self,
        request_id: int,
        path: Path,
        frame_index: int,
        pixels: np.ndarray,
    ) -> None:
        if request_id != self._pending_load_id:
            return
        if self._current_instance is None or self._current_instance.path != path:
            return
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        self._loaded_source_path = path
        self._loaded_frame_index = frame_index
        self.status_message.emit("Frame ready")
        self.frame_loaded.emit(pixels)

    def _on_frame_load_failed(self, request_id: int, message: str) -> None:
        if request_id != self._pending_load_id:
            return
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        self.status_message.emit(f"Load failed: {message}")
        self.frame_load_failed.emit(message)
