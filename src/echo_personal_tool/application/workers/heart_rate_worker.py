"""Background worker for heart rate estimation from cine echo."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.domain.services.heart_rate import HeartRateResult
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

_MAX_FRAMES_FOR_OPTICAL_FLOW = 60

#: Static UI-safe failure messages (QH-4a ER-09): the worker never emits raw
#: exception text into the ``failed`` signal — paths or backend details must
#: not reach the status bar. Stable codes travel separately once the consumer
#: slot takes them; until then the message itself is the contract.
HR_FAILURE_NO_FRAMES = "No frames available"
HR_FAILURE_NO_ESTIMATE = "Could not estimate heart rate"
HR_FAILURE_ERROR = "Heart rate estimation failed"


class HeartRateSignals(QObject):
    finished = Signal(float, float, str)  # bpm, confidence, method
    failed = Signal(str)


class HeartRateWorker(QRunnable):
    """Estimate heart rate from DICOM/MP4 in a background thread."""

    def __init__(
        self,
        source_path: Path,
        media_format: str,
        frame_time_ms: float | None = None,
        contour_areas: list[float] | None = None,
        contour_frame_indices: list[int] | None = None,
    ) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._media_format = media_format
        self._frame_time_ms = frame_time_ms
        self._contour_areas = contour_areas
        self._contour_frame_indices = contour_frame_indices
        self._sample_step = 1.0
        #: Effective ms/frame for burned-ECG timing (set by ``run`` from the
        #: measured fps; loaders called outside ``run`` fall back to the header).
        self._ecg_frame_time_ms: float | None = None
        #: R-peaks burned into the pixels, extracted while the color frames
        #: are in hand inside the loaders (gray conversion drops the trace).
        self._burned_peaks: np.ndarray | None = None
        self.signals = HeartRateSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        from echo_personal_tool.domain.services.heart_rate import (
            estimate_hr_area_time,
            estimate_hr_optical_flow,
        )

        try:
            fps = 1000.0 / self._frame_time_ms if self._frame_time_ms and self._frame_time_ms > 0 else 30.0
            if self._media_format == "mp4" and not self._frame_time_ms:
                cap = cv2.VideoCapture(str(self._source_path))
                try:
                    measured = cap.get(cv2.CAP_PROP_FPS) if cap.isOpened() else 0
                    if np.isfinite(measured) and measured > 0:
                        fps = float(measured)
                finally:
                    cap.release()
            self._ecg_frame_time_ms = 1000.0 / fps

            # Try area-time first if contours are available (instant)
            if self._contour_areas and len(self._contour_areas) >= 4:
                result = estimate_hr_area_time(
                    self._contour_areas,
                    fps=fps,
                    frame_indices=self._contour_frame_indices,
                )
                if result.bpm > 0:
                    self.signals.finished.emit(result.bpm, result.confidence, result.method)
                    return

            # A real DICOM ECG waveform beats any image heuristic (cheap:
            # header/waveform read only, no frame decode).
            ecg_result = self._hr_from_waveform(fps)
            if ecg_result is not None and ecg_result.bpm > 0:
                self.signals.finished.emit(ecg_result.bpm, ecg_result.confidence, ecg_result.method)
                return

            # Fall back to optical flow (subsampled)
            frames = self._load_frames_subsampled()
            if not frames:
                self.signals.failed.emit(HR_FAILURE_NO_FRAMES)
                return

            # An ECG trace burned into the pixels (extracted by the loaders)
            # is electrical timing — trust it over optical flow.
            burned_result = self._hr_from_burned(fps)
            if burned_result is not None and burned_result.bpm > 0:
                self.signals.finished.emit(burned_result.bpm, burned_result.confidence, burned_result.method)
                return

            result = estimate_hr_optical_flow(frames, fps=fps / self._sample_step)
            if result.bpm > 0:
                self.signals.finished.emit(result.bpm, result.confidence, result.method)
            else:
                self.signals.failed.emit(HR_FAILURE_NO_ESTIMATE)

        except Exception as exc:  # noqa: BLE001 - safe event only, never to the UI
            log_boundary_failure(logger, "heart_rate.estimate", exc, code="unexpected")
            self.signals.failed.emit(HR_FAILURE_ERROR)

    def _hr_from_waveform(self, fps: float) -> HeartRateResult | None:
        """HR from a real DICOM ECG waveform, when the file carries one."""
        if self._media_format != "dicom":
            return None
        try:
            from echo_personal_tool.application.dicom_io import read_ecg_waveform
            from echo_personal_tool.domain.services.ecg_rpeak_detector import detect_r_peaks_from_waveform

            waveform = read_ecg_waveform(self._source_path)
            if waveform is None:
                return None
            peaks = detect_r_peaks_from_waveform(waveform)
        except Exception as exc:  # noqa: BLE001 - ECG is optional evidence
            log_boundary_failure(logger, "heart_rate.ecg", exc, code="source", level=logging.DEBUG)
            return None
        if peaks is None or not 40.0 <= peaks.heart_rate_bpm <= 200.0:
            return None
        return HeartRateResult(
            bpm=round(float(peaks.heart_rate_bpm), 1),
            method="ecg",
            confidence=float(peaks.confidence),
            es_intervals_ms=[float(value) for value in peaks.rr_intervals_ms],
            frame_rate=fps,
            num_frames_used=0,
        )

    def _hr_from_burned(self, fps: float) -> HeartRateResult | None:
        """HR from a green ECG trace burned into the clip pixels."""
        if self._burned_peaks is None:
            return None
        times = np.asarray(self._burned_peaks, dtype=np.float64)
        if times.size < 2:
            return None
        rr = np.diff(times)
        median_rr = float(np.median(rr)) if rr.size else 0.0
        if median_rr <= 0:
            return None
        bpm = 60000.0 / median_rr
        if not 40.0 <= bpm <= 200.0:
            return None
        if rr.size >= 2:
            cv = float(np.std(rr) / float(np.mean(rr)))
            regularity = max(0.0, min(1.0, 1.0 - cv))
        else:
            regularity = 0.5
        # 0.6 caps the trust in an uncalibrated burned trace (same weight
        # build_phase_timeline gives it), scaled by rhythm regularity.
        return HeartRateResult(
            bpm=round(bpm, 1),
            method="burned_ecg",
            confidence=round(0.6 * regularity, 3),
            es_intervals_ms=[float(value) for value in rr],
            frame_rate=fps,
            num_frames_used=0,
        )

    def _extract_burned_ecg(self, color_frames: list) -> None:
        """Store R-peaks of a green trace; grayscale frames simply have none."""
        self._burned_peaks = None
        frame_time = self._ecg_frame_time_ms or self._frame_time_ms
        if not frame_time or frame_time <= 0 or not color_frames:
            return
        first = np.asarray(color_frames[0])
        if first.ndim != 3 or first.shape[-1] < 3:
            return
        try:
            from echo_personal_tool.domain.services.cine_phase_timeline import burned_ecg_signal

            self._burned_peaks = burned_ecg_signal(color_frames, float(frame_time), len(color_frames))
        except Exception as exc:  # noqa: BLE001 - ECG is optional evidence
            log_boundary_failure(logger, "heart_rate.ecg", exc, code="source", level=logging.DEBUG)

    def _load_frames_subsampled(self) -> list[np.ndarray]:
        frames, self._sample_step = self._load_frames_subsampled_with_step()
        return frames

    def _load_frames_subsampled_with_step(self) -> tuple[list[np.ndarray], float]:
        """Load frames and subsample to _MAX_FRAMES_FOR_OPTICAL_FLOW."""
        if self._media_format == "mp4":
            all_frames = self._load_from_mp4()
        else:
            all_frames = self._load_from_dicom()

        if len(all_frames) <= _MAX_FRAMES_FOR_OPTICAL_FLOW:
            return all_frames, 1.0

        # Evenly subsample
        n = len(all_frames)
        target = _MAX_FRAMES_FOR_OPTICAL_FLOW
        indices = np.linspace(0, n - 1, target, dtype=int)
        return [all_frames[i] for i in indices], (n - 1) / (target - 1)

    def _load_from_mp4(self) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(self._source_path))
        try:
            if not cap.isOpened():
                return []
            color_frames: list[np.ndarray] = []
            while True:
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    break
                color_frames.append(bgr)
            # Burned ECG needs the color frames; gray conversion comes after.
            self._extract_burned_ecg(color_frames)
            return [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in color_frames]
        finally:
            cap.release()

    def _load_from_dicom(self) -> list[np.ndarray]:
        from echo_personal_tool.infrastructure.dicom_session import (
            get_thread_dicom_session,
        )

        session = get_thread_dicom_session(self._source_path)
        session.open(self._source_path)
        try:
            all_frames = session.decode_all_frames()
        finally:
            session.release_heavy()
        # The trace lives in the color pixels; extract before going gray.
        self._extract_burned_ecg(list(all_frames))
        result: list[np.ndarray] = []
        for frame in all_frames:
            if frame.ndim == 3:
                gray = (
                    cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if frame.shape[2] == 3
                    else np.mean(frame, axis=2).astype(np.uint8)
                )
            else:
                gray = frame.astype(np.uint8)
            result.append(gray)
        return result
