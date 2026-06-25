"""Application use-case orchestration."""

from __future__ import annotations

import dataclasses
import logging
from functools import partial
from pathlib import Path
from time import perf_counter

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

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
)
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
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
from echo_personal_tool.infrastructure.onnx_engine import (
    OnnxInferenceEngine,
    _default_models_dir,
    _load_manifest,
)
from echo_personal_tool.infrastructure.video_reader import VideoReader

_FRAME_CACHE_WARN_BYTES = 512 * 1024 * 1024
logger = logging.getLogger(__name__)


class AppController(QObject):
    """Coordinates scanning and frame loading between UI and infrastructure."""

    studies_loaded = Signal(list)
    scan_failed = Signal(str)
    frame_loaded = Signal(np.ndarray)
    frame_load_failed = Signal(str)
    thumbnail_loaded = Signal(str, QImage)
    status_message = Signal(str)
    speckle_result_ready = Signal(object)

    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        segmenter: IOnnxSegmenter | None = None,
        thumbnail_scheduler: ThumbnailScheduler | None = None,
        thumbnail_max_in_flight: int = 2,
    ) -> None:
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._state_manager = StateManager()
        self._measurement_session = StudyMeasurementSessionStore()
        self._current_study_uid: str | None = None
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
        self._segment_in_progress = False
        self._auto_segment_phase: str | None = None
        self._auto_segment_view: str = "A4C"
        self._auto_segment_chamber: str = "LV"
        self._scan_started_at: float | None = None
        self._first_preview_emitted = False
        self._state_manager.state_changed.connect(self._on_state_changed)

    @property
    def studies(self) -> list[StudyMetadata]:
        return self._studies

    @property
    def state_manager(self) -> StateManager:
        return self._state_manager

    def open_folder(self, root: Path, error_log_path: Path | None = None) -> None:
        self._measurement_session.clear()
        self._current_study_uid = None
        self._scan_started_at = perf_counter()
        self._first_preview_emitted = False
        logger.info("scan_start root=%s", root)
        self.status_message.emit(f"Scanning {root}…")
        worker = ScanWorker(root, error_log_path=error_log_path, parent=self)
        worker.signals.finished.connect(self._on_studies_scanned)
        worker.signals.failed.connect(self._on_scan_failed)
        self._thread_pool.start(worker)

    def _on_studies_scanned(self, studies: object) -> None:
        self._studies = list(studies)  # type: ignore[arg-type]
        count = len(self._studies)
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
        self.status_message.emit(f"Loaded {count} studies")
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
            emit=False,
        )
        study_uid = self._resolve_study_uid(instance)
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
        self._state_manager.emit_state()
        if frame_index != 0:
            self._state_manager.set_frame(frame_index)
        self._current_study_uid = self._resolve_study_uid(instance)
        self._recompute_measurements()
        if instance.media_format == "dicom":
            request_id = self._decode_request_id
            self.status_message.emit(f"Decoding {instance.path.name}… ({total_frames} frames)")
            worker = DicomDecodeWorker(instance.path, request_id, parent=self)
            worker.signals.finished.connect(self._on_dicom_decoded)
            worker.signals.failed.connect(self._on_dicom_decode_failed)
            self._thread_pool.start(worker)
            return
        if instance.media_format == "mp4":
            request_id = self._decode_request_id
            self.status_message.emit(f"Decoding video {instance.path.name}… ({total_frames} frames)")
            worker = VideoDecodeWorker(instance.path, request_id, parent=self)
            worker.signals.finished.connect(self._on_dicom_decoded)
            worker.signals.failed.connect(self._on_dicom_decode_failed)
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
                worker.signals.finished.connect(self._on_thumbnail_loaded)
                worker.signals.failed.connect(self._on_thumbnail_failed)
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

    def set_playing(self, is_playing: bool) -> None:
        self._state_manager.set_playing(is_playing)

    def toggle_playback(self) -> None:
        self._state_manager.toggle_playback()

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
        self.on_contours_changed(updated_contours)
        self.status_message.emit(f"{target_view} {target_phase}: контур принят")
        return True

    def request_auto_segment(
        self,
        *,
        phase: str | None = None,
        view: str | None = None,
        chamber: str | None = None,
    ) -> None:
        if self._segment_in_progress:
            self.status_message.emit("Segmentation already in progress")
            return

        state = self._state_manager.snapshot
        if state.is_playing:
            self.status_message.emit("Pause playback before auto-segmentation")
            return

        phase = phase or self._auto_segment_phase
        view = view or self._auto_segment_view
        chamber = chamber or self._auto_segment_chamber
        if phase is None or phase not in {"ED", "ES"}:
            self.status_message.emit(
                "Auto-segmentation: select A4C/A2C ED or ES in worksheet first"
            )
            return

        if (view or "").upper() != "A4C":
            self.status_message.emit("A2C auto — в следующей версии")
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
        crop_mode = echonet_crop_mode_for_media(media_format)

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
        self.status_message.emit(f"M-mode: {float(time_per_pixel_ms):.3f} ms/px")

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
            f"Калибровка: {row_spacing:.3f} × {col_spacing:.3f} mm/px (ручная)"
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
            and self._resolve_study_uid() not in self._measurement_session._studies
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
        self.status_message.emit("Ручная калибровка сброшена")

    def reset_measurements_and_calibration(self) -> None:
        study_uid = self._resolve_study_uid()
        self._measurement_session.reset_measurements(study_uid)
        self._state_manager.reset_measurement_inputs()
        self._recompute_measurements()
        self.status_message.emit("Измерения и калибровка сброшены")

    def _on_state_changed(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        interval = max(
            1,
            int(round((state.frame_time_ms or 33.3) / self._playback_speed_multiplier)),
        )
        self._timer.setInterval(interval)
        if state.is_playing and not self._timer.isActive():
            self._timer.start()
        elif not state.is_playing and self._timer.isActive():
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
        """Recompute metrics from the current instance contours/linear only (for on-image overlay)."""
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
        return self._build_measurement_snapshot(
            contours=state.contours,
            linear_measurements=state.linear_measurements,
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
            pixel_spacing if spacing_calibrated else pixel_spacing,
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
                    self._emit_cached_frame(state.current_frame_index)
                return
            if (
                self._frame_cache.source_path is not None
                and self._frame_cache.source_path == Path(self._current_instance.path).resolve()
                and self._frame_cache.frame_count() > 0
            ):
                max_idx = self._frame_cache.frame_count() - 1
                idx = min(state.current_frame_index, max_idx)
                if self._loaded_frame_index != idx:
                    self._emit_cached_frame(idx)
                return
            if self._pending_decode_id != 0:
                return
        if self._current_instance.media_format in ("dicom", "mp4") and self._pending_decode_id != 0:
            return
        # Fallback after decode failure: load one frame on demand.
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
        if self._current_instance is not None and self._current_instance.media_format in ("dicom", "mp4"):
            if self._current_instance.path is not None and self._frame_cache.is_ready(
                self._current_instance.path
            ):
                self.step_frame(1)
                return
            if (
                self._current_instance.path is not None
                and self._frame_cache.source_path is not None
                and self._frame_cache.source_path == Path(self._current_instance.path).resolve()
                and self._frame_cache.frame_count() > 0
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
        if self._current_instance is None:
            return
        if Path(path).resolve() != self._current_instance.path.resolve():
            self._on_dicom_decode_failed(request_id, "DICOM path mismatch")
            return
        if not isinstance(frames, np.ndarray):
            self._on_dicom_decode_failed(request_id, "Decoded frames are invalid")
            return

        self._frame_cache.load(path, frames)
        if self._frame_cache.memory_bytes() > _FRAME_CACHE_WARN_BYTES:
            size_mb = self._frame_cache.memory_bytes() / (1024 * 1024)
            self.status_message.emit(f"Warning: DICOM cache uses {size_mb:.1f} MB")

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
        if pixels is not None:
            self._maybe_cache_cine_roi_from_frame(pixels, frame_index)
        self.frame_loaded.emit(pixels)

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
        if frame_index != 0 or self._frozen_cine_segment_roi() is not None:
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
        """B-mode ROI for ONNX: DICOM tags for DICOM; frozen heuristic ROI for cine."""
        if media_format == "dicom":
            return resolve_segment_roi_xyxy(
                frame,
                media_format=media_format,
                instance_path=instance_path,
            )

        if phase == "ED":
            roi = resolve_cine_segment_roi_xyxy(frame)
            self._cache_cine_segment_roi(roi)
            return roi

        frozen = self._frozen_cine_segment_roi()
        if frozen is not None:
            return frozen
        return resolve_cine_segment_roi_xyxy(frame)

    def _open_arc_from_cleaned_mask(
        self,
        cleaned_mask: np.ndarray,
        *,
        original_shape: tuple[int, int],
        view: str,
        cine: bool,
    ) -> tuple[
        list[tuple[float, float]],
        tuple[tuple[float, float], tuple[float, float]],
        tuple[float, float],
    ]:
        del cine
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

    def _should_auto_refine_after_segment(self) -> bool:
        manifest = _load_manifest(_default_models_dir())
        if not manifest:
            return False
        inference = manifest.get("inference", {})
        if not isinstance(inference, dict):
            return False
        return bool(inference.get("auto_refine_after_segment", False))

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

        cleaned_mask = papillary_mask_cleanup(mask)
        if int(np.count_nonzero(cleaned_mask)) < 80:
            self.status_message.emit(
                "сегментация: маска ONNX слишком мала — нужен A4C ED/ES с видимой полостью ЛЖ"
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
                cine=is_cine,
            )
        except ValueError:
            closed_points = smooth_contour(
                mask_to_contour(cleaned_mask, original_shape),
                num_nodes=32,
            )
            if not closed_points:
                self.status_message.emit("сегментация не нашла контур — используйте ручной")
                return
            try:
                open_points, annulus = closed_polygon_to_open_arc(closed_points, view_hint=view)
            except ValueError:
                self.status_message.emit("сегментация: не удалось построить open arc")
                return
            apex = apex_point(open_points, annulus)

        refined_points = exclude_papillary_concavities(open_points, annulus, apex)

        if self._should_auto_refine_after_segment() and self._current_frame_pixels is not None:
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
            refined, _ = refine_open_arc_contour(self._current_frame_pixels, draft)
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
                f"сегментация: {reject_reason} (маска {mask_px}px, дуга {arc_px:.0f}px) "
                "— используйте ручной контур"
            )
            return

        review_status = (
            f"{view} {phase}: проверьте контур (ASE, без папиллярных мышц) · "
            "R — уточнить · Enter — принять"
        )
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

    # ── Speckle Tracking ──────────────────────────────────────────────────

    def run_speckle_tracking(
        self,
        contour: object | None = None,
        *,
        manual_ed: int | None = None,
        manual_es: int | None = None,
    ) -> None:
        """Launch speckle tracking on current CINE frames."""
        from echo_personal_tool.application.workers.speckle_worker import (
            SpeckleTrackingWorker,
        )
        from echo_personal_tool.domain.models.speckle import SpeckleConfig
        from echo_personal_tool.domain.services.myocardial_zone import (
            create_myocardial_zone,
        )

        frames = self._frame_cache.frames
        if frames is None or len(frames) < 3:
            self.status_message.emit("speckle tracking: недостаточно кадров")
            return

        if contour is None:
            self.status_message.emit("speckle tracking: нарисуйте контур LV")
            return

        from echo_personal_tool.domain.models.contour import Contour

        if not isinstance(contour, Contour) or len(contour.points) < 3:
            self.status_message.emit("speckle tracking: контур LV не найден")
            return

        pixel_spacing = self._state_manager.snapshot.effective_pixel_spacing or (1.0, 1.0)
        endo_points = __import__("numpy").array(contour.points, dtype=__import__("numpy").float64)

        config = SpeckleConfig(wall_thickness_mm=8.0)
        zone = create_myocardial_zone(endo_points, pixel_spacing, config.wall_thickness_mm)

        frame_time_ms = self._state_manager.snapshot.frame_time_ms or 33.3

        self.status_message.emit("speckle tracking: вычисление...")
        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=pixel_spacing,
            frame_time_ms=frame_time_ms,
            config=config,
            manual_ed=manual_ed,
            manual_es=manual_es,
        )
        worker.signals.finished.connect(self._on_speckle_tracking_finished)
        worker.signals.error.connect(self._on_speckle_tracking_error)
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
        self.status_message.emit(f"speckle tracking ошибка: {message}")
