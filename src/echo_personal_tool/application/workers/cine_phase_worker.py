"""Background detection of systole/diastole for the active cine clip.

The worker owns all file I/O; the pure :mod:`cine_phase_timeline` module owns the
algorithm.  Frames are spatially reduced to at most 96x96 *before* they leave
the worker (temporal resolution is preserved), so a 120-frame HD cine costs a
few megabytes instead of a second full copy in the UI thread.

Results carry ``(instance_uid, generation)``: MainWindow discards a late result
from a clip the user has already left.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

_MAX_SPATIAL_SIZE = 96
_MIN_FRAMES = 4

FAILURE_NO_FRAMES = "no_frames"
FAILURE_UNEXPECTED = "unexpected"


class CinePhaseSignals(QObject):
    finished = Signal(object, str, int)  # PhaseTimeline, instance uid, generation
    failed = Signal(str, str, int)  # stable failure code, instance uid, generation


class CinePhaseWorker(QRunnable):
    """Build a :class:`PhaseTimeline` for one DICOM/MP4 instance off the UI thread."""

    def __init__(
        self,
        *,
        source_path: Path,
        media_format: str,
        frame_time_ms: float | None,
        n_frames: int,
        instance_uid: str,
        generation: int,
    ) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._media_format = str(media_format or "dicom")
        self._frame_time_ms = float(frame_time_ms) if frame_time_ms and frame_time_ms > 0 else None
        self._n_frames = max(0, int(n_frames))
        self._instance_uid = str(instance_uid)
        self._generation = int(generation)
        self.signals = CinePhaseSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        from echo_personal_tool.domain.services.cine_phase_timeline import build_phase_timeline

        try:
            frames = self._load_frames()
            if frames is None or frames.shape[0] < _MIN_FRAMES:
                self.signals.failed.emit(FAILURE_NO_FRAMES, self._instance_uid, self._generation)
                return
            r_peaks, confidence = self._read_ecg_r_peaks()
            # The decoded clip is authoritative: a mismatched DICOM header must
            # not silently stretch the annotation onto non-existent frames.
            timeline = build_phase_timeline(
                n_frames=int(frames.shape[0]),
                frame_time_ms=self._frame_time_ms,
                frames=frames,
                ecg_r_peaks_ms=r_peaks,
                ecg_confidence=confidence,
            )
            self.signals.finished.emit(timeline, self._instance_uid, self._generation)
        except Exception as exc:  # noqa: BLE001 - one stable code reaches the UI
            log_boundary_failure(logger, "cine_phase.detect", exc, code="unexpected")
            self.signals.failed.emit(FAILURE_UNEXPECTED, self._instance_uid, self._generation)

    # ── I/O ─────────────────────────────────────────────────────────
    def _load_frames(self) -> np.ndarray | None:
        if self._media_format == "mp4":
            raw = self._load_from_mp4()
        else:
            raw = self._load_from_dicom()
        if not raw:
            return None
        return self._downsample(raw)

    def _load_from_mp4(self) -> list[np.ndarray]:
        capture = cv2.VideoCapture(str(self._source_path))
        frames: list[np.ndarray] = []
        try:
            if not capture.isOpened():
                return frames
            while len(frames) < max(600, self._n_frames * 2):  # safety bound
                ok, bgr = capture.read()
                if not ok or bgr is None:
                    break
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        finally:
            capture.release()
        return frames

    def _load_from_dicom(self) -> list[np.ndarray]:
        from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

        session = get_thread_dicom_session(self._source_path)
        session.open(self._source_path)
        try:
            decoded = session.decode_all_frames()
        finally:
            session.release_heavy()
        frames: list[np.ndarray] = []
        for frame in decoded:
            arr = np.asarray(frame)
            if arr.ndim == 2:
                frames.append(arr)
            elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
                frames.append(arr[..., :3])
            elif arr.ndim == 3:
                frames.append(arr.mean(axis=0))
            else:
                return []
        return frames

    @staticmethod
    def _downsample(frames: list[np.ndarray]) -> np.ndarray | None:
        first = np.asarray(frames[0])
        height, width = first.shape[:2]
        scale = min(1.0, _MAX_SPATIAL_SIZE / max(1, height, width))
        out_h, out_w = max(4, int(height * scale)), max(4, int(width * scale))
        color = first.ndim == 3
        result = np.empty((len(frames), out_h, out_w, 3) if color else (len(frames), out_h, out_w), dtype=np.uint8)
        for index, frame in enumerate(frames):
            arr = np.asarray(frame)
            if arr.dtype != np.uint8:
                # DICOM pixel data may be 10/12/16-bit (values up to 4095+).
                # Clipping to 255 would saturate everything above 255 to white,
                # collapsing all phase signals.  Normalise by the actual range.
                lo = float(arr.min())
                hi = float(arr.max())
                if hi - lo > 1e-6:
                    arr = np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
                else:
                    arr = np.zeros_like(arr, dtype=np.uint8)
            resized = cv2.resize(arr, (out_w, out_h), interpolation=cv2.INTER_AREA)
            if color and resized.ndim == 2:
                resized = np.repeat(resized[..., None], 3, axis=2)
            result[index] = resized
        return result

    def _read_ecg_r_peaks(self) -> tuple[np.ndarray | None, float]:
        if self._media_format != "dicom":
            return None, 0.0
        from echo_personal_tool.application.dicom_io import read_ecg_waveform
        from echo_personal_tool.domain.services.ecg_rpeak_detector import detect_r_peaks_from_waveform

        try:
            waveform = read_ecg_waveform(self._source_path)
        except Exception as exc:  # noqa: BLE001 - ECG is optional evidence
            log_boundary_failure(logger, "cine_phase.ecg", exc, code="source", level=logging.DEBUG)
            return None, 0.0
        if waveform is None:
            return None, 0.0
        peaks = detect_r_peaks_from_waveform(waveform)
        if peaks is None or len(peaks.r_peak_indices) < 2:
            return None, 0.0
        return np.asarray(peaks.r_peak_times_ms, dtype=np.float64), float(peaks.confidence)
