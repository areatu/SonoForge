"""Application use-case orchestration."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.application.workers.dicom_decode_worker import DicomDecodeWorker
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker
from echo_personal_tool.application.workers.onnx_worker import OnnxWorker
from echo_personal_tool.application.workers.scan_worker import ScanWorker
from echo_personal_tool.application.workers.thumbnail_loader_worker import ThumbnailLoaderWorker
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.calculations.teichholz import from_linear_measurements
from echo_personal_tool.domain.models import (
    Contour,
    InstanceMetadata,
    LinearMeasurement,
    StudyMetadata,
)
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.ports import IOnnxSegmenter
from echo_personal_tool.domain.services.segmentation_service import (
    mask_to_contour,
    smooth_contour,
)
from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine
from echo_personal_tool.infrastructure.video_reader import VideoReader

_FRAME_CACHE_WARN_BYTES = 512 * 1024 * 1024


class AppController(QObject):
    """Coordinates scanning and frame loading between UI and infrastructure."""

    studies_loaded = Signal(list)
    scan_failed = Signal(str)
    frame_loaded = Signal(np.ndarray)
    frame_load_failed = Signal(str)
    thumbnail_loaded = Signal(str, QImage)
    status_message = Signal(str)

    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        segmenter: IOnnxSegmenter | None = None,
    ) -> None:
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._state_manager = StateManager()
        self._segmenter = segmenter or OnnxInferenceEngine()
        self._frame_cache = FrameCache()
        self._timer = QTimer(self)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._advance_playback)
        self._studies: list[StudyMetadata] = []
        self._current_instance: InstanceMetadata | None = None
        self._loaded_source_path: Path | None = None
        self._loaded_frame_index: int | None = None
        self._pending_source_path: Path | None = None
        self._pending_frame_index: int | None = None
        self._load_request_id = 0
        self._pending_load_id = 0
        self._decode_request_id = 0
        self._pending_decode_id = 0
        self._pending_thumbnails: set[str] = set()
        self._current_frame_pixels: np.ndarray | None = None
        self._segment_in_progress = False
        self._state_manager.state_changed.connect(self._on_state_changed)

    @property
    def studies(self) -> list[StudyMetadata]:
        return self._studies

    @property
    def state_manager(self) -> StateManager:
        return self._state_manager

    def open_folder(self, root: Path, error_log_path: Path | None = None) -> None:
        self.status_message.emit(f"Scanning {root}…")
        worker = ScanWorker(root, error_log_path=error_log_path, parent=self)
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
        self.status_message.emit(f"Loading {instance.path.name}…")
        try:
            if instance.media_format == "mp4":
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

        self._frame_cache.clear()
        self._loaded_source_path = None
        self._loaded_frame_index = None
        self._pending_source_path = None
        self._pending_frame_index = None
        self._current_frame_pixels = None
        self._segment_in_progress = False
        self._state_manager.set_instance(
            instance,
            total_frames=total_frames,
            frame_time_ms=frame_time_ms,
        )
        if frame_index != 0:
            self._state_manager.set_frame(frame_index)
        if instance.media_format == "dicom":
            self._state_manager.set_decode_in_progress(True)
            self._decode_request_id += 1
            request_id = self._decode_request_id
            self._pending_decode_id = request_id
            self.status_message.emit(
                f"Decoding {instance.path.name}… ({total_frames} frames)"
            )
            worker = DicomDecodeWorker(instance.path, request_id, parent=self)
            worker.signals.finished.connect(self._on_dicom_decoded)
            worker.signals.failed.connect(self._on_dicom_decode_failed)
            self._thread_pool.start(worker)
            return

        self._request_frame_if_needed(self._state_manager.snapshot)

    def load_thumbnail(self, instance: InstanceMetadata) -> None:
        if instance.path is None:
            return
        uid = instance.sop_instance_uid
        if uid in self._pending_thumbnails:
            return

        self._pending_thumbnails.add(uid)
        worker = ThumbnailLoaderWorker(
            instance.path,
            uid,
            number_of_frames=instance.number_of_frames,
            media_format=instance.media_format,
            parent=self,
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

    def request_auto_segment(self) -> None:
        if self._segment_in_progress:
            self.status_message.emit("Segmentation already in progress")
            return

        state = self._state_manager.snapshot
        if state.is_playing:
            self.status_message.emit("Pause playback before auto-segmentation")
            return

        phase = self._resolve_phase_for_frame(state.current_frame_index, state)
        if phase is None:
            self.status_message.emit("Auto-segmentation requires an ED or ES frame")
            return

        if (
            self._current_frame_pixels is None
            or self._loaded_frame_index != state.current_frame_index
        ):
            self.status_message.emit("Current frame is not loaded yet")
            return

        if not self._segmenter.is_available():
            self.status_message.emit("сегментация недоступна — используйте ручной контур")
            return

        frame = np.ascontiguousarray(self._current_frame_pixels)
        original_shape = (int(frame.shape[0]), int(frame.shape[1]))
        instance_path = self._current_instance.path if self._current_instance is not None else None
        frame_index = state.current_frame_index

        self._segment_in_progress = True
        worker = OnnxWorker(frame, parent=self)
        worker.signals.finished.connect(
            partial(
                self._on_auto_segment_finished,
                phase,
                instance_path,
                frame_index,
                original_shape,
            )
        )
        worker.signals.failed.connect(
            partial(self._on_auto_segment_failed, instance_path, frame_index)
        )
        worker.signals.timed_out.connect(
            partial(self._on_auto_segment_timed_out, instance_path, frame_index)
        )
        self._thread_pool.start(worker)

    def on_doppler_markers_changed(self, dto: object) -> None:
        if not isinstance(dto, DopplerMeasurementDTO):
            raise TypeError("Expected DopplerMeasurementDTO")

        self._state_manager.set_doppler_measurement(dto)
        self._recompute_measurements()
        self.status_message.emit(self._format_doppler_summary(dto))

    def on_contours_changed(self, contours: object) -> None:
        if not isinstance(contours, list) or not all(
            isinstance(contour, Contour) for contour in contours
        ):
            raise TypeError("Expected a list of Contour objects")

        self._state_manager.set_contours(tuple(contours))
        self._recompute_measurements()

    def on_linear_measurements_changed(self, measurements: object) -> None:
        if not isinstance(measurements, list) or not all(
            isinstance(measurement, LinearMeasurement) for measurement in measurements
        ):
            raise TypeError("Expected a list of LinearMeasurement objects")

        self._state_manager.set_linear_measurements(tuple(measurements))
        self._recompute_measurements()

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

    def _recompute_measurements(self) -> None:
        state = self._state_manager.snapshot
        doppler = compute(state.doppler_measurement) if state.doppler_measurement else None
        pixel_spacing = state.instance.pixel_spacing if state.instance is not None else None
        lvef = calculate(state.contours, pixel_spacing)
        teichholz = from_linear_measurements(state.linear_measurements)
        snapshot = MeasurementSnapshot(
            doppler=doppler,
            lvef=lvef,
            teichholz=teichholz,
            linear_measurements=state.linear_measurements,
        )
        self._state_manager.set_measurement_snapshot(snapshot)

    def _request_frame_if_needed(self, state: ViewerState) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        if self._current_instance.media_format == "dicom":
            if self._state_manager.snapshot.decode_in_progress:
                return
            if self._frame_cache.is_ready(self._current_instance.path):
                if self._loaded_frame_index != state.current_frame_index:
                    self._emit_cached_frame(state.current_frame_index)
                return
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

        worker = FrameLoaderWorker(
            self._current_instance.path,
            frame_index=state.current_frame_index,
            media_format=self._current_instance.media_format,
            parent=self,
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

    def _format_doppler_summary(self, dto: DopplerMeasurementDTO) -> str:
        peaks = len(dto.peaks)
        intervals = len(dto.intervals)
        traces = len(dto.traces)
        return (
            "Doppler: "
            f"{peaks} peak{'s' if peaks != 1 else ''}, "
            f"{intervals} interval{'s' if intervals != 1 else ''}, "
            f"{traces} trace{'s' if traces != 1 else ''}"
        )

    def _advance_playback(self) -> None:
        if self._current_instance is not None and self._current_instance.media_format == "dicom":
            if self._current_instance.path is not None and self._frame_cache.is_ready(
                self._current_instance.path
            ):
                self.step_frame(1)
            return
        if self._pending_load_id != 0:
            return
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
        self._current_frame_pixels = pixels
        self.status_message.emit("Frame ready")
        self.frame_loaded.emit(pixels)

    def _on_frame_load_failed(self, request_id: int, message: str) -> None:
        if request_id != self._pending_load_id:
            return
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        self._current_frame_pixels = None
        self.status_message.emit(f"Load failed: {message}")
        self.frame_load_failed.emit(message)

    def _on_dicom_decoded(self, request_id: int, path: Path, frames: object) -> None:
        if request_id != self._pending_decode_id:
            return
        if self._current_instance is None or self._current_instance.path != path:
            return
        if not isinstance(frames, np.ndarray):
            return

        self._frame_cache.load(path, frames)
        if self._frame_cache.memory_bytes() > _FRAME_CACHE_WARN_BYTES:
            size_mb = self._frame_cache.memory_bytes() / (1024 * 1024)
            self.status_message.emit(
                f"Warning: DICOM cache uses {size_mb:.1f} MB"
            )

        frame_count = self._frame_cache.frame_count()
        if frame_count != self._state_manager.snapshot.total_frames:
            self._state_manager.set_total_frames(frame_count)

        current_index = self._state_manager.snapshot.current_frame_index
        self._loaded_source_path = path
        self._loaded_frame_index = current_index
        self._pending_decode_id = 0
        self._state_manager.set_decode_in_progress(False)
        self._emit_cached_frame(current_index)
        self.status_message.emit("Ready")

    def _on_dicom_decode_failed(self, request_id: int, message: str) -> None:
        if request_id != self._pending_decode_id:
            return
        self._pending_decode_id = 0
        self._frame_cache.clear()
        self._loaded_source_path = None
        self._loaded_frame_index = None
        self._current_frame_pixels = None
        self._state_manager.set_decode_in_progress(False)
        self.status_message.emit(f"Load failed: {message}")
        self.frame_load_failed.emit(message)

    def _emit_cached_frame(self, frame_index: int) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        if not self._frame_cache.is_ready(self._current_instance.path):
            return
        pixels = self._frame_cache.get(frame_index)
        self._loaded_source_path = self._current_instance.path
        self._loaded_frame_index = frame_index
        self._current_frame_pixels = pixels
        self.frame_loaded.emit(pixels)

    def _resolve_phase_for_frame(
        self,
        frame_index: int,
        state: ViewerState,
    ) -> str | None:
        if state.ed_frame_index is not None and frame_index == state.ed_frame_index:
            return "ED"
        if state.es_frame_index is not None and frame_index == state.es_frame_index:
            return "ES"
        return None

    def _auto_segment_context_matches(
        self,
        instance_path: Path | None,
        frame_index: int,
    ) -> bool:
        return (
            self._current_instance is not None
            and self._current_instance.path == instance_path
            and self._loaded_frame_index == frame_index
            and self._state_manager.snapshot.current_frame_index == frame_index
        )

    def _on_auto_segment_finished(
        self,
        phase: str,
        instance_path: Path | None,
        frame_index: int,
        original_shape: tuple[int, int],
        mask: object,
    ) -> None:
        self._segment_in_progress = False
        if not self._auto_segment_context_matches(instance_path, frame_index):
            return
        if not isinstance(mask, np.ndarray):
            return

        contour_points = smooth_contour(
            mask_to_contour(mask, original_shape),
            num_nodes=32,
        )
        contour = Contour(phase=phase, points=contour_points, source="ai")
        contours = [
            existing
            for existing in self._state_manager.snapshot.contours
            if not (existing.phase == phase and existing.view == contour.view)
        ]
        contours.append(contour)
        self.on_contours_changed(contours)

    def _on_auto_segment_failed(
        self,
        instance_path: Path | None,
        frame_index: int,
        _message: str,
    ) -> None:
        self._segment_in_progress = False
        if not self._auto_segment_context_matches(instance_path, frame_index):
            return
        self.status_message.emit("сегментация недоступна — используйте ручной контур")

    def _on_auto_segment_timed_out(self, instance_path: Path | None, frame_index: int) -> None:
        self._segment_in_progress = False
        if not self._auto_segment_context_matches(instance_path, frame_index):
            return
        self.status_message.emit("сегментация недоступна — используйте ручной контур")
