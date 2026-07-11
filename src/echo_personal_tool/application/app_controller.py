"""Application use-case orchestration."""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from functools import partial
from pathlib import Path
from time import perf_counter

import numpy as np
from PySide6.QtCore import Qt, QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

from echo_personal_tool.infrastructure.profiler import profiled as _prof

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementData,
    StudyMeasurementSessionStore,
    contours_for_instance,
)
from echo_personal_tool.application.thumbnail_scheduler import (
    ThumbnailPriority,
    ThumbnailScheduler,
)
from echo_personal_tool.application.workers.dicom_decode_worker import DicomDecodeWorker
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker
from echo_personal_tool.application.workers.video_decode_worker import VideoDecodeWorker
from echo_personal_tool.application.workers.onnx_worker import OnnxWorker
from echo_personal_tool.application.workers.scan_worker import ScanWorker
from echo_personal_tool.application.workers.thumbnail_loader_worker import ThumbnailLoaderWorker
from echo_personal_tool.domain.calculations.body_surface import compute_indexed_measurements
from echo_personal_tool.domain.calculations.chamber_simpson import calculate_chamber
from echo_personal_tool.domain.calculations.diastology_grade import grade_diastolic_function
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.la_area_length import (
    from_measurements as la_from_measurements,
)
from echo_personal_tool.domain.calculations.lvef_simpson import (
    _contour_arc_span_px,
    calculate,
    explain_lv_auto_reject_reason,
)
from echo_personal_tool.domain.calculations.lvm import from_linear_measurements as lvm_from_linear
from echo_personal_tool.domain.calculations.rv_fac import from_rv_contours
from echo_personal_tool.domain.calculations.rwt import from_linear_measurements as rwt_from_linear
from echo_personal_tool.domain.calculations.teichholz import from_linear_measurements
from echo_personal_tool.domain.models import (
    Contour,
    InstanceMetadata,
    LinearMeasurement,
    StudyMetadata,
    TemporalFusionConfig,
    TemporalFusionResult,
)
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.speckle import SpeckleConfig
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.ports import IOnnxSegmenter
from echo_personal_tool.domain.services.contour_geometry import apex_point
from echo_personal_tool.domain.services.planimeter_formatter import planimeter_results_from_contours
from echo_personal_tool.domain.services.segment_roi import (
    echonet_crop_mode_for_media,
    resolve_cine_segment_roi_xyxy,
    resolve_segment_roi_xyxy,
)
from echo_personal_tool.domain.services.segmentation_service import (
    closed_polygon_to_open_arc,
    exclude_papillary_concavities,
    mask_to_contour,
    open_arc_from_cavity_mask,
    papillary_mask_cleanup,
    smooth_contour,
)
from echo_personal_tool.domain.services.lv_temporal_fusion import (
    compute_window,
    temporal_fuse,
)
from echo_personal_tool.infrastructure.onnx_engine import (
    OnnxInferenceEngine,
    _default_models_dir,
    _load_manifest,
)
from echo_personal_tool.domain.services.auto_depth_calibration import (
    try_auto_depth_calibration,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.system_profiler import (
    PlaybackConfig,
    detect_playback_config,
)
from echo_personal_tool.infrastructure.video_reader import VideoReader

_FRAME_CACHE_WARN_BYTES = 512 * 1024 * 1024

# ── Freeze diagnostics (set ECHO_FREEZE_DIAG=1 to enable) ────────────
import os as _os
_FREEZE_DIAG = _os.environ.get("ECHO_FREEZE_DIAG", "0") == "1"
_diag_log = logging.getLogger("echo_freeze_diag")
logger = logging.getLogger(__name__)


class AppController(QObject):
    """Coordinates scanning and frame loading between UI and infrastructure."""

    studies_loaded = Signal(list)
    scan_failed = Signal(str)
    frame_loaded = Signal(np.ndarray)
    frame_load_failed = Signal(str)
    thumbnail_loaded = Signal(str, QImage)
    status_message = Signal(str)
    decode_progress = Signal(int, int)  # current, total
    decode_finished = Signal()
    speckle_result_ready = Signal(object)
    scroll_settled = Signal()

    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        segmenter: IOnnxSegmenter | None = None,
        thumbnail_scheduler: ThumbnailScheduler | None = None,
        thumbnail_max_in_flight: int = 6,
    ) -> None:
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._state_manager = StateManager()
        self._measurement_session = StudyMeasurementSessionStore()
        self._current_study_uid: str | None = None
        self._segmenter = segmenter or OnnxInferenceEngine()
        self._playback_config: PlaybackConfig = detect_playback_config()
        self._frame_cache = FrameCache(evict_window=self._playback_config.evict_window)
        self._timer = QTimer(self)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._advance_playback)
        if sys.platform == "win32":
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._last_frame_shown_at: float = 0.0
        self._playback_warmup_pending = False
        self._playback_poll_interval_ms = 33
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
        self._pending_emit_after_decode = False
        self._thumbnail_max_in_flight = thumbnail_max_in_flight
        self._playback_speed_multiplier = 1.0
        self._thumbnail_scheduler = (
            thumbnail_scheduler
            if thumbnail_scheduler is not None
            else ThumbnailScheduler(max_in_flight=self._thumbnail_max_in_flight)
        )
        self._thumbnail_instances: dict[str, InstanceMetadata] = {}
        self._thumbnail_in_flight: dict[str, ThumbnailPriority] = {}
        self._current_frame_pixels: np.ndarray | None = None
        self._leading_static_frames: dict[Path, int] = {}
        self._batch_load_id: int = 0
        self._batch_target_frame: int = 0
        self._prefetch_request_id: int = 0
        self._prefetch_load_id: int = 0
        self._prefetch_load_started_at: float = 0.0
        self._prefetch_batch_start: float = 0.0
        self._prefetch_ema_latency_ms: float = 0.0
        self._diag_frame_counter: int = 0
        self._adaptive_batch_size: int = self._playback_config.batch_size
        self._scroll_load_id: int = 0
        self._scroll_load_started_at: float = 0.0
        self._scroll_neighbor_load_id: int = 0
        self._scroll_active: bool = False
        self._scroll_settle_timer: QTimer | None = None
        self._last_pinned_frame: int | None = None
        self._live_workers: set = set()
        self._segment_in_progress = False
        self._auto_segment_phase: str | None = None
        self._auto_segment_view: str = "A4C"
        self._auto_segment_chamber: str = "LV"
        # Debug ROI overlay
        self._last_segment_roi_xyxy: tuple[float, float, float, float] | None = None
        # Temporal fusion state
        self._fusion_in_progress = False
        self._fusion_config: object | None = None
        self._fusion_anchor_frame: int = -1
        self._fusion_phase: str | None = None
        self._fusion_view: str = "A4C"
        self._fusion_chamber: str = "LV"
        self._fusion_instance_path: Path | None = None
        self._fusion_original_shape: tuple[int, int] = (0, 0)
        self._fusion_masks: dict[int, np.ndarray] = {}
        self._fusion_contours: dict[int, Contour] = {}
        self._fusion_window: list[int] = []
        self._fusion_processed: set[int] = set()  # tracks done/failed frames
        self._fusion_result: TemporalFusionResult | None = None
        self._scan_started_at: float | None = None
        self._first_preview_emitted = False
        self._study_metrics_auto_filled = False
        self._state_manager.state_changed.connect(self._on_state_changed)

    def _retain_worker(self, worker: FrameLoaderWorker) -> None:
        """Prevent GC of a QRunnable until its QueuedConnection signals are delivered."""
        # Safety: if too many workers are retained, force-release the oldest
        # to prevent unbounded memory growth (each holds decoded numpy arrays).
        if len(self._live_workers) > 8:
            leaked = list(self._live_workers)[:len(self._live_workers) - 4]
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[retain_worker] LEAK DETECTED: force-releasing %d stale workers",
                    len(leaked),
                )
            for w in leaked:
                self._live_workers.discard(w)
        self._live_workers.add(worker)

    def _release_worker(self, worker: FrameLoaderWorker, *_args: object) -> None:
        """Release a retained worker after its signals have been processed."""
        self._live_workers.discard(worker)
        if len(self._live_workers) == 0:
            import gc
            gc.collect()

    @property
    def studies(self) -> list[StudyMetadata]:
        return self._studies

    @property
    def state_manager(self) -> StateManager:
        return self._state_manager

    @property
    def playback_config(self) -> PlaybackConfig:
        return self._playback_config

    @property
    def fusion_result(self) -> TemporalFusionResult | None:
        return self._fusion_result

    @property
    def last_segment_roi_xyxy(self) -> tuple[float, float, float, float] | None:
        return self._last_segment_roi_xyxy

    def is_scroll_active(self) -> bool:
        return self._scroll_active

    def open_folder(self, root: Path, error_log_path: Path | None = None) -> None:
        self._measurement_session.clear()
        self._current_study_uid = None
        self._scan_started_at = perf_counter()
        self._first_preview_emitted = False
        self._study_metrics_auto_filled = False
        logger.info("scan_start root=%s", root)
        self.status_message.emit(tr("status.scanning_folder", path=str(root)))
        worker = ScanWorker(root, error_log_path=error_log_path, parent=self)
        worker.signals.finished.connect(self._on_studies_scanned, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_scan_failed, Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def load_pre_scanned_studies(self, studies: list[StudyMetadata]) -> None:
        """Load studies already built by the download worker (skip ScanWorker)."""
        n_inst = sum(len(s.instances) for st in studies for s in st.series)
        logger.info("[CTRL] load_pre_scanned_studies: %d studies, %d instances", len(studies), n_inst)
        self._measurement_session.clear()
        self._current_study_uid = None
        self._first_preview_emitted = False
        self._study_metrics_auto_filled = False
        self._studies = studies
        count = len(self._studies)
        logger.info("pre_scanned_load studies=%d", count)
        self.status_message.emit(tr("status.studies_loaded", count=str(count)))
        self.studies_loaded.emit(self._studies)

    def _on_studies_scanned(self, studies: object) -> None:
        self._studies = list(studies)  # type: ignore[arg-type]
        count = len(self._studies)
        n_inst = sum(len(s.instances) for st in self._studies for s in st.series)
        logger.info("[CTRL] _on_studies_scanned: %d studies, %d instances", count, n_inst)
        elapsed_ms = (
            (perf_counter() - self._scan_started_at) * 1000.0
            if self._scan_started_at is not None
            else None
        )
        if elapsed_ms is None:
            logger.info("scan_done studies=%d", count)
        else:
            logger.info("scan_done studies=%d duration_ms=%.2f", count, elapsed_ms)
        self._scan_started_at = None
        self.status_message.emit(tr("status.studies_loaded", count=str(count)))
        self.studies_loaded.emit(self._studies)

    def _on_scan_failed(self, message: str) -> None:
        elapsed_ms = (
            (perf_counter() - self._scan_started_at) * 1000.0
            if self._scan_started_at is not None
            else None
        )
        if elapsed_ms is None:
            logger.warning("scan_failed reason=%s", message)
        else:
            logger.warning("scan_failed duration_ms=%.2f reason=%s", elapsed_ms, message)
        self._scan_started_at = None
        self.status_message.emit(tr("status.scan_failed", message=message))
        self.scan_failed.emit(message)

    def load_instance(self, instance: InstanceMetadata, frame_index: int = 0) -> None:
        if instance.path is None:
            self.frame_load_failed.emit("Instance has no file path")
            return
        self._current_instance = instance
        self._clear_fusion_state()
        if (
            not self._study_metrics_auto_filled
            and instance.patient_height_m is not None
            and instance.patient_weight_kg is not None
        ):
            study_uid = self._resolve_study_uid()
            session = self._measurement_session.get(study_uid)
            if session.height_cm is None and session.weight_kg is None:
                self.on_patient_metrics_changed(
                    instance.patient_height_m * 100,
                    instance.patient_weight_kg,
                )
                self._study_metrics_auto_filled = True
        self.status_message.emit(tr("status.loading", name=instance.path.name))
        total_frames = instance.number_of_frames
        frame_time_ms = instance.frame_time_ms or 33.3
        if total_frames <= 0 and instance.media_format == "mp4" and instance.path is not None:
            try:
                with VideoReader() as reader:
                    reader.open(instance.path)
                    total_frames = reader.frame_count
                    fps = reader.fps
                frame_time_ms = 1000.0 / fps if fps > 0 else 33.3
            except Exception as exc:  # noqa: BLE001
                self.frame_load_failed.emit(str(exc))
                return

        self._frame_cache.clear()
        # Free heavy DICOM buffers (pixel data, encapsulated frames) from
        # all thread-local sessions when switching instances.
        from echo_personal_tool.infrastructure.dicom_session import release_stale_sessions
        release_stale_sessions()
        self._last_pinned_frame = None
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
            emit=False,
        )
        study_uid = self._resolve_study_uid(instance)
        self._measurement_session.set_manual_pixel_spacing(study_uid, None)
        session_contours = contours_for_instance(
            self._measurement_session.get(study_uid).contours,
            instance.sop_instance_uid,
        )
        if instance.media_format != "dicom":
            session_contours = tuple(
                contour
                for contour in session_contours
                if not (contour.source == "ai" and contour.review_pending)
            )
            self._measurement_session.set_cine_segment_roi(study_uid, instance.sop_instance_uid, None)
        self._state_manager.set_contours(session_contours, emit=False)
        if instance.media_format == "dicom":
            self._state_manager.set_decode_in_progress(True, emit=False)
        if instance.media_format == "mp4":
            self._state_manager.set_decode_in_progress(True, emit=False)
        if instance.media_format in ("dicom", "mp4"):
            self._decode_request_id += 1
            self._pending_decode_id = self._decode_request_id
            self._pending_emit_after_decode = True
        else:
            self._state_manager.emit_state()
            self._pending_emit_after_decode = False
        if frame_index != 0:
            self._state_manager.set_frame(frame_index)
        self._current_study_uid = self._resolve_study_uid(instance)
        self._recompute_measurements()
        if instance.media_format == "dicom":
            request_id = self._decode_request_id
            self.status_message.emit(
                tr("status.decoding", name=instance.path.name, total=str(total_frames))
            )
            self._frame_cache.set_total_frames(instance.path, total_frames)
            worker = DicomDecodeWorker(instance.path, request_id, parent=self, first_frame_only=True)
            worker.signals.first_frame_ready.connect(self._on_first_frame_ready, Qt.ConnectionType.QueuedConnection)
            worker.signals.progress.connect(self.decode_progress.emit, Qt.ConnectionType.QueuedConnection)
            worker.signals.finished.connect(self._on_dicom_decoded, Qt.ConnectionType.QueuedConnection)
            worker.signals.failed.connect(self._on_dicom_decode_failed, Qt.ConnectionType.QueuedConnection)
            self._thread_pool.start(worker)
            return
        if instance.media_format == "mp4":
            request_id = self._decode_request_id
            self.status_message.emit(
                tr("status.decoding_video", name=instance.path.name, total=str(total_frames))
            )
            self._frame_cache.set_total_frames(instance.path, total_frames)
            worker = VideoDecodeWorker(instance.path, request_id, parent=self, first_frame_only=True)
            worker.signals.first_frame_ready.connect(self._on_first_frame_ready, Qt.ConnectionType.QueuedConnection)
            worker.signals.progress.connect(self.decode_progress.emit, Qt.ConnectionType.QueuedConnection)
            worker.signals.finished.connect(self._on_dicom_decoded, Qt.ConnectionType.QueuedConnection)
            worker.signals.failed.connect(self._on_dicom_decode_failed, Qt.ConnectionType.QueuedConnection)
            self._thread_pool.start(worker)
            return

        self._request_frame_if_needed(self._state_manager.snapshot)

    def load_thumbnail(self, instance: InstanceMetadata) -> None:
        self.request_thumbnail_preview(instance, ThumbnailPriority.P2_BACKGROUND)

    def request_thumbnail_preview(
        self,
        instance: InstanceMetadata,
        priority: ThumbnailPriority = ThumbnailPriority.P2_BACKGROUND,
    ) -> None:
        if instance.path is None:
            return
        uid = instance.sop_instance_uid
        self._thumbnail_instances[uid] = instance
        self._thumbnail_scheduler.enqueue(uid, priority)
        self._pump_thumbnail_queue()

    def request_thumbnail_previews(
        self,
        instances: list[InstanceMetadata],
        priority: ThumbnailPriority = ThumbnailPriority.P2_BACKGROUND,
    ) -> None:
        uids: list[str] = []
        for instance in instances:
            if instance.path is None:
                continue
            uid = instance.sop_instance_uid
            self._thumbnail_instances[uid] = instance
            uids.append(uid)
        if not uids:
            return
        self._thumbnail_scheduler.reprioritize(uids, priority)
        self._pump_thumbnail_queue()

    def _pump_thumbnail_queue(self) -> None:
        while True:
            batch = self._thumbnail_scheduler.next_batch(limit=16)
            if not batch:
                return
            for task in batch:
                instance = self._thumbnail_instances.get(task.sop_instance_uid)
                if instance is None or instance.path is None:
                    self._thumbnail_scheduler.mark_failed(task.sop_instance_uid)
                    self._thumbnail_instances.pop(task.sop_instance_uid, None)
                    continue
                worker = ThumbnailLoaderWorker(
                    instance.path,
                    task.sop_instance_uid,
                    number_of_frames=instance.number_of_frames,
                    media_format=instance.media_format,
                    parent=self,
                )
                worker.signals.finished.connect(self._on_thumbnail_loaded, Qt.ConnectionType.QueuedConnection)
                worker.signals.failed.connect(self._on_thumbnail_failed, Qt.ConnectionType.QueuedConnection)
                self._thumbnail_in_flight[task.sop_instance_uid] = task.priority
                self._thread_pool.start(worker)

    def _on_thumbnail_loaded(self, sop_instance_uid: str, image: QImage) -> None:
        self._thumbnail_scheduler.mark_done(sop_instance_uid)
        self._thumbnail_in_flight.pop(sop_instance_uid, None)
        self._thumbnail_instances.pop(sop_instance_uid, None)
        if not self._first_preview_emitted:
            self._first_preview_emitted = True
            logger.info("first_preview_emitted uid=%s", sop_instance_uid)
        self.thumbnail_loaded.emit(sop_instance_uid, image)
        self._pump_thumbnail_queue()

    def _on_thumbnail_failed(self, sop_instance_uid: str, _message: str) -> None:
        self._thumbnail_scheduler.mark_failed(sop_instance_uid)
        self._thumbnail_in_flight.pop(sop_instance_uid, None)
        self._thumbnail_instances.pop(sop_instance_uid, None)
        self._pump_thumbnail_queue()

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

    def _detect_leading_static_from_cache(self, path: Path, total: int) -> int:
        if not self._frame_cache.is_loaded(0):
            return 0
        ref = self._frame_cache.get(0).astype(np.float32, copy=False)
        leading = 0
        for idx in range(1, min(total, 16)):
            if not self._frame_cache.is_loaded(idx):
                break
            diff = float(np.mean(np.abs(self._frame_cache.get(idx).astype(np.float32, copy=False) - ref)))
            if diff > 1.0:
                break
            leading = idx
        return leading

    def _ensure_leading_static_scanned(self) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        path = self._current_instance.path.resolve()
        if path in self._leading_static_frames:
            return
        total = self._frame_cache.frame_count()
        if total <= 1:
            self._leading_static_frames[path] = 0
            return
        if not self._frame_cache.is_loaded(0):
            self._prefetch_leading_scan_frames(path, total)
            return
        leading = self._detect_leading_static_from_cache(path, total)
        self._leading_static_frames[path] = leading

    def _prefetch_leading_scan_frames(self, path: Path, total: int) -> None:
        scan_count = min(8, total)
        batch = [i for i in range(scan_count) if not self._frame_cache.is_loaded(i)]
        if not batch:
            leading = self._detect_leading_static_from_cache(path, total)
            self._leading_static_frames[path] = leading
            return
        self._prefetch_request_id += 1
        request_id = self._prefetch_request_id
        self._prefetch_load_id = request_id
        worker = FrameLoaderWorker(
            path,
            frame_index=batch[0],
            media_format=self._current_instance.media_format if self._current_instance else "dicom",
            parent=self,
            total_frames=total,
            batch_size=len(batch),
        )
        worker.signals.batch_finished.connect(
            partial(self._on_leading_scan_batch_loaded, request_id, path, total)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(partial(self._on_leading_scan_failed, request_id, path, total), Qt.ConnectionType.QueuedConnection)
        self._retain_worker(worker)
        worker.signals.batch_finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def _on_leading_scan_batch_loaded(self, request_id: int, path: Path, total: int, frames: list) -> None:
        is_current = request_id == self._prefetch_load_id
        if is_current:
            self._prefetch_load_id = 0
        # Always cache frames even for stale requests.
        for idx, pixels in frames:
            self._frame_cache.put(idx, pixels)
        if path not in self._leading_static_frames:
            leading = self._detect_leading_static_from_cache(path, total)
            self._leading_static_frames[path] = leading
        if self._state_manager.snapshot.is_playing:
            current = self._state_manager.snapshot.current_frame_index
            self._prefetch_playback_buffer(current)

    def _on_leading_scan_failed(self, request_id: int, path: Path, total: int, message: str) -> None:
        if request_id != self._prefetch_load_id:
            return
        self._prefetch_load_id = 0
        self._leading_static_frames[path] = 0
        if self._state_manager.snapshot.is_playing:
            current = self._state_manager.snapshot.current_frame_index
            self._prefetch_playback_buffer(current)

    def set_playing(self, is_playing: bool) -> None:
        if is_playing:
            self._invalidate_prefetch()
            if self._current_instance is not None and self._current_instance.path is not None:
                self._ensure_leading_static_scanned()
                state = self._state_manager.snapshot
                if state.current_frame_index == 0:
                    leading = self._leading_static_frames.get(
                        self._current_instance.path.resolve(), 0
                    )
                    if leading > 0:
                        target = min(leading + 1, max(0, state.total_frames - 1))
                        if target > 0:
                            self._state_manager.set_frame(target)
            warmup_needed = False
            current = self._state_manager.snapshot.current_frame_index
            cfg = self._playback_config
            if (
                self._current_instance is not None
                and self._current_instance.path is not None
                and self._frame_cache.is_ready(self._current_instance.path)
            ):
                ahead = self._frame_cache.loaded_ahead(current)
                warmup_needed = ahead < cfg.min_buffer
            self._playback_warmup_pending = warmup_needed
        else:
            self._invalidate_prefetch()
            self._playback_warmup_pending = False
        self._state_manager.set_playing(is_playing)
        if is_playing:
            current = self._state_manager.snapshot.current_frame_index
            self._prefetch_playback_buffer(current)
            if self._playback_warmup_pending:
                self._reschedule_playback_timer(poll=True)
                return
            self._last_frame_shown_at = perf_counter()
            self._reschedule_playback_timer()

    def toggle_playback(self) -> None:
        self.set_playing(not self._state_manager.snapshot.is_playing)

    def set_playback_speed_multiplier(self, multiplier: float) -> None:
        self._playback_speed_multiplier = max(0.25, min(4.0, float(multiplier)))
        self._on_state_changed(self._state_manager.snapshot)

    def step_frame(self, delta: int) -> None:
        self._state_manager.step_frame(delta)

    def set_simpson_workflow_context(
        self,
        *,
        phase: str | None,
        view: str = "A4C",
        chamber: str = "LV",
    ) -> None:
        self._auto_segment_phase = phase.upper() if phase else None
        self._auto_segment_view = view
        self._auto_segment_chamber = chamber

    def is_lv_auto_session_active(self) -> bool:
        phase = self._auto_segment_phase
        view = self._auto_segment_view or ""
        return phase in {"ED", "ES"} and view.upper() == "A4C"

    def accept_ai_contour_review(self, view: str, phase: str) -> bool:
        target_view = view.upper()
        target_phase = phase.upper()
        updated_contours: list[Contour] = []
        found = False
        for contour in self._state_manager.snapshot.contours:
            if (
                contour.source == "ai"
                and contour.review_pending
                and contour.view.upper() == target_view
                and contour.phase.upper() == target_phase
            ):
                updated_contours.append(dataclasses.replace(contour, review_pending=False))
                found = True
            else:
                updated_contours.append(contour)
        if not found:
            return False
        self._clear_fusion_state()
        self.on_contours_changed(updated_contours)
        self.status_message.emit(tr("app.contour_accepted", target_view=target_view, target_phase=target_phase))
        return True

    def save_gold_annotation(self, *, phase: str, frame_index: int, chamber: str = "LV") -> None:
        """Save the accepted contour on the given frame as gold annotation."""
        from echo_personal_tool.domain.services.gold_store import (
            gold_filename,
            make_gold_frame,
            make_gold_study,
            merge_frame_into_gold,
            rebuild_manifest_from_gold_dir,
            save_gold,
            try_load_gold,
        )

        chamber = chamber.upper()
        if chamber == "LA":
            if phase != "ES":
                self.status_message.emit(tr("app.gold_la_requires_es_a4c"))
                return

        snapshot = self._state_manager.snapshot
        instance = snapshot.instance
        if instance is None or instance.media_format != "dicom":
            return

        import os
        from echo_personal_tool.infrastructure.user_preferences import _read_bool, _settings_store
        store = _settings_store()
        gold_enabled = _read_bool(store.value("gold_annotation_enabled"), False)
        if not gold_enabled and os.environ.get("ECHO_GOLD_EXPORT", "") != "1":
            return

        gold_path_str = str(store.value("gold_dataset_path", ""))
        if not gold_path_str:
            gold_path_str = os.environ.get("ECHO_GOLD_PATH", "")
        gold_root = Path(gold_path_str)
        if not gold_root.is_dir():
            self.status_message.emit(tr("app.gold_path_invalid"))
            return

        study_uid = self._resolve_study_uid(instance)
        gold_dir = gold_root / "gold"
        gold_path = gold_dir / gold_filename(study_uid, chamber)

        # Find accepted contour on this frame matching chamber
        contour = None
        for c in snapshot.contours:
            if not self._gold_contour_matches(c, chamber=chamber, phase=phase, frame_index=frame_index):
                continue
            contour = c
            break
        if contour is None:
            self.status_message.emit(tr("app.gold_no_contour", phase=phase, chamber=chamber))
            return
        if chamber == "LA" and contour.view != "A4C":
            self.status_message.emit(tr("app.gold_la_requires_es_a4c"))
            return
        if contour.mitral_annulus is None:
            self.status_message.emit(tr("app.gold_no_annulus", chamber=chamber))
            return

        pixel_spacing = snapshot.effective_pixel_spacing
        ps_mm = list(pixel_spacing) if pixel_spacing else [0.0, 0.0]
        source = "ai_corrected" if contour.source == "ai" else "manual"

        frame_data = make_gold_frame(
            frame_index=frame_index,
            phase=phase,
            chamber=chamber,
            points=[list(p) for p in contour.points],
            mitral_annulus=[list(contour.mitral_annulus[0]), list(contour.mitral_annulus[1])],
            apex_landmark=list(contour.apex_landmark) if contour.apex_landmark else None,
            source=source,
            annotator="",
            view="A4C",
            sop_instance_uid=instance.sop_instance_uid,
            instance_path=str(instance.path),
        )

        existing = try_load_gold(gold_path)
        if existing is not None:
            merged = merge_frame_into_gold(existing, frame_data)
        else:
            merged = make_gold_study(
                study_id=study_uid,
                instance_path=str(instance.path),
                pixel_spacing_mm=ps_mm,
                chamber=chamber,
                sop_instance_uid=instance.sop_instance_uid,
            )
            merged = merge_frame_into_gold(merged, frame_data)

        gold_path.parent.mkdir(parents=True, exist_ok=True)
        save_gold(gold_path, merged)

        rebuild_manifest_from_gold_dir(gold_root)

        self.status_message.emit(
            tr("app.gold_saved", phase=phase, frame=frame_index + 1, path=str(gold_path))
        )

    @staticmethod
    def _gold_contour_matches(
        contour: Contour,
        *,
        chamber: str,
        phase: str,
        frame_index: int,
        view: str = "A4C",
    ) -> bool:
        if contour.chamber != chamber or contour.view != view or contour.phase != phase:
            return False
        if contour.review_pending:
            return False
        if contour.frame_index is not None and contour.frame_index != frame_index:
            return False
        return True

    def _clear_fusion_state(self) -> None:
        """Clear temporal fusion state after accept/discard/instance change."""
        self._fusion_in_progress = False
        self._fusion_config = None
        self._fusion_anchor_frame = -1
        self._fusion_phase = None
        self._fusion_view = "A4C"
        self._fusion_chamber = "LV"
        self._fusion_instance_path = None
        self._fusion_original_shape = (0, 0)
        self._fusion_masks = {}
        self._fusion_contours = {}
        self._fusion_window = []
        self._fusion_processed = set()
        self._fusion_result = None

    def request_auto_segment(
        self,
        *,
        phase: str | None = None,
        view: str | None = None,
        chamber: str | None = None,
    ) -> None:
        if self._segment_in_progress:
            self.status_message.emit(tr("status.segmentation_in_progress"))
            return

        state = self._state_manager.snapshot
        if state.is_playing:
            self.status_message.emit(tr("status.pause_before_segmentation"))
            return

        phase = phase or self._auto_segment_phase
        view = view or self._auto_segment_view
        chamber = chamber or self._auto_segment_chamber
        if phase is None or phase not in {"ED", "ES"}:
            self.status_message.emit(tr("status.auto_segmentation_select_phase"))
            return

        if (view or "").upper() != "A4C":
            self.status_message.emit(tr("app.segmentation_unavailable"))
            return

        if (
            self._current_frame_pixels is None
            or self._loaded_frame_index != state.current_frame_index
        ):
            self.status_message.emit(tr("status.frame_not_loaded"))
            return

        if not self._segmenter.is_available():
            self.status_message.emit(tr("app.segmentation_unavailable"))
            return

        frame = np.ascontiguousarray(self._current_frame_pixels)
        original_shape = (int(frame.shape[0]), int(frame.shape[1]))
        instance_path = self._current_instance.path if self._current_instance is not None else None
        media_format = (
            self._current_instance.media_format if self._current_instance is not None else "dicom"
        )
        frame_index = state.current_frame_index
        roi_xyxy = self._resolve_segment_roi_bounds(
            frame,
            instance_path,
            media_format=media_format,
            phase=phase,
        )
        self._last_segment_roi_xyxy = roi_xyxy
        crop_mode = echonet_crop_mode_for_media(media_format)

        if media_format != "dicom" and frame.ndim == 3 and frame.shape[2] == 3:
            gray = np.mean(frame[..., :3], axis=2).astype(np.uint8)
            frame = np.stack([gray, gray, gray], axis=-1)  # grayscale → 3ch for ONNX

        self._segment_in_progress = True
        worker = OnnxWorker(frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode, parent=self)
        worker.signals.finished.connect(
            partial(
                self._on_auto_segment_finished,
                phase,
                view,
                chamber,
                instance_path,
                frame_index,
                original_shape,
            )
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(
            partial(self._on_auto_segment_failed, instance_path, frame_index)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.timed_out.connect(
            partial(self._on_auto_segment_timed_out, instance_path, frame_index)
        , Qt.ConnectionType.QueuedConnection)

        worker.setAutoDelete(False)
        self._retain_worker(worker)
        worker.signals.finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.timed_out.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def on_doppler_markers_changed(self, dto: object) -> None:
        if not isinstance(dto, DopplerMeasurementDTO):
            raise TypeError("Expected DopplerMeasurementDTO")

        self._state_manager.set_doppler_measurement(dto, emit=False)
        instance = self._current_instance or self._state_manager.snapshot.instance
        if instance is not None:
            study_uid = self._resolve_study_uid()
            frame_index = self._state_manager.snapshot.current_frame_index
            self._measurement_session.merge_doppler_for_instance_frame(
                study_uid,
                instance.sop_instance_uid,
                frame_index,
                dto,
            )
        self._recompute_measurements()
        self.status_message.emit(self._format_doppler_summary(dto))

    def save_doppler_for_frame(
        self,
        instance_uid: str,
        frame_index: int,
        dto: DopplerMeasurementDTO,
    ) -> None:
        if not dto.peaks and not dto.intervals and not dto.traces:
            return
        study_uid = self._resolve_study_uid()
        self._measurement_session.merge_doppler_for_instance_frame(
            study_uid,
            instance_uid,
            frame_index,
            dto,
        )
        self._recompute_measurements()

    def get_doppler_dto_for_instance_frame(
        self,
        instance_uid: str,
        frame_index: int,
    ) -> DopplerMeasurementDTO | None:
        study_uid = self._resolve_study_uid()
        return self._measurement_session.get_doppler_for_instance_frame(
            study_uid,
            instance_uid,
            frame_index,
        )

    def save_current_instance_doppler(self, dto: DopplerMeasurementDTO) -> None:
        """Persist Doppler markers for the active instance before switching clips."""
        if self._current_instance is None:
            return
        if not dto.peaks and not dto.intervals and not dto.traces:
            return
        study_uid = self._resolve_study_uid()
        self._measurement_session.merge_doppler_for_instance(
            study_uid,
            self._current_instance.sop_instance_uid,
            dto,
        )
        self._recompute_measurements()

    def save_current_doppler_calibration(
        self,
        calibration: DopplerCalibrationState | None,
    ) -> None:
        if self._current_instance is None or calibration is None:
            return
        study_uid = self._resolve_study_uid()
        self._measurement_session.set_doppler_calibration(
            study_uid,
            self._current_instance.sop_instance_uid,
            calibration,
        )

    def on_doppler_calibration_changed(self, calibration: object) -> None:
        if not isinstance(calibration, DopplerCalibrationState):
            raise TypeError("Expected DopplerCalibrationState")
        if self._current_instance is None:
            return
        study_uid = self._resolve_study_uid()
        frame_index = self._state_manager.snapshot.current_frame_index
        self._measurement_session.set_doppler_calibration(
            study_uid,
            self._current_instance.sop_instance_uid,
            calibration,
        )
        self._measurement_session.set_doppler_calibration_for_frame(
            study_uid,
            self._current_instance.sop_instance_uid,
            frame_index,
            calibration,
        )

    def save_doppler_calibration_for_frame(
        self,
        instance_uid: str,
        frame_index: int,
        calibration: DopplerCalibrationState | None,
    ) -> None:
        study_uid = self._resolve_study_uid()
        self._measurement_session.set_doppler_calibration_for_frame(
            study_uid,
            instance_uid,
            frame_index,
            calibration,
        )

    def get_doppler_calibration_for_instance_frame(
        self,
        instance_uid: str,
        frame_index: int,
    ) -> DopplerCalibrationState | None:
        study_uid = self._resolve_study_uid()
        return self._measurement_session.get_doppler_calibration_for_frame(
            study_uid,
            instance_uid,
            frame_index,
        )

    def on_mmode_time_calibration(self, time_per_pixel_ms: object) -> None:
        if not isinstance(time_per_pixel_ms, (int, float)):
            raise TypeError("Expected numeric time_per_pixel_ms")
        study_uid = self._resolve_study_uid()
        self._measurement_session.set_mmode_time_per_pixel_ms(study_uid, float(time_per_pixel_ms))
        self.status_message.emit(
            tr("status.mmode_time", time=f"{float(time_per_pixel_ms):.3f}")
        )

    def on_mmode_calibration_changed(self, calibration: object) -> None:
        from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState

        if not isinstance(calibration, MmodeCalibrationState):
            raise TypeError("Expected MmodeCalibrationState")
        if self._current_instance is None:
            return
        study_uid = self._resolve_study_uid()
        self._measurement_session.set_mmode_calibration(
            study_uid,
            self._current_instance.sop_instance_uid,
            calibration,
        )

    def get_mmode_calibration_for_instance(
        self,
        instance_uid: str,
    ):

        study_uid = self._resolve_study_uid()
        return self._measurement_session.get_mmode_calibration(study_uid, instance_uid)

    def get_doppler_calibration_for_instance(
        self,
        instance_uid: str,
    ) -> DopplerCalibrationState | None:
        study_uid = self._resolve_study_uid()
        return self._measurement_session.get_doppler_calibration(study_uid, instance_uid)

    def get_doppler_dto_for_instance(self, instance_uid: str) -> DopplerMeasurementDTO | None:
        study_uid = self._resolve_study_uid()
        return self._measurement_session.get_doppler_for_instance(study_uid, instance_uid)

    def _current_doppler_dto(
        self,
        session: StudyMeasurementData,
    ) -> DopplerMeasurementDTO | None:
        instance = self._current_instance or self._state_manager.snapshot.instance
        if instance is None:
            return session.doppler_measurement
        frame_index = self._state_manager.snapshot.current_frame_index
        return self._measurement_session.get_doppler_for_instance_frame(
            self._resolve_study_uid(instance),
            instance.sop_instance_uid,
            frame_index,
        )

    def on_contours_changed(self, contours: object) -> None:
        if not isinstance(contours, list) or not all(
            isinstance(contour, Contour) for contour in contours
        ):
            raise TypeError("Expected a list of Contour objects")

        instance = self._current_instance or self._state_manager.snapshot.instance
        if instance is None:
            return
        tagged: list[Contour] = []
        for contour in contours:
            if contour.sop_instance_uid != instance.sop_instance_uid:
                tagged.append(
                    dataclasses.replace(contour, sop_instance_uid=instance.sop_instance_uid)
                )
            else:
                tagged.append(contour)
        contour_tuple = tuple(tagged)
        self._state_manager.set_contours(contour_tuple, emit=False)
        study_uid = self._resolve_study_uid()
        self._measurement_session.merge_contours(study_uid, contour_tuple)
        self._recompute_measurements()

    def on_linear_measurements_changed(self, measurements: object) -> None:
        if not isinstance(measurements, list) or not all(
            isinstance(measurement, LinearMeasurement) for measurement in measurements
        ):
            raise TypeError("Expected a list of LinearMeasurement objects")

        measurement_tuple = tuple(measurements)
        self._state_manager.set_linear_measurements(measurement_tuple, emit=False)
        study_uid = self._resolve_study_uid()
        self._measurement_session.merge_linear_measurements(study_uid, measurement_tuple)
        self._recompute_measurements()

    def on_manual_calibration(self, spacing: object) -> None:
        if not isinstance(spacing, tuple) or len(spacing) != 2:
            raise TypeError("Expected manual calibration spacing as (row, column) tuple")
        row_spacing, col_spacing = float(spacing[0]), float(spacing[1])
        if row_spacing <= 0 or col_spacing <= 0:
            raise ValueError("Manual pixel spacing must be positive")
        spacing_tuple = (row_spacing, col_spacing)
        self._state_manager.set_manual_pixel_spacing(spacing_tuple)
        study_uid = self._resolve_study_uid()
        self._measurement_session.set_manual_pixel_spacing(study_uid, spacing_tuple)
        self._recompute_measurements()
        self.status_message.emit(
            tr("status.calibration_info", row=row_spacing, col=col_spacing)
        )

    def needs_manual_calibration(self) -> bool:
        instance = self._current_instance
        if instance is None or instance.media_format == "dicom":
            return False
        state = self._state_manager.snapshot
        if state.manual_pixel_spacing is not None:
            return False
        study_uid = self._resolve_study_uid(instance)
        session = self._measurement_session.get(study_uid)
        if session.manual_pixel_spacing is not None:
            return False
        return True

    def try_auto_depth_calibration(self, frame: np.ndarray) -> bool:
        if not self.needs_manual_calibration():
            return False
        result = try_auto_depth_calibration(frame)
        if result is None:
            return False
        self.on_manual_calibration(result.spacing)
        self.status_message.emit(tr("status.calibration_ok"))
        return True

    def on_patient_metrics_changed(
        self,
        height_cm: float | None,
        weight_kg: float | None,
    ) -> None:
        study_uid = self._resolve_study_uid()
        self._measurement_session.set_patient_metrics(study_uid, height_cm, weight_kg)
        self._recompute_measurements()

    def clear_manual_calibration(self) -> None:
        if (
            self._state_manager.snapshot.manual_pixel_spacing is None
            and self._resolve_study_uid() not in self._measurement_session
        ):
            return
        study_uid = self._resolve_study_uid()
        session = self._measurement_session.get(study_uid)
        if (
            self._state_manager.snapshot.manual_pixel_spacing is None
            and session.manual_pixel_spacing is None
        ):
            return
        self._state_manager.clear_manual_pixel_spacing()
        self._measurement_session.set_manual_pixel_spacing(study_uid, None)
        self._recompute_measurements()
        self.status_message.emit(tr("status.calibration_reset"))

    def reset_measurements_and_calibration(self) -> None:
        study_uid = self._resolve_study_uid()
        self._measurement_session.reset_measurements(study_uid)
        self._state_manager.reset_measurement_inputs()
        self._recompute_measurements()
        self.status_message.emit(tr("status.measurements_reset"))

    def _playback_interval_ms(self, state: ViewerState | None = None) -> int:
        snapshot = state if state is not None else self._state_manager.snapshot
        return max(
            1,
            int(round((snapshot.frame_time_ms or 33.3) / self._playback_speed_multiplier)),
        )

    def _reschedule_playback_timer(self, *, poll: bool = False) -> None:
        delay_ms = (
            self._playback_poll_interval_ms
            if poll or self._playback_warmup_pending
            else self._playback_interval_ms()
        )
        if not poll and not self._playback_warmup_pending and self._last_frame_shown_at > 0:
            elapsed_ms = (perf_counter() - self._last_frame_shown_at) * 1000.0
            delay_ms = max(1, int(delay_ms - elapsed_ms))
        self._timer.setInterval(delay_ms)
        if not self._timer.isActive():
            self._timer.start()

    def _on_state_changed(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        self._timer.setInterval(self._playback_interval_ms(state))
        if state.is_playing and not self._pending_decode_id and not self._playback_warmup_pending:
            self._reschedule_playback_timer()
        elif self._timer.isActive():
            self._timer.stop()
        self._request_frame_if_needed(state)

    def _resolve_pixel_spacing(
        self,
        state: ViewerState,
        session_manual_spacing: tuple[float, float] | None = None,
    ) -> tuple[tuple[float, float], bool]:
        """Return spacing for calculations and whether it is calibrated (DICOM or manual)."""
        manual_spacing = state.manual_pixel_spacing or session_manual_spacing
        if manual_spacing is not None:
            row_spacing, col_spacing = manual_spacing
            if row_spacing > 0.0 and col_spacing > 0.0:
                return manual_spacing, True
        spacing = state.effective_pixel_spacing
        if spacing is not None:
            row_spacing, col_spacing = spacing
            if row_spacing > 0.0 and col_spacing > 0.0:
                return spacing, True
        return (1.0, 1.0), False

    def resolve_study_uid(
        self,
        instance: InstanceMetadata | None = None,
    ) -> str:
        """Public API: resolve study UID for the given (or current) instance."""
        return self._resolve_study_uid(instance)

    def _resolve_study_uid(
        self,
        instance: InstanceMetadata | None = None,
    ) -> str:
        active = instance or self._current_instance or self._state_manager.snapshot.instance
        if active is None:
            return "__default__"
        for study in self._studies:
            for series in study.series:
                if series.series_uid == active.series_uid:
                    return study.study_uid
                if any(
                    item.sop_instance_uid == active.sop_instance_uid for item in series.instances
                ):
                    return study.study_uid
        if self._current_study_uid is not None:
            return self._current_study_uid
        return active.series_uid

    def compute_overlay_snapshot(self, state: ViewerState) -> MeasurementSnapshot | None:
        """Recompute metrics from study-wide measurements (for on-image overlay)."""
        instance = state.instance
        if instance is None:
            return None
        study_uid = self._resolve_study_uid(instance)
        session = self._measurement_session.get(study_uid)
        frame_index = state.current_frame_index
        doppler_dto = self._measurement_session.get_doppler_for_instance(
            study_uid,
            instance.sop_instance_uid,
        )
        if doppler_dto is None:
            doppler_dto = self._measurement_session.get_doppler_for_instance_frame(
                study_uid,
                instance.sop_instance_uid,
                frame_index,
            )
        if doppler_dto is None and instance.number_of_frames <= 1:
            doppler_dto = self._measurement_session.get_doppler_for_instance(
                study_uid,
                instance.sop_instance_uid,
            )
        # Filter contours to current instance so volumes use the correct pixel spacing.
        # Fall back to study-wide contours when the current instance has none.
        instance_uid = instance.sop_instance_uid
        instance_contours = tuple(
            c for c in session.contours if c.sop_instance_uid == instance_uid
        )
        contours = instance_contours if instance_contours else session.contours
        return self._build_measurement_snapshot(
            contours=contours,
            linear_measurements=session.linear_measurements,
            doppler_dto=doppler_dto,
            state=state,
            session=session,
        )

    def _recompute_measurements(self) -> None:
        state = self._state_manager.snapshot
        study_uid = self._resolve_study_uid()
        session = self._measurement_session.get(study_uid)
        doppler_dto = self._current_doppler_dto(session)
        snapshot = self._build_measurement_snapshot(
            contours=session.contours,
            linear_measurements=session.linear_measurements,
            doppler_dto=doppler_dto,
            state=state,
            session=session,
        )
        self._state_manager.set_measurement_snapshot(snapshot, emit=False)
        self._state_manager.set_linear_measurements(session.linear_measurements, emit=False)
        self._state_manager.emit_state()

    def _build_measurement_snapshot(
        self,
        *,
        contours: tuple[Contour, ...],
        linear_measurements: tuple[LinearMeasurement, ...],
        doppler_dto: DopplerMeasurementDTO | None,
        state: ViewerState,
        session: StudyMeasurementData,
    ) -> MeasurementSnapshot:
        doppler = compute(doppler_dto) if doppler_dto is not None else None
        pixel_spacing, spacing_calibrated = self._resolve_pixel_spacing(
            state,
            session.manual_pixel_spacing,
        )
        lvef = calculate(contours, pixel_spacing)
        teichholz = from_linear_measurements(linear_measurements)
        la_simpson = calculate_chamber(contours, "LA", pixel_spacing)
        ra_simpson = calculate_chamber(contours, "RA", pixel_spacing)
        rv_simpson = calculate_chamber(contours, "RV", pixel_spacing)
        la_volume = la_from_measurements(
            contours,
            linear_measurements,
            pixel_spacing if spacing_calibrated else None,
        )
        lvm_g = lvm_from_linear(linear_measurements)
        rwt = rwt_from_linear(linear_measurements)
        rv_fac_percent = (
            from_rv_contours(contours, pixel_spacing) if spacing_calibrated else None
        )
        planimeter = planimeter_results_from_contours(
            contours,
            pixel_spacing,
            spacing_calibrated=spacing_calibrated,
        )
        base_snapshot = MeasurementSnapshot(
            doppler=doppler,
            lvef=lvef,
            teichholz=teichholz,
            la_volume=la_volume,
            la_simpson=la_simpson,
            ra_simpson=ra_simpson,
            rv_simpson=rv_simpson,
            lvm_g=lvm_g,
            rwt=rwt,
            rv_fac_percent=rv_fac_percent,
            linear_measurements=linear_measurements,
            spacing_calibrated=spacing_calibrated,
            height_cm=session.height_cm,
            weight_kg=session.weight_kg,
            planimeter=planimeter,
        )
        indexed = compute_indexed_measurements(
            base_snapshot,
            height_cm=session.height_cm,
            weight_kg=session.weight_kg,
        )
        diastology_grade = None
        if doppler is not None and indexed is not None:
            lav_i = indexed.lav_bi_index_ml_m2 or indexed.lav_4c_index_ml_m2
            diastology_grade = grade_diastolic_function(
                e_over_e_prime=doppler.e_over_e_prime,
                lav_index_ml_m2=lav_i,
                tr_vmax_cm_s=doppler.tr_vmax_cm_s,
            )
        return MeasurementSnapshot(
            doppler=doppler,
            lvef=lvef,
            teichholz=teichholz,
            la_volume=la_volume,
            la_simpson=la_simpson,
            ra_simpson=ra_simpson,
            rv_simpson=rv_simpson,
            lvm_g=lvm_g,
            rwt=rwt,
            rv_fac_percent=rv_fac_percent,
            diastology_grade=diastology_grade,
            linear_measurements=linear_measurements,
            spacing_calibrated=spacing_calibrated,
            height_cm=session.height_cm,
            weight_kg=session.weight_kg,
            indexed=indexed,
            planimeter=planimeter,
        )

    def _request_frame_if_needed(self, state: ViewerState) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        if self._current_instance.media_format in ("dicom", "mp4"):
            if self._frame_cache.is_ready(self._current_instance.path):
                if self._loaded_frame_index != state.current_frame_index:
                    if self._emit_cached_frame(state.current_frame_index):
                        if state.scroll_navigation and not state.is_playing:
                            self._mark_scroll_active()
                            self._maybe_start_scroll_neighbors(state.current_frame_index)
                        return
                else:
                    return
            if (
                self._frame_cache.source_path is not None
                and self._frame_cache.source_path == Path(self._current_instance.path).resolve()
                and self._frame_cache.frame_count() > 0
            ):
                max_idx = self._frame_cache.frame_count() - 1
                idx = min(state.current_frame_index, max_idx)
                if self._loaded_frame_index != idx:
                    if self._emit_cached_frame(idx):
                        if state.scroll_navigation and not state.is_playing:
                            self._mark_scroll_active()
                            self._maybe_start_scroll_neighbors(idx)
                        return
                else:
                    return
            if self._pending_decode_id != 0:
                return
        if self._current_instance.media_format in ("dicom", "mp4") and self._pending_decode_id != 0:
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
            # Stale pending-load guard: force-clear if the worker hung.
            if perf_counter() - self._scroll_load_started_at < self._PREFETCH_TIMEOUT_SEC:
                return
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[request_frame] STALE pending_load_id=%d after %.1fs, clearing",
                    self._pending_load_id, perf_counter() - self._scroll_load_started_at,
                )
            self._pending_load_id = 0

        if self._current_instance.media_format in ("dicom", "mp4") and self._frame_cache.frame_count() > 0:
            scroll = state.scroll_navigation and not state.is_playing
            self._start_scroll_target_load(state.current_frame_index, scroll=scroll)
            return

        self._batch_target_frame = state.current_frame_index
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
            total_frames=self._frame_cache.frame_count(),
            batch_size=0,
        )
        worker.signals.finished.connect(
            partial(
                self._on_frame_loaded,
                request_id,
                self._current_instance.path,
                state.current_frame_index,
            )
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(partial(self._on_frame_load_failed, request_id), Qt.ConnectionType.QueuedConnection)
        self._retain_worker(worker)
        worker.signals.finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def _start_scroll_target_load(self, target: int, *, scroll: bool = False) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        if scroll and not self._state_manager.snapshot.is_playing:
            self._mark_scroll_active()
            self._invalidate_prefetch()
        self._scroll_neighbor_load_id = 0
        self._batch_target_frame = target
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[scroll_start] target=%d scroll=%d old_scroll_load=%d",
                target, scroll, self._scroll_load_id,
            )
        self._load_request_id += 1
        request_id = self._load_request_id
        self._scroll_load_id = request_id
        self._scroll_load_started_at = perf_counter()
        self._pending_load_id = request_id
        self._pending_source_path = self._current_instance.path
        self._pending_frame_index = target

        worker = FrameLoaderWorker(
            self._current_instance.path,
            frame_index=target,
            media_format=self._current_instance.media_format,
            parent=self,
            total_frames=self._frame_cache.frame_count(),
            batch_size=1,
        )
        self._batch_load_id = request_id
        worker.signals.batch_finished.connect(
            partial(self._on_scroll_target_loaded, request_id, self._current_instance.path)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(partial(self._on_frame_load_failed, request_id), Qt.ConnectionType.QueuedConnection)
        self._retain_worker(worker)
        worker.signals.batch_finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def _mark_scroll_active(self) -> None:
        self._scroll_active = True
        if self._scroll_settle_timer is None:
            self._scroll_settle_timer = QTimer(self)
            self._scroll_settle_timer.setSingleShot(True)
            self._scroll_settle_timer.timeout.connect(self._on_scroll_settled)
        settle_ms = self._playback_config.scroll_debounce_ms + 50
        self._scroll_settle_timer.start(settle_ms)

    def _on_scroll_settled(self) -> None:
        self._scroll_active = False
        self.scroll_settled.emit()

    def _maybe_start_scroll_neighbors(self, center: int) -> None:
        if self._state_manager.snapshot.is_playing:
            return
        if self._current_instance is None or self._current_instance.path is None:
            return
        if self._current_instance.media_format not in ("dicom", "mp4"):
            return
        if not self._frame_cache.is_ready(self._current_instance.path):
            return
        if self._scroll_neighbor_load_id != 0:
            return

        cfg = self._playback_config
        total = self._frame_cache.frame_count()

        # Detect scroll direction: compare with previous scroll frame
        prev = getattr(self, "_prev_scroll_frame", center)
        scroll_forward = center >= prev
        self._prev_scroll_frame = center

        if scroll_forward:
            ahead = self._frame_cache.loaded_ahead(center)
            if ahead >= cfg.scroll_batch_size:
                return
            start = center + 1
            while start < total and self._frame_cache.is_loaded(start):
                start += 1
            if start >= total:
                return
            target_ahead = (
                cfg.scroll_batch_size
                if ahead >= cfg.min_buffer
                else min(cfg.min_buffer, cfg.scroll_batch_size)
            )
            slots_needed = target_ahead - ahead
            batch_size = min(slots_needed, total - start)
        else:
            behind = self._frame_cache.loaded_before(center)
            if behind >= cfg.scroll_batch_size:
                return
            start = center - 1
            while start >= 0 and self._frame_cache.is_loaded(start):
                start -= 1
            if start < 0:
                return
            target_behind = (
                cfg.scroll_batch_size
                if behind >= cfg.min_buffer
                else min(cfg.min_buffer, cfg.scroll_batch_size)
            )
            slots_needed = target_behind - behind
            batch_size = min(slots_needed, start + 1)
            start = start - batch_size + 1

        if batch_size <= 0:
            return

        self._load_request_id += 1
        request_id = self._load_request_id
        self._scroll_neighbor_load_id = request_id

        worker = FrameLoaderWorker(
            self._current_instance.path,
            frame_index=start,
            media_format=self._current_instance.media_format,
            parent=self,
            total_frames=total,
            batch_size=batch_size,
        )
        worker.signals.batch_finished.connect(
            partial(self._on_scroll_neighbors_loaded, request_id, self._current_instance.path)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(partial(self._on_frame_load_failed, request_id), Qt.ConnectionType.QueuedConnection)
        self._retain_worker(worker)
        worker.signals.batch_finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
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

    def _invalidate_prefetch(self) -> None:
        self._prefetch_request_id += 1
        self._prefetch_load_id = 0

    _PREFETCH_TIMEOUT_SEC = 1.0

    def _prefetch_playback_buffer(self, center: int) -> None:
        if self._current_instance is None or self._current_instance.path is None:
            return
        if not self._state_manager.snapshot.is_playing:
            return
        if self._prefetch_load_id != 0:
            # Stale prefetch guard: if the worker hasn't completed within
            # _PREFETCH_TIMEOUT_SEC, force-clear it to prevent playback stall.
            stale_sec = perf_counter() - self._prefetch_load_started_at
            if stale_sec < self._PREFETCH_TIMEOUT_SEC:
                if _FREEZE_DIAG:
                    _diag_log.warning(
                        "[prefetch] center=%d BLOCKED by pending_load_id=%d (%.1fs old)",
                        center, self._prefetch_load_id, stale_sec,
                    )
                return
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[prefetch] STALE timeout! clearing pending_load_id=%d after %.1fs",
                    self._prefetch_load_id, stale_sec,
                )
            self._prefetch_load_id = 0

        cfg = self._playback_config
        ahead = self._frame_cache.loaded_ahead(center)
        if ahead >= cfg.prefetch_radius:
            return

        total = self._frame_cache.frame_count()
        if total <= 0:
            return

        # Small-loop optimization: if cine is <= 60 frames, prefetch all unloaded
        if total <= 60:
            unloaded = [i for i in range(total) if not self._frame_cache.is_loaded(i)]
            if not unloaded:
                return
            batch = len(unloaded)
            start = unloaded[0]
        else:
            start = (center + 1 + ahead) % total
            if start == center:
                return
            slots_remaining = cfg.prefetch_radius - ahead
            batch = min(self._adaptive_batch_size, slots_remaining, total)
            if batch <= 0:
                return

        self._prefetch_request_id += 1
        request_id = self._prefetch_request_id
        self._prefetch_load_id = request_id
        self._prefetch_load_started_at = perf_counter()
        self._prefetch_batch_start = perf_counter()

        worker = FrameLoaderWorker(
            self._current_instance.path,
            frame_index=start,
            media_format=self._current_instance.media_format,
            parent=self,
            total_frames=total,
            batch_size=batch,
        )
        worker.signals.batch_finished.connect(
            partial(self._on_prefetch_batch_loaded, request_id, self._current_instance.path)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(partial(self._on_prefetch_failed, request_id), Qt.ConnectionType.QueuedConnection)
        self._retain_worker(worker)
        worker.signals.batch_finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[prefetch_submit] req=%d start=%d batch=%d active_threads=%d",
                request_id, start, batch, self._thread_pool.activeThreadCount(),
            )
        self._thread_pool.start(worker)

    def _on_prefetch_batch_loaded(
        self, request_id: int, path: Path, frames: list
    ) -> None:
        is_current = request_id == self._prefetch_load_id
        if is_current:
            total_ms = (perf_counter() - self._prefetch_load_started_at) * 1000.0
            self._prefetch_load_id = 0
            if self._current_instance is None or self._current_instance.path != path:
                return
            # Adaptive batch sizing: EMA of batch latency
            if self._prefetch_batch_start > 0:
                elapsed_ms = (perf_counter() - self._prefetch_batch_start) * 1000.0
                self._prefetch_batch_start = 0.0
                alpha = 0.3
                self._prefetch_ema_latency_ms = (
                    alpha * elapsed_ms + (1 - alpha) * self._prefetch_ema_latency_ms
                )
                cfg = self._playback_config
                if self._prefetch_ema_latency_ms < 10 and self._adaptive_batch_size < 16:
                    self._adaptive_batch_size += 2
                elif self._prefetch_ema_latency_ms > 60 and self._adaptive_batch_size > 2:
                    self._adaptive_batch_size -= 1
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[prefetch_batch] req=%d frames=%d batch_ms=%.1f total_ms=%.0f ema=%.1fms batch_size=%d",
                    request_id, len(frames), elapsed_ms if self._prefetch_batch_start == 0 else 0,
                    total_ms, self._prefetch_ema_latency_ms, self._adaptive_batch_size,
                )
        else:
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[prefetch_batch] STALE req=%d (current=%d) frames=%d — caching anyway",
                    request_id, self._prefetch_load_id, len(frames),
                )
        # Always cache frames even for stale requests — they may be
        # needed if playback catches up to that region.
        for idx, pixels in frames:
            self._frame_cache.put(idx, pixels)
        if self._state_manager.snapshot.is_playing:
            current = self._state_manager.snapshot.current_frame_index
            self._prefetch_playback_buffer(current)

    def _on_prefetch_failed(self, request_id: int, message: str) -> None:
        if request_id != self._prefetch_load_id:
            return
        self._prefetch_load_id = 0
        self.status_message.emit(tr("status.prefetch_failed", message=message))

    def _advance_playback(self) -> None:
        _t0 = perf_counter() if _FREEZE_DIAG else 0
        state = self._state_manager.snapshot
        if not state.is_playing:
            return
        if self._pending_decode_id != 0:
            if _FREEZE_DIAG:
                _diag_log.warning("[advance] frame=%s PENDING_DECODE skip", state.current_frame_index)
            return
        if self._playback_warmup_pending:
            cfg = self._playback_config
            current = state.current_frame_index
            if (
                self._current_instance is not None
                and self._current_instance.path is not None
                and self._frame_cache.is_ready(self._current_instance.path)
            ):
                ahead = self._frame_cache.loaded_ahead(current)
                if ahead >= cfg.min_buffer:
                    self._playback_warmup_pending = False
                    self._last_frame_shown_at = perf_counter()
                    self._reschedule_playback_timer()
                    return
            self._reschedule_playback_timer(poll=True)
            return
        if self._last_frame_shown_at > 0:
            interval_ms = self._playback_interval_ms(state)
            elapsed_ms = (perf_counter() - self._last_frame_shown_at) * 1000.0
            if elapsed_ms < interval_ms - 1:
                self._timer.setInterval(max(1, int(interval_ms - elapsed_ms)))
                return
        if (
            self._current_instance is not None
            and self._current_instance.media_format in ("dicom", "mp4")
            and self._current_instance.path is not None
            and self._frame_cache.is_ready(self._current_instance.path)
        ):
            current = state.current_frame_index
            total = state.total_frames
            if total <= 0:
                return
            next_idx = (current + 1) % total

            if self._frame_cache.is_loaded(next_idx):
                self._frame_cache.set_current(next_idx)
                self.step_frame(1)
                self._last_frame_shown_at = perf_counter()
                self._prefetch_playback_buffer(next_idx)
                self._reschedule_playback_timer()
                if _FREEZE_DIAG:
                    _diag_log.warning(
                        "[advance] frame=%d→%d cache_hit=True elapsed=%.2fms",
                        current, next_idx, (perf_counter() - _t0) * 1000,
                    )
                    self._diag_frame_counter += 1
                    if self._diag_frame_counter % 50 == 0:
                        import os as _os
                        proc = _os.getpid()
                        try:
                            with open(f"/proc/{proc}/status") as _f:
                                for line in _f:
                                    if line.startswith("VmRSS:"):
                                        _diag_log.warning("[mem] %s", line.strip())
                                        break
                        except Exception:
                            pass
                        _diag_log.warning(
                            "[mem] cache_frames=%d cache_bytes=%.1fMB live_workers=%d",
                            len(self._frame_cache._frame_store),
                            self._frame_cache.memory_bytes() / (1024 * 1024),
                            len(self._live_workers),
                        )
                return

            # Double-next skip: if next frame is missing but next+1 is loaded, skip forward
            next_next = (next_idx + 1) % total
            if self._frame_cache.is_loaded(next_next):
                self._frame_cache.set_current(next_next)
                self._state_manager.set_frame(next_next)
                self._emit_cached_frame(next_next)
                self._last_frame_shown_at = perf_counter()
                self._prefetch_playback_buffer(next_next)
                self._reschedule_playback_timer()
                return

            cfg = self._playback_config
            ahead = self._frame_cache.loaded_ahead(current)
            if ahead > cfg.max_lag_frames:
                skip_to = self._frame_cache.nearest_loaded_ahead(current)
                if skip_to is not None:
                    self._frame_cache.set_current(skip_to)
                    self._state_manager.set_frame(skip_to)
                    self._emit_cached_frame(skip_to)
                    self._last_frame_shown_at = perf_counter()
                    self._prefetch_playback_buffer(skip_to)
                    self._reschedule_playback_timer()
                    return

            self._prefetch_playback_buffer(current)
            self._reschedule_playback_timer(poll=True)
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[advance] frame=%d cache_miss prefetch_pending elapsed=%.2fms",
                    current, (perf_counter() - _t0) * 1000,
                )
            return

        if self._pending_load_id != 0:
            self._reschedule_playback_timer(poll=True)
            return
        self.step_frame(1)
        self._last_frame_shown_at = perf_counter()
        self._reschedule_playback_timer()

    def _load_playback_frame(self, frame_index: int) -> None:
        self._prefetch_playback_buffer(frame_index - 1)

    def _on_playback_frame_loaded(
        self, request_id: int, path: Path, frame_index: int, pixels: np.ndarray
    ) -> None:
        if request_id != self._pending_load_id:
            return
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        self._frame_cache.set_current(frame_index)
        self._frame_cache.put(frame_index, pixels)
        self._loaded_source_path = path
        self._loaded_frame_index = frame_index
        self._current_frame_pixels = pixels
        self.frame_loaded.emit(pixels)

    def _on_frame_loaded(
        self,
        request_id: int,
        path: Path,
        frame_index: int,
        pixels: np.ndarray,
    ) -> None:
        if request_id != self._pending_load_id:
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[frame_load_single] REJECTED req=%d current_pending=%d frame=%d",
                    request_id, self._pending_load_id, frame_index,
                )
            return
        if self._current_instance is None or self._current_instance.path != path:
            return
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        self._loaded_source_path = path
        self._loaded_frame_index = frame_index
        self._current_frame_pixels = pixels
        self._frame_cache.put(frame_index, pixels)
        self.frame_loaded.emit(pixels)

    def _on_scroll_target_loaded(
        self,
        request_id: int,
        path: Path,
        frames: list,
    ) -> None:
        if request_id != self._scroll_load_id:
            if _FREEZE_DIAG:
                _diag_log.warning(
                    "[scroll_target] REJECTED req=%d current_scroll_load=%d frames=%s",
                    request_id, self._scroll_load_id,
                    [idx for idx, _ in frames],
                )
            return
        if self._current_instance is None or self._current_instance.path != path:
            return
        self._scroll_load_id = 0
        self._batch_load_id = 0
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        target = self._batch_target_frame
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[scroll_target] OK req=%d target=%d frames=%s",
                request_id, target, [idx for idx, _ in frames],
            )
        emitted = False
        for idx, pixels in frames:
            self._frame_cache.put(idx, pixels)
            if idx == target:
                self._loaded_source_path = path
                self._loaded_frame_index = idx
                self._current_frame_pixels = pixels
                self.frame_loaded.emit(pixels)
                emitted = True
        if not emitted and _FREEZE_DIAG:
            _diag_log.warning(
                "[scroll_target] NO_MATCH! target=%d not in frames=%s",
                target, [idx for idx, _ in frames],
            )
        self._maybe_start_scroll_neighbors(target)

    def _on_scroll_neighbors_loaded(
        self,
        request_id: int,
        path: Path,
        frames: list,
    ) -> None:
        if request_id != self._scroll_neighbor_load_id:
            return
        self._scroll_neighbor_load_id = 0
        if self._current_instance is None or self._current_instance.path != path:
            return
        for idx, pixels in frames:
            self._frame_cache.put(idx, pixels)

    def _on_batch_frame_loaded(
        self,
        request_id: int,
        path: Path,
        frames: list,
    ) -> None:
        if request_id != self._batch_load_id:
            return
        if self._current_instance is None or self._current_instance.path != path:
            return
        self._batch_load_id = 0
        self._pending_load_id = 0
        self._pending_source_path = None
        self._pending_frame_index = None
        target = self._batch_target_frame
        for idx, pixels in frames:
            self._frame_cache.put(idx, pixels)
            if idx == target:
                self._loaded_source_path = path
                self._loaded_frame_index = idx
                self._current_frame_pixels = pixels
                self.frame_loaded.emit(pixels)

    def _on_frame_load_failed(self, request_id: int, message: str) -> None:
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[load_failed] req=%d msg=%s pending=%d scroll=%d",
                request_id, message, self._pending_load_id, self._scroll_load_id,
            )
        is_current = False
        if request_id == self._pending_load_id:
            self._pending_load_id = 0
            self._pending_source_path = None
            self._pending_frame_index = None
            is_current = True
        if request_id == self._batch_load_id:
            self._batch_load_id = 0
        if request_id == self._scroll_load_id:
            self._scroll_load_id = 0
        if request_id == self._scroll_neighbor_load_id:
            self._scroll_neighbor_load_id = 0
        # Only clear pixels if the failed request was for the current frame
        if is_current:
            self._current_frame_pixels = None
        self.status_message.emit(tr("status.load_failed", message=message))
        self.frame_load_failed.emit(message)

    def _on_first_frame_ready(self, request_id: int, path: Path, first_frame: object) -> None:
        """Show first frame immediately; store in cache for lazy scroll loading."""
        if request_id != self._pending_decode_id:
            return
        if self._current_instance is None:
            return
        if Path(path).resolve() != self._current_instance.path.resolve():
            return
        if not isinstance(first_frame, np.ndarray):
            return
        self._frame_cache.put(0, first_frame)
        self._current_frame_pixels = first_frame
        self._loaded_source_path = path
        self._loaded_frame_index = 0
        self._pending_decode_id = 0
        self._state_manager.set_decode_in_progress(False)
        if self._pending_emit_after_decode:
            self._pending_emit_after_decode = False
            self._state_manager.emit_state()
        self.frame_loaded.emit(first_frame)
        self.status_message.emit(tr("status.first_frame_ready"))
        self.decode_finished.emit()

    def _on_dicom_decoded(self, request_id: int, path: Path, frames: object) -> None:
        if request_id != self._pending_decode_id:
            return
        if self._current_instance is None:
            return
        if Path(path).resolve() != self._current_instance.path.resolve():
            self._on_dicom_decode_failed(request_id, "DICOM path mismatch")
            return
        if not isinstance(frames, np.ndarray):
            self._on_dicom_decode_failed(request_id, "Decoded frames are invalid")
            return

        leading_static = 0
        if frames.shape[0] > 1:
            ref = frames[0].astype(np.float32, copy=False)
            for idx in range(1, min(frames.shape[0], 16)):
                diff = float(np.mean(np.abs(frames[idx].astype(np.float32, copy=False) - ref)))
                if diff > 1.0:
                    break
                leading_static = idx
        self._leading_static_frames[path.resolve()] = leading_static
        # Cap to prevent unbounded growth across sessions
        if len(self._leading_static_frames) > 200:
            self._leading_static_frames.clear()

        self._frame_cache.load(path, frames)
        from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session
        get_thread_dicom_session().release()
        if self._frame_cache.memory_bytes() > _FRAME_CACHE_WARN_BYTES:
            size_mb = self._frame_cache.memory_bytes() / (1024 * 1024)
            self.status_message.emit(
                tr("status.dicom_cache_warning", size_mb=f"{size_mb:.1f}")
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
        self.decode_finished.emit()
        self.status_message.emit(tr("system_bar.ready"))

    def _on_dicom_decode_failed(self, request_id: int, message: str) -> None:
        if request_id != self._pending_decode_id:
            return
        self._pending_decode_id = 0
        self._frame_cache.clear()
        self._loaded_source_path = None
        self._loaded_frame_index = None
        self._current_frame_pixels = None
        self._state_manager.set_decode_in_progress(False)
        if self._pending_emit_after_decode:
            self._pending_emit_after_decode = False
            self._state_manager.emit_state()
        self.status_message.emit(tr("status.load_failed", message=message))
        self.frame_load_failed.emit(message)

    def _emit_cached_frame(self, frame_index: int) -> bool:
        if self._current_instance is None or self._current_instance.path is None:
            return False
        if not self._frame_cache.is_ready(self._current_instance.path):
            return False
        try:
            pixels = self._frame_cache.get(frame_index)
        except (RuntimeError, IndexError):
            return False
        self._frame_cache.set_current(frame_index)
        if self._last_pinned_frame is not None and self._last_pinned_frame != frame_index:
            self._frame_cache.unpin(self._last_pinned_frame)
        self._frame_cache.pin(frame_index)
        self._last_pinned_frame = frame_index
        self._loaded_source_path = self._current_instance.path
        self._loaded_frame_index = frame_index
        self._current_frame_pixels = pixels
        if pixels is not None:
            self._maybe_cache_cine_roi_from_frame(pixels, frame_index)
        self.frame_loaded.emit(pixels)
        return True

    def _frozen_cine_segment_roi(self) -> tuple[float, float, float, float] | None:
        instance = self._current_instance
        if instance is None or instance.media_format == "dicom":
            return None
        return self._measurement_session.get_cine_segment_roi(
            self._resolve_study_uid(),
            instance.sop_instance_uid,
        )

    def _cache_cine_segment_roi(
        self,
        roi_xyxy: tuple[float, float, float, float] | None,
    ) -> None:
        instance = self._current_instance
        if instance is None or instance.media_format == "dicom" or roi_xyxy is None:
            return
        self._measurement_session.set_cine_segment_roi(
            self._resolve_study_uid(),
            instance.sop_instance_uid,
            roi_xyxy,
        )

    def _maybe_cache_cine_roi_from_frame(
        self,
        frame: np.ndarray,
        frame_index: int,
    ) -> None:
        if self._frozen_cine_segment_roi() is not None:
            return
        roi = resolve_cine_segment_roi_xyxy(frame)
        self._cache_cine_segment_roi(roi)

    def _resolve_segment_roi_bounds(
        self,
        frame: np.ndarray,
        instance_path: Path | None,
        *,
        media_format: str = "dicom",
        phase: str | None = None,
    ) -> tuple[float, float, float, float] | None:
        """B-mode ROI for ONNX: DICOM tags for DICOM; frozen ROI or None for cine."""
        if media_format == "dicom":
            return resolve_segment_roi_xyxy(
                frame,
                media_format=media_format,
                instance_path=instance_path,
            )
        # Cine: use frozen ROI from frame 0, or None (full frame)
        frozen = self._frozen_cine_segment_roi()
        if frozen is not None:
            return frozen
        return None

    def _open_arc_from_cleaned_mask(
        self,
        cleaned_mask: np.ndarray,
        *,
        original_shape: tuple[int, int],
        view: str,
    ) -> tuple[
        list[tuple[float, float]],
        tuple[tuple[float, float], tuple[float, float]],
        tuple[float, float],
    ]:
        return open_arc_from_cavity_mask(
            cleaned_mask,
            original_shape=original_shape,
            num_nodes=32,
            view_hint=view,
        )

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

    def _should_auto_refine_after_segment(self, manifest_section: str = "inference") -> bool:
        manifest = _load_manifest(_default_models_dir())
        if not manifest:
            return False
        inference = manifest.get(manifest_section, {})
        if not isinstance(inference, dict):
            return False
        return bool(inference.get("auto_refine_after_segment", False))

    def _resolve_temporal_fusion_config(self) -> TemporalFusionConfig | None:
        manifest = _load_manifest(_default_models_dir())
        if not manifest:
            return None
        tf = manifest.get("temporal_fusion")
        if not isinstance(tf, dict) or not tf.get("enabled", False):
            return None
        return TemporalFusionConfig(
            window=tf.get("window", 2),
            vote_threshold=tf.get("vote_threshold", 3),
            max_node_shift_ratio_ed=tf.get("max_node_shift_ratio_ed", 0.03),
            max_node_shift_ratio_es=tf.get("max_node_shift_ratio_es", 0.025),
            apex_max_shift_ratio_ed=tf.get("apex_max_shift_ratio_ed", 0.02),
            apex_max_shift_ratio_es=tf.get("apex_max_shift_ratio_es", 0.015),
            annulus_max_shift_ratio_ed=tf.get("annulus_max_shift_ratio_ed", 0.015),
            annulus_max_shift_ratio_es=tf.get("annulus_max_shift_ratio_es", 0.012),
            apex_direction_lock=tf.get("apex_direction_lock", True),
        )

    def _on_auto_segment_finished(
        self,
        phase: str,
        view: str,
        chamber: str,
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

        cleaned_mask = papillary_mask_cleanup(mask, phase=phase)
        if int(np.count_nonzero(cleaned_mask)) < 80:
            self.status_message.emit(
                tr("app.segmentation_mask_too_small")
            )
            return

        is_cine = (
            self._current_instance is not None
            and self._current_instance.media_format != "dicom"
        )

        try:
            open_points, annulus, apex = self._open_arc_from_cleaned_mask(
                cleaned_mask,
                original_shape=original_shape,
                view=view,
            )
        except ValueError:
            closed_points = smooth_contour(
                mask_to_contour(cleaned_mask, original_shape),
                num_nodes=32,
            )
            if not closed_points:
                self.status_message.emit(tr("app.segmentation_no_contour"))
                return
            try:
                open_points, annulus = closed_polygon_to_open_arc(closed_points, view_hint=view)
            except ValueError:
                self.status_message.emit(tr("app.segmentation_open_arc_fail"))
                return
            apex = apex_point(open_points, annulus)

        refined_points = exclude_papillary_concavities(open_points, annulus, apex, phase=phase)

        if self._current_frame_pixels is not None and self._should_auto_refine_after_segment():
            from echo_personal_tool.domain.services.mbs_lite_service import refine_open_arc_contour

            instance_uid = (
                self._current_instance.sop_instance_uid if self._current_instance is not None else None
            )
            draft = Contour(
                phase=phase,
                view=view,
                chamber=chamber,
                mitral_annulus=annulus,
                apex_landmark=apex,
                points=refined_points,
                source="ai",
                num_nodes=len(refined_points),
                frame_index=frame_index,
                sop_instance_uid=instance_uid,
            )
            refined, _ = refine_open_arc_contour(
                self._current_frame_pixels, draft, cine=is_cine,
            )
            refined_points = list(refined.points)
            if refined.mitral_annulus is not None:
                annulus = refined.mitral_annulus
            if refined.apex_landmark is not None:
                apex = refined.apex_landmark

        instance_uid = (
            self._current_instance.sop_instance_uid if self._current_instance is not None else None
        )
        contour = Contour(
            phase=phase,
            view=view,
            chamber=chamber,
            mitral_annulus=annulus,
            apex_landmark=apex,
            points=refined_points,
            source="ai",
            num_nodes=len(refined_points),
            frame_index=frame_index,
            sop_instance_uid=instance_uid,
            review_pending=True,
            refine_step=0,
            refine_locked_indices=(),
        )
        pixel_spacing, _ = self._resolve_pixel_spacing(self._state_manager.snapshot)
        reject_reason = explain_lv_auto_reject_reason(contour, pixel_spacing)
        if reject_reason is not None:
            mask_px = int(np.count_nonzero(cleaned_mask))
            arc_px = _contour_arc_span_px(contour)
            self.status_message.emit(
                tr("app.segmentation_reject", reason=reject_reason, mask=mask_px, arc=arc_px)
            )
            return

        review_status = tr("app.ai_review_prompt", view=view, phase=phase)
        contours = [
            existing
            for existing in self._state_manager.snapshot.contours
            if not (
                existing.phase == phase and existing.view == view and existing.chamber == chamber
            )
        ]
        contours.append(contour)
        self.status_message.emit(review_status)
        self.on_contours_changed(contours)

        # Temporal fusion: after showing center contour, queue neighbors
        self._maybe_start_temporal_fusion(
            phase=phase,
            view=view,
            chamber=chamber,
            instance_path=instance_path,
            frame_index=frame_index,
            original_shape=original_shape,
            mask=mask,
            center_contour=contour,
        )

    def _on_auto_segment_failed(
        self,
        instance_path: Path | None,
        frame_index: int,
        _message: str,
    ) -> None:
        self._segment_in_progress = False
        if not self._auto_segment_context_matches(instance_path, frame_index):
            return
        self.status_message.emit(tr("app.segmentation_unavailable"))

    def _on_auto_segment_timed_out(self, instance_path: Path | None, frame_index: int) -> None:
        self._segment_in_progress = False
        if not self._auto_segment_context_matches(instance_path, frame_index):
            return
        self.status_message.emit(tr("app.segmentation_unavailable"))

    # ── LA Auto Segment ────────────────────────────────────────────────

    def request_la_auto_segment(self) -> None:
        """Request LA auto-segmentation on the current A4C ES frame."""
        from echo_personal_tool.domain.services.la_segmentation_service import (
            explain_la_auto_reject_reason,
            la_mask_to_contour,
        )

        if self._segment_in_progress:
            self.status_message.emit(tr("status.segmentation_in_progress"))
            return

        state = self._state_manager.snapshot
        if state.is_playing:
            self.status_message.emit(tr("status.pause_before_segmentation"))
            return

        if self._current_frame_pixels is None or self._loaded_frame_index != state.current_frame_index:
            self.status_message.emit(tr("status.frame_not_loaded"))
            return

        # LA auto is A4C ES only
        view = "A4C"
        phase = "ES"
        chamber = "LA"

        if not self._la_segmenter_available():
            self.status_message.emit(tr("app.segmentation_unavailable"))
            return

        frame = np.ascontiguousarray(self._current_frame_pixels)
        original_shape = (int(frame.shape[0]), int(frame.shape[1]))
        instance_path = self._current_instance.path if self._current_instance is not None else None
        media_format = (
            self._current_instance.media_format if self._current_instance is not None else "dicom"
        )
        frame_index = state.current_frame_index
        roi_xyxy = self._resolve_segment_roi_bounds(
            frame, instance_path, media_format=media_format, phase=phase,
        )
        self._last_segment_roi_xyxy = roi_xyxy
        crop_mode = echonet_crop_mode_for_media(media_format)

        if media_format != "dicom" and frame.ndim == 3 and frame.shape[2] == 3:
            gray = np.mean(frame[..., :3], axis=2).astype(np.uint8)
            frame = np.stack([gray, gray, gray], axis=-1)

        self._segment_in_progress = True
        worker = OnnxWorker(
            frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode,
            manifest_section="la_inference", parent=self,
        )
        worker.signals.finished.connect(
            partial(
                self._on_la_auto_segment_finished,
                phase, view, chamber, instance_path, frame_index, original_shape,
            )
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(
            partial(self._on_auto_segment_failed, instance_path, frame_index)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.timed_out.connect(
            partial(self._on_auto_segment_timed_out, instance_path, frame_index)
        , Qt.ConnectionType.QueuedConnection)

        worker.setAutoDelete(False)
        self._retain_worker(worker)
        worker.signals.finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.timed_out.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def _la_segmenter_available(self) -> bool:
        """Check if LA ONNX model is available."""
        from echo_personal_tool.infrastructure.onnx_engine import _default_models_dir, _load_manifest, _resolve_model_path
        models_dir = _default_models_dir()
        manifest = _load_manifest(models_dir)
        if manifest is None:
            return False
        path = _resolve_model_path(models_dir, manifest, manifest_section="la_inference")
        return path is not None and path.is_file()

    def _on_la_auto_segment_finished(
        self,
        phase: str,
        view: str,
        chamber: str,
        instance_path: Path | None,
        frame_index: int,
        original_shape: tuple[int, int],
        mask: object,
    ) -> None:
        """Post-inference: LA mask → contour → refine → reject gate → review."""
        from echo_personal_tool.domain.services.la_segmentation_service import (
            explain_la_auto_reject_reason,
            la_mask_to_contour,
        )

        self._segment_in_progress = False
        if not self._auto_segment_context_matches(instance_path, frame_index):
            return
        if not isinstance(mask, np.ndarray):
            return

        mask_pixels = int(np.count_nonzero(mask))
        if mask_pixels < 80:
            self.status_message.emit(tr("app.segmentation_mask_too_small"))
            return

        try:
            open_points, annulus, apex = la_mask_to_contour(mask, num_nodes=32)
        except ValueError as exc:
            self.status_message.emit(tr("app.segmentation_no_contour"))
            return

        # Optional auto-refine (LA-specific elliptical template)
        if self._current_frame_pixels is not None and self._should_auto_refine_after_segment(
            manifest_section="la_inference",
        ):
            from echo_personal_tool.domain.services.mbs_lite_service import refine_open_arc_contour

            instance_uid = (
                self._current_instance.sop_instance_uid if self._current_instance is not None else None
            )
            draft = Contour(
                phase=phase, view=view, chamber=chamber,
                mitral_annulus=annulus, apex_landmark=apex,
                points=open_points, source="ai", num_nodes=32,
                frame_index=frame_index, sop_instance_uid=instance_uid,
            )
            refined, _ = refine_open_arc_contour(
                self._current_frame_pixels, draft, cine=False,
            )
            open_points = list(refined.points)
            if refined.mitral_annulus is not None:
                annulus = refined.mitral_annulus
            if refined.apex_landmark is not None:
                apex = refined.apex_landmark

        instance_uid = (
            self._current_instance.sop_instance_uid if self._current_instance is not None else None
        )
        contour = Contour(
            phase=phase, view=view, chamber=chamber,
            mitral_annulus=annulus, apex_landmark=apex,
            points=open_points, source="ai", num_nodes=32,
            frame_index=frame_index, sop_instance_uid=instance_uid,
            review_pending=True, refine_step=0, refine_locked_indices=(),
        )

        pixel_spacing, _ = self._resolve_pixel_spacing(self._state_manager.snapshot)
        reject_reason = explain_la_auto_reject_reason(
            contour,
            pixel_spacing,
            mask_pixels=mask_pixels,
            mask=mask,
            roi_xyxy=self._last_segment_roi_xyxy,
        )
        if reject_reason is not None:
            self.status_message.emit(
                tr("app.segmentation_reject", reason=reject_reason, mask=mask_pixels, arc=0)
            )
            return

        review_status = tr("app.ai_review_prompt", view=view, phase=phase)
        contours = [
            existing for existing in self._state_manager.snapshot.contours
            if not (existing.phase == phase and existing.view == view and existing.chamber == chamber)
        ]
        contours.append(contour)
        self.status_message.emit(review_status)
        self.on_contours_changed(contours)

    # ── Temporal Fusion ──────────────────────────────────────────────────

    def _maybe_start_temporal_fusion(
        self,
        *,
        phase: str,
        view: str,
        chamber: str,
        instance_path: Path | None,
        frame_index: int,
        original_shape: tuple[int, int],
        mask: np.ndarray,
        center_contour: Contour,
    ) -> None:
        """After center segment, queue neighbors if temporal fusion enabled."""
        config = self._resolve_temporal_fusion_config()
        if config is None:
            return
        if self._current_instance is None:
            return
        total = self._current_instance.number_of_frames
        if total <= 1:
            return

        window = compute_window(frame_index, total, config.window)
        neighbors = [i for i in window if i != frame_index]
        if not neighbors:
            return

        self._fusion_in_progress = True
        self._fusion_config = config
        self._fusion_anchor_frame = frame_index
        self._fusion_phase = phase
        self._fusion_view = view
        self._fusion_chamber = chamber
        self._fusion_instance_path = instance_path
        self._fusion_original_shape = original_shape
        self._fusion_masks = {frame_index: mask}
        self._fusion_contours = {frame_index: center_contour}
        self._fusion_window = window
        self._fusion_processed = {frame_index}  # anchor already done
        self._fusion_result = None

        self.status_message.emit(
            tr("status.temporal_fusion_started", count=len(neighbors))
        )

        for neighbor_idx in neighbors:
            self._queue_neighbor_segment(neighbor_idx, phase, view, chamber, instance_path)

    def _queue_neighbor_segment(
        self,
        neighbor_idx: int,
        phase: str,
        view: str,
        chamber: str,
        instance_path: Path | None,
    ) -> None:
        """Load frame at neighbor_idx and segment it."""
        if self._current_instance is None:
            return

        media_format = self._current_instance.media_format

        worker = FrameLoaderWorker(
            self._current_instance.path,
            frame_index=neighbor_idx,
            media_format=media_format,
            parent=self,
        )
        worker.signals.finished.connect(
            partial(
                self._on_neighbor_frame_loaded,
                phase=phase,
                view=view,
                chamber=chamber,
                instance_path=instance_path,
                neighbor_idx=neighbor_idx,
            )
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(
            partial(self._on_neighbor_segment_failed, neighbor_idx=neighbor_idx)
        , Qt.ConnectionType.QueuedConnection)
        self._retain_worker(worker)
        worker.signals.finished.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(partial(self._release_worker, worker), Qt.ConnectionType.QueuedConnection)

        self._thread_pool.start(worker)

    def _on_neighbor_frame_loaded(
        self,
        pixels: np.ndarray,
        *,
        phase: str,
        view: str,
        chamber: str,
        instance_path: Path | None,
        neighbor_idx: int,
    ) -> None:
        """Got neighbor frame pixels — segment them."""
        if not isinstance(pixels, np.ndarray):
            self._on_neighbor_segment_failed(neighbor_idx)
            return

        frame = np.ascontiguousarray(pixels)
        original_shape = (int(frame.shape[0]), int(frame.shape[1]))
        media_format = (
            self._current_instance.media_format if self._current_instance is not None else "dicom"
        )

        roi_xyxy = self._resolve_segment_roi_bounds(
            frame,
            instance_path,
            media_format=media_format,
            phase=phase,
        )
        crop_mode = echonet_crop_mode_for_media(media_format)

        if media_format != "dicom" and frame.ndim == 3 and frame.shape[2] == 3:
            gray = np.mean(frame[..., :3], axis=2).astype(np.uint8)
            frame = np.stack([gray, gray, gray], axis=-1)

        worker = OnnxWorker(frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode, parent=self)
        worker.signals.finished.connect(
            partial(
                self._on_neighbor_segment_finished,
                view=view,
                chamber=chamber,
                instance_path=instance_path,
                neighbor_idx=neighbor_idx,
                original_shape=original_shape,
                phase=phase,
            )
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(
            partial(self._on_neighbor_segment_failed, neighbor_idx=neighbor_idx)
        , Qt.ConnectionType.QueuedConnection)

        worker.signals.timed_out.connect(
            partial(self._on_neighbor_segment_failed, neighbor_idx=neighbor_idx)
        , Qt.ConnectionType.QueuedConnection)

        self._thread_pool.start(worker)

    def _on_neighbor_segment_finished(
        self,
        mask: object,
        *,
        phase: str,
        view: str,
        chamber: str,
        instance_path: Path | None,
        neighbor_idx: int,
        original_shape: tuple[int, int],
    ) -> None:
        """Neighbor ONNX finished — store mask and contour, try fusion."""
        if not isinstance(mask, np.ndarray):
            self._on_neighbor_segment_failed(neighbor_idx)
            return

        cleaned_mask = papillary_mask_cleanup(mask, phase=phase)
        if int(np.count_nonzero(cleaned_mask)) < 80:
            self._on_neighbor_segment_failed(neighbor_idx)
            return

        try:
            open_points, annulus, apex = self._open_arc_from_cleaned_mask(
                cleaned_mask,
                original_shape=original_shape,
                view=view,
            )
        except ValueError:
            self._on_neighbor_segment_failed(neighbor_idx)
            return

        refined_points = exclude_papillary_concavities(open_points, annulus, apex, phase=phase)

        instance_uid = (
            self._current_instance.sop_instance_uid if self._current_instance is not None else None
        )
        contour = Contour(
            phase=phase,
            view=view,
            chamber=chamber,
            mitral_annulus=annulus,
            apex_landmark=apex,
            points=refined_points,
            source="ai",
            num_nodes=len(refined_points),
            frame_index=neighbor_idx,
            sop_instance_uid=instance_uid,
        )

        self._fusion_masks[neighbor_idx] = mask
        self._fusion_contours[neighbor_idx] = contour
        self._fusion_processed.add(neighbor_idx)

        done = len(self._fusion_processed)
        self.status_message.emit(
            tr("status.temporal_fusion_progress", done=done, total=len(self._fusion_window))
        )

        self._try_complete_temporal_fusion()

    def _on_neighbor_segment_failed(self, neighbor_idx: int) -> None:
        """Neighbor segment failed — mark processed and try fusion."""
        self._fusion_processed.add(neighbor_idx)
        done = len(self._fusion_processed)
        self.status_message.emit(
            tr("status.temporal_fusion_progress", done=done, total=len(self._fusion_window))
        )
        self._try_complete_temporal_fusion()

    def _try_complete_temporal_fusion(self) -> None:
        """If all window frames processed (or enough valid), run fusion.

        Early-exit: if ≥3 valid frames (including anchor) have completed,
        proceed without waiting for remaining frames (spec §1 partial fusion).
        """
        if not self._fusion_in_progress:
            return

        expected = len(self._fusion_window)
        processed = len(self._fusion_processed)
        valid = len(self._fusion_masks)  # successful segments

        # Full completion
        if processed >= expected:
            pass
        # Early-exit: ≥3 valid frames completed (anchor + ≥2 neighbors)
        elif valid >= 3 and processed >= 3:
            pass
        else:
            return

        self._fusion_in_progress = False
        config = self._fusion_config
        if config is None:
            return

        anchor = self._fusion_anchor_frame
        center_mask = self._fusion_masks.get(anchor)
        center_contour = self._fusion_contours.get(anchor)
        if center_mask is None or center_contour is None:
            return

        neighbor_masks = {i: m for i, m in self._fusion_masks.items() if i != anchor}
        neighbor_contours = {i: c for i, c in self._fusion_contours.items() if i != anchor}

        result = temporal_fuse(
            center_mask=center_mask,
            neighbor_masks=neighbor_masks,
            center_contour=center_contour,
            neighbor_contours=neighbor_contours,
            anchor_frame_index=anchor,
            phase=self._fusion_phase or "ED",
            config=config,
            original_shape=self._fusion_original_shape,
        )

        self._fusion_result = result

        # Refine fused contour on frame N pixels (spec §5.2 step 6)
        fused_contour = result.fused_contour
        if self._current_frame_pixels is not None and self._should_auto_refine_after_segment():
            from echo_personal_tool.domain.services.mbs_lite_service import refine_open_arc_contour

            is_cine = (
                self._current_instance is not None
                and self._current_instance.media_format != "dicom"
            )
            refined, _ = refine_open_arc_contour(
                self._current_frame_pixels, fused_contour, cine=is_cine,
            )
            fused_contour = refined
            # Keep fusion_result in sync with refined contour
            self._fusion_result = dataclasses.replace(result, fused_contour=fused_contour)

        # Replace pending contour with fused contour
        contours = [
            existing
            for existing in self._state_manager.snapshot.contours
            if not (
                existing.phase == fused_contour.phase
                and existing.view == fused_contour.view
                and existing.chamber == fused_contour.chamber
            )
        ]
        contours.append(fused_contour)
        self.on_contours_changed(contours)

        self.status_message.emit(
            tr(
                "status.temporal_fusion_complete",
                used=result.frames_used,
                requested=result.frames_requested,
            )
        )

    # ── Speckle Tracking ──────────────────────────────────────────────────

    def run_speckle_tracking(
        self,
        contour: object | None = None,
        *,
        config: SpeckleConfig | None = None,
        config_preset: str = "echo_pac",
        manual_ed: int | None = None,
        manual_es: int | None = None,
    ) -> None:
        """Launch speckle tracking on current CINE frames."""
        from echo_personal_tool.application.workers.speckle_worker import (
            SpeckleTrackingWorker,
        )
        from echo_personal_tool.domain.services.myocardial_zone import (
            create_myocardial_zone,
        )

        # Use cached frames directly — load_all_frames is too slow for main thread
        try:
            frames = self._frame_cache.require_full_cine()
        except RuntimeError:
            self.status_message.emit("Speckle tracking: загрузите полную cine-последовательность")
            return

        if contour is None:
            self.status_message.emit(tr("app.speckle_draw_contour"))
            return

        from echo_personal_tool.domain.models.contour import Contour

        if not isinstance(contour, Contour) or len(contour.points) < 3:
            self.status_message.emit(tr("app.speckle_contour_not_found"))
            return

        pixel_spacing = self._state_manager.snapshot.effective_pixel_spacing or (1.0, 1.0)
        endo_points = __import__("numpy").array(contour.points, dtype=__import__("numpy").float64)

        active_config = config or SpeckleConfig.preset_echo_pac()
        zone = create_myocardial_zone(
            endo_points,
            pixel_spacing,
            active_config.wall_thickness_mm,
        )

        frame_time_ms = self._state_manager.snapshot.frame_time_ms or 33.3

        self.status_message.emit(tr("app.speckle_compute"))
        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=pixel_spacing,
            frame_time_ms=frame_time_ms,
            config=active_config,
            config_preset=config_preset,
            manual_ed=manual_ed,
            manual_es=manual_es,
        )
        worker.signals.finished.connect(self._on_speckle_tracking_finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.error.connect(self._on_speckle_tracking_error, Qt.ConnectionType.QueuedConnection)
        self._thread_pool.start(worker)

    def _on_speckle_tracking_finished(self, result: object) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult

        if not isinstance(result, StrainResult):
            return

        gls_text = f"GLS: {result.gls:.1f}%"
        hr_text = f"HR: {result.heart_rate_bpm:.0f} bpm" if result.heart_rate_bpm > 0 else ""
        status = f"{gls_text}  {hr_text}".strip()
        self.status_message.emit(status)
        self.speckle_result_ready.emit(result)

    def _on_speckle_tracking_error(self, message: str) -> None:
        self.status_message.emit(tr("app.speckle_error", message=message))
