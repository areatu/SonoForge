"""Application coordinator for one-click biplane Auto-EF."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from echo_personal_tool.application.composition import services_of
from echo_personal_tool.domain.models.metadata import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.services.auto_ef_pipeline import (
    AutoEfClipCandidate,
    AutoEfPipelineResult,
    recalculate_auto_ef,
    run_auto_ef_pipeline,
)
from echo_personal_tool.domain.services.segment_roi import resolve_segment_roi_xyxy

logger = logging.getLogger(__name__)
_MAX_DECODE_FRAMES = 48


def _iter_2d_instances(
    study: StudyMetadata | None,
    current_instance: InstanceMetadata | None,
) -> list[InstanceMetadata]:
    instances: list[InstanceMetadata] = []
    seen: set[str] = set()
    if study is not None:
        for series in study.series:
            for inst in series.instances:
                if inst.clip_mode == "2d" and inst.sop_instance_uid not in seen:
                    seen.add(inst.sop_instance_uid)
                    instances.append(inst)
    if current_instance is not None and current_instance.sop_instance_uid not in seen:
        instances.append(current_instance)
    return instances


def _decode_instance_frames(inst: InstanceMetadata) -> list[np.ndarray]:
    if inst.path is None or not inst.path.is_file():
        return []
    total = max(1, int(inst.number_of_frames))
    indices = (
        list(range(total))
        if total <= _MAX_DECODE_FRAMES
        else [int(i) for i in np.linspace(0, total - 1, num=_MAX_DECODE_FRAMES, dtype=int)]
    )
    frames: list[np.ndarray] = []
    if inst.media_format == "dicom":
        from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

        reader = DicomReaderImpl()
        for idx in indices:
            try:
                frames.append(reader.read_pixels(inst.path, idx))
            except (OSError, ValueError, RuntimeError, LookupError) as exc:
                logger.debug("auto-ef skip dicom frame %d: %s", idx, type(exc).__name__)
                break
        return frames

    if total == 1:
        from echo_personal_tool.infrastructure.image_reader import ImageReader

        try:
            return [ImageReader().read_pixels(inst.path)]
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("auto-ef image read failed: %s", type(exc).__name__)
            return []

    from echo_personal_tool.infrastructure.video_reader import VideoReader

    vreader = VideoReader()
    try:
        vreader.open(inst.path)
        for idx in indices:
            frames.append(vreader.read_frame(idx))
    except (OSError, ValueError, RuntimeError, LookupError) as exc:
        logger.debug("auto-ef video read failed: %s", type(exc).__name__)
    finally:
        vreader.release()
    return frames


def _resolve_clip_roi(inst: InstanceMetadata, first_frame: np.ndarray) -> tuple[float, float, float, float] | None:
    if inst.media_format != "dicom" or inst.path is None:
        return None
    from echo_personal_tool.infrastructure.dicom_frame_panels import try_parse_from_path

    panel_layout = try_parse_from_path(inst.path)
    return resolve_segment_roi_xyxy(first_frame, media_format="dicom", panel_layout=panel_layout)


def build_candidates_from_instances(
    instances: Sequence[InstanceMetadata],
    *,
    study_uid: str,
    view_overrides: dict[str, str] | None = None,
) -> list[AutoEfClipCandidate]:
    """Build AutoEfClipCandidate records from study instances."""
    candidates: list[AutoEfClipCandidate] = []
    overrides = view_overrides or {}
    for inst in instances:
        frames = _decode_instance_frames(inst)
        if not frames:
            continue
        roi = _resolve_clip_roi(inst, frames[0])
        override = overrides.get(inst.sop_instance_uid)
        if not override:
            desc = (inst.series_description or "").upper()
            if "A4C" in desc or "4CH" in desc:
                override = "A4C"
            elif "A2C" in desc or "2CH" in desc:
                override = "A2C"
        candidates.append(
            AutoEfClipCandidate(
                sop_instance_uid=inst.sop_instance_uid,
                frames=frames,
                pixel_spacing_mm=inst.pixel_spacing,
                frame_time_ms=inst.frame_time_ms,
                view_override=override,
                roi_xyxy=roi,
                crop_mode="center_square",
                series_uid=inst.series_uid,
                is_cine=inst.media_format != "dicom",
            )
        )
    del study_uid
    return candidates


class _AutoEfWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _AutoEfWorker(QRunnable):
    def __init__(
        self,
        instances: list[InstanceMetadata],
        *,
        study_uid: str,
        view_overrides: dict[str, str],
        a4c_segmenter: Any,
        a2c_segmenter: Any,
        view_recognizer: Any,
        pixel_spacing_override: tuple[float, float] | None,
        bsa_m2: float | None,
        model_id: str,
        model_hash: str,
    ) -> None:
        super().__init__()
        self._instances = instances
        self._study_uid = study_uid
        self._view_overrides = view_overrides
        self._a4c_segmenter = a4c_segmenter
        self._a2c_segmenter = a2c_segmenter
        self._view_recognizer = view_recognizer
        self._pixel_spacing_override = pixel_spacing_override
        self._bsa_m2 = bsa_m2
        self._model_id = model_id
        self._model_hash = model_hash
        self.signals = _AutoEfWorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            candidates = build_candidates_from_instances(
                self._instances,
                study_uid=self._study_uid,
                view_overrides=self._view_overrides,
            )
            if (
                len(candidates) == 1
                and candidates[0].view_override is None
                and (
                    self._view_recognizer is None
                    or str(self._view_recognizer.recognize(candidates[0].frames[:4]).view).upper() == "UNKNOWN"
                )
            ):
                only = candidates[0]
                candidates = [
                    AutoEfClipCandidate(
                        sop_instance_uid=only.sop_instance_uid,
                        frames=only.frames,
                        pixel_spacing_mm=only.pixel_spacing_mm,
                        frame_time_ms=only.frame_time_ms,
                        view_override="A4C",
                        roi_xyxy=only.roi_xyxy,
                        crop_mode=only.crop_mode,
                        series_uid=only.series_uid,
                        is_cine=only.is_cine,
                    )
                ]
            result = run_auto_ef_pipeline(
                candidates,
                study_uid=self._study_uid,
                a4c_segmenter=self._a4c_segmenter,
                a2c_segmenter=self._a2c_segmenter,
                view_recognizer=self._view_recognizer,
                pixel_spacing_override=self._pixel_spacing_override,
                bsa_m2=self._bsa_m2,
                model_id=self._model_id,
                model_hash=self._model_hash,
            )
            self.signals.finished.emit(result)
        except (OSError, ValueError, RuntimeError, LookupError, TypeError) as exc:
            logger.warning("auto-ef worker failed: %s", type(exc).__name__)
            self.signals.failed.emit("auto_ef_failed")


def _extract_view_overrides(services: Any, study_uid: str, instances: Sequence[InstanceMetadata]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if services is None:
        return overrides
    workflow = getattr(services, "view_workflow", None)
    if workflow is None or not hasattr(workflow, "restore"):
        return overrides
    for inst in instances:
        try:
            decision = workflow.restore(study_uid, inst.sop_instance_uid)
        except (OSError, ValueError, RuntimeError, LookupError, TypeError):
            decision = None
        if decision is not None:
            view = str(getattr(decision, "effective_view", "") or getattr(decision, "view", "")).upper()
            if view in {"A4C", "A2C"}:
                overrides[inst.sop_instance_uid] = view
    return overrides


def _resolve_services(controller: Any) -> Any:
    return services_of(controller) or getattr(controller, "_services", None) or getattr(controller, "services", None)


def apply_auto_ef_to_controller(
    controller: Any,
    result: AutoEfPipelineResult,
    *,
    bsa_m2: float | None = None,
    operator_confirmed: bool = True,
) -> AutoEfPipelineResult:
    """Commit confirmed Auto-EF contours and provenance to the active session."""
    final = recalculate_auto_ef(
        result,
        result.contours,
        bsa_m2=bsa_m2,
        operator_confirmed=operator_confirmed,
    )
    services = _resolve_services(controller)
    study_uid = final.study_uid
    if services is not None:
        store = services.measurement_store
        store.merge_contours(study_uid, final.contours)
        if final.pixel_spacing_mm is not None:
            store.merge_simpson_areas(study_uid, final.contours, final.pixel_spacing_mm)
        store.upsert_result_provenance(study_uid, final.provenance)

    snap = controller.state_manager.snapshot
    active_inst = getattr(controller, "_current_instance", None) or snap.instance
    active_uid = active_inst.sop_instance_uid if active_inst is not None else None
    merged_ui = [
        existing
        for existing in snap.contours
        if not any(
            existing.chamber.upper() == "LV"
            and existing.view.upper() == incoming.view.upper()
            and existing.phase.lower() == incoming.phase.lower()
            for incoming in final.contours
        )
    ]
    merged_ui.extend(final.contours)
    if hasattr(controller, "on_contours_changed"):
        controller.on_contours_changed(merged_ui)
    del active_uid
    if services is not None and services.persistence is not None:
        services.persistence.save_pending()
    return final


class AutoEfCoordinator(QObject):
    """Dispatches asynchronous Auto-EF study runs and delivers results on UI thread."""

    started = Signal()
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, controller: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._running = False
        self._worker: _AutoEfWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return False
        snap = self._controller.state_manager.snapshot
        current_inst = getattr(self._controller, "_current_instance", None) or snap.instance
        instances = _iter_2d_instances(snap.study, current_inst)
        if not instances:
            self.failed.emit("no_study")
            return False
        services = _resolve_services(self._controller)
        a4c_seg = getattr(self._controller, "_segmenter", None)
        if a4c_seg is None and services is not None:
            a4c_seg = services.segmenter
        if a4c_seg is None or not a4c_seg.is_available():
            self.failed.emit("segmenter_unavailable")
            return False
        a2c_seg = services.a2c_segmenter if services is not None else a4c_seg
        view_rec = services.view_recognizer if services is not None else None
        study_uid = snap.study.study_uid if snap.study is not None else "study.active"
        overrides = _extract_view_overrides(services, study_uid, instances)
        bsa_m2 = None
        if snap.calculations is not None and snap.calculations.indexed is not None:
            bsa_m2 = snap.calculations.indexed.bsa_m2
        model_id = str(getattr(a4c_seg, "model_id", "") or "echonet_seg_resnet50")
        model_hash = str(getattr(a4c_seg, "model_sha256", "") or "")
        worker = _AutoEfWorker(
            instances,
            study_uid=study_uid,
            view_overrides=overrides,
            a4c_segmenter=a4c_seg,
            a2c_segmenter=a2c_seg,
            view_recognizer=view_rec,
            pixel_spacing_override=snap.effective_pixel_spacing,
            bsa_m2=bsa_m2,
            model_id=model_id,
            model_hash=model_hash,
        )
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        self._running = True
        self._worker = worker
        self.started.emit()
        QThreadPool.globalInstance().start(worker)
        return True

    def _on_finished(self, result: object) -> None:
        self._running = False
        self._worker = None
        self.finished.emit(result)

    def _on_failed(self, code: str) -> None:
        self._running = False
        self._worker = None
        self.failed.emit(code)
