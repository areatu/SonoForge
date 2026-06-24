"""Background worker for speckle tracking and strain computation."""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    StrainResult,
)
from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    auto_detect_ed_es,
    estimate_heart_rate_fft,
)
from echo_personal_tool.domain.services.myocardial_zone import sample_kernels_in_zone
from echo_personal_tool.domain.services.speckle_tracking import track_cine
from echo_personal_tool.domain.services.strain_computation import (
    compute_gls,
    compute_longitudinal_strain,
    compute_radial_strain,
    compute_strain_rate,
)

logger = logging.getLogger(__name__)


class SpeckleTrackingSignals(QObject):
    """Signals for speckle tracking worker."""

    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int)


class SpeckleTrackingWorker(QRunnable):
    """Background worker for speckle tracking + strain computation."""

    def __init__(
        self,
        frames: np.ndarray,
        zone: MyocardialZone,
        pixel_spacing: tuple[float, float],
        frame_time_ms: float = 33.3,
        config: SpeckleConfig | None = None,
    ) -> None:
        super().__init__()
        self._frames = frames
        self._zone = zone
        self._pixel_spacing = pixel_spacing
        self._frame_time_ms = frame_time_ms
        self._config = config or SpeckleConfig()
        self.signals = SpeckleTrackingSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            kernels = sample_kernels_in_zone(self._zone)

            self.signals.progress.emit(0, 100)
            tracking_results = track_cine(
                self._frames,
                kernels,
                self._config,
                progress_callback=lambda cur, tot: self.signals.progress.emit(
                    int(cur / tot * 70), 100
                ),
            )

            self.signals.progress.emit(70, 100)
            longitudinal = compute_longitudinal_strain(
                tracking_results, kernels, self._pixel_spacing
            )
            radial = compute_radial_strain(
                tracking_results, kernels, self._pixel_spacing
            )

            self.signals.progress.emit(80, 100)
            ed_index, es_index = auto_detect_ed_es(
                tracking_results, kernels, self._pixel_spacing
            )
            gls = compute_gls(longitudinal, ed_index, es_index)

            fps = 1000.0 / self._frame_time_ms if self._frame_time_ms > 0 else 30.0
            heart_rate = estimate_heart_rate_fft(self._frames, fps=fps)

            n_frames = self._frames.shape[0]
            frame_times = [self._frame_time_ms] * n_frames
            strain_rate = compute_strain_rate(longitudinal, frame_times)

            self.signals.progress.emit(100, 100)
            result = StrainResult(
                longitudinal=longitudinal,
                radial=radial,
                gls=gls,
                strain_rate=strain_rate,
                ed_index=ed_index,
                es_index=es_index,
                heart_rate_bpm=heart_rate,
                phases={"ED": ed_index, "ES": es_index},
            )
            self.signals.finished.emit(result)

        except Exception as e:
            logger.exception("Speckle tracking failed")
            self.signals.error.emit(str(e))
